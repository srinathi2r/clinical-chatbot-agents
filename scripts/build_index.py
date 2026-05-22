#!/usr/bin/env python3
"""Build the local Chroma index from page-sized guideline PDF chunks."""

from __future__ import annotations

import os
import sys
from collections import Counter
from pathlib import Path

GUIDELINES_DIR = Path("data/guidelines")
INDEX_DIR = Path(os.getenv("CHROMA_INDEX_PATH", "data/vector_index"))
COLLECTION_NAME = "pair_guideline_pages"
EXPECTED_PDFS = (
    "Infections_Respiratory.pdf",
    "Vancomycin Algorithm_doctor ver.pdf",
    "Warfarin Therapy Guide.pdf",
    "Infections_Musculoskeletal.pdf",
    "SGH NBM Guidance 2018.pdf",
)
# NOTE: "SGH NBM Guidance 2018.pdf" is the available file; eval scenarios reference
# NBM_Guidance_2023.pdf. Deterministic CBG rules live in calculators.py and are
# not affected by this discrepancy, but LLM citations will cite the 2018 document.


def embedding_provider() -> str:
    """Return the approved configured embedding provider."""
    provider = os.getenv("EMBEDDING_PROVIDER", "openai").strip().lower()
    if provider not in {"openai", "local"}:
        raise ValueError("EMBEDDING_PROVIDER must be 'openai' or 'local'")
    return provider


def embedding_function(provider: str):
    """Create the Chroma embedding function for the configured provider."""
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


def expected_paths() -> list[Path]:
    """Return the exact local guideline PDF paths required by the index."""
    return [GUIDELINES_DIR / filename for filename in EXPECTED_PDFS]


def missing_guidelines() -> list[Path]:
    """Return required guideline PDF paths that are not present."""
    return [path for path in expected_paths() if not path.is_file()]


def pages_from_pdf(path: Path) -> list[dict[str, object]]:
    """Extract one page chunk per PDF page with citation metadata."""
    from pypdf import PdfReader

    reader = PdfReader(path)
    pages: list[dict[str, object]] = []

    for page_number, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        if not text:
            continue
        pages.append(
            {
                "id": f"{path.stem}-page-{page_number}",
                "text": text,
                "metadata": {
                    "document_name": path.name,
                    "page_number": page_number,
                    "source_path": str(path),
                },
            }
        )

    return pages


def build_index() -> int:
    """Build and persist the page-level Chroma index."""
    missing = missing_guidelines()
    if missing:
        print("Missing required guideline PDFs:")
        for path in missing:
            print(f"  - {path}")
        print("Add the files listed above and rerun scripts/build_index.py.")
        return 0

    try:
        import chromadb

        provider = embedding_provider()
        pages = [
            page
            for path in expected_paths()
            for page in pages_from_pdf(path)
        ]
        if not pages:
            print("No extractable PDF page text was found. Index was not built.")
            return 1

        INDEX_DIR.mkdir(parents=True, exist_ok=True)
        client = chromadb.PersistentClient(path=str(INDEX_DIR))
        try:
            client.delete_collection(COLLECTION_NAME)
        except Exception:
            pass
        collection = client.create_collection(
            name=COLLECTION_NAME,
            embedding_function=embedding_function(provider),
            metadata={"embedding_provider": provider, "chunking": "pdf_page"},
        )
        collection.add(
            ids=[str(page["id"]) for page in pages],
            documents=[str(page["text"]) for page in pages],
            metadatas=[dict(page["metadata"]) for page in pages],
        )
    except ImportError as exc:
        print(f"Missing indexing dependency: {exc}")
        return 1
    except Exception as exc:
        print(f"Index build failed: {exc}")
        return 1

    counts = Counter(
        str(page["metadata"]["document_name"])
        for page in pages
    )
    print(f"Embedding provider: {provider}")
    print(f"Chroma index saved to {INDEX_DIR}/")
    print("Pages indexed per document:")
    for path in expected_paths():
        print(f"  - {path.name}: {counts[path.name]}")
    print(f"Total pages indexed: {len(pages)}")
    return 0


if __name__ == "__main__":
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass
    sys.exit(build_index())
