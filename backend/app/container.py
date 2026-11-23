"""Composition Root: monta os adaptadores de infraestrutura e injeta nos serviços."""

from functools import lru_cache

from app.core.config import get_settings
from app.core.exceptions import ProviderNotConfiguredError
from app.domain.ports import EmbeddingProvider, LLMProvider, Reranker
from app.infrastructure.chunking.recursive_chunker import RecursiveTextChunker
from app.infrastructure.embeddings.google_embeddings import GoogleEmbeddingProvider
from app.infrastructure.llm.factory import LLMProviderFactory
from app.infrastructure.loaders.factory import LoaderFactory
from app.infrastructure.ocr.scan_detector import HeuristicScanDetector
from app.infrastructure.ocr.tesseract_ocr import TesseractOcrEngine
from app.infrastructure.rerank.cohere_reranker import CohereReranker, PassthroughReranker
from app.infrastructure.storage.local_storage import LocalFileStorage
from app.infrastructure.vectorstore.qdrant_store import QdrantVectorStore
from app.services.credentials_service import get_key_resolver
from app.services.settings_service import RagSettings


@lru_cache
def get_vector_store() -> QdrantVectorStore:
    settings = get_settings()
    return QdrantVectorStore(
        url=settings.qdrant_url,
        collection=settings.qdrant_collection,
        dimensions=settings.embedding_dimensions,
        api_key=settings.qdrant_api_key,
    )


def get_embedder() -> EmbeddingProvider:
    api_key = get_key_resolver()("google")
    if not api_key:
        raise ProviderNotConfiguredError(
            "Chave da Google não configurada: necessária para os embeddings. Cadastre-a em Modelos e RAG."
        )
    return _embedder(api_key)


@lru_cache(maxsize=4)
def _embedder(api_key: str) -> EmbeddingProvider:
    # Um cliente por chave: trocar a chave na interface cria um cliente novo.
    settings = get_settings()
    return GoogleEmbeddingProvider(
        api_key=api_key,
        model=settings.embedding_model,
        dimensions=settings.embedding_dimensions,
        batch_size=settings.embedding_batch_size,
    )


@lru_cache
def get_loader_factory() -> LoaderFactory:
    settings = get_settings()
    return LoaderFactory.default(
        ocr=TesseractOcrEngine(settings.ocr_languages),
        detector=HeuristicScanDetector(),
        ocr_dpi=settings.ocr_dpi,
        soffice_bin=settings.libreoffice_bin,
    )


@lru_cache
def get_file_storage() -> LocalFileStorage:
    return LocalFileStorage(get_settings().upload_dir)


def get_llm_factory() -> LLMProviderFactory:
    return LLMProviderFactory(get_settings(), get_key_resolver())


def build_llm(rag: RagSettings) -> LLMProvider:
    return get_llm_factory().create(rag.llm_provider, rag.llm_model, rag.reasoning_level)


def build_reranker(rag: RagSettings) -> Reranker:
    api_key = get_key_resolver()("cohere") if rag.rerank_enabled else None
    if rag.rerank_enabled and api_key:
        return CohereReranker(api_key, rag.rerank_model)
    return PassthroughReranker()


def build_chunker(rag: RagSettings) -> RecursiveTextChunker:
    return RecursiveTextChunker(rag.chunk_size, rag.chunk_overlap)
