"""Chaves de API dos provedores (Google, OpenAI, Cohere), cadastráveis pela interface.

- As chaves cadastradas ficam na tabela ``app_settings`` **criptografadas** (Fernet, AES-128 com
  HMAC), com a chave derivada de ``JWT_SECRET``. A API nunca devolve a chave completa.
- Prioridade: chave cadastrada na interface; na falta dela, a variável de ambiente (``.env``).
- API e worker são processos distintos: a resolução usa um cache curto (``CACHE_SEGUNDOS``), de modo
  que uma chave nova passa a valer em ambos sem reiniciar os contêineres.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import threading
import time
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timezone

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.exceptions import ValidationError
from app.repositories.settings_repository import SettingsRepository

logger = logging.getLogger(__name__)

CHAVE_CONFIG = "api_keys"
CACHE_SEGUNDOS = 10.0


@dataclass(frozen=True)
class Provedor:
    id: str
    nome: str
    uso: str
    variavel: str  # variável de ambiente
    campo: str  # atributo em Settings


PROVEDORES: dict[str, Provedor] = {
    "google": Provedor("google", "Google Gemini", "LLM e embeddings (obrigatória para indexar e buscar)", "GOOGLE_API_KEY", "google_api_key"),
    "openai": Provedor("openai", "OpenAI", "LLM alternativo", "OPENAI_API_KEY", "openai_api_key"),
    "cohere": Provedor("cohere", "Cohere", "Rerank de trechos", "COHERE_API_KEY", "cohere_api_key"),
}


def _fernet(settings: Settings) -> Fernet:
    material = hashlib.sha256(f"mon-api-keys:{settings.jwt_secret}".encode()).digest()
    return Fernet(base64.urlsafe_b64encode(material))


def mascarar(chave: str | None) -> str | None:
    if not chave:
        return None
    if len(chave) <= 12:
        return "•" * len(chave)
    return f"{chave[:4]}…{chave[-4:]}"


def obter_provedor(provedor: str) -> Provedor:
    try:
        return PROVEDORES[provedor]
    except KeyError:
        raise ValidationError(f"Provedor desconhecido: {provedor}. Use: {', '.join(PROVEDORES)}.") from None


class CredentialStore:
    """Leitura e gravação das chaves cadastradas, dentro de uma sessão do banco."""

    def __init__(self, session: Session, settings: Settings | None = None):
        self.session = session
        self.settings = settings or get_settings()
        self.repo = SettingsRepository(session)

    def _registros(self) -> dict:
        return dict(self.repo.get_value(CHAVE_CONFIG) or {})

    def cadastrada(self, provedor: str) -> str | None:
        registro = self._registros().get(provedor)
        if not registro:
            return None
        try:
            return _fernet(self.settings).decrypt(registro["cifrada"].encode()).decode()
        except (InvalidToken, KeyError, ValueError):
            # Ex.: JWT_SECRET mudou depois do cadastro. A chave precisa ser cadastrada de novo.
            logger.warning("Chave de API cadastrada para %s não pôde ser lida.", provedor)
            return None

    def salvar(self, provedor: str, chave: str) -> None:
        obter_provedor(provedor)
        chave = chave.strip()
        if len(chave) < 8:
            raise ValidationError("Chave de API muito curta.")
        registros = self._registros()
        registros[provedor] = {
            "cifrada": _fernet(self.settings).encrypt(chave.encode()).decode(),
            "atualizada_em": datetime.now(timezone.utc).isoformat(),
        }
        self.repo.set_value(CHAVE_CONFIG, registros)
        limpar_cache()

    def remover(self, provedor: str) -> None:
        obter_provedor(provedor)
        registros = self._registros()
        registros.pop(provedor, None)
        self.repo.set_value(CHAVE_CONFIG, registros)
        limpar_cache()

    def status(self) -> list[dict]:
        registros = self._registros()
        resultado = []
        for provedor in PROVEDORES.values():
            cadastrada = self.cadastrada(provedor.id)
            ambiente = getattr(self.settings, provedor.campo)
            efetiva = cadastrada or ambiente
            if cadastrada:
                origem = "interface"
            elif ambiente:
                origem = "ambiente"
            else:
                origem = "nenhuma"
            resultado.append(
                {
                    "id": provedor.id,
                    "nome": provedor.nome,
                    "uso": provedor.uso,
                    "variavel": provedor.variavel,
                    "configurada": bool(efetiva),
                    "origem": origem,
                    "mascara": mascarar(efetiva),
                    "atualizada_em": (registros.get(provedor.id) or {}).get("atualizada_em") if cadastrada else None,
                    "ilegivel": bool(registros.get(provedor.id)) and not cadastrada,
                }
            )
        return resultado


class KeyResolver:
    """Chave efetiva de cada provedor (interface > ambiente), com cache curto entre processos."""

    def __init__(self, session_factory: Callable[[], AbstractContextManager[Session]], settings: Settings | None = None):
        self.session_factory = session_factory
        self.settings = settings or get_settings()
        self._cache: dict[str, tuple[float, str | None]] = {}
        self._lock = threading.Lock()

    def __call__(self, provedor: str) -> str | None:
        agora = time.monotonic()
        with self._lock:
            em_cache = self._cache.get(provedor)
            if em_cache and agora - em_cache[0] < CACHE_SEGUNDOS:
                return em_cache[1]
        chave = None
        try:
            with self.session_factory() as session:
                chave = CredentialStore(session, self.settings).cadastrada(provedor)
        except Exception:
            logger.exception("Falha ao ler as chaves cadastradas; usando as variáveis de ambiente.")
        chave = chave or getattr(self.settings, obter_provedor(provedor).campo)
        with self._lock:
            self._cache[provedor] = (agora, chave)
        return chave

    def limpar(self) -> None:
        with self._lock:
            self._cache.clear()


_resolver: KeyResolver | None = None


def get_key_resolver() -> KeyResolver:
    global _resolver
    if _resolver is None:
        from app.db.base import SessionLocal

        _resolver = KeyResolver(SessionLocal)
    return _resolver


def limpar_cache() -> None:
    if _resolver is not None:
        _resolver.limpar()


def testar_chave(provedor: str, chave: str, rerank_model: str | None = None) -> dict:
    """Faz uma chamada mínima ao provedor com a chave informada. Não grava nada."""
    obter_provedor(provedor)
    inicio = time.perf_counter()
    try:
        if provedor == "google":
            from app.infrastructure.llm.google_provider import GoogleLLMProvider

            detalhe = f"{len(GoogleLLMProvider(chave, 'gemini-flash-latest').list_models())} modelos disponíveis"
        elif provedor == "openai":
            from app.infrastructure.llm.openai_provider import OpenAILLMProvider

            detalhe = f"{len(OpenAILLMProvider(chave, 'gpt-5-mini').list_models())} modelos disponíveis"
        else:
            import cohere

            modelo = rerank_model or get_settings().default_rerank_model
            cohere.ClientV2(api_key=chave).rerank(model=modelo, query="teste", documents=["teste"], top_n=1)
            detalhe = f"rerank com {modelo} respondeu"
        return {"ok": True, "detalhe": detalhe, "latencia_ms": int((time.perf_counter() - inicio) * 1000)}
    except Exception as exc:
        mensagem = getattr(exc, "message", None) or str(exc) or exc.__class__.__name__
        # Evita ecoar a chave caso o SDK a inclua na mensagem.
        mensagem = mensagem.replace(chave, mascarar(chave) or "")
        return {"ok": False, "erro": mensagem[:500], "latencia_ms": int((time.perf_counter() - inicio) * 1000)}
