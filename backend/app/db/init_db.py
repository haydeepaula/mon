import logging
import time

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import models  # noqa: F401  (registra as tabelas no metadata)
from app.db.base import Base, engine

logger = logging.getLogger(__name__)

_INIT_LOCK_KEY = 724001

# Colunas acrescentadas a tabelas existentes. O projeto não usa Alembic: create_all só cria
# tabelas novas, então colunas novas entram aqui (idempotente; apenas PostgreSQL).
_SCHEMA_UPGRADES = (
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS colecao VARCHAR(20) NOT NULL DEFAULT 'institucional'",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS tipo_documento VARCHAR(40)",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS curso VARCHAR(80)",
    "CREATE INDEX IF NOT EXISTS ix_documents_colecao ON documents (colecao)",
    "CREATE INDEX IF NOT EXISTS ix_documents_tipo_documento ON documents (tipo_documento)",
    "CREATE INDEX IF NOT EXISTS ix_documents_curso ON documents (curso)",
)


def wait_for_database(timeout: int = 60) -> None:
    deadline = time.monotonic() + timeout
    while True:
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            return
        except Exception:
            if time.monotonic() > deadline:
                raise
            logger.info("Aguardando o banco de dados...")
            time.sleep(2)


def init_database() -> None:
    """Cria tabelas e dados iniciais. O advisory lock evita corrida entre API e worker."""
    from app.services.auth_service import AuthService
    from app.services.settings_service import SettingsService

    wait_for_database()
    with engine.begin() as connection:
        if connection.dialect.name == "postgresql":
            connection.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _INIT_LOCK_KEY})
        Base.metadata.create_all(connection)
        _upgrade_schema(connection)
        with Session(bind=connection) as session:
            AuthService(session).ensure_admin()
            SettingsService(session).ensure_defaults()
            session.flush()


def _upgrade_schema(connection) -> None:
    if connection.dialect.name != "postgresql":
        return
    for statement in _SCHEMA_UPGRADES:
        connection.execute(text(statement))


def sync_vector_payloads() -> int:
    """Replica no Qdrant a classificação (coleção, tipo, curso) registrada no banco.

    Necessário para pontos indexados antes da existência desses campos; é idempotente.
    """
    from app.container import get_vector_store
    from app.db.base import SessionLocal
    from app.db.models import Document, DocumentStatus
    from app.services.ingestion_service import vector_payload

    store = get_vector_store()
    with SessionLocal() as session:
        documents = session.query(Document).filter(Document.status == DocumentStatus.INDEXED).all()
        for document in documents:
            store.set_payload(str(document.id), vector_payload(document))
    return len(documents)


def ensure_vector_collection(timeout: int = 60) -> None:
    from app.container import get_vector_store

    store = get_vector_store()
    deadline = time.monotonic() + timeout
    while True:
        try:
            store.ensure_collection()
            break
        except Exception:
            if time.monotonic() > deadline:
                logger.exception("Qdrant indisponível.")
                return
            logger.info("Aguardando o Qdrant...")
            time.sleep(2)
    try:
        logger.info("Classificação replicada no Qdrant para %s documento(s).", sync_vector_payloads())
    except Exception:
        logger.exception("Falha ao replicar a classificação dos documentos no Qdrant.")
