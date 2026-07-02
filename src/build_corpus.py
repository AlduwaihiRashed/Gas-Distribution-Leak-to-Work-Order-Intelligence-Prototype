"""
M5 — RAG corpus builder (no LLM; embeddings only).

Chunks the gas-relevant procedure/regulatory documents and embeds them into a
persistent ChromaDB collection so step M6 (retrieve_procedures.py) can fetch
cited text for a graded incident. This script never grades or decides
anything — it only prepares text for retrieval.

Corpus scope (deliberately gas-only, per design review): the gas utility EA
and the platform wiki. The power/water EA PDFs are cross-utility background
reading, not gas leak procedure, and are excluded so a gas work order can
never cite an irrelevant document.

Pipeline:
  1. Extract text per-page from the gas EA PDF (pypdf) and per-heading-section
     from the wiki markdown, so each chunk can carry a real location marker.
  2. Split into fixed-size overlapping word-count chunks (chunking is source-
     structure-agnostic; the location marker carries the structure instead).
  3. Embed each chunk with Ollama's nomic-embed-text.
  4. Upsert into ChromaDB collection "l2wo_procedures" at data/chroma_db/.
"""

import argparse
import re
from pathlib import Path
from typing import Any

import chromadb
import ollama
from pypdf import PdfReader

CFG: dict[str, Any] = {
    "chunk_words": 400,
    "overlap_words": 50,
    "embed_model": "nomic-embed-text",
    "collection_name": "l2wo_procedures",
    "corpus_docs": [
        "gas-utility-ea-togaf.pdf",
        "utility-analytics-ecosystem-wiki (1).md",
        "gas-leak-response-procedures.md",
    ],
}


def _sliding_windows(words: list[str], chunk_words: int, overlap_words: int) -> list[str]:
    """Split a word list into overlapping windows, joined back into text."""
    if not words:
        return []
    step = chunk_words - overlap_words
    windows = []
    for start in range(0, len(words), step):
        window = words[start:start + chunk_words]
        if not window:
            break
        windows.append(" ".join(window))
        if start + chunk_words >= len(words):
            break
    return windows


def chunk_pdf(path: Path, cfg: dict) -> list[dict]:
    """One chunk list per page, tagged with a page-number location."""
    reader = PdfReader(str(path))
    chunks = []
    for page_num, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        words = text.split()
        for i, window in enumerate(_sliding_windows(words, cfg["chunk_words"], cfg["overlap_words"])):
            chunks.append({
                "text": window,
                "source_doc": path.name,
                "location": f"p.{page_num}",
                "chunk_id": f"{path.stem}_p{page_num}_{i}",
            })
    return chunks


def chunk_markdown(path: Path, cfg: dict) -> list[dict]:
    """Split on markdown headings to build a location path, then window each section."""
    text = path.read_text(encoding="utf-8")
    heading_re = re.compile(r"^(#{1,6})\s+(.*)$", re.MULTILINE)

    sections = []  # list of (heading_path, body_text)
    heading_stack: list[str] = []
    last_end = 0
    last_heading_path = "(preamble)"
    for m in heading_re.finditer(text):
        body = text[last_end:m.start()]
        if body.strip():
            sections.append((last_heading_path, body))
        level = len(m.group(1))
        title = m.group(2).strip()
        heading_stack = heading_stack[:level - 1] + [title]
        last_heading_path = " > ".join(heading_stack)
        last_end = m.end()
    trailing = text[last_end:]
    if trailing.strip():
        sections.append((last_heading_path, trailing))

    chunks = []
    for sec_i, (heading_path, body) in enumerate(sections):
        words = body.split()
        for i, window in enumerate(_sliding_windows(words, cfg["chunk_words"], cfg["overlap_words"])):
            chunks.append({
                "text": window,
                "source_doc": path.name,
                "location": heading_path,
                "chunk_id": f"{path.stem}_sec{sec_i}_{i}",
            })
    return chunks


def build_chunks(docs_dir: Path, cfg: dict) -> list[dict]:
    chunks = []
    for doc_name in cfg["corpus_docs"]:
        path = docs_dir / doc_name
        if path.suffix.lower() == ".pdf":
            chunks.extend(chunk_pdf(path, cfg))
        elif path.suffix.lower() == ".md":
            chunks.extend(chunk_markdown(path, cfg))
        else:
            raise ValueError(f"Unsupported corpus doc type: {path}")
    return chunks


def embed_and_store(chunks: list[dict], db_dir: Path, cfg: dict, verbose: bool = True) -> chromadb.Collection:
    client = chromadb.PersistentClient(path=str(db_dir))
    client.delete_collection(cfg["collection_name"]) if cfg["collection_name"] in [c.name for c in client.list_collections()] else None
    collection = client.create_collection(cfg["collection_name"])

    texts = [c["text"] for c in chunks]
    response = ollama.embed(model=cfg["embed_model"], input=texts)

    collection.add(
        ids=[c["chunk_id"] for c in chunks],
        embeddings=response.embeddings,
        documents=texts,
        metadatas=[{"source_doc": c["source_doc"], "location": c["location"]} for c in chunks],
    )

    if verbose:
        print(f"[M5] Embedded {len(chunks)} chunks from {cfg['corpus_docs']} into '{cfg['collection_name']}' at {db_dir}/")

    return collection


def run_pipeline(docs_dir: str, db_dir: str, cfg: dict, verbose: bool = True) -> chromadb.Collection:
    chunks = build_chunks(Path(docs_dir), cfg)
    return embed_and_store(chunks, Path(db_dir), cfg, verbose=verbose)


def main():
    parser = argparse.ArgumentParser(description="M5 RAG corpus builder")
    parser.add_argument("--docs", "-d", default="docs")
    parser.add_argument("--db", default="data/chroma_db")
    args = parser.parse_args()

    run_pipeline(args.docs, args.db, CFG, verbose=True)


if __name__ == "__main__":
    main()
