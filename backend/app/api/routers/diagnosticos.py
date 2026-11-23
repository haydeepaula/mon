"""Processo de diagnóstico (TCC, seção 3.7, Quadro 9)."""

import uuid
from collections import Counter

from fastapi import APIRouter, status
from fastapi.responses import Response

from app.api.deps import AdminUser, DbSession
from app.api.schemas.diagnosticos import (
    DiagnosticoCreate,
    DiagnosticoOut,
    DiagnosticoUpdate,
    EscopoIn,
    GutIn,
    ItemOut,
    ValidacaoIn,
    VerificarIn,
)
from app.api.schemas.framework import RequisitoOut
from app.api.schemas.jobs import JobOut
from app.db.models import Diagnostico, DiagnosticoItem
from app.services.diagnostico.diagnostico_service import DiagnosticoService

router = APIRouter(prefix="/diagnosticos", tags=["Diagnóstico"])


def _resumo(diagnostico: Diagnostico) -> dict:
    itens = diagnostico.itens
    return {
        "total": len(itens),
        "propostas": dict(Counter(i.proposta_status for i in itens)),
        "validados": sum(1 for i in itens if i.classificacao_final),
        "classificacao_final": dict(Counter(i.classificacao_final for i in itens if i.classificacao_final)),
        "priorizados": sum(1 for i in itens if i.prioridade is not None),
    }


def diagnostico_out(diagnostico: Diagnostico) -> DiagnosticoOut:
    return DiagnosticoOut(
        id=diagnostico.id,
        nome=diagnostico.nome,
        curso=diagnostico.curso,
        curso_nome=diagnostico.curso_nome,
        escopo=diagnostico.escopo or {},
        framework_versao=diagnostico.framework_versao,
        config={k: v for k, v in (diagnostico.config or {}).items() if k != "execucoes"},
        status=diagnostico.status,
        job_id=diagnostico.job_id,
        metricas=diagnostico.metricas or {},
        relatorio_emitido_em=diagnostico.relatorio_emitido_em,
        devolutiva=diagnostico.devolutiva or {},
        referencia_id=diagnostico.referencia_id,
        created_at=diagnostico.created_at,
        updated_at=diagnostico.updated_at,
        resumo=_resumo(diagnostico),
    )


def item_out(item: DiagnosticoItem, escopo: dict) -> ItemOut:
    # Validação cega: a proposta só aparece depois que o consultor registra a própria decisão.
    oculta = bool(escopo.get("validacao_cega")) and not item.classificacao_final
    evidencias = item.evidencias or []
    if oculta:
        evidencias = [{k: v for k, v in e.items() if k not in ("score", "rerank_score", "vector_score")} for e in evidencias]
    return ItemOut(
        id=item.id,
        requisito_codigo=item.requisito_codigo,
        requisito=item.requisito or {},
        ordem=item.ordem,
        consulta=item.consulta,
        evidencias=evidencias,
        normativos=item.normativos or [],
        proposta_status=item.proposta_status,
        proposta_oculta=oculta,
        proposta=None if oculta else (item.proposta or None),
        classificacao_proposta=None if oculta else item.classificacao_proposta,
        conceito_proposto=None if oculta else item.conceito_proposto,
        alertas=[] if oculta else list(item.alertas or []),
        erro=item.erro,
        latencia_ms=item.latencia_ms,
        gerado_em=item.gerado_em,
        classificacao_final=item.classificacao_final,
        conceito_final=item.conceito_final,
        divergencia_causa=item.divergencia_causa,
        comentario=item.comentario,
        validado_em=item.validado_em,
        gut_g=item.gut_g,
        gut_u=item.gut_u,
        gut_t=item.gut_t,
        gut_sugestao=item.gut_sugestao or {},
        prioridade=item.prioridade,
    )


# --- etapa 1: planejamento -----------------------------------------------------------------
@router.get("", response_model=list[DiagnosticoOut])
def list_diagnostics(_: AdminUser, db: DbSession):
    return [diagnostico_out(d) for d in DiagnosticoService(db).listar()]


@router.post("/requisitos-aplicaveis", response_model=list[RequisitoOut])
def applicable_requirements(body: EscopoIn, _: AdminUser, db: DbSession, versao: str | None = None):
    """Prévia dos requisitos que entrarão no diagnóstico com esse escopo."""
    return DiagnosticoService(db).requisitos_aplicaveis(body.model_dump(mode="json"), versao)


@router.post("", response_model=DiagnosticoOut, status_code=status.HTTP_201_CREATED)
def create_diagnostic(body: DiagnosticoCreate, user: AdminUser, db: DbSession):
    diagnostico = DiagnosticoService(db).criar(body.model_dump(mode="json"), user.id)
    db.commit()
    return diagnostico_out(diagnostico)


@router.get("/{diagnostico_id}", response_model=DiagnosticoOut)
def get_diagnostic(diagnostico_id: uuid.UUID, _: AdminUser, db: DbSession):
    return diagnostico_out(DiagnosticoService(db).obter(diagnostico_id))


@router.patch("/{diagnostico_id}", response_model=DiagnosticoOut)
def update_diagnostic(diagnostico_id: uuid.UUID, body: DiagnosticoUpdate, _: AdminUser, db: DbSession):
    diagnostico = DiagnosticoService(db).atualizar(diagnostico_id, body.model_dump(mode="json", exclude_unset=True))
    db.commit()
    return diagnostico_out(diagnostico)


@router.delete("/{diagnostico_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_diagnostic(diagnostico_id: uuid.UUID, _: AdminUser, db: DbSession):
    DiagnosticoService(db).excluir(diagnostico_id)
    db.commit()


# --- etapa 4: verificação assistida -------------------------------------------------------------
@router.post("/{diagnostico_id}/verificar", response_model=JobOut)
def verify(diagnostico_id: uuid.UUID, body: VerificarIn, user: AdminUser, db: DbSession):
    job = DiagnosticoService(db).iniciar_verificacao(diagnostico_id, body.item_ids, user.id)
    db.commit()
    return job


@router.get("/{diagnostico_id}/itens", response_model=list[ItemOut])
def list_items(diagnostico_id: uuid.UUID, _: AdminUser, db: DbSession):
    diagnostico = DiagnosticoService(db).obter(diagnostico_id)
    return [item_out(i, diagnostico.escopo or {}) for i in diagnostico.itens]


@router.get("/{diagnostico_id}/itens/{item_id}", response_model=ItemOut)
def get_item(diagnostico_id: uuid.UUID, item_id: uuid.UUID, _: AdminUser, db: DbSession):
    service = DiagnosticoService(db)
    return item_out(service.item(diagnostico_id, item_id), service.obter(diagnostico_id).escopo or {})


# --- etapa 5: validação ---------------------------------------------------------------------------
@router.put("/{diagnostico_id}/itens/{item_id}/validacao", response_model=ItemOut)
def validate_item(diagnostico_id: uuid.UUID, item_id: uuid.UUID, body: ValidacaoIn, user: AdminUser, db: DbSession):
    service = DiagnosticoService(db)
    item = service.validar_item(
        diagnostico_id, item_id, body.classificacao_final, body.conceito_final,
        body.divergencia_causa, body.comentario, user.id,
    )
    db.commit()
    return item_out(item, service.obter(diagnostico_id).escopo or {})


# --- etapa 6: priorização GUT --------------------------------------------------------------------
@router.get("/{diagnostico_id}/priorizacao", response_model=list[ItemOut])
def prioritization(diagnostico_id: uuid.UUID, _: AdminUser, db: DbSession):
    """Itens NC e PC em ordem de prioridade, com sugestões de G e U."""
    service = DiagnosticoService(db)
    itens = service.priorizacao(diagnostico_id)
    db.commit()
    escopo = service.obter(diagnostico_id).escopo or {}
    return [item_out(i, escopo) for i in itens]


@router.put("/{diagnostico_id}/itens/{item_id}/gut", response_model=ItemOut)
def set_gut(diagnostico_id: uuid.UUID, item_id: uuid.UUID, body: GutIn, _: AdminUser, db: DbSession):
    service = DiagnosticoService(db)
    item = service.definir_gut(diagnostico_id, item_id, body.g, body.u, body.t)
    db.commit()
    return item_out(item, service.obter(diagnostico_id).escopo or {})


# --- etapa 7: relatório ------------------------------------------------------------------------------
@router.post("/{diagnostico_id}/relatorio", response_model=DiagnosticoOut)
def issue_report(diagnostico_id: uuid.UUID, _: AdminUser, db: DbSession):
    """Emite e congela o relatório; validação e priorização ficam bloqueadas."""
    diagnostico = DiagnosticoService(db).emitir_relatorio(diagnostico_id)
    db.commit()
    return diagnostico_out(diagnostico)


@router.get("/{diagnostico_id}/relatorio")
def get_report(diagnostico_id: uuid.UUID, _: AdminUser, db: DbSession, download: bool = False):
    """Relatório em Markdown: o emitido ou, antes da emissão, uma prévia."""
    conteudo = DiagnosticoService(db).relatorio(diagnostico_id)
    headers = {"Content-Disposition": f'attachment; filename="relatorio-{diagnostico_id}.md"'} if download else None
    return Response(conteudo, media_type="text/markdown; charset=utf-8", headers=headers)


# --- seção 3.8, nível 2 ---------------------------------------------------------------------------
@router.get("/{diagnostico_id}/metricas")
def metrics(diagnostico_id: uuid.UUID, _: AdminUser, db: DbSession, referencia: uuid.UUID | None = None):
    service = DiagnosticoService(db)
    diagnostico = service.obter(diagnostico_id)
    return service.metricas(diagnostico, service.obter(referencia) if referencia else None)
