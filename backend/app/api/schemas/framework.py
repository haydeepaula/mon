import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.api.schemas.common import ORMModel


class VersaoOut(BaseModel):
    id: uuid.UUID
    versao: str
    descricao: str
    data_corte: date | None
    status: str
    ativa: bool
    notas: str | None
    validado_por: uuid.UUID | None
    validado_em: datetime | None
    created_at: datetime
    updated_at: datetime
    total_requisitos: int
    aprovados: int


class VersaoCreate(BaseModel):
    versao: str = Field(min_length=1, max_length=40)
    descricao: str = Field("", max_length=4000)
    data_corte: date | None = None
    ativar: bool = False


class VersaoClone(BaseModel):
    versao: str = Field(min_length=1, max_length=40)
    descricao: str | None = Field(None, max_length=4000)


class VersaoUpdate(BaseModel):
    status: Literal["rascunho", "em_validacao", "validado", "arquivado"] | None = None
    ativa: bool | None = None
    descricao: str | None = Field(None, max_length=4000)
    notas: str | None = Field(None, max_length=8000)
    data_corte: date | None = None


class RequisitoBase(BaseModel):
    grupo: str | None = Field(None, max_length=20)
    fonte_documento: str | None = Field(None, max_length=300)
    fonte_dispositivo: str | None = Field(None, max_length=300)
    texto: str | None = Field(None, max_length=4000)
    tipo: Literal["legal", "qualidade", "competencia"] | None = None
    dimensao_inep: int | None = Field(None, ge=1, le=4)
    indicador_inep: str | None = Field(None, max_length=20)
    evidencia_esperada: str | None = Field(None, max_length=4000)
    documentos_provaveis: list[str] | None = None
    consulta_padrao: str | None = Field(None, max_length=2000)
    termos_chave: list[str] | None = None
    gravidade_base: int | None = Field(None, ge=1, le=5)
    peso_dimensao: int | None = Field(None, ge=1, le=100)
    formatos: list[str] | None = None
    situacao_normativa: Literal["vigente", "tendencia"] | None = None
    prazo_referencia: date | None = None
    ordem: int | None = Field(None, ge=0)


class RequisitoCreate(RequisitoBase):
    codigo: str = Field(min_length=3, max_length=40)
    fonte_documento: str = Field(min_length=1, max_length=300)
    texto: str = Field(min_length=1, max_length=4000)
    tipo: Literal["legal", "qualidade", "competencia"]
    evidencia_esperada: str = Field(min_length=1, max_length=4000)


class RequisitoUpdate(RequisitoBase):
    """Atualização parcial: apenas os campos enviados são alterados."""


class RequisitoOut(ORMModel):
    codigo: str
    grupo: str
    fonte_documento: str
    fonte_dispositivo: str | None
    texto: str
    tipo: str
    dimensao_inep: int | None
    indicador_inep: str | None
    evidencia_esperada: str
    documentos_provaveis: list[str]
    consulta_padrao: str | None
    termos_chave: list[str]
    gravidade_base: int | None
    peso_dimensao: int | None
    formatos: list[str]
    situacao_normativa: str
    prazo_referencia: date | None
    status_validacao: str
    comentario_validacao: str | None
    ordem: int
    versao: str | None


class ValidacaoRequisitoIn(BaseModel):
    status: Literal["pendente", "aprovado", "ajustar"]
    comentario: str | None = Field(None, max_length=4000)


class FrameworkImport(BaseModel):
    versao: str = Field(min_length=1, max_length=40)
    descricao: str | None = Field(None, max_length=4000)
    data_corte: date | None = None
    modo: Literal["mesclar", "substituir"] = "mesclar"
    ativar: bool = False
    requisitos: list[dict[str, Any]] = Field(min_length=1, max_length=2000)


class FrameworkImportResult(BaseModel):
    versao: str
    criados: int
    atualizados: int
    total: int


class EvidenciaOut(ORMModel):
    documento: str
    trecho: str
    score: float
    chunk_id: str
    pagina: int | None
    document_id: str | None
    versao: int | None
    sha256: str | None
    ocr: bool
    colecao: str | None
    tipo_documento: str | None
    localizacao: str | None
    vector_score: float | None
    rerank_score: float | None


class RecuperacaoOut(ORMModel):
    requisito: RequisitoOut
    consulta: str
    evidencias: list[EvidenciaOut]
    normativos: list[EvidenciaOut]
    timings_ms: dict[str, int]
    config: dict[str, Any]
