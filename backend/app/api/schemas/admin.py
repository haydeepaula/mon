from typing import Literal

from pydantic import BaseModel, Field


class RagSettingsUpdate(BaseModel):
    """Atualização parcial das configurações do RAG."""

    llm_provider: str | None = None
    llm_model: str | None = None
    reasoning_level: Literal["low", "medium", "high"] | None = None
    system_prompt: str | None = Field(None, max_length=8000)
    retrieval_top_k: int | None = Field(None, ge=1, le=100)
    rerank_enabled: bool | None = None
    rerank_model: str | None = None
    rerank_top_n: int | None = Field(None, ge=1, le=20)
    min_relevance: float | None = Field(None, ge=0.0, le=1.0)
    query_rewrite_enabled: bool | None = None
    history_window: int | None = Field(None, ge=0, le=30)
    chunk_size: int | None = Field(None, ge=200, le=8000)
    chunk_overlap: int | None = Field(None, ge=0, le=2000)


class ProviderOut(BaseModel):
    id: str
    name: str
    configured: bool


class ModelOut(BaseModel):
    id: str
    provider: str
    display_name: str
    description: str = ""
    input_token_limit: int | None = None
    output_token_limit: int | None = None
    supports_thinking: bool | None = None
    created: int | None = None


class ModelTestRequest(BaseModel):
    provider: str
    model: str


class ModelTestResponse(BaseModel):
    ok: bool
    latency_ms: int | None = None
    reply: str | None = None
    error: str | None = None


class ApiKeyStatus(BaseModel):
    id: str
    nome: str
    uso: str
    variavel: str
    configurada: bool
    origem: Literal["interface", "ambiente", "nenhuma"]
    mascara: str | None
    atualizada_em: str | None
    ilegivel: bool


class ApiKeyIn(BaseModel):
    api_key: str = Field(min_length=8, max_length=500)
    testar: bool = True


class ApiKeyTestIn(BaseModel):
    # Sem chave, testa a chave efetiva atual do provedor.
    api_key: str | None = Field(None, min_length=8, max_length=500)


class ApiKeyTestOut(BaseModel):
    ok: bool
    detalhe: str | None = None
    erro: str | None = None
    latencia_ms: int = 0

