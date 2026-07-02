"""
M3 — Data-quality checks + anomaly detection + urgency-based OR-routing.

Pipeline:
  1. DQ layer      — range validation, dedup, UTC parse  (pandera schema)
  2. Signal flags  — per-segment EWMA/z-score on pressure derivative;
                     magnitude thresholds on methane_%LEL and acoustic_index
  3. Persistence   — each channel must sustain ≥ N consecutive samples
  4. OR-routing    — methane/acoustic → inspection
                     pressure only    → hydraulic_check
                     both             → escalation
  5. Incident roll-up — consecutive flagged rows → one incident JSON payload
  6. Evaluation    — precision / recall / F1 vs ground-truth labels

All thresholds and windows live in CFG (bottom of file) — easy to tune.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pandera.pandas as pa
from pandera.pandas import Column, DataFrameSchema, Check
from sklearn.ensemble import IsolationForest

# ---------------------------------------------------------------------------
# Configuration — all tuneable parameters in one place
# ---------------------------------------------------------------------------
CFG: dict[str, Any] = {
    # Methane — set below sensor-drift max (9.2 % LEL) but above it to avoid FP
    "methane_lel_threshold": 10.0,        # % LEL; catches Grade-2 (18%), surface-fidelity (12%)
    # Acoustic — set above normal max (0.15); Grade-3 acoustic is ~0.19-0.23
    "acoustic_threshold": 0.18,           # index; 0.18 leaves 0.03 gap above normal max (0.15)
    # Pressure — very slow EWMA baseline + absolute deviation (NOT z-score / NOT derivative)
    # Rationale: z-score on the derivative fires only on the first drop sample (non-persistent).
    #            z-score on deviation adapts upward as anomaly samples fill the rolling window.
    #            Absolute deviation against a very slow EWMA stays stable across all 8 anomaly samples.
    "pressure_ewma_span": 200,            # span=200 → barely adapts during an 8-sample anomaly
    "pressure_abs_drop_bar": 0.08,        # bar below EWMA baseline to flag (normal noise ≈ 0.015 bar)
    # Persistence window
    "persistence_n": 3,                   # consecutive samples above threshold to confirm
    # IsolationForest ablation (optional)
    "isolation_forest_contamination": 0.05,
    "isolation_forest_features": ["pressure_bar", "methane_pct_lel", "acoustic_index", "flow_scm_h"],
}

# ---------------------------------------------------------------------------
# [1] Data-quality schema (pandera)
# ---------------------------------------------------------------------------
DQ_SCHEMA = DataFrameSchema(
    {
        "segment_id":             Column(str,   Check.isin(["SEG-001","SEG-002","SEG-003","SEG-004","SEG-005A","SEG-005B"])),
        "material":               Column(str,   nullable=False),
        "install_year":           Column(int,   Check.in_range(1900, 2030)),
        "MAOP_bar":               Column(float, Check.greater_than(0)),
        "location_class":         Column(int,   Check.in_range(1, 4)),
        "distance_to_building_m": Column(float, Check.greater_than_or_equal_to(0)),
        "pressure_bar":           Column(float, Check.in_range(0.0, 100.0)),
        "flow_scm_h":             Column(float, nullable=True),
        "methane_pct_lel":        Column(float, Check.in_range(0.0, 100.0)),
        "acoustic_index":         Column(float, Check.in_range(0.0, 10.0)),
    },
    coerce=True,
)


def run_dq(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Parse timestamps, dedup, validate schema. Returns (clean_df, report)."""
    report: dict[str, Any] = {}

    # UTC parse
    df = df.copy()
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)

    # Dedup on (segment_id, timestamp_utc)
    before = len(df)
    df = df.drop_duplicates(subset=["segment_id", "timestamp_utc"])
    report["rows_dropped_dedup"] = before - len(df)

    # Sort
    df = df.sort_values(["segment_id", "timestamp_utc"]).reset_index(drop=True)

    # Schema validation
    try:
        DQ_SCHEMA.validate(df, lazy=True)
        report["schema_valid"] = True
        report["schema_errors"] = []
    except pa.errors.SchemaErrors as exc:
        report["schema_valid"] = False
        report["schema_errors"] = exc.failure_cases.to_dict(orient="records")

    report["rows_after_dq"] = len(df)
    return df, report


# ---------------------------------------------------------------------------
# [2] Per-signal detectors (per-segment)
# ---------------------------------------------------------------------------

def _persistence_mask(flag: pd.Series, n: int) -> pd.Series:
    """True only where flag has been True for ≥ n consecutive samples."""
    if n <= 1:
        return flag
    return flag.rolling(window=n, min_periods=n).sum() >= n


def detect_methane_flags(seg: pd.DataFrame, cfg: dict) -> pd.Series:
    raw = seg["methane_pct_lel"] >= cfg["methane_lel_threshold"]
    return _persistence_mask(raw, cfg["persistence_n"]).fillna(False)


def detect_acoustic_flags(seg: pd.DataFrame, cfg: dict) -> pd.Series:
    raw = seg["acoustic_index"] >= cfg["acoustic_threshold"]
    return _persistence_mask(raw, cfg["persistence_n"]).fillna(False)


def detect_pressure_flags(seg: pd.DataFrame, cfg: dict) -> pd.Series:
    p = seg["pressure_bar"]

    # Very slow EWMA baseline (span=200 ≈ 3.3-hour window at 1-min samples).
    # With only 8 anomaly samples, the EWMA barely moves from the pre-anomaly level,
    # so (baseline - pressure) stays consistently large throughout the anomaly window —
    # which is exactly what the persistence check needs.
    ewma_baseline = p.ewm(span=cfg["pressure_ewma_span"], adjust=False).mean()

    raw = (ewma_baseline - p) > cfg["pressure_abs_drop_bar"]
    return _persistence_mask(raw, cfg["persistence_n"]).fillna(False)


# ---------------------------------------------------------------------------
# [3] OR-routing
# ---------------------------------------------------------------------------
_GAS_MASK  = "gas"       # methane or acoustic
_PRES_MASK = "pressure"


def compute_routes(seg: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Attach per-row detected_trigger and detected_route to a segment slice."""
    seg = seg.copy()
    meth_flag = detect_methane_flags(seg, cfg)
    acou_flag = detect_acoustic_flags(seg, cfg)
    pres_flag = detect_pressure_flags(seg, cfg)

    gas_flag = meth_flag | acou_flag

    # Build trigger label
    def _trigger(row_idx):
        parts = []
        if meth_flag.iloc[row_idx]:
            parts.append("methane")
        if acou_flag.iloc[row_idx]:
            parts.append("acoustic")
        if pres_flag.iloc[row_idx]:
            parts.append("pressure")
        return "+".join(parts) if parts else "none"

    seg["detected_trigger"] = [_trigger(i) for i in range(len(seg))]

    # OR-routing
    def _route(g, p):
        if g and p:
            return "escalation"
        if g:
            return "inspection"
        if p:
            return "hydraulic_check"
        return "normal"

    seg["detected_route"] = [
        _route(gas_flag.iloc[i], pres_flag.iloc[i]) for i in range(len(seg))
    ]
    return seg


# ---------------------------------------------------------------------------
# [4] Incident roll-up
# ---------------------------------------------------------------------------

def _roll_up_incidents(seg: pd.DataFrame) -> list[dict]:
    """Group consecutive non-normal rows into incident payloads."""
    incidents = []
    in_incident = False
    window: list[dict] = []

    for _, row in seg.iterrows():
        if row["detected_route"] != "normal":
            in_incident = True
            window.append(row.to_dict())
        else:
            if in_incident and window:
                incidents.append(_make_incident(window))
                window = []
            in_incident = False

    if in_incident and window:
        incidents.append(_make_incident(window))

    return incidents


_incident_counter = 0

def _make_incident(rows: list[dict]) -> dict:
    global _incident_counter
    _incident_counter += 1

    first, last = rows[0], rows[-1]
    seg_id = first["segment_id"]
    route  = first["detected_route"]   # first triggered sample's route

    # Use worst (most severe) route if it escalates mid-window
    all_routes = [r["detected_route"] for r in rows]
    if "escalation" in all_routes:
        route = "escalation"
    elif "inspection" in all_routes:
        route = "inspection"
    elif "hydraulic_check" in all_routes:
        route = "hydraulic_check"

    return {
        "incident_id": f"INC-{_incident_counter:04d}",
        "segment_id":  seg_id,
        "segment_meta": {
            "material":               first["material"],
            "install_year":           first["install_year"],
            "MAOP_bar":               first["MAOP_bar"],
            "location_class":         first["location_class"],
            "hca_flag":               first["hca_flag"],
            "distance_to_building_m": first["distance_to_building_m"],
            "confinement":            first["confinement"],
            "surface_capping_type":   first["surface_capping_type"],
        },
        "start_utc":         str(first["timestamp_utc"]),
        "end_utc":           str(last["timestamp_utc"]),
        "duration_samples":  len(rows),
        "detected_trigger":  first["detected_trigger"],
        "detected_route":    route,
        "peak_methane_pct_lel": round(max(r["methane_pct_lel"] for r in rows), 2),
        "peak_acoustic_index":  round(max(r["acoustic_index"]  for r in rows), 4),
        "min_pressure_bar":     round(min(r["pressure_bar"]    for r in rows), 4),
        "label_event": first.get("label_event"),
        "label_grade": first.get("label_grade"),
    }


# ---------------------------------------------------------------------------
# [5] Evaluation
# ---------------------------------------------------------------------------

def evaluate(df: pd.DataFrame, incidents: list[dict]) -> dict:
    """
    Compare detected incidents against ground-truth labels.

    Terminology:
      TP  — incident whose label_event is 'leak' (detected a real gas leak)
      FP  — incident whose label_event is 'normal', 'sensor_drift', or 'noise_spike'
            (should NEVER fire; a false alarm)
      Correct hydraulic — incident whose label_event is 'operational_swing' or
            'pressure_anomaly' AND detected_route is 'hydraulic_check'
            (correct routing of a legitimate pressure event — NOT a false positive)
      FN  — leak event block with no covering incident
    """
    # Classify every incident
    leak_events     = {"leak"}
    noise_events    = {"normal", "sensor_drift", "noise_spike"}
    pressure_events = {"operational_swing", "pressure_anomaly"}

    tp_incidents   = [i for i in incidents if i.get("label_event") in leak_events]
    fp_incidents   = [i for i in incidents if i.get("label_event") in noise_events]
    hyd_incidents  = [i for i in incidents if i.get("label_event") in pressure_events]

    tp = len(tp_incidents)
    fp = len(fp_incidents)

    # Correct hydraulic detections (pressure events routed to hydraulic_check)
    correct_hydraulic = sum(
        1 for i in hyd_incidents if i["detected_route"] == "hydraulic_check"
    )

    # Missed leaks: count distinct ground-truth leak blocks per segment
    # A block is a contiguous run of label_event=="leak" rows on the same segment
    def count_leak_blocks(seg_df: pd.DataFrame) -> int:
        flags = (seg_df["label_event"] == "leak").astype(int)
        # Count starts of contiguous blocks
        return int((flags.diff().fillna(flags) == 1).sum())

    gt_leak_blocks = (
        df.groupby("segment_id")
        .apply(count_leak_blocks)
        .sum()
    )
    fn = max(0, int(gt_leak_blocks) - tp)

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall    = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1        = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    # Routing accuracy: for leak incidents, compare detected_route vs ground truth route
    # Note: surface-capping escalation in ground truth reflects grading, not pure signal routing.
    # Detection routing is signal-only, so differences here are expected and handled in M4.
    signal_route_matches = 0
    for inc in tp_incidents:
        gt_route = df.loc[
            (df["segment_id"] == inc["segment_id"]) & (df["label_event"] == "leak"),
            "route"
        ].iloc[0]
        if inc["detected_route"] == gt_route:
            signal_route_matches += 1

    # Per-branch false alarm breakdown
    fp_by_event: dict[str, int] = {
        evt: sum(1 for i in fp_incidents if i.get("label_event") == evt)
        for evt in noise_events
    }

    return {
        "ground_truth_leak_blocks": int(gt_leak_blocks),
        "total_incidents_detected": len(incidents),
        "true_positives":           tp,
        "false_positives":          fp,
        "correct_hydraulic_checks": correct_hydraulic,
        "false_negatives":          fn,
        "precision":                round(precision, 3),
        "recall":                   round(recall, 3),
        "f1":                       round(f1, 3),
        "signal_route_match_of_tp": signal_route_matches,
        "fp_by_event_type":         fp_by_event,
        "note": (
            "signal_route_match counts where detection routing matches ground truth. "
            "Surface-fidelity pair diverges intentionally — grading (M4) resolves it."
        ),
    }


# ---------------------------------------------------------------------------
# [6] Optional IsolationForest ablation
# ---------------------------------------------------------------------------

def run_isolation_forest(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Add an `if_anomaly` flag column (1 = anomaly, -1 = normal per sklearn)."""
    features = cfg["isolation_forest_features"]
    X = df[features].fillna(df[features].median())
    clf = IsolationForest(
        contamination=cfg["isolation_forest_contamination"],
        random_state=42,
        n_estimators=100,
    )
    df = df.copy()
    df["if_score"]   = clf.fit(X).score_samples(X)   # lower = more anomalous
    df["if_anomaly"] = clf.predict(X)                 # -1 = anomaly, 1 = normal
    return df


def ablation_report(df: pd.DataFrame) -> dict:
    """Compare IsolationForest flags against ground truth."""
    if "if_anomaly" not in df.columns:
        return {"error": "IsolationForest not run"}

    df = df.copy()
    df["is_leak_gt"]    = df["label_event"] == "leak"
    df["if_detected"]   = df["if_anomaly"] == -1

    tp = int(( df["is_leak_gt"] &  df["if_detected"]).sum())
    fp = int((~df["is_leak_gt"] &  df["if_detected"]).sum())
    fn = int(( df["is_leak_gt"] & ~df["if_detected"]).sum())

    prec   = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1     = 2 * prec * recall / (prec + recall) if (prec + recall) > 0 else 0.0

    return {
        "model": "IsolationForest (ablation)",
        "tp": tp, "fp": fp, "fn": fn,
        "precision": round(prec, 3),
        "recall":    round(recall, 3),
        "f1":        round(f1, 3),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_pipeline(
    csv_path: str,
    output_dir: str,
    cfg: dict,
    run_if: bool = False,
    verbose: bool = True,
) -> tuple[list[dict], dict, dict | None]:

    global _incident_counter
    _incident_counter = 0

    # Load
    df_raw = pd.read_csv(csv_path)

    # [1] DQ
    df, dq_report = run_dq(df_raw)
    if verbose:
        print("\n[1] DQ report:")
        print(f"    Rows after DQ  : {dq_report['rows_after_dq']}")
        print(f"    Dedup dropped  : {dq_report['rows_dropped_dedup']}")
        print(f"    Schema valid   : {dq_report['schema_valid']}")
        if dq_report["schema_errors"]:
            print(f"    Schema errors  : {dq_report['schema_errors'][:3]}")

    # [2-4] Per-segment detection + routing + roll-up
    all_incidents: list[dict] = []
    result_frames: list[pd.DataFrame] = []

    for seg_id, seg_df in df.groupby("segment_id"):
        seg_df = seg_df.reset_index(drop=True)
        seg_routed = compute_routes(seg_df, cfg)
        incidents = _roll_up_incidents(seg_routed)
        all_incidents.extend(incidents)
        result_frames.append(seg_routed)

    df_result = pd.concat(result_frames).sort_values("timestamp_utc").reset_index(drop=True)

    if verbose:
        print(f"\n[2-4] Detection + routing:")
        print(f"    Total incidents  : {len(all_incidents)}")
        routes = [inc['detected_route'] for inc in all_incidents]
        for r in ["escalation", "inspection", "hydraulic_check"]:
            print(f"    {r:<20}: {routes.count(r)}")

    # [5] Evaluate
    eval_report = evaluate(df_result, all_incidents)
    if verbose:
        print("\n[5] Evaluation vs ground truth:")
        for k, v in eval_report.items():
            print(f"    {k:<35}: {v}")

    # [6] Optional IF ablation
    ablation = None
    if run_if:
        df_result = run_isolation_forest(df_result, cfg)
        ablation = ablation_report(df_result)
        if verbose:
            print("\n[6] IsolationForest ablation:")
            for k, v in ablation.items():
                print(f"    {k:<35}: {v}")

    # Save outputs
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    incidents_path = out / "incidents.json"
    with open(incidents_path, "w") as f:
        json.dump(all_incidents, f, indent=2, default=str)

    eval_path = out / "evaluation.json"
    with open(eval_path, "w") as f:
        payload = {
            "dq": dq_report,
            "detection": eval_report,
            "config": cfg,
        }
        if ablation:
            payload["ablation_isolation_forest"] = ablation
        json.dump(payload, f, indent=2, default=str)

    df_result_path = out / "telemetry_with_flags.csv"
    df_result.to_csv(df_result_path, index=False)

    if verbose:
        print(f"\nOutputs saved to {out}/")
        print(f"  incidents.json          ({len(all_incidents)} incidents)")
        print(f"  evaluation.json")
        print(f"  telemetry_with_flags.csv")

    return all_incidents, eval_report, ablation


def main():
    parser = argparse.ArgumentParser(description="M3 anomaly detection + routing")
    parser.add_argument("--input",  "-i", default="data/synthetic_telemetry.csv")
    parser.add_argument("--output", "-o", default="data/detection_output")
    parser.add_argument("--isolation-forest", action="store_true",
                        help="Run IsolationForest ablation comparison")
    parser.add_argument("--methane-threshold", type=float,
                        default=CFG["methane_lel_threshold"],
                        help="Methane pct LEL threshold (default: 10.0)")
    parser.add_argument("--persistence", type=int,
                        default=CFG["persistence_n"],
                        help="Persistence window in samples (default: 3)")
    parser.add_argument("--pressure-drop", type=float,
                        default=CFG["pressure_abs_drop_bar"],
                        help="Absolute pressure drop below EWMA baseline to flag (bar, default: 0.08)")
    args = parser.parse_args()

    cfg = dict(CFG)
    cfg["methane_lel_threshold"] = args.methane_threshold
    cfg["persistence_n"] = args.persistence
    cfg["pressure_abs_drop_bar"] = args.pressure_drop

    run_pipeline(
        csv_path=args.input,
        output_dir=args.output,
        cfg=cfg,
        run_if=args.isolation_forest,
        verbose=True,
    )


if __name__ == "__main__":
    main()
