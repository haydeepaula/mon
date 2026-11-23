import uuid
from datetime import date, datetime, timezone
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, JsonType


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UserRole(StrEnum):
    ADMIN = "admin"
    USER = "user"


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class DocumentStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    INDEXED = "indexed"
    FAILED = "failed"


class DocumentSource(StrEnum):
    UPLOAD = "upload"
    FOLDER = "folder"


class JobType(StrEnum):
    INGEST_DOCUMENT = "ingest_document"
    SYNC_FOLDER = "sync_folder"
    REINDEX_ALL = "reindex_all"
    EVAL_RUN = "eval_run"
    EVAL_GENERATE = "eval_generate"
    DIAGNOSTICO_VERIFICAR = "diagnostico_verificar"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(160), default="")
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default=UserRole.USER)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Conversation(TimestampMixin, Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200), default="Nova conversa")

    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.created_at",
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text, default="")
    sources: Mapped[list] = mapped_column(JsonType, default=list)
    # Metadados da geração: modelo, latências, consulta reescrita.
    details: Mapped[dict] = mapped_column(JsonType, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class Document(TimestampMixin, Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    filename: Mapped[str] = mapped_column(String(255), index=True)
    file_type: Mapped[str] = mapped_column(String(20))
    mime_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    storage_path: Mapped[str] = mapped_column(String(500))
    source: Mapped[str] = mapped_column(String(20), default=DocumentSource.UPLOAD)
    source_path: Mapped[str | None] = mapped_column(String(500), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default=DocumentStatus.PENDING, index=True)
    # Versão dos vetores ativos no Qdrant; muda a cada reindexação.
    version: Mapped[int] = mapped_column(Integer, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ocr_pages: Mapped[int] = mapped_column(Integer, default=0)
    # Coleção lógica (normativa | institucional), tipo do documento e curso: ver domain/knowledge_base.py.
    colecao: Mapped[str] = mapped_column(String(20), default="institucional", server_default="institucional", index=True)
    tipo_documento: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    curso: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    extraction: Mapped[dict] = mapped_column(JsonType, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    type: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(20), default=JobStatus.QUEUED, index=True)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    payload: Mapped[dict] = mapped_column(JsonType, default=dict)
    result: Mapped[dict | None] = mapped_column(JsonType, nullable=True)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    log: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[dict] = mapped_column(JsonType)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class EvalCase(TimestampMixin, Base):
    __tablename__ = "eval_cases"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    question: Mapped[str] = mapped_column(Text)
    expected_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    expected_documents: Mapped[list] = mapped_column(JsonType, default=list)
    tags: Mapped[list] = mapped_column(JsonType, default=list)


class EvalRun(Base):
    __tablename__ = "eval_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(20), default=JobStatus.QUEUED)
    config: Mapped[dict] = mapped_column(JsonType, default=dict)
    metrics: Mapped[dict] = mapped_column(JsonType, default=dict)
    case_count: Mapped[int] = mapped_column(Integer, default=0)
    job_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    results: Mapped[list["EvalResult"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="EvalResult.position"
    )


class EvalResult(Base):
    __tablename__ = "eval_results"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("eval_runs.id", ondelete="CASCADE"), index=True)
    case_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("eval_cases.id", ondelete="SET NULL"), nullable=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0)
    question: Mapped[str] = mapped_column(Text)
    expected_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    expected_documents: Mapped[list] = mapped_column(JsonType, default=list)
    answer: Mapped[str] = mapped_column(Text, default="")
    retrieved: Mapped[list] = mapped_column(JsonType, default=list)
    metrics: Mapped[dict] = mapped_column(JsonType, default=dict)
    judge_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    run: Mapped[EvalRun] = relationship(back_populates="results")


class FrameworkVersao(TimestampMixin, Base):
    """Versão do framework de critérios. Versões validadas ou arquivadas são imutáveis."""

    __tablename__ = "framework_versoes"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    versao: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    descricao: Mapped[str] = mapped_column(Text, default="")
    data_corte: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="rascunho")
    ativa: Mapped[bool] = mapped_column(Boolean, default=False)
    notas: Mapped[str | None] = mapped_column(Text, nullable=True)
    validado_por: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    validado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    requisitos: Mapped[list["RequisitoModel"]] = relationship(
        back_populates="framework",
        cascade="all, delete-orphan",
        order_by=lambda: [RequisitoModel.ordem, RequisitoModel.codigo],
    )


class RequisitoModel(TimestampMixin, Base):
    """Requisito do framework (TCC, seção 3.5 e Quadro 6). Campos descritos em domain/framework.py."""

    __tablename__ = "requisitos"
    __table_args__ = (UniqueConstraint("framework_id", "codigo", name="uq_requisito_versao_codigo"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    framework_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("framework_versoes.id", ondelete="CASCADE"), index=True
    )
    codigo: Mapped[str] = mapped_column(String(40), index=True)
    grupo: Mapped[str] = mapped_column(String(20), index=True)
    fonte_documento: Mapped[str] = mapped_column(String(300))
    fonte_dispositivo: Mapped[str | None] = mapped_column(String(300), nullable=True)
    texto: Mapped[str] = mapped_column(Text)
    tipo: Mapped[str] = mapped_column(String(20), index=True)
    dimensao_inep: Mapped[int | None] = mapped_column(Integer, nullable=True)
    indicador_inep: Mapped[str | None] = mapped_column(String(20), nullable=True)
    evidencia_esperada: Mapped[str] = mapped_column(Text)
    documentos_provaveis: Mapped[list] = mapped_column(JsonType, default=list)
    consulta_padrao: Mapped[str | None] = mapped_column(Text, nullable=True)
    termos_chave: Mapped[list] = mapped_column(JsonType, default=list)
    gravidade_base: Mapped[int | None] = mapped_column(Integer, nullable=True)
    peso_dimensao: Mapped[int | None] = mapped_column(Integer, nullable=True)
    aplicabilidade: Mapped[dict] = mapped_column(JsonType, default=dict)
    situacao_normativa: Mapped[str] = mapped_column(String(20), default="vigente")
    prazo_referencia: Mapped[date | None] = mapped_column(Date, nullable=True)
    status_validacao: Mapped[str] = mapped_column(String(20), default="pendente", index=True)
    comentario_validacao: Mapped[str | None] = mapped_column(Text, nullable=True)
    ordem: Mapped[int] = mapped_column(Integer, default=0)

    framework: Mapped[FrameworkVersao] = relationship(back_populates="requisitos")


class Diagnostico(TimestampMixin, Base):
    """Execução do processo de diagnóstico para um curso (TCC, seção 3.7, Quadro 9)."""

    __tablename__ = "diagnosticos"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    nome: Mapped[str] = mapped_column(String(200))
    curso: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    curso_nome: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Plano de diagnóstico (etapa 1): formato de oferta, próximo ato regulatório, filtros...
    escopo: Mapped[dict] = mapped_column(JsonType, default=dict)
    framework_versao: Mapped[str] = mapped_column(String(40))
    # Reprodutibilidade (seção 3.8): modelo, provedor, parâmetros, hash do prompt, base indexada.
    config: Mapped[dict] = mapped_column(JsonType, default=dict)
    status: Mapped[str] = mapped_column(String(30), default="planejamento", index=True)
    job_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    metricas: Mapped[dict] = mapped_column(JsonType, default=dict)
    relatorio_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    relatorio_emitido_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    devolutiva: Mapped[dict] = mapped_column(JsonType, default=dict)
    # Diagnóstico de referência (decisões do consultor) quando este é uma variação de configuração.
    referencia_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("diagnosticos.id", ondelete="SET NULL"), nullable=True
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    itens: Mapped[list["DiagnosticoItem"]] = relationship(
        back_populates="diagnostico",
        cascade="all, delete-orphan",
        order_by=lambda: [DiagnosticoItem.ordem, DiagnosticoItem.requisito_codigo],
    )


class DiagnosticoItem(Base):
    """Um requisito no diagnóstico: proposta do protótipo, decisão do consultor e priorização.

    A proposta nunca é sobrescrita pela validação (TCC, seção 3.6.1 d).
    """

    __tablename__ = "diagnostico_itens"
    __table_args__ = (UniqueConstraint("diagnostico_id", "requisito_codigo", name="uq_item_diagnostico_requisito"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    diagnostico_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("diagnosticos.id", ondelete="CASCADE"), index=True)
    requisito_codigo: Mapped[str] = mapped_column(String(40))
    # Cópia do requisito no momento da criação: o framework pode mudar depois.
    requisito: Mapped[dict] = mapped_column(JsonType, default=dict)
    ordem: Mapped[int] = mapped_column(Integer, default=0)

    # Etapa 4: verificação assistida.
    consulta: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidencias: Mapped[list] = mapped_column(JsonType, default=list)
    normativos: Mapped[list] = mapped_column(JsonType, default=list)
    proposta: Mapped[dict] = mapped_column(JsonType, default=dict)
    resposta_bruta: Mapped[str | None] = mapped_column(Text, nullable=True)
    classificacao_proposta: Mapped[str | None] = mapped_column(String(4), nullable=True)
    conceito_proposto: Mapped[int | None] = mapped_column(Integer, nullable=True)
    proposta_status: Mapped[str] = mapped_column(String(20), default="pendente")
    alertas: Mapped[list] = mapped_column(JsonType, default=list)
    erro: Mapped[str | None] = mapped_column(Text, nullable=True)
    latencia_ms: Mapped[int] = mapped_column(Integer, default=0)
    gerado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Etapa 5: validação pelo consultor.
    classificacao_final: Mapped[str | None] = mapped_column(String(4), nullable=True)
    conceito_final: Mapped[int | None] = mapped_column(Integer, nullable=True)
    divergencia_causa: Mapped[str | None] = mapped_column(String(20), nullable=True)
    comentario: Mapped[str | None] = mapped_column(Text, nullable=True)
    validado_por: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    validado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Etapa 6: priorização GUT (apenas itens NC e PC).
    gut_g: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gut_u: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gut_t: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gut_sugestao: Mapped[dict] = mapped_column(JsonType, default=dict)
    prioridade: Mapped[int | None] = mapped_column(Integer, nullable=True)

    diagnostico: Mapped[Diagnostico] = relationship(back_populates="itens")

