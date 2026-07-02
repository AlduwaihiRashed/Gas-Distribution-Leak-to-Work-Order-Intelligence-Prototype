"""
M4 — Deterministic leak-grade rule engine (no LLM).

Grades every incident from data/detection_output/incidents.json as 1/2/3
(or None for hydraulic_check incidents, which aren't gas leaks at all).

Decision table (first match wins, most severe first):
  1. escalation route (methane/acoustic + pressure together) -> Grade 1
  2. inspection route (gas-only) + paved capping (asphalt/concrete)
       -> Grade 1  (GPTC/49 CFR 192: pavement forces lateral migration
                     into structures regardless of concentration)
  3. inspection route + unpaved capping (soil/grass), but near occupancy
     (HCA flag or close to a building) or elevated concentration -> Grade 2
  4. inspection route, unpaved, far from occupancy, low concentration -> Grade 3

Every decision is logged with the rule that fired (`grading_rule`) so the
output is auditable, per the blueprint's "no ungrounded safety output" rule.
"""

import argparse
import json
import math
from pathlib import Path
from typing import Any

CFG: dict[str, Any] = {
    "paved_capping_types": {"asphalt", "concrete"},   # forces lateral migration
    "moderate_lel_pct": 15.0,     # % LEL at/above which an unpaved leak escalates to Grade 2
    "building_proximity_m": 20.0, # distance below which an unpaved leak escalates to Grade 2
}


def grade_incident(inc: dict, cfg: dict) -> tuple[int | None, str]:
    """Return (grade, rule_fired) for one incident dict from incidents.json."""
    route = inc["detected_route"]
    meta = inc["segment_meta"]

    if route == "hydraulic_check":
        return None, "no gas signal -> hydraulic/SCADA check, not a leak grade"

    if route == "escalation":
        return 1, "multi-signal corroboration (gas + pressure) -> immediate hazard"

    # route == "inspection" (gas-only, confirmed persistent signal)
    if meta["surface_capping_type"] in cfg["paved_capping_types"]:
        return 1, f"paved capping ({meta['surface_capping_type']}) forces lateral migration -> immediate hazard"

    near_occupancy = meta["hca_flag"] or meta["distance_to_building_m"] <= cfg["building_proximity_m"]
    elevated_conc = inc["peak_methane_pct_lel"] >= cfg["moderate_lel_pct"]
    if near_occupancy or elevated_conc:
        return 2, "unpaved but near occupancy/HCA or elevated concentration -> scheduled repair"

    return 3, "unpaved, low concentration, away from occupancy -> monitor/re-evaluate"


def _clean_label(label: Any) -> int | None:
    """incidents.json stores un-graded rows as float('nan'); normalise to None."""
    if label is None or (isinstance(label, float) and math.isnan(label)):
        return None
    return int(label)


def grade_incidents(incidents: list[dict], cfg: dict) -> list[dict]:
    graded = []
    for inc in incidents:
        grade, rule = grade_incident(inc, cfg)
        graded.append({**inc, "assigned_grade": grade, "grading_rule": rule})
    return graded


def evaluate(graded: list[dict]) -> dict:
    """Confusion matrix + accuracy of assigned_grade vs ground-truth label_grade."""
    mismatches = []
    correct = 0
    for g in graded:
        truth = _clean_label(g.get("label_grade"))
        if g["assigned_grade"] == truth:
            correct += 1
        else:
            mismatches.append({
                "incident_id": g["incident_id"],
                "assigned_grade": g["assigned_grade"],
                "label_grade": truth,
                "grading_rule": g["grading_rule"],
            })

    return {
        "total_incidents": len(graded),
        "correct": correct,
        "accuracy": round(correct / len(graded), 3) if graded else 0.0,
        "mismatches": mismatches,
    }


def run_pipeline(input_path: str, output_dir: str, cfg: dict, verbose: bool = True) -> tuple[list[dict], dict]:
    incidents = json.loads(Path(input_path).read_text())
    graded = grade_incidents(incidents, cfg)
    eval_report = evaluate(graded)

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "graded_incidents.json").write_text(json.dumps(graded, indent=2, default=str))
    (out / "grading_evaluation.json").write_text(json.dumps({"grading": eval_report, "config": {**cfg, "paved_capping_types": list(cfg["paved_capping_types"])}}, indent=2))

    if verbose:
        print(f"\n[M4] Graded {len(graded)} incidents:")
        for g in graded:
            print(f"    {g['incident_id']:<10} route={g['detected_route']:<16} grade={str(g['assigned_grade']):<4} ({g['grading_rule']})")
        print(f"\n[M4] Evaluation vs ground truth:")
        print(f"    accuracy: {eval_report['accuracy']} ({eval_report['correct']}/{eval_report['total_incidents']})")
        for m in eval_report["mismatches"]:
            print(f"    MISMATCH {m['incident_id']}: assigned={m['assigned_grade']} label={m['label_grade']} ({m['grading_rule']})")
        print(f"\nOutputs saved to {out}/")

    return graded, eval_report


def main():
    parser = argparse.ArgumentParser(description="M4 deterministic leak-grade rule engine")
    parser.add_argument("--input", "-i", default="data/detection_output/incidents.json")
    parser.add_argument("--output", "-o", default="data/grading_output")
    parser.add_argument("--moderate-lel", type=float, default=CFG["moderate_lel_pct"])
    parser.add_argument("--building-proximity", type=float, default=CFG["building_proximity_m"])
    args = parser.parse_args()

    cfg = dict(CFG)
    cfg["moderate_lel_pct"] = args.moderate_lel
    cfg["building_proximity_m"] = args.building_proximity

    run_pipeline(args.input, args.output, cfg, verbose=True)


if __name__ == "__main__":
    main()
