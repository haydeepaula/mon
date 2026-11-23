from fastapi import APIRouter

from app.api.deps import AdminUser, DbSession
from app.api.schemas.admin import (
    ApiKeyIn,
    ApiKeyStatus,
    ApiKeyTestIn,
    ApiKeyTestOut,
    ModelOut,
    ModelTestRequest,
    ModelTestResponse,
    ProviderOut,
    RagSettingsUpdate,
)
from app.core.exceptions import ValidationError
from app.services.credentials_service import CredentialStore, get_key_resolver, obter_provedor, testar_chave
from app.services.model_catalog_service import ModelCatalogService
from app.services.settings_service import RagSettings, SettingsService

router = APIRouter(prefix="/admin", tags=["Administração"])


@router.get("/settings", response_model=RagSettings)
def get_settings(_: AdminUser, db: DbSession):
    return SettingsService(db).get_rag()


@router.put("/settings", response_model=RagSettings)
def update_settings(body: RagSettingsUpdate, _: AdminUser, db: DbSession):
    return SettingsService(db).update_rag(body.model_dump(exclude_none=True))


@router.get("/providers", response_model=list[ProviderOut])
def list_providers(_: AdminUser):
    return ModelCatalogService().providers()


@router.get("/models/{provider}", response_model=list[ModelOut])
def list_models(provider: str, _: AdminUser):
    return ModelCatalogService().list_models(provider)


@router.post("/models/test", response_model=ModelTestResponse)
def test_model(body: ModelTestRequest, _: AdminUser):
    try:
        return ModelCatalogService().test(body.provider, body.model)
    except Exception as exc:
        return ModelTestResponse(ok=False, error=getattr(exc, "message", None) or str(exc))


# --- chaves de API -------------------------------------------------------------------------------
@router.get("/api-keys", response_model=list[ApiKeyStatus])
def list_api_keys(_: AdminUser, db: DbSession):
    """Situação das chaves (mascaradas): cadastrada na interface, vinda do ambiente ou ausente."""
    return CredentialStore(db).status()


@router.put("/api-keys/{provider}", response_model=list[ApiKeyStatus])
def save_api_key(provider: str, body: ApiKeyIn, _: AdminUser, db: DbSession):
    """Cadastra ou substitui a chave. Por padrão, testa no provedor antes de gravar."""
    obter_provedor(provider)
    if body.testar:
        resultado = testar_chave(provider, body.api_key.strip(), SettingsService(db).get_rag().rerank_model)
        if not resultado["ok"]:
            raise ValidationError(f"A chave não funcionou: {resultado['erro']}")
    store = CredentialStore(db)
    store.salvar(provider, body.api_key)
    db.commit()
    return store.status()


@router.delete("/api-keys/{provider}", response_model=list[ApiKeyStatus])
def delete_api_key(provider: str, _: AdminUser, db: DbSession):
    """Remove a chave cadastrada; volta a valer a variável de ambiente, se houver."""
    store = CredentialStore(db)
    store.remover(provider)
    db.commit()
    return store.status()


@router.post("/api-keys/{provider}/test", response_model=ApiKeyTestOut)
def test_api_key(provider: str, body: ApiKeyTestIn, _: AdminUser, db: DbSession):
    obter_provedor(provider)
    chave = body.api_key.strip() if body.api_key else get_key_resolver()(provider)
    if not chave:
        return ApiKeyTestOut(ok=False, erro="Nenhuma chave configurada para este provedor.")
    return testar_chave(provider, chave, SettingsService(db).get_rag().rerank_model)

