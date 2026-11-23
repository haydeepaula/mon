"""Recuperação de evidências orientada por requisito (TCC, seção 3.6.1 b).

Para cada requisito do framework, o serviço monta a consulta padronizada e busca
evidências candidatas apenas na coleção institucional (documentos do curso):

1. busca vetorial restrita aos ``documentos_provaveis`` do requisito (ex.: matriz, PPC);
2. busca vetorial em toda a coleção institucional, que cobre documentos sem tipo
   ou evidências fora do lugar esperado;
3. união dos candidatos, sem duplicatas, e reordenação (rerank) para escolher os mais relevantes.

Opcionalmente recupera também o texto normativo de origem na coleção normativa,
útil ao consultor e ao prompt de diagnóstico.
"""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy.orm import Session

from app.domain.entities import RetrievedChunk
from app.domain.framework import Evidencia, RecuperacaoRequisito, Requisito
from app.domain.knowledge_base import Colecao
from app.domain.ports import EmbeddingProvider, FrameworkRepository, Reranker, VectorStore
from app.services.rag.prompt_builder import describe_location
from app.services.settings_service import RagSettings

NORMATIVOS_TOP_N = 3


def para_evidencia(chunk: RetrievedChunk) -> Evidencia:
    payload = chunk.payload or {}
    return Evidencia(
        documento=payload.get("filename") or "documento",
        trecho=chunk.text,
        score=round(chunk.relevance, 4),
        chunk_id=chunk.id,
        pagina=payload.get("page"),
        document_id=payload.get("document_id"),
        versao=payload.get("version"),
        sha256=payload.get("sha256"),
        ocr=bool(payload.get("ocr")),
        colecao=payload.get("colecao"),
        tipo_documento=payload.get("tipo_documento"),
        localizacao=describe_location(payload),
        vector_score=round(chunk.score, 4),
        rerank_score=round(chunk.rerank_score, 4) if chunk.rerank_score is not None else None,
    )


def consulta_normativa(requisito: Requisito) -> str:
    partes = [requisito.fonte_documento, requisito.fonte_dispositivo or "", requisito.texto]
    return " ".join(p for p in partes if p)


class EvidenceRetrievalService:
    def __init__(
        self,
        framework: FrameworkRepository,
        embedder: EmbeddingProvider,
        store: VectorStore,
        reranker: Reranker,
        top_k: int = 20,
        top_n: int = 6,
        min_relevance: float = 0.0,
    ):
        self.framework = framework
        self.embedder = embedder
        self.store = store
        self.reranker = reranker
        self.top_k = top_k
        self.top_n = top_n
        self.min_relevance = min_relevance

    @classmethod
    def from_settings(cls, session: Session, settings: RagSettings | None = None) -> EvidenceRetrievalService:
        from app.container import build_reranker, get_embedder, get_vector_store
        from app.repositories.framework_repository import SqlFrameworkRepository
        from app.services.settings_service import SettingsService

        settings = settings or SettingsService(session).get_rag()
        return cls(
            SqlFrameworkRepository(session),
            get_embedder(),
            get_vector_store(),
            build_reranker(settings),
            top_k=settings.retrieval_top_k,
            top_n=settings.rerank_top_n,
            min_relevance=settings.min_relevance,
        )

    def config(self) -> dict[str, Any]:
        """Parâmetros da recuperação, registrados para reprodutibilidade (seção 3.8)."""
        return {
            "top_k": self.top_k,
            "top_n": self.top_n,
            "min_relevance": self.min_relevance,
            "embedding_model": getattr(self.embedder, "model", None),
            "reranker": type(self.reranker).__name__,
            "rerank_model": getattr(self.reranker, "model", None),
        }

    # --- contrato consumido pelo diagnóstico -------------------------------------------
    def recuperar(
        self, requisito_codigo: str, curso: str | None = None, top_n: int | None = None, versao: str | None = None
    ) -> list[Evidencia]:
        return self.recuperar_detalhado(requisito_codigo, curso, top_n, versao).evidencias

    def recuperar_detalhado(
        self,
        requisito_codigo: str,
        curso: str | None = None,
        top_n: int | None = None,
        versao: str | None = None,
        incluir_normativa: bool = False,
    ) -> RecuperacaoRequisito:
        requisito = self.framework.obter(requisito_codigo, versao)
        return self.recuperar_para(requisito, curso, top_n, incluir_normativa)

    def recuperar_para(
        self,
        requisito: Requisito,
        curso: str | None = None,
        top_n: int | None = None,
        incluir_normativa: bool = False,
    ) -> RecuperacaoRequisito:
        """Recupera evidências para um requisito já carregado (ex.: snapshot do diagnóstico)."""
        top_n = top_n or self.top_n
        timings: dict[str, int] = {}
        consulta = requisito.consulta()

        inicio = time.perf_counter()
        vetor = self.embedder.embed_query(consulta)
        timings["embedding"] = _ms(inicio)

        inicio = time.perf_counter()
        filtros: dict[str, Any] = {"colecao": Colecao.INSTITUCIONAL.value}
        if curso:
            filtros["curso"] = curso
        candidatos: dict[str, RetrievedChunk] = {}
        if requisito.documentos_provaveis:
            restritos = {**filtros, "tipo_documento": list(requisito.documentos_provaveis)}
            for chunk in self.store.search(vetor, self.top_k, restritos):
                candidatos.setdefault(chunk.id, chunk)
        for chunk in self.store.search(vetor, self.top_k, filtros):
            candidatos.setdefault(chunk.id, chunk)
        timings["search"] = _ms(inicio)

        inicio = time.perf_counter()
        ordenados = sorted(candidatos.values(), key=lambda c: c.score, reverse=True)
        selecionados = self.reranker.rerank(consulta, ordenados, top_n) if ordenados else []
        selecionados = [c for c in selecionados if c.relevance >= self.min_relevance]
        timings["rerank"] = _ms(inicio)

        normativos: list[Evidencia] = []
        if incluir_normativa:
            inicio = time.perf_counter()
            normativos = self._normativos(requisito)
            timings["normativa"] = _ms(inicio)

        config = {**self.config(), "top_n": top_n, "curso": curso, "candidatos": len(candidatos)}
        return RecuperacaoRequisito(
            requisito=requisito,
            consulta=consulta,
            evidencias=[para_evidencia(c) for c in selecionados],
            normativos=normativos,
            timings_ms=timings,
            config=config,
        )

    def _normativos(self, requisito: Requisito) -> list[Evidencia]:
        consulta = consulta_normativa(requisito)
        vetor = self.embedder.embed_query(consulta)
        candidatos = self.store.search(vetor, self.top_k, {"colecao": Colecao.NORMATIVA.value})
        if not candidatos:
            return []
        return [para_evidencia(c) for c in self.reranker.rerank(consulta, candidatos, NORMATIVOS_TOP_N)]


def _ms(inicio: float) -> int:
    return int((time.perf_counter() - inicio) * 1000)
