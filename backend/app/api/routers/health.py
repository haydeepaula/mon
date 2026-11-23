from fastapi import APIRouter
from sqlalchemy import text

from app.api.deps import DbSession
from app.container import get_vector_store
from app.services.credentials_service import PROVEDORES, get_key_resolver

router = APIRouter(tags=["Saúde"])


@router.get("/health")
def health(db: DbSession):
    resolver = get_key_resolver()
    try:
        db.execute(text("SELECT 1"))
        database = True
    except Exception:
        database = False
    return {
        "status": "ok",
        "database": database,
        "qdrant": get_vector_store().is_healthy(),
        "providers": {provider: bool(resolver(provider)) for provider in PROVEDORES},
    }
