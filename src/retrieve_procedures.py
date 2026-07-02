"""
M6 — RAG retrieval over the procedure corpus (no LLM; embeddings only).

Given step 2's graded incidents, builds one templated natural-language query
per incident and retrieves the top-k matching chunks from the ChromaDB
collection built by build_corpus.py (M5). This step reads `assigned_grade`
to build the query text — it never writes or influences it.

Incidents with `assigned_grade is None` (the hydraulic_check route — not a
gas leak) are skipped; there is no leak procedure to cite for them.

Output: data/retrieval_output/retrieved_citations.json
Evaluation: data/retrieval_output/retrieval_evaluation.json
  - coverage check: every gradable incident must have >=1 citation above
    MIN_SCORE (the blueprint requires 100% of work orders cite a chunk)
  - spot-check log: top chunk for the Grade 1/2/3 examples and the
    soil-vs-asphalt fidelity pair (SEG-005A/B), for manual eyeballing
"""

import argparse
import json
from pathlib import Path
from typing import Any

import chromadb
import ollama

CFG: dict[str, Any] = {
    "embed_model": "nomic-embed-text",
    "collection_name": "l2wo_procedures",
    "top_k": 3,
    "min_score": 0.55,  # chroma returns cosine distance; similarity = 1 - distance
}


def build_query(incident: dict) -> str:
    meta = incident["segment_meta"]
    grade = incident["assigned_grade"]
    route = incident["detected_route"]

    proximity = "near occupied building" if meta["distance_to_building_m"] <= 20 else "in open right-of-way"
    hca = ", HCA zone" if meta["hca_flag"] else ""
    signal = "methane and pressure corroborated" if route == "escalation" else "methane/acoustic detected"

    return (
        f"Grade {grade} gas leak, {signal}, {meta['surface_capping_type']} surface capping, "
        f"{proximity}{hca} — isolation and emergency response procedure."
    )


def retrieve_for_incident(collection: chromadb.Collection, incident: dict, cfg: dict) -> dict:
    query = build_query(incident)
    response = ollama.embed(model=cfg["embed_model"], input=[query])
    result = collection.query(query_embeddings=response.embeddings, n_results=cfg["top_k"])

    citations = []
    for doc, meta, distance, chunk_id in zip(
        result["documents"][0], result["metadatas"][0], result["distances"][0], result["ids"][0]
    ):
        citations.append({
            "chunk_id": chunk_id,
            "source_doc": meta["source_doc"],
            "location": meta["location"],
            "text": doc,
            "score": round(1 - distance, 4),
        })

    return {"incident_id": incident["incident_id"], "query": query, "citations": citations}


def retrieve_all(collection: chromadb.Collection, incidents: list[dict], cfg: dict) -> list[dict]:
    results = []
    for inc in incidents:
        if inc.get("assigned_grade") is None:
            continue
        results.append(retrieve_for_incident(collection, inc, cfg))
    return results


def evaluate(results: list[dict], incidents: list[dict], cfg: dict) -> dict:
    by_incident = {inc["incident_id"]: inc for inc in incidents}
    gradable = [i for i in incidents if i.get("assigned_grade") is not None]

    uncovered = []
    for r in results:
        best_score = max((c["score"] for c in r["citations"]), default=0.0)
        if best_score < cfg["min_score"]:
            uncovered.append({"incident_id": r["incident_id"], "best_score": best_score})

    spot_check = []
    for r in results:
        inc = by_incident[r["incident_id"]]
        top = r["citations"][0] if r["citations"] else None
        spot_check.append({
            "incident_id": r["incident_id"],
            "segment_id": inc["segment_id"],
            "assigned_grade": inc["assigned_grade"],
            "surface_capping_type": inc["segment_meta"]["surface_capping_type"],
            "query": r["query"],
            "top_citation": top,
        })

    return {
        "total_gradable_incidents": len(gradable),
        "incidents_with_citation_retrieved": len(results),
        "incidents_below_min_score": uncovered,
        "coverage_ok": len(uncovered) == 0,
        "spot_check": spot_check,
    }


def run_pipeline(incidents_path: str, db_dir: str, output_dir: str, cfg: dict, verbose: bool = True) -> tuple[list[dict], dict]:
    incidents = json.loads(Path(incidents_path).read_text())
    client = chromadb.PersistentClient(path=db_dir)
    collection = client.get_collection(cfg["collection_name"])

    results = retrieve_all(collection, incidents, cfg)
    eval_report = evaluate(results, incidents, cfg)

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "retrieved_citations.json").write_text(json.dumps(results, indent=2))
    (out / "retrieval_evaluation.json").write_text(json.dumps(eval_report, indent=2))

    if verbose:
        print(f"\n[M6] Retrieved citations for {len(results)}/{len(incidents)} incidents ({eval_report['total_gradable_incidents']} gradable):")
        for r in results:
            top = r["citations"][0] if r["citations"] else None
            top_desc = f"{top['source_doc']}@{top['location']} (score={top['score']})" if top else "NO CITATION"
            print(f"    {r['incident_id']:<10} -> {top_desc}")
        print(f"\n[M6] Coverage OK: {eval_report['coverage_ok']}")
        if eval_report["incidents_below_min_score"]:
            print(f"    BELOW MIN SCORE: {eval_report['incidents_below_min_score']}")
        print(f"\nOutputs saved to {out}/")

    return results, eval_report


def main():
    parser = argparse.ArgumentParser(description="M6 RAG retrieval over procedure corpus")
    parser.add_argument("--incidents", "-i", default="data/grading_output/graded_incidents.json")
    parser.add_argument("--db", default="data/chroma_db")
    parser.add_argument("--output", "-o", default="data/retrieval_output")
    args = parser.parse_args()

    run_pipeline(args.incidents, args.db, args.output, CFG, verbose=True)


if __name__ == "__main__":
    main()
