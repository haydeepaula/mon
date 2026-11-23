"""Framework de critérios (TCC, seção 3.5): versões, requisitos, validação, importação e exportação."""

import json
import uuid
from datetime import date
from typing import Literal

from fastapi import APIRouter, File, Form, Query, UploadFile, status
from fastapi.responses import Response

from app.api.deps import AdminUser, DbSession
from app.api.schemas.framework import (
    FrameworkImport,
    FrameworkImportResult,
    RecuperacaoOut,
    RequisitoCreate,
    RequisitoOut,
    RequisitoUpdate,
    ValidacaoRequisitoIn,
    VersaoClone,
    VersaoCreate,
    VersaoOut,
    VersaoUpdate,
)
from app.db.models import FrameworkVersao
from app.domain.framework import FiltroRequisitos, StatusValidacao
from app.repositories.framework_repository import SqlFrameworkRepository
from app.services.framework.evidence_retrieval_service import EvidenceRetrievalService
from app.services.framework.framework_service import FrameworkService

router = APIRouter(prefix="/framework", tags=["Framework de critérios"])


def _versao_out(model: FrameworkVersao) -> VersaoOut:
    return VersaoOut(
        id=model.id,
        versao=model.versao,
        descricao=model.descricao or "",
        data_corte=model.data_corte,
        status=model.status,
        ativa=model.ativa,
        notas=model.notas,
        validado_por=model.validado_por,
        validado_em=model.validado_em,
        created_at=model.created_at,
        updated_at=model.updated_at,
        total_requisitos=len(model.requisitos),
        aprovados=sum(1 for r in model.requisitos if r.status_validacao == StatusValidacao.APROVADO),
    )


# --- versões ---------------------------------------------------------------------------
@router.get("/versoes", response_model=list[VersaoOut])
def list_versions(_: AdminUser, db: DbSession):
    return [_versao_out(v) for v in FrameworkService(db).listar_versoes()]


@router.post("/versoes", response_model=VersaoOut, status_code=status.HTTP_201_CREATED)
def create_version(body: VersaoCreate, _: AdminUser, db: DbSession):
    model = FrameworkService(db).criar_versao(body.versao, body.descricao, body.data_corte, body.ativar)
    db.commit()
    return _versao_out(model)


@router.post("/versoes/{versao_id}/clonar", response_model=VersaoOut, status_code=status.HTTP_201_CREATED)
def clone_version(versao_id: uuid.UUID, body: VersaoClone, _: AdminUser, db: DbSession):
    model = FrameworkService(db).clonar(versao_id, body.versao, body.descricao)
    db.commit()
    return _versao_out(model)


@router.patch("/versoes/{versao_id}", response_model=VersaoOut)
def update_version(versao_id: uuid.UUID, body: VersaoUpdate, user: AdminUser, db: DbSession):
    model = FrameworkService(db).atualizar_versao(versao_id, body.model_dump(exclude_unset=True), user.id)
    db.commit()
    return _versao_out(model)


@router.delete("/versoes/{versao_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_version(versao_id: uuid.UUID, _: AdminUser, db: DbSession):
    FrameworkService(db).excluir_versao(versao_id)
    db.commit()


# --- requisitos ------------------------------------------------------------------------
@router.get("/requisitos", response_model=list[RequisitoOut])
def list_requirements(
    _: AdminUser,
    db: DbSession,
    versao: str | None = None,
    tipo: list[str] = Query(default_factory=list),
    grupo: list[str] = Query(default_factory=list),
    dimensao: int | None = None,
    formato: str | None = None,
    status_validacao: str | None = None,
    incluir_tendencia: bool = True,
    q: str | None = None,
):
    filtros = FiltroRequisitos(
        versao=versao,
        tipos=tipo,
        grupos=grupo,
        dimensao_inep=dimensao,
        formato_oferta=formato,
        status_validacao=status_validacao,
        incluir_tendencia=incluir_tendencia,
        texto=q,
    )
    return SqlFrameworkRepository(db).listar(filtros)


@router.post("/requisitos", response_model=RequisitoOut, status_code=status.HTTP_201_CREATED)
def create_requirement(body: RequisitoCreate, _: AdminUser, db: DbSession, versao: str | None = None):
    requisito = FrameworkService(db).criar_requisito(versao, body.model_dump(exclude_none=True))
    db.commit()
    return requisito


@router.get("/requisitos/{codigo}", response_model=RequisitoOut)
def get_requirement(codigo: str, _: AdminUser, db: DbSession, versao: str | None = None):
    return SqlFrameworkRepository(db).obter(codigo, versao)


@router.put("/requisitos/{codigo}", response_model=RequisitoOut)
def update_requirement(codigo: str, body: RequisitoUpdate, _: AdminUser, db: DbSession, versao: str | None = None):
    requisito = FrameworkService(db).atualizar_requisito(codigo, versao, body.model_dump(exclude_unset=True))
    db.commit()
    return requisito


@router.delete("/requisitos/{codigo}", status_code=status.HTTP_204_NO_CONTENT)
def delete_requirement(codigo: str, _: AdminUser, db: DbSession, versao: str | None = None):
    FrameworkService(db).excluir_requisito(codigo, versao)
    db.commit()


@router.get("/requisitos/{codigo}/evidencias", response_model=RecuperacaoOut)
def requirement_evidence(
    codigo: str,
    _: AdminUser,
    db: DbSession,
    versao: str | None = None,
    curso: str | None = None,
    top_n: int | None = Query(None, ge=1, le=20),
    incluir_normativa: bool = False,
):
    """Evidências candidatas do requisito na coleção institucional (seção 3.6.1 b)."""
    service = EvidenceRetrievalService.from_settings(db)
    return service.recuperar_detalhado(codigo, curso, top_n, versao, incluir_normativa)


@router.patch("/requisitos/{codigo}/validacao", response_model=RequisitoOut)
def validate_requirement(
    codigo: str, body: ValidacaoRequisitoIn, _: AdminUser, db: DbSession, versao: str | None = None
):
    """Revisão do orientador (seção 3.5, passo c)."""
    requisito = FrameworkService(db).validar_requisito(codigo, versao, body.status, body.comentario)
    db.commit()
    return requisito


# --- importação e exportação -------------------------------------------------------------
@router.post("/importar", response_model=FrameworkImportResult)
def import_framework(body: FrameworkImport, _: AdminUser, db: DbSession):
    result = FrameworkService(db).importar(
        body.versao, body.requisitos, body.modo, body.descricao, body.data_corte, body.ativar
    )
    db.commit()
    return result


@router.post("/importar/csv", response_model=FrameworkImportResult)
def import_framework_csv(
    _: AdminUser,
    db: DbSession,
    file: UploadFile = File(...),
    versao: str = Form(...),
    modo: Literal["mesclar", "substituir"] = Form("mesclar"),
    descricao: str | None = Form(None),
    data_corte: date | None = Form(None),
    ativar: bool = Form(False),
):
    service = FrameworkService(db)
    itens = service.ler_csv(file.file.read())
    result = service.importar(versao, itens, modo, descricao, data_corte, ativar)
    db.commit()
    return result


@router.get("/exportar")
def export_framework(
    _: AdminUser, db: DbSession, versao: str | None = None, formato: Literal["json", "csv"] = "json"
):
    service = FrameworkService(db)
    if formato == "csv":
        conteudo = service.exportar_csv(versao)
        nome = f"framework-{versao or 'ativo'}.csv"
        return Response(
            conteudo,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{nome}"'},
        )
    dados = service.exportar(versao)
    return Response(
        json.dumps(dados, ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="framework-{dados["versao"]}.json"'},
    )
