"""
Retrieval tool: queries the FAISS vector index and returns cited passages.
The FAISS index is built by scripts/build_index.py over data/guidelines/*.txt files.
"""
from __future__ import annotations

import os
import warnings
from dataclasses import dataclass, field
from pathlib import Path

FAISS_INDEX_PATH = Path(os.getenv("FAISS_INDEX_PATH", "data/faiss_index"))
TOP_K = int(os.getenv("RETRIEVAL_TOP_K", "5"))


@dataclass
class CitedPassage:
    text: str
    source: str
    score: float = 0.0

    @property
    def citation(self) -> str:
        return self.source.replace("_", " ").replace(".txt", "")


@dataclass
class RetrievalResult:
    query: str
    passages: list[CitedPassage] = field(default_factory=list)
    coverage_status: str = "not_covered"
    notes: str = ""


def retrieve_passages(query: str, top_k: int = TOP_K) -> RetrievalResult:
    """
    Query the FAISS index and return top_k cited passages.
    Coverage status: 'directly_covered' when passages found, else 'not_covered'.
    """
    if not FAISS_INDEX_PATH.exists():
        return RetrievalResult(
            query=query,
            coverage_status="not_covered",
            notes=f"FAISS index not found at {FAISS_INDEX_PATH}. Run scripts/build_index.py first.",
        )

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            from langchain_community.vectorstores import FAISS
            from langchain_community.embeddings import HuggingFaceEmbeddings

        embeddings = HuggingFaceEmbeddings(
            model_name="sentence-transformers/all-MiniLM-L6-v2",
            model_kwargs={"device": "cpu"},
        )
        vectorstore = FAISS.load_local(
            str(FAISS_INDEX_PATH),
            embeddings,
            allow_dangerous_deserialization=True,
        )
        results = vectorstore.similarity_search_with_score(query, k=top_k)
    except Exception as exc:
        return RetrievalResult(query=query, coverage_status="error", notes=str(exc))

    passages = [
        CitedPassage(
            text=doc.page_content,
            source=doc.metadata.get("source", "unknown"),
            score=float(score),
        )
        for doc, score in results
    ]

    coverage = "directly_covered" if passages else "not_covered"
    return RetrievalResult(query=query, passages=passages, coverage_status=coverage)
