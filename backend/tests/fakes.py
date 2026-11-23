"""Dublês das portas, para testar serviços sem Qdrant, provedores de IA ou banco."""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import replace

from app.core.exceptions import NotFoundError
from app.domain.entities import ModelInfo, RetrievedChunk
from app.domain.framework import FiltroRequisitos, Requisito, VersaoInfo, requisito_de_dict
from app.domain.ports import EmbeddingProvider, FrameworkRepository, LLMProvider, Reranker, VectorStore

DIM = 256


class HashEmbedder(EmbeddingProvider):
    """Embedding determinístico por hashing de palavras (bag-of-words)."""

    dimensions = DIM
    model = "hash-embedder"

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * DIM
        for word in re.findall(r"\w+", text.lower()):
            vector[int(hashlib.md5(word.encode()).hexdigest(), 16) % DIM] += 1.0
        norm = math.sqrt(sum(v * v for v in vector)) or 1.0
        return [v / norm for v in vector]

    def embed_documents(self, texts, title=None):
        return [self._vector(t) for t in texts]

    def embed_query(self, text):
        return self._vector(text)


class MemoryVectorStore(VectorStore):
    """Banco vetorial em memória com a mesma semântica de filtros do adaptador Qdrant."""

    def __init__(self):
        self.points: dict[str, tuple[list[float], dict]] = {}
        self.searches: list[dict | None] = []

    def add(self, chunk_id: str, text: str, embedder: EmbeddingProvider, **payload) -> None:
        self.points[chunk_id] = (embedder.embed_query(text), {"text": text, **payload})

    def ensure_collection(self) -> None: ...

    def upsert(self, points) -> None:
        for p in points:
            self.points[p.id] = (p.vector, dict(p.payload))

    def search(self, vector, limit, filters=None):
        self.searches.append(dict(filters) if filters else None)
        hits = []
        for chunk_id, (vec, payload) in self.points.items():
            if not _match(payload, filters):
                continue
            score = sum(a * b for a, b in zip(vector, vec))
            hits.append(RetrievedChunk(chunk_id, payload["text"], score, payload))
        return sorted(hits, key=lambda h: h.score, reverse=True)[:limit]

    def set_payload(self, document_id, payload) -> None:
        for _, stored in self.points.values():
            if stored.get("document_id") == document_id:
                stored.update(payload)

    def delete_document(self, document_id) -> None:
        self.points = {k: v for k, v in self.points.items() if v[1].get("document_id") != document_id}

    def delete_other_versions(self, document_id, keep_version) -> None: ...

    def delete_version(self, document_id, version) -> None: ...

    def count(self, document_id=None) -> int:
        return len(self.points)

    def sample(self, limit):
        return []

    def is_healthy(self) -> bool:
        return True


def _match(payload: dict, filters) -> bool:
    for field, value in (filters or {}).items():
        if value is None:
            continue
        if isinstance(value, str):
            if payload.get(field) != value:
                return False
        elif value and payload.get(field) not in value:
            return False
    return True


class KeywordReranker(Reranker):
    """Reranker determinístico: fração das palavras da consulta presentes no trecho."""

    model = "keyword-reranker"

    def rerank(self, query, chunks, top_n):
        words = set(re.findall(r"\w+", query.lower()))
        scored = []
        for chunk in chunks:
            present = set(re.findall(r"\w+", chunk.text.lower()))
            scored.append(replace(chunk, rerank_score=len(words & present) / max(len(words), 1)))
        return sorted(scored, key=lambda c: c.rerank_score, reverse=True)[:top_n]


class MemoryFrameworkRepository(FrameworkRepository):
    def __init__(self, requisitos: list[dict] | list[Requisito], versao: str = "1.0"):
        self.versao = versao
        self.requisitos = [r if isinstance(r, Requisito) else requisito_de_dict(r) for r in requisitos]
        for requisito in self.requisitos:
            requisito.versao = versao

    def versao_ativa(self):
        return VersaoInfo(self.versao, "rascunho", True)

    def listar(self, filtros: FiltroRequisitos | None = None):
        filtros = filtros or FiltroRequisitos()
        return [
            r
            for r in self.requisitos
            if (not filtros.tipos or r.tipo in filtros.tipos)
            and r.aplica_a(filtros.formato_oferta, filtros.incluir_tendencia)
        ]

    def obter(self, codigo, versao=None):
        for requisito in self.requisitos:
            if requisito.codigo == codigo.upper():
                return requisito
        raise NotFoundError(f"Requisito {codigo} não encontrado.")


class ScriptedLLM(LLMProvider):
    """LLM que devolve respostas pré-definidas por código de requisito (ou uma padrão)."""

    provider = "fake"
    model = "fake-llm"

    def __init__(self, respostas: dict[str, dict] | None = None, padrao: dict | None = None):
        self.respostas = respostas or {}
        self.padrao = padrao
        self.chamadas: list[dict] = []

    def _resposta(self, prompt: str) -> dict:
        for codigo, resposta in self.respostas.items():
            if f"<codigo>{codigo}</codigo>" in prompt:
                if isinstance(resposta, Exception):
                    raise resposta
                return resposta
        if self.padrao is None:
            raise RuntimeError("Sem resposta roteirizada.")
        return self.padrao

    def stream(self, messages, system):
        yield ""

    def generate(self, messages, system):
        return ""

    def generate_json(self, prompt, system):
        self.chamadas.append({"prompt": prompt, "system": system})
        return self._resposta(prompt)

    def generate_structured(self, prompt, system, schema, name):
        self.chamadas.append({"prompt": prompt, "system": system, "schema": schema})
        return self._resposta(prompt)

    def list_models(self):
        return [ModelInfo(id="fake-llm", provider="fake", display_name="Fake")]
