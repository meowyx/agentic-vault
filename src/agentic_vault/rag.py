"""Retrieval over the Chroma index built by ingest.

The LangGraph agent calls `retrieve` as its search tool (Stage 2). Generation
lives in the agent now, so this module is retrieval-only: the monolithic
retrieve-and-answer chain from wiki-rag was dropped in the Stage 2 refactor.
"""

from functools import lru_cache
from pathlib import Path

from langchain_chroma import Chroma
from langchain_classic.embeddings import CacheBackedEmbeddings
from langchain_community.storage import RedisStore
from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
from langfuse import Langfuse
from langfuse.langchain import CallbackHandler

from agentic_vault.config import settings
from agentic_vault.ingest import CHROMA_DIR, COLLECTION_NAME, EMBED_CACHE_NAMESPACE


@lru_cache(maxsize=1)
def _vectorstore() -> Chroma:
    underlying = OpenAIEmbeddings(
        model="text-embedding-3-small",
        api_key=settings.openai_api_key,
    )
    store = RedisStore(redis_url=settings.redis_url, namespace=EMBED_CACHE_NAMESPACE)
    embeddings = CacheBackedEmbeddings.from_bytes_store(
        underlying_embeddings=underlying,
        document_embedding_cache=store,
        namespace=underlying.model,
        key_encoder="sha256",  # collision-resistant cache keys (SHA-1 is the default)
    )
    return Chroma(
        collection_name=COLLECTION_NAME,
        embedding_function=embeddings,
        persist_directory=str(CHROMA_DIR),
    )


@lru_cache(maxsize=1)
def _langfuse_handler() -> CallbackHandler:
    _ = Langfuse(
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key,
        host=settings.langfuse_base_url,
    )
    return CallbackHandler()


def _format_context(docs: list[Document]) -> str:
    return "\n\n---\n\n".join(
        f"[{Path(doc.metadata.get('source', 'unknown')).name}]\n{doc.page_content}"
        for doc in docs
    )


class VectorStoreNotInitializedError(RuntimeError):
    """Raised when chroma_db/ is missing; the user needs to run ingest first."""


async def retrieve(query: str, k: int = 4) -> str:
    """Return the top-k matching note chunks, formatted with [filename] headers."""
    if not CHROMA_DIR.exists():
        raise VectorStoreNotInitializedError(
            f"vector store not found at {CHROMA_DIR}; "
            "run `uv run python -m agentic_vault.ingest` first"
        )
    docs = await _vectorstore().asimilarity_search(query, k=k)
    if not docs:
        return "No relevant notes found."
    return _format_context(docs)
