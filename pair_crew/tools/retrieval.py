"""Page-level Chroma retrieval with guideline citation metadata."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

COLLECTION_NAME = "pair_guideline_pages"
INDEX_DIR = Path(os.getenv("CHROMA_INDEX_PATH", "data/vector_index"))
TOP_K = int(os.getenv("RETRIEVAL_TOP_K", "4"))


@dataclass
class CitedPassage:
    text: str
    document_name: str
    page_number: int
    source_path: str
    distance: float | None = None

    @property
    def citation(self) -> str:
        return f"{self.document_name}, page {self.page_number}"


@dataclass
class RetrievalResult:
    query: str
    passages: list[CitedPassage] = field(default_factory=list)
    coverage_status: str = "not_covered"
    notes: str = ""


def embedding_provider() -> str:
    """Return the approved configured embedding provider."""
    provider = os.getenv("EMBEDDING_PROVIDER", "openai").strip().lower()
    if provider not in {"openai", "local"}:
        raise ValueError("EMBEDDING_PROVIDER must be 'openai' or 'local'")
    return provider


def embedding_function(provider: str):
    """Create the Chroma query embedding function for a stored index."""
    from chromadb.utils.embedding_functions import (
        OpenAIEmbeddingFunction,
        SentenceTransformerEmbeddingFunction,
    )

    if provider == "local":
        return SentenceTransformerEmbeddingFunction(
            model_name="sentence-transformers/all-MiniLM-L6-v2",
            device="cpu",
        )
    return OpenAIEmbeddingFunction(
        api_key_env_var="OPENAI_API_KEY",
        model_name="text-embedding-3-small",
    )


def retrieve_passages(query: str, top_k: int = TOP_K) -> RetrievalResult:
    """Query page chunks and return cited top-k passages."""
    if not INDEX_DIR.exists():
        return RetrievalResult(
            query=query,
            notes=f"Chroma index not found at {INDEX_DIR}. Run scripts/build_index.py first.",
        )

    try:
        import chromadb

        client = chromadb.PersistentClient(path=str(INDEX_DIR))
        collection = client.get_collection(
            COLLECTION_NAME,
            embedding_function=embedding_function(embedding_provider()),
        )
        result = collection.query(
            query_texts=[query],
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )
    except Exception as exc:
        return RetrievalResult(
            query=query,
            coverage_status="error",
            notes=f"Retrieval failed: {exc}",
        )

    documents = result.get("documents", [[]])[0]
    metadatas = result.get("metadatas", [[]])[0]
    distances = result.get("distances", [[]])[0]
    passages = [
        CitedPassage(
            text=document,
            document_name=str(metadata["document_name"]),
            page_number=int(metadata["page_number"]),
            source_path=str(metadata["source_path"]),
            distance=float(distance) if distance is not None else None,
        )
        for document, metadata, distance in zip(documents, metadatas, distances)
    ]

    coverage = "directly_covered" if passages else "not_covered"
    return RetrievalResult(query=query, passages=passages, coverage_status=coverage)
