"""
M7 — Work-order synthesis (the single LLM step).

Takes one graded incident (M4) + its retrieved procedure citations (M6) and
drafts a dispatch-ready work order via a local Ollama model, constrained to a
JSON schema so the output is always structurally valid. The model may only
use supplied facts and retrieved text — it never re-derives the grade.

If the Ollama call fails or returns invalid JSON, `degraded_work_order()`
builds a banner-flagged template work order directly from the deterministic
incident payload, with no LLM involved, so the safety output never drops
(blueprint's "LLM-not-load-bearing" fail-safe).

Output: data/synthesis_output/work_orders.json
Evaluation: data/synthesis_output/synthesis_evaluation.json
"""

import argparse
import json
import time
from pathlib import Path
from typing import Any

import ollama

# Model choice is the configurable accuracy/speed variable (blueprint B.5).
# Picked via an 8-model bakeoff on this host's RTX 3050 (6GB VRAM) — see
# src/bakeoff_synthesis_models.py and data/synthesis_output/model_bakeoff.json.
# gemma4:e2b won on groundedness (richest use of the retrieved procedure text,
# most specific numeric detail) while still running well inside the 40s
# budget (~6-9s/incident warm). Runner-up llama3.2:3b was faster but thinner.
# Rejected: qwen3.5 (0.8b/2b) doesn't reliably honor the JSON-schema format
# constraint; deepseek-r1 (1.5b/8b) spends its whole token budget on hidden
# reasoning even with think=False, leaving no room to emit the work order;
# llama3.2:1b never produced a real citation (hallucinated chunk ids) —
# disqualifying given the blueprint's 100%-cited requirement.
CFG: dict[str, Any] = {
    "model": "gemma4:e2b",
    "think": False,
    "num_predict": 500,
    "timeout_s": 40,
}

PRIORITY_BY_GRADE = {1: "IMMEDIATE", 2: "SCHEDULED", 3: "MONITOR"}


def build_schema(valid_chunk_ids: list[str]) -> dict[str, Any]:
    """citations is constrained to an enum of this incident's actual retrieved
    chunk_ids — closes a failure mode seen in the bakeoff where a model cited
    the right chunk but appended a hallucinated `#anchor` suffix to it."""
    return {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "situation_summary": {"type": "string"},
            "isolation_protocol": {"type": "array", "items": {"type": "string"}},
            "permit_to_work_required": {"type": "boolean"},
            "ppe_required": {"type": "array", "items": {"type": "string"}},
            "proximity_hazards": {"type": "array", "items": {"type": "string"}},
            "crew_summary": {"type": "string"},
            "citations": (
                {"type": "array", "items": {"enum": valid_chunk_ids}, "minItems": 1}
                if valid_chunk_ids else
                {"type": "array", "items": {"type": "string"}}
            ),
        },
        "required": [
            "title", "situation_summary", "isolation_protocol",
            "permit_to_work_required", "ppe_required", "proximity_hazards",
            "crew_summary", "citations",
        ],
    }


# kept for callers (e.g. the bakeoff) that want a generic schema without a
# per-incident chunk_id enum
WORK_ORDER_SCHEMA: dict[str, Any] = build_schema([])

SYSTEM_PROMPT = (
    "You are a gas-utility dispatch assistant drafting an emergency work order. "
    "You MUST use only the facts given in the incident payload and the retrieved "
    "procedure excerpts below — never invent sensor readings, locations, or "
    "regulatory claims. The leak grade and priority are already decided upstream; "
    "do not change or contradict them. Every work order must cite at least one "
    "retrieved chunk_id in `citations`. Respond with JSON matching the given schema only."
)


def build_prompt(incident: dict, citations: list[dict], actuator_state: dict | None = None) -> str:
    meta = incident["segment_meta"]
    grade = incident["assigned_grade"]
    chunks = "\n".join(
        f"- [{c['chunk_id']}] ({c['source_doc']} > {c['location']}): {c['text']}"
        for c in citations
    )

    if actuator_state and actuator_state.get("actuator_confirmed_state") == "isolated":
        actuation_line = (
            f"\nACTUATOR STATE: this segment's shutoff has already been isolated automatically "
            f"(confirmed, latency {actuator_state.get('actuator_command_latency_s')}s) — do NOT "
            f"instruct the crew to isolate the segment; isolation is done. The isolation_protocol "
            f"field should cover only what remains: verification, monitoring, and any follow-up "
            f"physical work, not re-isolating an already-isolated segment.\n"
        )
    elif grade == 1 and actuator_state and actuator_state.get("actuator_commanded"):
        actuation_line = (
            f"\nACTUATOR STATE: isolation was commanded but is NOT yet confirmed "
            f"(state: {actuator_state.get('actuator_confirmed_state', 'unknown')}) — flag this "
            f"explicitly in proximity_hazards as unconfirmed, don't assume it succeeded.\n"
        )
    else:
        actuation_line = ""

    return (
        f"INCIDENT PAYLOAD\n"
        f"incident_id: {incident['incident_id']}\n"
        f"segment_id: {incident['segment_id']}\n"
        f"grade: {grade} (priority: {PRIORITY_BY_GRADE[grade]})\n"
        f"grading_rule: {incident['grading_rule']}\n"
        f"detected_route: {incident['detected_route']}\n"
        f"start_utc: {incident['start_utc']}  end_utc: {incident['end_utc']}\n"
        f"peak_methane_pct_lel: {incident['peak_methane_pct_lel']}\n"
        f"peak_acoustic_index: {incident['peak_acoustic_index']}\n"
        f"min_pressure_bar: {incident['min_pressure_bar']}\n"
        f"material: {meta['material']}  install_year: {meta['install_year']}  MAOP_bar: {meta['MAOP_bar']}\n"
        f"location_class: {meta['location_class']}  hca_flag: {meta['hca_flag']}\n"
        f"distance_to_building_m: {meta['distance_to_building_m']}\n"
        f"confinement: {meta['confinement']}  surface_capping_type: {meta['surface_capping_type']}\n"
        f"{actuation_line}"
        f"\nRETRIEVED PROCEDURE EXCERPTS\n{chunks}\n"
        f"\nDraft the work order JSON now."
    )


def degraded_work_order(incident: dict, reason: str) -> dict:
    """No-LLM fallback template, built purely from the deterministic payload."""
    meta = incident["segment_meta"]
    grade = incident["assigned_grade"]
    return {
        "title": f"DEGRADED MODE — Grade {grade} leak, segment {incident['segment_id']}",
        "situation_summary": (
            f"LLM unavailable ({reason}). Deterministic grade {grade} "
            f"({incident['grading_rule']}) stands. Peak methane {incident['peak_methane_pct_lel']}% LEL, "
            f"surface capping {meta['surface_capping_type']}, distance to building {meta['distance_to_building_m']}m."
        ),
        "isolation_protocol": ["MANUAL REVIEW REQUIRED — template only, no synthesis available"],
        "permit_to_work_required": True,
        "ppe_required": ["MANUAL REVIEW REQUIRED"],
        "proximity_hazards": ["HCA" if meta["hca_flag"] else "none flagged — verify manually"],
        "crew_summary": "Dispatch per standard Grade-{} procedure; full narrative unavailable.".format(grade),
        "citations": [],
        "degraded_mode": True,
        "degraded_reason": reason,
    }


def synthesize(incident: dict, citations: list[dict], cfg: dict, actuator_state: dict | None = None) -> dict:
    grade = incident["assigned_grade"]
    schema = build_schema([c["chunk_id"] for c in citations])
    t0 = time.monotonic()
    try:
        response = ollama.chat(
            model=cfg["model"],
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_prompt(incident, citations, actuator_state)},
            ],
            format=schema,
            think=cfg["think"],
            options={"num_predict": cfg["num_predict"]},
        )
        latency_s = time.monotonic() - t0
        work_order = json.loads(response.message.content)
        for field in schema["required"]:
            if field not in work_order:
                raise ValueError(f"missing required field: {field}")
        work_order["degraded_mode"] = False
    except Exception as exc:
        latency_s = time.monotonic() - t0
        work_order = degraded_work_order(incident, reason=str(exc))

    return {
        "incident_id": incident["incident_id"],
        "segment_id": incident["segment_id"],
        "grade": grade,
        "priority": PRIORITY_BY_GRADE[grade],
        "model": cfg["model"],
        "latency_s": round(latency_s, 3),
        "work_order": work_order,
    }


def synthesize_all(incidents: list[dict], citations_by_incident: dict[str, list[dict]], cfg: dict) -> list[dict]:
    results = []
    for inc in incidents:
        if inc.get("assigned_grade") is None:
            continue
        cites = citations_by_incident.get(inc["incident_id"], [])
        results.append(synthesize(inc, cites, cfg))
    return results


def evaluate(results: list[dict], citations_by_incident: dict[str, list[dict]], cfg: dict) -> dict:
    """Checks against the blueprint's Part D metrics: 100% of work orders
    must cite a retrieved chunk, and end-to-end latency must stay < 40s."""
    uncited = []
    degraded = []
    for r in results:
        wo = r["work_order"]
        if wo["degraded_mode"]:
            degraded.append(r["incident_id"])
            continue
        valid_chunk_ids = {c["chunk_id"] for c in citations_by_incident.get(r["incident_id"], [])}
        if not set(wo.get("citations", [])) & valid_chunk_ids:
            uncited.append(r["incident_id"])

    latencies = [r["latency_s"] for r in results]
    over_budget = [r["incident_id"] for r in results if r["latency_s"] >= cfg["timeout_s"]]

    total = len(results)
    cited_ok = total - len(uncited) - len(degraded)
    return {
        "model": cfg["model"],
        "total_incidents": total,
        "degraded_count": len(degraded),
        "degraded_incidents": degraded,
        "citation_coverage": round(cited_ok / total, 3) if total else 0.0,
        "uncited_incidents": uncited,
        "latency_s": {
            "avg": round(sum(latencies) / total, 3) if total else 0.0,
            "max": round(max(latencies), 3) if latencies else 0.0,
            "min": round(min(latencies), 3) if latencies else 0.0,
        },
        "within_40s_budget": len(over_budget) == 0,
        "over_budget_incidents": over_budget,
    }


def run_pipeline(incidents_path: str, citations_path: str, output_dir: str, cfg: dict, verbose: bool = True) -> tuple[list[dict], dict]:
    incidents = json.loads(Path(incidents_path).read_text())
    citation_records = json.loads(Path(citations_path).read_text())
    citations_by_incident = {r["incident_id"]: r["citations"] for r in citation_records}

    results = synthesize_all(incidents, citations_by_incident, cfg)
    eval_report = evaluate(results, citations_by_incident, cfg)

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "work_orders.json").write_text(json.dumps(results, indent=2))
    (out / "synthesis_evaluation.json").write_text(json.dumps(eval_report, indent=2))

    if verbose:
        print(f"\n[M7] Synthesized {len(results)} work orders with model={cfg['model']}:")
        for r in results:
            status = "DEGRADED" if r["work_order"]["degraded_mode"] else "ok"
            print(f"    {r['incident_id']:<10} grade={r['grade']} latency={r['latency_s']}s  [{status}]")
        print(f"\n[M7] Citation coverage: {eval_report['citation_coverage']}  Within 40s budget: {eval_report['within_40s_budget']}")
        print(f"    latency avg/min/max: {eval_report['latency_s']['avg']}s / {eval_report['latency_s']['min']}s / {eval_report['latency_s']['max']}s")
        if eval_report["uncited_incidents"]:
            print(f"    UNCITED: {eval_report['uncited_incidents']}")
        print(f"\nOutputs saved to {out}/")

    return results, eval_report


def main():
    parser = argparse.ArgumentParser(description="M7 work-order synthesis (single Ollama call)")
    parser.add_argument("--incidents", "-i", default="data/grading_output/graded_incidents.json")
    parser.add_argument("--citations", "-c", default="data/retrieval_output/retrieved_citations.json")
    parser.add_argument("--output", "-o", default="data/synthesis_output")
    parser.add_argument("--model", "-m", default=CFG["model"],
                         help="configurable accuracy/speed variable (blueprint B.5)")
    args = parser.parse_args()

    cfg = dict(CFG)
    cfg["model"] = args.model

    run_pipeline(args.incidents, args.citations, args.output, cfg, verbose=True)


if __name__ == "__main__":
    main()
