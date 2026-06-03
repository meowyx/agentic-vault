"""Load corpus .md files, chunk, embed (Redis-cached), persist to Chroma."""

import shutil
from pathlib import Path

from langchain_chroma import Chroma
from langchain_classic.embeddings import CacheBackedEmbeddings
from langchain_community.document_loaders import DirectoryLoader, TextLoader
from langchain_community.storage import RedisStore
from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

from agentic_vault.config import settings

CHROMA_DIR = Path("./chroma_db")
COLLECTION_NAME = "agentic_vault"
EMBED_CACHE_NAMESPACE = "agentic-vault"


def main() -> None:
    loader = DirectoryLoader(
        str(settings.vault_corpus_path),
        glob="*.md",
        loader_cls=TextLoader,
        show_progress=True,
    )
    docs = loader.load()
    print(f"loaded {len(docs)} documents from {settings.vault_corpus_path}")

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
    )
    chunks = splitter.split_documents(docs)
    print(f"split into {len(chunks)} chunks")

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

    if CHROMA_DIR.exists():
        shutil.rmtree(CHROMA_DIR)

    _ = Chroma.from_documents(
        documents=chunks,
        embedding=embeddings,
        collection_name=COLLECTION_NAME,
        persist_directory=str(CHROMA_DIR),
    )
    print(f"persisted {len(chunks)} chunks to {CHROMA_DIR}")


if __name__ == "__main__":
    main()
