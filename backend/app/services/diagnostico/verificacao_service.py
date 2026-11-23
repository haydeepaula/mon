"""Etapa 4 do Quadro 9: verificação assistida.

Para cada requisito pendente do diagnóstico: recupera evidências na coleção institucional,
pede ao LLM uma proposta com saída estruturada e aplica as regras de pós-validação
(domain/diagnostico.py). Cada item é gravado com commit próprio, de modo que o job pode ser
interrompido e retomado sem refazer o que já foi gerado.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import asdict

from sqlalchemy.orm import Session

from app.db.models import Diagnostico, DiagnosticoItem, utcnow
from app.domain.diagnostico import (
    PROPOSTA_SCHEMA,
    DiagnosticoStatus,
    PropostaStatus,
    proposta_sem_evidencia,
    validar_proposta,
)
from app.domain.framework import requisito_de_dict
from app.domain.ports import LLMProvider
from app.services.diagnostico.prompt import NOME_SCHEMA, Instrucao, montar_prompt
from app.services.framework.evidence_retrieval_service import EvidenceRetrievalService
from app.services.progress import NullProgressReporter, ProgressReporter

logger = logging.getLogger(__name__)


class VerificacaoService:
    def __init__(
        self,
        session: Session,
        retrieval: EvidenceRetrievalService,
        llm: LLMProvider,
        instrucao: Instrucao,
        max_tentativas: int = 3,
        espera_base: float = 2.0,
    ):
        self.session = session
        self.retrieval = retrieval
        self.llm = llm
        self.instrucao = instrucao
        self.max_tentativas = max(1, max_tentativas)
        self.espera_base = espera_base

    def executar(
        self, diagnostico_id: uuid.UUID, item_ids: list[str] | None = None, reporter: ProgressReporter | None = None
    ) -> dict:
        reporter = reporter or NullProgressReporter()
        diagnostico = self.session.get(Diagnostico, diagnostico_id)
        if diagnostico is None:
            raise ValueError("Diagnóstico não encontrado.")
        alvo = set(item_ids or [])
        itens = [
            item
            for item in diagnostico.itens
            if item.proposta_status != PropostaStatus.GERADA and (not alvo or str(item.id) in alvo)
        ]
        resumo = {"verificados": 0, "erros": 0, "sem_evidencia": 0}
        try:
            for posicao, item in enumerate(itens, start=1):
                reporter.report((posicao - 1) / max(len(itens), 1), f"{item.requisito_codigo} ({posicao}/{len(itens)})")
                self.verificar_item(diagnostico, item)
                self.session.commit()
                if item.proposta_status == PropostaStatus.ERRO:
                    resumo["erros"] += 1
                    reporter.log(f"{item.requisito_codigo}: erro — {item.erro}")
                else:
                    resumo["verificados"] += 1
                    if "sem_evidencia" in (item.alertas or []):
                        resumo["sem_evidencia"] += 1
                    reporter.log(f"{item.requisito_codigo}: {item.classificacao_proposta}")
        except Exception:
            diagnostico.status = DiagnosticoStatus.FALHOU
            self.session.commit()
            raise
        diagnostico.status = (
            DiagnosticoStatus.VALIDADO
            if diagnostico.itens and all(i.classificacao_final for i in diagnostico.itens)
            else DiagnosticoStatus.EM_VALIDACAO
        )
        self.session.commit()
        reporter.report(1.0, "Verificação concluída")
        return resumo

    def verificar_item(self, diagnostico: Diagnostico, item: DiagnosticoItem) -> None:
        inicio = time.perf_counter()
        item.erro = None
        item.resposta_bruta = None
        try:
            requisito = requisito_de_dict(item.requisito)
            escopo = diagnostico.escopo or {}
            recuperacao = self.retrieval.recuperar_para(
                requisito, diagnostico.curso, incluir_normativa=bool(escopo.get("incluir_normativa", True))
            )
            item.consulta = recuperacao.consulta
            item.evidencias = [{"n": n, **asdict(e)} for n, e in enumerate(recuperacao.evidencias, start=1)]
            item.normativos = [asdict(e) for e in recuperacao.normativos]

            if not recuperacao.evidencias:
                proposta = proposta_sem_evidencia(requisito.evidencia_esperada)
            else:
                prompt = montar_prompt(requisito, recuperacao.evidencias, escopo, diagnostico.curso_nome)
                proposta = self._propor(prompt, len(recuperacao.evidencias), requisito.tipo, item)

            item.proposta = proposta.to_dict()
            item.classificacao_proposta = proposta.classificacao
            item.conceito_proposto = proposta.conceito_inep
            item.alertas = list(proposta.alertas)
            item.proposta_status = PropostaStatus.GERADA
        except Exception as exc:
            logger.exception("Falha ao verificar %s.", item.requisito_codigo)
            item.proposta_status = PropostaStatus.ERRO
            item.erro = (getattr(exc, "message", None) or str(exc) or exc.__class__.__name__)[:2000]
        item.latencia_ms = int((time.perf_counter() - inicio) * 1000)
        item.gerado_em = utcnow()

    def _propor(self, prompt: str, n_evidencias: int, tipo: str, item: DiagnosticoItem):
        """Chama o LLM com saída estruturada. Resposta inválida é repetida de imediato; falhas do
        provedor (cota, sobrecarga) são repetidas com espera exponencial."""
        ultimo_erro: Exception | None = None
        for tentativa in range(self.max_tentativas):
            if tentativa and ultimo_erro is not None and not isinstance(ultimo_erro, ValueError):
                time.sleep(self.espera_base * 2 ** (tentativa - 1))
            try:
                bruta = self.llm.generate_structured(prompt, self.instrucao.texto, PROPOSTA_SCHEMA, NOME_SCHEMA)
                item.resposta_bruta = json.dumps(bruta, ensure_ascii=False)[:20000]
                return validar_proposta(bruta, n_evidencias, tipo)
            except Exception as exc:
                ultimo_erro = exc
                logger.warning("Tentativa %s falhou para %s: %s", tentativa + 1, item.requisito_codigo, exc)
        raise ultimo_erro  # type: ignore[misc]
