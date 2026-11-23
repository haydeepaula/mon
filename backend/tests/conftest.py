import os
import sys
from pathlib import Path

os.environ.setdefault("JWT_SECRET", "segredo-de-teste-com-tamanho-adequado-para-hs256")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


import pytest  # noqa: E402


@pytest.fixture()
def db_session():
    """Sessão SQLite em memória com todas as tabelas (testes de serviço sem Postgres)."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import StaticPool

    from app.db import models  # noqa: F401
    from app.db.base import Base

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = Session(engine, autoflush=False, expire_on_commit=False)
    yield session
    session.close()
    engine.dispose()
