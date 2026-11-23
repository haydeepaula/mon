from contextlib import contextmanager

import pytest
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import ValidationError
from app.db.models import AppSetting
from app.infrastructure.llm.factory import LLMProviderFactory
from app.services.credentials_service import CHAVE_CONFIG, CredentialStore, KeyResolver, mascarar

CHAVE = "AIzaSyTESTE-chave-de-teste-1234"


def _settings(**extra):
    chaves = {"google_api_key": None, "openai_api_key": None, "cohere_api_key": None, **extra}
    return Settings(jwt_secret="segredo-de-teste-com-tamanho-adequado", **chaves)


def test_mascara():
    assert mascarar(CHAVE) == "AIza…1234"
    assert mascarar("curta1234") == "•" * 9
    assert mascarar(None) is None


def test_chave_fica_criptografada_e_tem_prioridade_sobre_o_ambiente(db_session):
    settings = _settings(cohere_api_key="cohere-do-ambiente-xyz")
    store = CredentialStore(db_session, settings)
    store.salvar("google", f"  {CHAVE}  ")
    db_session.commit()

    bruto = db_session.get(AppSetting, CHAVE_CONFIG).value
    assert CHAVE not in str(bruto)  # nada em texto puro no banco
    assert store.cadastrada("google") == CHAVE

    status = {s["id"]: s for s in store.status()}
    assert status["google"]["origem"] == "interface" and status["google"]["mascara"] == "AIza…1234"
    assert status["cohere"]["origem"] == "ambiente" and status["cohere"]["configurada"]
    assert status["openai"]["origem"] == "nenhuma" and not status["openai"]["configurada"]
    assert all(CHAVE not in str(s) for s in status.values())

    store.remover("google")
    assert store.cadastrada("google") is None
    with pytest.raises(ValidationError):
        store.salvar("anthropic", CHAVE)
    with pytest.raises(ValidationError, match="curta"):
        store.salvar("openai", "  abc ")


def test_segredo_trocado_deixa_chave_ilegivel(db_session):
    CredentialStore(db_session, _settings()).salvar("openai", CHAVE)
    outro = CredentialStore(db_session, Settings(jwt_secret="outro-segredo-totalmente-diferente-123"))
    assert outro.cadastrada("openai") is None
    assert {s["id"]: s for s in outro.status()}["openai"]["ilegivel"]


def test_resolvedor_usa_cache_e_cai_para_o_ambiente(db_session):
    settings = _settings(openai_api_key="openai-do-ambiente-123")
    chamadas = []

    @contextmanager
    def sessao():
        chamadas.append(1)
        yield Session(bind=db_session.get_bind())

    resolver = KeyResolver(sessao, settings)
    assert resolver("openai") == "openai-do-ambiente-123"
    assert resolver("google") is None

    CredentialStore(db_session, settings).salvar("openai", CHAVE)
    db_session.commit()
    assert resolver("openai") == "openai-do-ambiente-123"  # ainda em cache
    resolver.limpar()
    assert resolver("openai") == CHAVE
    assert len(chamadas) == 3

    fabrica = LLMProviderFactory(settings, resolver)
    assert fabrica.is_configured("openai") and not fabrica.is_configured("google")


def test_resolvedor_tolera_banco_indisponivel():
    @contextmanager
    def quebrada():
        raise RuntimeError("banco fora do ar")
        yield  # pragma: no cover

    resolver = KeyResolver(quebrada, _settings(google_api_key="google-do-ambiente-123"))
    assert resolver("google") == "google-do-ambiente-123"
