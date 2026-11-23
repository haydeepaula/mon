from collections.abc import Callable

from app.core.config import Settings
from app.core.exceptions import ProviderNotConfiguredError, ValidationError
from app.domain.ports import LLMProvider
from app.infrastructure.llm.google_provider import GoogleLLMProvider
from app.infrastructure.llm.openai_provider import OpenAILLMProvider

ProviderBuilder = Callable[[str, str, str], LLMProvider]


class LLMProviderFactory:
    """Factory com registro de provedores: novos provedores entram sem alterar os serviços."""

    _registry: dict[str, tuple[ProviderBuilder, str]] = {
        "google": (GoogleLLMProvider, "google_api_key"),
        "openai": (OpenAILLMProvider, "openai_api_key"),
    }

    def __init__(self, settings: Settings, key_resolver: Callable[[str], str | None] | None = None):
        self.settings = settings
        # Resolve a chave efetiva (cadastrada na interface ou variável de ambiente).
        self.key_resolver = key_resolver

    def _api_key(self, provider: str, key_name: str) -> str | None:
        if self.key_resolver is not None:
            return self.key_resolver(provider)
        return getattr(self.settings, key_name)

    @classmethod
    def providers(cls) -> list[str]:
        return list(cls._registry)

    def is_configured(self, provider: str) -> bool:
        entry = self._registry.get(provider)
        return bool(entry and self._api_key(provider, entry[1]))

    def create(self, provider: str, model: str, reasoning_level: str = "low") -> LLMProvider:
        entry = self._registry.get(provider)
        if entry is None:
            raise ValidationError(f"Provedor desconhecido: {provider}")
        builder, key_name = entry
        api_key = self._api_key(provider, key_name)
        if not api_key:
            raise ProviderNotConfiguredError(
                f"Chave de API do provedor '{provider}' não configurada. Cadastre-a em Modelos e RAG ou em {key_name.upper()}."
            )
        return builder(api_key, model, reasoning_level)
