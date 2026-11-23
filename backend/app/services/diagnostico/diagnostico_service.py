"""Casos de uso do diagnóstico (TCC, seção 3.7, Quadro 9).

1. Planejamento: escopo (formato de oferta, próximo ato, filtros) e requisitos aplicáveis.
2-3. Coleta e indexação: módulo de documentos.
4. Verificação assistida: job no worker (VerificacaoService).
5. Validação: o consultor confirma ou corrige cada proposta; a proposta é preservada.
6-8. Priorização, relatório e devolutiva: ver os métodos correspondentes.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.db.models import Diagnostico, DiagnosticoItem, Document, DocumentStatus, Job, JobType, utcnow
from app.domain import gut
from app.domain.concordancia import resumo_concordancia
from app.domain.diagnostico import (
    CausaDivergencia,
    Classificacao,
    DiagnosticoStatus,
    PropostaStatus,
    causa_obrigatoria,
)
from app.domain.framework import FORMATOS_OFERTA, FiltroRequisitos, Requisito, requisito_para_dict
from app.domain.knowledge_base import Colecao
from app.repositories.framework_repository import SqlFrameworkRepository
from app.services.diagnostico.prompt import carregar_instrucao
from app.services.diagnostico.relatorio import gerar_relatorio
from app.services.job_service import JobService
from app.services.settings_service import SettingsService

ATOS = ("autorizacao", "reconhecimento", "renovacao", "outro")

# Status em que o consultor ainda pode registrar ou alterar validações.
_STATUS_VALIDACAO = {DiagnosticoStatus.EM_VALIDACAO, DiagnosticoStatus.VALIDADO, DiagnosticoStatus.PRIORIZADO}


def normalizar_escopo(dados: dict[str, Any] | None) -> dict[str, Any]:
    """Plano de diagnóstico (Quadro 9, etapa 1)."""
    dados = dict(dados or {})
    formato = (dados.get("formato_oferta") or None) and str(dados["formato_oferta"]).lower()
    if formato and formato not in FORMATOS_OFERTA:
        raise ValidationError(f"Formato de oferta inválido: {formato}. Use: {', '.join(FORMATOS_OFERTA)}.")
    ato = (dados.get("proximo_ato") or None) and str(dados["proximo_ato"]).lower()
    if ato and ato not in ATOS:
        raise ValidationError(f"Ato regulatório inválido: {ato}. Use: {', '.join(ATOS)}.")
    data_ato = dados.get("data_ato") or None
    if data_ato:
        try:
            data_ato = date.fromisoformat(str(data_ato)).isoformat()
        except ValueError:
            raise ValidationError("data_ato deve estar no formato AAAA-MM-DD.") from None
    return {
        "formato_oferta": formato,
        "proximo_ato": ato,
        "data_ato": data_ato,
        "incluir_tendencia": bool(dados.get("incluir_tendencia", False)),
        "tipos": [str(t) for t in dados.get("tipos") or []],
        "grupos": [str(g).upper() for g in dados.get("grupos") or []],
        "codigos": [str(c).upper() for c in dados.get("codigos") or []],
        "validacao_cega": bool(dados.get("validacao_cega", False)),
        "incluir_normativa": bool(dados.get("incluir_normativa", True)),
        "observacoes": (dados.get("observacoes") or "").strip() or None,
    }


def snapshot_requisito(requisito: Requisito) -> dict[str, Any]:
    return {**requisito_para_dict(requisito), "ordem": requisito.ordem}


class DiagnosticoService:
    def __init__(self, session: Session):
        self.session = session
        self.framework = SqlFrameworkRepository(session)
        self.jobs = JobService(session)

    # --- consulta --------------------------------------------------------------------------
    def listar(self) -> list[Diagnostico]:
        return list(self.session.scalars(select(Diagnostico).order_by(Diagnostico.created_at.desc())))

    def obter(self, diagnostico_id: uuid.UUID) -> Diagnostico:
        diagnostico = self.session.get(Diagnostico, diagnostico_id)
        if diagnostico is None:
            raise NotFoundError("Diagnóstico não encontrado.")
        return diagnostico

    def item(self, diagnostico_id: uuid.UUID, item_id: uuid.UUID) -> DiagnosticoItem:
        item = self.session.get(DiagnosticoItem, item_id)
        if item is None or item.diagnostico_id != diagnostico_id:
            raise NotFoundError("Item do diagnóstico não encontrado.")
        return item

    # --- etapa 1: planejamento ---------------------------------------------------------------
    def requisitos_aplicaveis(self, escopo: dict[str, Any], versao: str | None = None) -> list[Requisito]:
        escopo = normalizar_escopo(escopo)
        filtros = FiltroRequisitos(
            versao=versao,
            tipos=escopo["tipos"],
            grupos=escopo["grupos"],
            formato_oferta=escopo["formato_oferta"],
            incluir_tendencia=escopo["incluir_tendencia"],
        )
        requisitos = self.framework.listar(filtros)
        if escopo["codigos"]:
            requisitos = [r for r in requisitos if r.codigo in escopo["codigos"]]
        return requisitos

    def criar(self, dados: dict[str, Any], user_id: uuid.UUID | None) -> Diagnostico:
        escopo = normalizar_escopo(dados.get("escopo"))
        framework = self.framework.versao_model(dados.get("framework_versao") or None)
        diagnostico = Diagnostico(
            nome=(dados.get("nome") or "").strip() or f"Diagnóstico {utcnow():%d/%m/%Y}",
            curso=(dados.get("curso") or "").strip() or None,
            curso_nome=(dados.get("curso_nome") or "").strip() or None,
            escopo=escopo,
            framework_versao=framework.versao,
            config={"framework_status": framework.status},
            status=DiagnosticoStatus.PLANEJAMENTO,
            created_by=user_id,
        )
        self.session.add(diagnostico)
        self._materializar_itens(diagnostico)
        self.session.flush()
        return diagnostico

    def atualizar(self, diagnostico_id: uuid.UUID, dados: dict[str, Any]) -> Diagnostico:
        diagnostico = self.obter(diagnostico_id)
        if "nome" in dados and dados["nome"]:
            diagnostico.nome = dados["nome"].strip()
        if "curso_nome" in dados:
            diagnostico.curso_nome = (dados["curso_nome"] or "").strip() or None
        muda_plano = any(k in dados for k in ("escopo", "curso", "framework_versao"))
        if muda_plano:
            if diagnostico.status != DiagnosticoStatus.PLANEJAMENTO:
                raise ConflictError("O escopo só pode ser alterado na etapa de planejamento.")
            if "escopo" in dados:
                diagnostico.escopo = normalizar_escopo(dados["escopo"])
            if "curso" in dados:
                diagnostico.curso = (dados["curso"] or "").strip() or None
            if dados.get("framework_versao"):
                framework = self.framework.versao_model(dados["framework_versao"])
                diagnostico.framework_versao = framework.versao
                diagnostico.config = {**(diagnostico.config or {}), "framework_status": framework.status}
            diagnostico.itens.clear()
            self.session.flush()
            self._materializar_itens(diagnostico)
        self.session.flush()
        return diagnostico

    def excluir(self, diagnostico_id: uuid.UUID) -> None:
        diagnostico = self.obter(diagnostico_id)
        if diagnostico.status == DiagnosticoStatus.VERIFICANDO and self._job_ativo(diagnostico):
            raise ConflictError("Aguarde o fim da verificação para excluir o diagnóstico.")
        self.session.delete(diagnostico)
        self.session.flush()

    def _materializar_itens(self, diagnostico: Diagnostico) -> None:
        requisitos = self.requisitos_aplicaveis(diagnostico.escopo, diagnostico.framework_versao)
        if not requisitos:
            raise ValidationError("Nenhum requisito do framework se aplica a esse escopo.")
        for posicao, requisito in enumerate(requisitos, start=1):
            diagnostico.itens.append(
                DiagnosticoItem(
                    requisito_codigo=requisito.codigo,
                    requisito=snapshot_requisito(requisito),
                    ordem=posicao,
                )
            )

    # --- etapa 4: verificação assistida -------------------------------------------------------
    def iniciar_verificacao(
        self, diagnostico_id: uuid.UUID, item_ids: list[uuid.UUID] | None, user_id: uuid.UUID | None
    ) -> Job:
        diagnostico = self.obter(diagnostico_id)
        if diagnostico.status == DiagnosticoStatus.VERIFICANDO and self._job_ativo(diagnostico):
            raise ConflictError("A verificação deste diagnóstico já está em andamento.")
        if diagnostico.status in {DiagnosticoStatus.RELATORIO_EMITIDO, DiagnosticoStatus.CONCLUIDO}:
            raise ConflictError("O relatório já foi emitido; crie um novo diagnóstico para reverificar.")

        alvo = {str(i) for i in item_ids or []}
        if alvo:
            itens = [i for i in diagnostico.itens if str(i.id) in alvo]
            if len(itens) != len(alvo):
                raise NotFoundError("Item do diagnóstico não encontrado.")
            validados = [i.requisito_codigo for i in itens if i.classificacao_final]
            if validados:
                raise ConflictError(f"Itens já validados não podem ser reverificados: {', '.join(validados)}.")
            for item in itens:
                item.proposta_status = PropostaStatus.PENDENTE
        else:
            itens = [i for i in diagnostico.itens if i.proposta_status != PropostaStatus.GERADA]
            if not itens:
                raise ConflictError("Todos os itens já têm proposta. Selecione itens para reverificar.")

        execucao = self._registrar_execucao(diagnostico, len(itens))
        diagnostico.status = DiagnosticoStatus.VERIFICANDO
        job = self.jobs.enqueue(
            JobType.DIAGNOSTICO_VERIFICAR,
            {"diagnostico_id": str(diagnostico.id), "item_ids": sorted(str(i.id) for i in itens)},
            user_id,
            message=f"Verificação de {len(itens)} requisito(s) na fila",
        )
        diagnostico.job_id = job.id
        execucao["job_id"] = str(job.id)
        self.session.flush()
        return job

    def _registrar_execucao(self, diagnostico: Diagnostico, n_itens: int) -> dict[str, Any]:
        """Registra modelo, parâmetros, prompt e base indexada (reprodutibilidade, seção 3.8)."""
        rag = SettingsService(self.session).get_rag()
        instrucao = carregar_instrucao(get_settings().diagnostico_prompt_file)
        documentos = self.session.scalars(
            select(Document).where(
                Document.status == DocumentStatus.INDEXED, Document.colecao == Colecao.INSTITUCIONAL.value
            )
        ).all()
        if diagnostico.curso:
            documentos = [d for d in documentos if d.curso == diagnostico.curso]
        execucao = {
            "executado_em": utcnow().isoformat(),
            "itens": n_itens,
            "llm_provider": rag.llm_provider,
            "llm_model": rag.llm_model,
            "reasoning_level": rag.reasoning_level,
            "retrieval_top_k": rag.retrieval_top_k,
            "rerank_enabled": rag.rerank_enabled,
            "rerank_model": rag.rerank_model if rag.rerank_enabled else None,
            "rerank_top_n": rag.rerank_top_n,
            "min_relevance": rag.min_relevance,
            "chunk_size": rag.chunk_size,
            "chunk_overlap": rag.chunk_overlap,
            "prompt_origem": instrucao.origem,
            "prompt_sha256": instrucao.sha256,
            "base": [
                {
                    "document_id": str(d.id),
                    "filename": d.filename,
                    "version": d.version,
                    "sha256": d.sha256,
                    "tipo_documento": d.tipo_documento,
                    "ocr_pages": d.ocr_pages,
                }
                for d in documentos
            ],
        }
        config = dict(diagnostico.config or {})
        config["execucoes"] = [*config.get("execucoes", []), execucao]
        config["ultima_execucao"] = {k: v for k, v in execucao.items() if k != "base"}
        diagnostico.config = config
        return execucao

    def _job_ativo(self, diagnostico: Diagnostico) -> bool:
        if diagnostico.job_id is None:
            return False
        job = self.session.get(Job, diagnostico.job_id)
        return job is not None and job.status in ("queued", "running")

    # --- etapa 5: validação ------------------------------------------------------------------
    def validar_item(
        self,
        diagnostico_id: uuid.UUID,
        item_id: uuid.UUID,
        classificacao_final: str,
        conceito_final: int | None,
        divergencia_causa: str | None,
        comentario: str | None,
        user_id: uuid.UUID | None,
    ) -> DiagnosticoItem:
        diagnostico = self.obter(diagnostico_id)
        if diagnostico.status not in _STATUS_VALIDACAO:
            raise ConflictError("A validação só é possível depois da verificação e antes da emissão do relatório.")
        item = self.item(diagnostico_id, item_id)
        if item.proposta_status == PropostaStatus.PENDENTE:
            raise ConflictError("Este item ainda não foi verificado.")

        try:
            final = Classificacao(str(classificacao_final).upper())
        except ValueError:
            raise ValidationError(f"Classificação inválida: {classificacao_final}.") from None
        tipo = (item.requisito or {}).get("tipo")
        if conceito_final is not None:
            if tipo != "qualidade":
                raise ValidationError("O conceito de 1 a 5 só se aplica a requisitos do tipo qualidade.")
            if not 1 <= int(conceito_final) <= 5:
                raise ValidationError("O conceito deve estar entre 1 e 5.")

        proposta = item.classificacao_proposta if item.proposta_status == PropostaStatus.GERADA else None
        if causa_obrigatoria(proposta, final):
            if not divergencia_causa:
                raise ValidationError("Informe a causa da divergência em relação à proposta.")
            try:
                divergencia_causa = CausaDivergencia(divergencia_causa).value
            except ValueError:
                raise ValidationError(f"Causa de divergência inválida: {divergencia_causa}.") from None
        else:
            divergencia_causa = None

        item.classificacao_final = final.value
        item.conceito_final = int(conceito_final) if conceito_final is not None else None
        item.divergencia_causa = divergencia_causa
        item.comentario = (comentario or "").strip() or None
        item.validado_por = user_id
        item.validado_em = utcnow()
        if final not in (Classificacao.NC, Classificacao.PC):
            self._limpar_gut(item)
        if diagnostico.status == DiagnosticoStatus.PRIORIZADO:
            self._atualizar_status_priorizacao(diagnostico)

        if diagnostico.status == DiagnosticoStatus.EM_VALIDACAO and all(i.classificacao_final for i in diagnostico.itens):
            diagnostico.status = DiagnosticoStatus.VALIDADO
        diagnostico.metricas = self.metricas(diagnostico)
        self.session.flush()
        return item

    @staticmethod
    def _limpar_gut(item: DiagnosticoItem) -> None:
        item.gut_g = item.gut_u = item.gut_t = item.prioridade = None
        item.gut_sugestao = {}

    # --- seção 3.8, nível 2: concordância ---------------------------------------------------------
    def metricas(self, diagnostico: Diagnostico, referencia: Diagnostico | None = None) -> dict[str, Any]:
        """Concordância entre propostas e decisões finais.

        Com ``referencia``, compara as propostas deste diagnóstico com as decisões do consultor
        registradas no diagnóstico de referência (variação de um fator por vez).
        """
        finais = {i.requisito_codigo: i for i in (referencia.itens if referencia else diagnostico.itens)}
        linhas = []
        for item in diagnostico.itens:
            decisao = finais.get(item.requisito_codigo)
            gerada = item.proposta_status == PropostaStatus.GERADA
            linhas.append(
                {
                    "proposta": item.classificacao_proposta if gerada else None,
                    "final": decisao.classificacao_final if decisao else None,
                    "conceito_proposto": item.conceito_proposto if gerada else None,
                    "conceito_final": decisao.conceito_final if decisao else None,
                    "tipo": (item.requisito or {}).get("tipo"),
                    "causa": decisao.divergencia_causa if decisao and not referencia else None,
                }
            )
        resumo = resumo_concordancia(linhas)
        latencias = [i.latencia_ms for i in diagnostico.itens if i.proposta_status == PropostaStatus.GERADA]
        resumo.update(
            {
                "n_erros": sum(1 for i in diagnostico.itens if i.proposta_status == PropostaStatus.ERRO),
                "n_sem_evidencia": sum(1 for i in diagnostico.itens if "sem_evidencia" in (i.alertas or [])),
                "latencia_media_ms": int(sum(latencias) / len(latencias)) if latencias else None,
                "referencia_id": str(referencia.id) if referencia else None,
            }
        )
        return resumo

    # --- etapa 6: priorização GUT -------------------------------------------------------------
    def priorizacao(self, diagnostico_id: uuid.UUID, hoje: date | None = None) -> list[DiagnosticoItem]:
        """Itens NC e PC ordenados por G×U×T, com as sugestões de G e U atualizadas."""
        diagnostico = self.obter(diagnostico_id)
        hoje = hoje or date.today()
        data_ato = (diagnostico.escopo or {}).get("data_ato")
        itens = [i for i in diagnostico.itens if gut.priorizavel(i.classificacao_final)]
        for item in itens:
            item.gut_sugestao = gut.sugerir(item.requisito or {}, item.classificacao_final, data_ato, hoje).to_dict()
        self.session.flush()
        return sorted(itens, key=lambda i: gut.chave_ranking(i.prioridade, i.gut_g, i.gut_u, i.requisito_codigo))

    def definir_gut(self, diagnostico_id: uuid.UUID, item_id: uuid.UUID, g: int, u: int, t: int) -> DiagnosticoItem:
        diagnostico = self.obter(diagnostico_id)
        if diagnostico.status not in {DiagnosticoStatus.VALIDADO, DiagnosticoStatus.PRIORIZADO}:
            raise ConflictError("A priorização é feita depois da validação de todos os itens e antes do relatório.")
        item = self.item(diagnostico_id, item_id)
        if not gut.priorizavel(item.classificacao_final):
            raise ValidationError("Apenas itens não conformes (NC) ou parcialmente conformes (PC) são priorizados.")
        try:
            item.gut_g, item.gut_u, item.gut_t = (gut.validar_nota(n, v) for n, v in (("G", g), ("U", u), ("T", t)))
        except ValueError as exc:
            raise ValidationError(str(exc)) from None
        item.prioridade = item.gut_g * item.gut_u * item.gut_t
        self._atualizar_status_priorizacao(diagnostico)
        self.session.flush()
        return item

    def _atualizar_status_priorizacao(self, diagnostico: Diagnostico) -> None:
        alvo = [i for i in diagnostico.itens if gut.priorizavel(i.classificacao_final)]
        if all(i.prioridade is not None for i in alvo):
            diagnostico.status = DiagnosticoStatus.PRIORIZADO
        elif diagnostico.status == DiagnosticoStatus.PRIORIZADO:
            diagnostico.status = DiagnosticoStatus.VALIDADO

    # --- etapa 7: relatório -------------------------------------------------------------------------
    def relatorio(self, diagnostico_id: uuid.UUID) -> str:
        """Relatório emitido (congelado) ou, antes da emissão, uma prévia."""
        diagnostico = self.obter(diagnostico_id)
        if diagnostico.relatorio_md:
            return diagnostico.relatorio_md
        return gerar_relatorio(diagnostico)

    def emitir_relatorio(self, diagnostico_id: uuid.UUID) -> Diagnostico:
        diagnostico = self.obter(diagnostico_id)
        if diagnostico.status == DiagnosticoStatus.VALIDADO:
            # Sem itens NC/PC não há o que priorizar.
            self._atualizar_status_priorizacao(diagnostico)
        if diagnostico.status != DiagnosticoStatus.PRIORIZADO:
            raise ConflictError("Valide todos os itens e priorize os NC e PC antes de emitir o relatório.")
        emitido_em = utcnow()
        diagnostico.metricas = self.metricas(diagnostico)
        diagnostico.relatorio_md = gerar_relatorio(diagnostico, emitido_em)
        diagnostico.relatorio_emitido_em = emitido_em
        diagnostico.status = DiagnosticoStatus.RELATORIO_EMITIDO
        self.session.flush()
        return diagnostico
