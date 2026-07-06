"""
M6 RAG retrieval tests — 100% citation coverage requirement (blueprint A.5:
"100% of generated work orders cite at least one real retrieved chunk").

Needs the ChromaDB corpus already built (data/chroma_db/) — no network,
no Ollama LLM call (embeddings only), so this runs fast and offline.
"""

import chromadb
import pytest

import retrieve_procedures as retriever


@pytest.fixture(scope="module")
def collection():
    client = chromadb.PersistentClient(path="data/chroma_db")
    try:
        return client.get_collection(retriever.CFG["collection_name"])
    except Exception:
        pytest.skip("ChromaDB corpus not built — run src/build_corpus.py first")


class TestCitationCoverage:
    def test_every_gradable_incident_gets_a_citation(self, collection, graded_incidents):
        gradable = [i for i in graded_incidents if i.get("assigned_grade") is not None]
        assert gradable, "no gradable incidents in graded_incidents.json"

        for inc in gradable:
            result = retriever.retrieve_for_incident(collection, inc, retriever.CFG)
            assert result["citations"], f"{inc['incident_id']} got zero citations"
            best_score = max(c["score"] for c in result["citations"])
            assert best_score >= retriever.CFG["min_score"], (
                f"{inc['incident_id']}: best score {best_score} below min_score threshold"
            )

    def test_grade1_query_surfaces_grade1_procedure_text(self, collection, grade1_incident):
        result = retriever.retrieve_for_incident(collection, grade1_incident, retriever.CFG)
        top_text = result["citations"][0]["text"].lower()
        assert "grade 1" in top_text or "immediate" in top_text

    def test_citation_chunk_ids_are_stable_identifiers(self, collection, grade1_incident):
        """Same query twice should return the same top chunk_id — retrieval must be
        deterministic given a fixed corpus, since work orders cite these ids by id."""
        r1 = retriever.retrieve_for_incident(collection, grade1_incident, retriever.CFG)
        r2 = retriever.retrieve_for_incident(collection, grade1_incident, retriever.CFG)
        assert r1["citations"][0]["chunk_id"] == r2["citations"][0]["chunk_id"]
