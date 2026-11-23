import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

Formato = Literal["presencial", "semipresencial", "distancia"]
Ato = Literal["autorizacao", "reconhecimento", "renovacao", "outro"]
ClassificacaoLiteral = Literal["C", "PC", "NC", "EI"]
CausaLiteral = Literal["recuperacao", "ocr", "chunking", "geracao", "interpretacao"]


class EscopoIn(BaseModel):
    """Plano de diagnóstico (Quadro 9, etapa 1)."""

    formato_oferta: Formato | None = None
    proximo_ato: Ato | None = None
    data_ato: date | None = None
    incluir_tendencia: bool = False
    tipos: list[Literal["legal", "qualidade", "competencia"]] = []
    grupos: list[str] = []
    codigos: list[str] = []
    validacao_cega: bool = False
    incluir_normativa: bool = True
    observacoes: str | None = Field(None, max_length=4000)


class DiagnosticoCreate(BaseModel):
    nome: str | None = Field(None, max_length=200)
    curso: str | None = Field(None, max_length=80)
    curso_nome: str | None = Field(None, max_length=200)
    framework_versao: str | None = Field(None, max_length=40)
    escopo: EscopoIn = EscopoIn()


class DiagnosticoUpdate(BaseModel):
    nome: str | None = Field(None, max_length=200)
    curso: str | None = Field(None, max_length=80)
    curso_nome: str | None = Field(None, max_length=200)
    framework_versao: str | None = Field(None, max_length=40)
    escopo: EscopoIn | None = None


class DiagnosticoOut(BaseModel):
    id: uuid.UUID
    nome: str
    curso: str | None
    curso_nome: str | None
    escopo: dict[str, Any]
    framework_versao: str
    config: dict[str, Any]
    status: str
    job_id: uuid.UUID | None
    metricas: dict[str, Any]
    relatorio_emitido_em: datetime | None
    devolutiva: dict[str, Any]
    referencia_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    resumo: dict[str, Any]


class ItemOut(BaseModel):
    id: uuid.UUID
    requisito_codigo: str
    requisito: dict[str, Any]
    ordem: int
    consulta: str | None
    evidencias: list[dict[str, Any]]
    normativos: list[dict[str, Any]]
    proposta_status: str
    proposta_oculta: bool
    proposta: dict[str, Any] | None
    classificacao_proposta: str | None
    conceito_proposto: int | None
    alertas: list[str]
    erro: str | None
    latencia_ms: int
    gerado_em: datetime | None
    classificacao_final: str | None
    conceito_final: int | None
    divergencia_causa: str | None
    comentario: str | None
    validado_em: datetime | None
    gut_g: int | None
    gut_u: int | None
    gut_t: int | None
    gut_sugestao: dict[str, Any]
    prioridade: int | None


class VerificarIn(BaseModel):
    item_ids: list[uuid.UUID] | None = None


class ValidacaoIn(BaseModel):
    classificacao_final: ClassificacaoLiteral
    conceito_final: int | None = Field(None, ge=1, le=5)
    divergencia_causa: CausaLiteral | None = None
    comentario: str | None = Field(None, max_length=4000)


class GutIn(BaseModel):
    g: int = Field(ge=1, le=5)
    u: int = Field(ge=1, le=5)
    t: int = Field(ge=1, le=5)


class DevolutivaIn(BaseModel):
    data: date | None = None
    participantes: list[str] = []
    resultado: Literal["aceito", "revisado"]
    observacoes: str | None = Field(None, max_length=8000)


class ClonarIn(BaseModel):
    nome: str | None = Field(None, max_length=200)
    llm_provider: str | None = Field(None, max_length=40)
    llm_model: str | None = Field(None, max_length=120)
    reasoning_level: Literal["low", "medium", "high"] | None = None

