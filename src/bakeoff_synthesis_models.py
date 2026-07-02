"""
M7 bakeoff — re-run the work-order synthesis model bakeoff with latency as a
hard constraint (blueprint B.5: the earlier ministral-3 pick assumed a
~30-minute budget; the real target is <40s end-to-end, so it must be
revisited).

For each candidate local model: warm the model into VRAM (untimed), then
synthesize a work order for two contrasting incidents (INC-0001, a Grade-1
escalation — the most demanding case; INC-0004, a Grade-3 monitor case — the
simplest) using the real M7 prompt/schema. Records warm latency and runs a
handful of automated groundedness checks per output. Unloads the model
before moving to the next one (host GPU is 6GB VRAM; several candidate
models don't fit alongside each other).

Output: data/synthesis_output/model_bakeoff.json
"""

import json
import time
from pathlib import Path

import ollama

from synthesize_work_order import PRIORITY_BY_GRADE, WORK_ORDER_SCHEMA, SYSTEM_PROMPT, build_prompt

MODELS = [
    "llama3.2:1b",
    "llama3.2:3b",
    "qwen3.5:0.8b",
    "qwen3.5:2b",
    "gemma4:e2b",
    "gemma4:e4b",
    "deepseek-r1:1.5b",
    "deepseek-r1:8b",
]

TEST_INCIDENT_IDS = ["INC-0001", "INC-0004"]  # Grade 1 (hardest) + Grade 3 (simplest)

CFG = {"think": False, "num_predict": 500, "call_timeout_s": 120}


def load_test_cases():
    incidents = {i["incident_id"]: i for i in json.loads(Path("data/grading_output/graded_incidents.json").read_text())}
    citation_records = {r["incident_id"]: r["citations"] for r in json.loads(Path("data/retrieval_output/retrieved_citations.json").read_text())}
    return [(incidents[iid], citation_records[iid]) for iid in TEST_INCIDENT_IDS]


def quality_checks(work_order: dict, incident: dict, citations: list[dict]) -> dict:
    grade = incident["assigned_grade"]
    valid_chunk_ids = {c["chunk_id"] for c in citations}
    text_blob = " ".join([
        work_order.get("title", ""), work_order.get("situation_summary", ""), work_order.get("crew_summary", ""),
    ])

    other_grade_mentions = [g for g in (1, 2, 3) if g != grade and f"Grade {g}" in text_blob]

    return {
        "schema_valid": not work_order.get("degraded_mode", True),
        "cites_retrieved_chunk": bool(set(work_order.get("citations", [])) & valid_chunk_ids),
        "no_contradicting_grade_mention": len(other_grade_mentions) == 0,
        "isolation_protocol_nonempty": bool(work_order.get("isolation_protocol")),
        "ppe_nonempty": bool(work_order.get("ppe_required")),
        "situation_summary_len": len(work_order.get("situation_summary", "")),
        "crew_summary_len": len(work_order.get("crew_summary", "")),
    }


def unload(client: ollama.Client, model: str):
    try:
        client.generate(model=model, prompt="", keep_alive=0)
    except Exception:
        pass


def bench_model(model: str, test_cases: list[tuple[dict, list[dict]]]) -> dict:
    client = ollama.Client(timeout=CFG["call_timeout_s"])
    print(f"\n=== {model} ===")

    t0 = time.monotonic()
    try:
        client.chat(model=model, messages=[{"role": "user", "content": "Reply with OK."}], think=False, options={"num_predict": 5})
        warmup_s = round(time.monotonic() - t0, 2)
        print(f"  warmup: {warmup_s}s")
    except Exception as exc:
        print(f"  warmup FAILED: {exc}")
        return {"model": model, "warmup_s": None, "warmup_error": str(exc), "runs": []}

    runs = []
    for incident, citations in test_cases:
        t0 = time.monotonic()
        error = None
        work_order = None
        try:
            response = client.chat(
                model=model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": build_prompt(incident, citations)},
                ],
                format=WORK_ORDER_SCHEMA,
                think=CFG["think"],
                options={"num_predict": CFG["num_predict"]},
            )
            latency_s = round(time.monotonic() - t0, 2)
            work_order = json.loads(response.message.content)
            for field in WORK_ORDER_SCHEMA["required"]:
                if field not in work_order:
                    raise ValueError(f"missing field: {field}")
            work_order["degraded_mode"] = False
        except Exception as exc:
            latency_s = round(time.monotonic() - t0, 2)
            error = str(exc)
            work_order = {"degraded_mode": True}

        checks = quality_checks(work_order, incident, citations) if not error else None
        run = {
            "incident_id": incident["incident_id"],
            "grade": incident["assigned_grade"],
            "latency_s": latency_s,
            "error": error,
            "work_order": work_order,
            "checks": checks,
        }
        runs.append(run)
        status = "FAILED: " + error if error else f"ok, {latency_s}s"
        print(f"  {incident['incident_id']} (grade {incident['assigned_grade']}): {status}")

    unload(client, model)
    return {"model": model, "warmup_s": warmup_s, "runs": runs}


def main():
    test_cases = load_test_cases()
    results = [bench_model(m, test_cases) for m in MODELS]

    out = Path("data/synthesis_output")
    out.mkdir(parents=True, exist_ok=True)
    (out / "model_bakeoff.json").write_text(json.dumps(results, indent=2))

    print("\n\n=== SUMMARY (warm latency, avg over 2 test incidents) ===")
    for r in results:
        latencies = [run["latency_s"] for run in r["runs"] if run["error"] is None]
        avg = round(sum(latencies) / len(latencies), 2) if latencies else None
        passed = sum(
            1 for run in r["runs"] if run["checks"] and all(
                run["checks"][k] for k in ("schema_valid", "cites_retrieved_chunk", "no_contradicting_grade_mention", "isolation_protocol_nonempty", "ppe_nonempty")
            )
        )
        print(f"  {r['model']:<20} warmup={r['warmup_s']}s  avg_latency={avg}s  passed_checks={passed}/{len(r['runs'])}")

    print(f"\nFull outputs saved to {out}/model_bakeoff.json")


if __name__ == "__main__":
    main()
