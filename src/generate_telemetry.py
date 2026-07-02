"""
Synthetic telemetry generator for the Gas Distribution L2WO prototype.

Produces a labelled CSV covering all scenario types required by Part D of the blueprint:
  - Grade 1/2/3 positive leak cases
  - Negative/trap cases (sensor drift, operational pressure swing, sub-threshold noise)
  - Routing cases (methane-only, pressure-only, both-signals)
  - Surface-capping fidelity pair (soil vs asphalt, identical leak → Grade 3 vs Grade 1)

Schema (Appendix A):
  timestamp_utc, segment_id, material, install_year, MAOP_bar, location_class,
  hca_flag, distance_to_building_m, confinement, surface_capping_type,
  pressure_bar, flow_scm_h, methane_pct_lel, acoustic_index,
  trigger_channel, route, label_event, label_grade
"""

import argparse
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

RNG = np.random.default_rng(42)

# ---------------------------------------------------------------------------
# Segment catalogue — each entry is a pipeline segment with fixed topology
# ---------------------------------------------------------------------------
SEGMENTS = [
    {
        "segment_id": "SEG-001",
        "material": "PE",
        "install_year": 2008,
        "MAOP_bar": 4.0,
        "location_class": 3,
        "hca_flag": True,
        "distance_to_building_m": 8.0,
        "confinement": "below_pavement",
        "surface_capping_type": "asphalt",
        "nominal_pressure_bar": 3.6,
        "nominal_flow_scm_h": 120.0,
    },
    {
        "segment_id": "SEG-002",
        "material": "cast_iron",
        "install_year": 1975,
        "MAOP_bar": 1.0,
        "location_class": 2,
        "hca_flag": False,
        "distance_to_building_m": 45.0,
        "confinement": "open_row",
        "surface_capping_type": "soil",
        "nominal_pressure_bar": 0.85,
        "nominal_flow_scm_h": 55.0,
    },
    {
        "segment_id": "SEG-003",
        "material": "steel",
        "install_year": 1992,
        "MAOP_bar": 7.0,
        "location_class": 1,
        "hca_flag": False,
        "distance_to_building_m": 120.0,
        "confinement": "open_row",
        "surface_capping_type": "grass",
        "nominal_pressure_bar": 6.2,
        "nominal_flow_scm_h": 310.0,
    },
    {
        "segment_id": "SEG-004",
        "material": "PE",
        "install_year": 2015,
        "MAOP_bar": 4.0,
        "location_class": 3,
        "hca_flag": True,
        "distance_to_building_m": 5.0,
        "confinement": "below_pavement",
        "surface_capping_type": "concrete",
        "nominal_pressure_bar": 3.5,
        "nominal_flow_scm_h": 95.0,
    },
    # Pair for surface-capping fidelity test (identical pipe, only capping differs)
    {
        "segment_id": "SEG-005A",
        "material": "PE",
        "install_year": 2010,
        "MAOP_bar": 4.0,
        "location_class": 2,
        "hca_flag": False,
        "distance_to_building_m": 30.0,
        "confinement": "open_row",
        "surface_capping_type": "soil",       # same leak → Grade 3
        "nominal_pressure_bar": 3.4,
        "nominal_flow_scm_h": 100.0,
    },
    {
        "segment_id": "SEG-005B",
        "material": "PE",
        "install_year": 2010,
        "MAOP_bar": 4.0,
        "location_class": 2,
        "hca_flag": False,
        "distance_to_building_m": 30.0,
        "confinement": "below_pavement",
        "surface_capping_type": "asphalt",    # same leak → Grade 1
        "nominal_pressure_bar": 3.4,
        "nominal_flow_scm_h": 100.0,
    },
]

SEG_MAP = {s["segment_id"]: s for s in SEGMENTS}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ts_range(start: datetime, n: int, step_s: int = 60):
    return [start + timedelta(seconds=i * step_s) for i in range(n)]


def _noise(scale: float, size: int) -> np.ndarray:
    return RNG.normal(0, scale, size)


def _baseline_row(seg: dict, ts: datetime) -> dict:
    """Return one normal-operation row for a segment."""
    p = seg["nominal_pressure_bar"] + _noise(0.01, 1)[0]
    f = seg["nominal_flow_scm_h"] + _noise(1.5, 1)[0]
    m = max(0.0, RNG.uniform(0.0, 2.0))   # background methane noise 0-2 % LEL
    a = max(0.0, RNG.uniform(0.0, 0.15))  # low acoustic background
    return {
        "timestamp_utc": ts.isoformat(),
        "segment_id": seg["segment_id"],
        "material": seg["material"],
        "install_year": seg["install_year"],
        "MAOP_bar": seg["MAOP_bar"],
        "location_class": seg["location_class"],
        "hca_flag": seg["hca_flag"],
        "distance_to_building_m": seg["distance_to_building_m"],
        "confinement": seg["confinement"],
        "surface_capping_type": seg["surface_capping_type"],
        "pressure_bar": round(p, 4),
        "flow_scm_h": round(f, 2),
        "methane_pct_lel": round(m, 2),
        "acoustic_index": round(a, 4),
        "trigger_channel": "none",
        "route": "normal",
        "label_event": "normal",
        "label_grade": None,
    }


def _rows_baseline(seg: dict, start: datetime, n: int) -> list[dict]:
    return [_baseline_row(seg, ts) for ts in _ts_range(start, n)]


# ---------------------------------------------------------------------------
# Scenario builders
# Each returns a list of dicts (rows) with fully labelled data.
# ---------------------------------------------------------------------------

def scenario_grade1_near_building(start: datetime) -> list[dict]:
    """
    Grade 1: high methane + acoustic, near building, asphalt, HCA.
    Both channels fire → escalation route.
    """
    seg = SEG_MAP["SEG-001"]
    rows = _rows_baseline(seg, start, 5)  # 5-sample pre-event baseline
    # inject persistent anomaly for 8 samples (> persistence window)
    for i, ts in enumerate(_ts_range(start + timedelta(minutes=5), 8)):
        m = round(35.0 + _noise(2.0, 1)[0], 2)   # 35 % LEL — above threshold (20 %)
        a = round(0.75 + _noise(0.05, 1)[0], 4)   # high acoustic
        p = round(seg["nominal_pressure_bar"] - 0.12 + _noise(0.005, 1)[0], 4)
        f = round(seg["nominal_flow_scm_h"] - 8.0 + _noise(0.5, 1)[0], 2)
        rows.append({
            **{k: seg[k] for k in [
                "segment_id", "material", "install_year", "MAOP_bar",
                "location_class", "hca_flag", "distance_to_building_m",
                "confinement", "surface_capping_type",
            ]},
            "timestamp_utc": ts.isoformat(),
            "pressure_bar": p,
            "flow_scm_h": f,
            "methane_pct_lel": m,
            "acoustic_index": a,
            "trigger_channel": "methane+acoustic+pressure",
            "route": "escalation",
            "label_event": "leak",
            "label_grade": 1,
        })
    return rows


def scenario_grade2_subsurface(start: datetime) -> list[dict]:
    """
    Grade 2: moderate methane, away from buildings, soil, no HCA.
    Methane-only channel → inspection WO, grade 2 due to distance + soil.
    """
    seg = SEG_MAP["SEG-002"]
    rows = _rows_baseline(seg, start, 5)
    for ts in _ts_range(start + timedelta(minutes=5), 8):
        m = round(18.0 + _noise(1.5, 1)[0], 2)   # 18 % LEL — moderate
        a = round(0.35 + _noise(0.03, 1)[0], 4)
        p = round(seg["nominal_pressure_bar"] + _noise(0.008, 1)[0], 4)  # stable
        f = round(seg["nominal_flow_scm_h"] + _noise(1.0, 1)[0], 2)
        rows.append({
            **{k: seg[k] for k in [
                "segment_id", "material", "install_year", "MAOP_bar",
                "location_class", "hca_flag", "distance_to_building_m",
                "confinement", "surface_capping_type",
            ]},
            "timestamp_utc": ts.isoformat(),
            "pressure_bar": p,
            "flow_scm_h": f,
            "methane_pct_lel": m,
            "acoustic_index": a,
            "trigger_channel": "methane+acoustic",
            "route": "inspection",
            "label_event": "leak",
            "label_grade": 2,
        })
    return rows


def scenario_grade3_open_row(start: datetime) -> list[dict]:
    """
    Grade 3: low methane, open ROW, soil, far from buildings, no HCA.
    Gas vents upward safely → monitor/re-evaluate.
    """
    seg = SEG_MAP["SEG-003"]
    rows = _rows_baseline(seg, start, 5)
    for ts in _ts_range(start + timedelta(minutes=5), 8):
        m = round(8.0 + _noise(1.0, 1)[0], 2)    # 8 % LEL — low
        a = round(0.22 + _noise(0.02, 1)[0], 4)
        p = round(seg["nominal_pressure_bar"] + _noise(0.015, 1)[0], 4)
        f = round(seg["nominal_flow_scm_h"] + _noise(2.0, 1)[0], 2)
        rows.append({
            **{k: seg[k] for k in [
                "segment_id", "material", "install_year", "MAOP_bar",
                "location_class", "hca_flag", "distance_to_building_m",
                "confinement", "surface_capping_type",
            ]},
            "timestamp_utc": ts.isoformat(),
            "pressure_bar": p,
            "flow_scm_h": f,
            "methane_pct_lel": m,
            "acoustic_index": a,
            "trigger_channel": "methane",
            "route": "inspection",
            "label_event": "leak",
            "label_grade": 3,
        })
    return rows


def scenario_sensor_drift(start: datetime) -> list[dict]:
    """
    Negative/trap: gradual methane sensor drift — never clears persistence
    threshold cleanly; sub-threshold; should NOT trigger.
    """
    seg = SEG_MAP["SEG-002"]
    rows = _rows_baseline(seg, start, 5)
    for i, ts in enumerate(_ts_range(start + timedelta(minutes=5), 10)):
        # Slow linear drift, stays below action threshold of 20 % LEL
        m = round(2.0 + i * 0.8 + _noise(0.5, 1)[0], 2)  # peaks ~9.2 % LEL
        a = round(0.05 + _noise(0.02, 1)[0], 4)
        p = round(seg["nominal_pressure_bar"] + _noise(0.01, 1)[0], 4)
        f = round(seg["nominal_flow_scm_h"] + _noise(1.0, 1)[0], 2)
        rows.append({
            **{k: seg[k] for k in [
                "segment_id", "material", "install_year", "MAOP_bar",
                "location_class", "hca_flag", "distance_to_building_m",
                "confinement", "surface_capping_type",
            ]},
            "timestamp_utc": ts.isoformat(),
            "pressure_bar": p,
            "flow_scm_h": f,
            "methane_pct_lel": m,
            "acoustic_index": a,
            "trigger_channel": "none",
            "route": "normal",
            "label_event": "sensor_drift",
            "label_grade": None,
        })
    return rows


def scenario_operational_pressure_swing(start: datetime) -> list[dict]:
    """
    Negative/trap: planned pressure reduction (e.g. network balancing).
    Pressure drops but no gas reading — should raise hydraulic/SCADA check,
    NOT a leak work order.
    """
    seg = SEG_MAP["SEG-001"]
    rows = _rows_baseline(seg, start, 5)
    for ts in _ts_range(start + timedelta(minutes=5), 8):
        p = round(seg["nominal_pressure_bar"] - 0.35 + _noise(0.01, 1)[0], 4)  # large drop
        f = round(seg["nominal_flow_scm_h"] - 25.0 + _noise(1.5, 1)[0], 2)
        m = round(RNG.uniform(0.0, 2.0), 2)   # background only
        a = round(RNG.uniform(0.0, 0.12), 4)
        rows.append({
            **{k: seg[k] for k in [
                "segment_id", "material", "install_year", "MAOP_bar",
                "location_class", "hca_flag", "distance_to_building_m",
                "confinement", "surface_capping_type",
            ]},
            "timestamp_utc": ts.isoformat(),
            "pressure_bar": p,
            "flow_scm_h": f,
            "methane_pct_lel": m,
            "acoustic_index": a,
            "trigger_channel": "pressure",
            "route": "hydraulic_check",
            "label_event": "operational_swing",
            "label_grade": None,
        })
    return rows


def scenario_subthreshold_noise(start: datetime) -> list[dict]:
    """
    Negative/trap: single-sample methane spike (1 sample, not sustained).
    Must NOT trigger — persistence window suppresses it.
    """
    seg = SEG_MAP["SEG-003"]
    rows = _rows_baseline(seg, start, 5)
    # One big spike then back to normal
    spike_ts = start + timedelta(minutes=5)
    rows.append({
        **{k: seg[k] for k in [
            "segment_id", "material", "install_year", "MAOP_bar",
            "location_class", "hca_flag", "distance_to_building_m",
            "confinement", "surface_capping_type",
        ]},
        "timestamp_utc": spike_ts.isoformat(),
        "pressure_bar": round(seg["nominal_pressure_bar"] + _noise(0.01, 1)[0], 4),
        "flow_scm_h": round(seg["nominal_flow_scm_h"] + _noise(1.5, 1)[0], 2),
        "methane_pct_lel": 28.0,  # above threshold but single sample
        "acoustic_index": 0.05,
        "trigger_channel": "none",
        "route": "normal",
        "label_event": "noise_spike",
        "label_grade": None,
    })
    rows += _rows_baseline(seg, spike_ts + timedelta(minutes=1), 4)
    return rows


def scenario_methane_only_routing(start: datetime) -> list[dict]:
    """
    Routing case: methane spike sustained, NO pressure drop.
    Expect: inspection route (single-channel signal, not multi-signal escalation) —
    but concrete capping + HCA + near-building still forces Grade 1 at the grading
    layer (M4), since paved cover escalates independent of signal count. This is
    the intended split between routing (signal-based) and grading (capping-aware).
    """
    seg = SEG_MAP["SEG-004"]
    rows = _rows_baseline(seg, start, 5)
    for ts in _ts_range(start + timedelta(minutes=5), 8):
        m = round(25.0 + _noise(2.0, 1)[0], 2)    # >20% LEL threshold
        a = round(0.55 + _noise(0.04, 1)[0], 4)
        p = round(seg["nominal_pressure_bar"] + _noise(0.008, 1)[0], 4)  # stable
        f = round(seg["nominal_flow_scm_h"] + _noise(1.0, 1)[0], 2)
        rows.append({
            **{k: seg[k] for k in [
                "segment_id", "material", "install_year", "MAOP_bar",
                "location_class", "hca_flag", "distance_to_building_m",
                "confinement", "surface_capping_type",
            ]},
            "timestamp_utc": ts.isoformat(),
            "pressure_bar": p,
            "flow_scm_h": f,
            "methane_pct_lel": m,
            "acoustic_index": a,
            "trigger_channel": "methane+acoustic",
            "route": "inspection",
            "label_event": "leak",
            "label_grade": 1,
        })
    return rows


def scenario_pressure_only_routing(start: datetime) -> list[dict]:
    """
    Routing case: pressure drop sustained, NO methane reading.
    Expect: hydraulic/SCADA check, NOT a leak emergency dispatch.
    """
    seg = SEG_MAP["SEG-003"]
    rows = _rows_baseline(seg, start, 5)
    for ts in _ts_range(start + timedelta(minutes=5), 8):
        p = round(seg["nominal_pressure_bar"] - 0.4 + _noise(0.01, 1)[0], 4)
        f = round(seg["nominal_flow_scm_h"] - 30.0 + _noise(2.0, 1)[0], 2)
        m = round(RNG.uniform(0.0, 2.0), 2)   # background
        a = round(RNG.uniform(0.0, 0.10), 4)
        rows.append({
            **{k: seg[k] for k in [
                "segment_id", "material", "install_year", "MAOP_bar",
                "location_class", "hca_flag", "distance_to_building_m",
                "confinement", "surface_capping_type",
            ]},
            "timestamp_utc": ts.isoformat(),
            "pressure_bar": p,
            "flow_scm_h": f,
            "methane_pct_lel": m,
            "acoustic_index": a,
            "trigger_channel": "pressure",
            "route": "hydraulic_check",
            "label_event": "pressure_anomaly",
            "label_grade": None,
        })
    return rows


def scenario_surface_fidelity_soil(start: datetime) -> list[dict]:
    """
    Surface-capping fidelity: identical small leak, SOIL cover → Grade 3
    (gas vents upward safely).
    """
    seg = SEG_MAP["SEG-005A"]
    rows = _rows_baseline(seg, start, 5)
    for ts in _ts_range(start + timedelta(minutes=5), 8):
        m = round(12.0 + _noise(1.0, 1)[0], 2)
        a = round(0.28 + _noise(0.02, 1)[0], 4)
        p = round(seg["nominal_pressure_bar"] + _noise(0.01, 1)[0], 4)
        f = round(seg["nominal_flow_scm_h"] + _noise(1.0, 1)[0], 2)
        rows.append({
            **{k: seg[k] for k in [
                "segment_id", "material", "install_year", "MAOP_bar",
                "location_class", "hca_flag", "distance_to_building_m",
                "confinement", "surface_capping_type",
            ]},
            "timestamp_utc": ts.isoformat(),
            "pressure_bar": p,
            "flow_scm_h": f,
            "methane_pct_lel": m,
            "acoustic_index": a,
            "trigger_channel": "methane",
            "route": "inspection",
            "label_event": "leak",
            "label_grade": 3,
        })
    return rows


def scenario_surface_fidelity_asphalt(start: datetime) -> list[dict]:
    """
    Surface-capping fidelity: IDENTICAL small leak, ASPHALT cover → Grade 1
    (gas migrates laterally into basements; immediate hazard).
    """
    seg = SEG_MAP["SEG-005B"]
    rows = _rows_baseline(seg, start, 5)
    for ts in _ts_range(start + timedelta(minutes=5), 8):
        m = round(12.0 + _noise(1.0, 1)[0], 2)   # same concentration as soil case
        a = round(0.28 + _noise(0.02, 1)[0], 4)
        p = round(seg["nominal_pressure_bar"] + _noise(0.01, 1)[0], 4)
        f = round(seg["nominal_flow_scm_h"] + _noise(1.0, 1)[0], 2)
        rows.append({
            **{k: seg[k] for k in [
                "segment_id", "material", "install_year", "MAOP_bar",
                "location_class", "hca_flag", "distance_to_building_m",
                "confinement", "surface_capping_type",
            ]},
            "timestamp_utc": ts.isoformat(),
            "pressure_bar": p,
            "flow_scm_h": f,
            "methane_pct_lel": m,
            "acoustic_index": a,
            "trigger_channel": "methane",
            "route": "escalation",
            "label_event": "leak",
            "label_grade": 1,
        })
    return rows


def scenario_extended_baseline(start: datetime, n: int = 60) -> list[dict]:
    """
    Extended normal background for all segments — provides the majority of
    negative examples for detection training/evaluation.
    """
    rows = []
    for seg in SEGMENTS:
        rows += _rows_baseline(seg, start, n // len(SEGMENTS))
    return rows


# ---------------------------------------------------------------------------
# Main assembler
# ---------------------------------------------------------------------------

def build_dataset(n_background: int = 300) -> pd.DataFrame:
    base = datetime(2025, 6, 1, 0, 0, 0, tzinfo=timezone.utc)

    all_rows: list[dict] = []

    # Background normal operation spread over several starting points
    all_rows += scenario_extended_baseline(base, n_background)

    # Positive leak scenarios
    all_rows += scenario_grade1_near_building(base + timedelta(hours=6))
    all_rows += scenario_grade2_subsurface(base + timedelta(hours=8))
    all_rows += scenario_grade3_open_row(base + timedelta(hours=10))

    # Negative / trap cases
    all_rows += scenario_sensor_drift(base + timedelta(hours=12))
    all_rows += scenario_operational_pressure_swing(base + timedelta(hours=14))
    all_rows += scenario_subthreshold_noise(base + timedelta(hours=16))

    # Routing tests
    all_rows += scenario_methane_only_routing(base + timedelta(hours=18))
    all_rows += scenario_pressure_only_routing(base + timedelta(hours=20))

    # Surface-capping fidelity pair
    all_rows += scenario_surface_fidelity_soil(base + timedelta(hours=22))
    all_rows += scenario_surface_fidelity_asphalt(base + timedelta(hours=23))

    df = pd.DataFrame(all_rows)
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"])
    df.sort_values("timestamp_utc", inplace=True)
    df.reset_index(drop=True, inplace=True)
    return df


def print_summary(df: pd.DataFrame) -> None:
    print("\n=== Dataset summary ===")
    print(f"Total rows       : {len(df)}")
    print(f"Segments         : {sorted(df['segment_id'].unique())}")
    print(f"\nEvent distribution:")
    print(df["label_event"].value_counts().to_string())
    print(f"\nGrade distribution:")
    print(df["label_grade"].value_counts(dropna=False).to_string())
    print(f"\nRoute distribution:")
    print(df["route"].value_counts().to_string())
    print(f"\nTrigger-channel distribution:")
    print(df["trigger_channel"].value_counts().to_string())
    print(f"\nSurface-capping fidelity pair check:")
    fidelity = df[df["segment_id"].isin(["SEG-005A", "SEG-005B"]) & (df["label_event"] == "leak")]
    print(fidelity[["segment_id", "surface_capping_type", "methane_pct_lel", "label_grade"]].to_string(index=False))


def main():
    parser = argparse.ArgumentParser(description="Generate synthetic gas telemetry dataset")
    parser.add_argument(
        "--output", "-o",
        default="data/synthetic_telemetry.csv",
        help="Output CSV path (default: data/synthetic_telemetry.csv)",
    )
    parser.add_argument(
        "--background-rows", type=int, default=300,
        help="Number of background normal-operation rows (default: 300)",
    )
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    args = parser.parse_args()

    global RNG
    RNG = np.random.default_rng(args.seed)
    random.seed(args.seed)

    print(f"Generating synthetic telemetry (seed={args.seed}, background={args.background_rows})...")
    df = build_dataset(n_background=args.background_rows)
    print_summary(df)

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    print(f"\nSaved → {out}  ({len(df)} rows × {len(df.columns)} columns)")


if __name__ == "__main__":
    main()
