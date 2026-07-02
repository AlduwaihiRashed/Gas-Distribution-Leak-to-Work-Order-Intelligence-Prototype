"""
M9 — Live telemetry ingestion for the benchtop hardware rig (blueprint R8).

Feeds real ESP32 readings through the *same* deterministic detection
(M3/detect_anomalies.py) and grading (M4/grade_leak.py) logic the batch CSV
path uses — no separate "streaming" detection rules to keep in sync or
drift out of sync with the evaluated batch pipeline. RAG citation (M6) is
reused too.

Design choice, stated explicitly: an incident is graded and (if Grade 1)
isolation is fired the INSTANT persistence confirms an anomaly on the
latest reading — not when the anomaly later subsides. Waiting for the leak
to "end" before acting would defeat the entire point of a time-critical
action. The incident record is then refined (final peak values, end_utc)
when the window closes, but the grade and any isolate command already
fired are never revised — the earliest safety-relevant action stands.

In-memory per-segment state (buffers, open-incident tracking) lives only in
this process; it is not persisted, because it's a live-session cache over
data that IS persisted (graded_incidents.json, retrieved_citations.json).
Restarting the API loses in-flight incident context but not the safety
record already written for anything already graded.
"""

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import chromadb
import pandas as pd

import actuation
import detect_anomalies as det
import grade_leak as grader
import retrieve_procedures as retriever

GRADED_INCIDENTS_PATH = Path("data/grading_output/graded_incidents.json")
CITATIONS_PATH = Path("data/retrieval_output/retrieved_citations.json")

MAX_BUFFER = 260  # > pressure_ewma_span (200) so the EWMA baseline has room to settle

_lock = threading.Lock()
_buffers: dict[str, list[dict]] = {}
_open_incidents: dict[str, dict] = {}  # segment_id -> {"incident_id", "window": [rows]}
_incident_seq = 0

_chroma_client = chromadb.PersistentClient(path="data/chroma_db")
_collection = _chroma_client.get_collection(retriever.CFG["collection_name"])


def _next_incident_id() -> str:
    global _incident_seq
    _incident_seq += 1
    return f"LIVE-{int(time.time())}-{_incident_seq:04d}"


def _load_json(path: Path) -> list:
    if not path.exists():
        return []
    return json.loads(path.read_text())


def _save_json(path: Path, data: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str))


def _upsert(path: Path, record: dict, key: str) -> None:
    records = _load_json(path)
    for i, r in enumerate(records):
        if r.get(key) == record.get(key):
            records[i] = record
            _save_json(path, records)
            return
    records.append(record)
    _save_json(path, records)


def _row_to_incident(incident_id: str, route: str, rows: list[dict]) -> dict:
    first, last = rows[0], rows[-1]
    return {
        "incident_id": incident_id,
        "segment_id": first["segment_id"],
        "segment_meta": {
            "material": first["material"],
            "install_year": first["install_year"],
            "MAOP_bar": first["MAOP_bar"],
            "location_class": first["location_class"],
            "hca_flag": first["hca_flag"],
            "distance_to_building_m": first["distance_to_building_m"],
            "confinement": first["confinement"],
            "surface_capping_type": first["surface_capping_type"],
        },
        "start_utc": str(first["timestamp_utc"]),
        "end_utc": str(last["timestamp_utc"]),
        "duration_samples": len(rows),
        "detected_trigger": last["detected_trigger"],
        "detected_route": route,
        "peak_methane_pct_lel": round(max(r["methane_pct_lel"] for r in rows), 2),
        "peak_acoustic_index": round(max(r["acoustic_index"] for r in rows), 4),
        "min_pressure_bar": round(min(r["pressure_bar"] for r in rows), 4),
        "label_event": None,
        "label_grade": None,
        "source": "live",
    }


def _grade_and_cite(incident: dict) -> dict:
    grade, rule = grader.grade_incident(incident, grader.CFG)
    incident = {**incident, "assigned_grade": grade, "grading_rule": rule}
    _upsert(GRADED_INCIDENTS_PATH, incident, "incident_id")

    if grade is not None:
        result = retriever.retrieve_for_incident(_collection, incident, retriever.CFG)
        citations = _load_json(CITATIONS_PATH)
        citations = [c for c in citations if c["incident_id"] != incident["incident_id"]]
        citations.append(result)
        _save_json(CITATIONS_PATH, citations)

    return incident


def ingest_reading(reading: dict) -> dict:
    """One ESP32 sample in. Returns a status dict describing what happened —
    a new incident opened/extended/closed, and whether isolation fired."""
    segment_id = reading["segment_id"]

    with _lock:
        buf = _buffers.setdefault(segment_id, [])
        buf.append(reading)
        if len(buf) > MAX_BUFFER:
            del buf[: len(buf) - MAX_BUFFER]

        df = pd.DataFrame(buf)
        df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)
        routed = det.compute_routes(df, det.CFG)
        latest = routed.iloc[-1]

        open_inc = _open_incidents.get(segment_id)
        isolate_fired = False
        graded_incident = None

        if latest["detected_route"] != "normal":
            latest_row = latest.to_dict()
            if open_inc is None:
                incident_id = _next_incident_id()
                _open_incidents[segment_id] = {"incident_id": incident_id, "window": [latest_row]}
                incident = _row_to_incident(incident_id, latest["detected_route"], [latest_row])
                graded_incident = _grade_and_cite(incident)
                if graded_incident["assigned_grade"] == 1:
                    actuation.publish_isolate(segment_id, incident_id)
                    isolate_fired = True
                status = "incident_opened"
            else:
                open_inc["window"].append(latest_row)
                routes_so_far = [r["detected_route"] for r in open_inc["window"]]
                worst = "escalation" if "escalation" in routes_so_far else (
                    "inspection" if "inspection" in routes_so_far else "hydraulic_check"
                )
                status = "incident_extended"
                incident_id = open_inc["incident_id"]
                if worst != _load_incident_route(incident_id):
                    # escalated mid-window (e.g. gas-only -> gas+pressure): re-grade,
                    # and if that NEWLY crosses into Grade 1, fire isolation now —
                    # but never re-fire if it was already commanded for this incident.
                    incident = _row_to_incident(incident_id, worst, open_inc["window"])
                    graded_incident = _grade_and_cite(incident)
                    if graded_incident["assigned_grade"] == 1 and actuation.get_actuator_state(incident_id) is None:
                        actuation.publish_isolate(segment_id, incident_id)
                        isolate_fired = True
        else:
            if open_inc is not None:
                incident_id = open_inc["incident_id"]
                worst_route = _load_incident_route(incident_id) or "inspection"
                incident = _row_to_incident(incident_id, worst_route, open_inc["window"])
                # grade/citations already set when opened (or last escalated); only
                # refine the descriptive summary fields, never revise the grade.
                existing = next((r for r in _load_json(GRADED_INCIDENTS_PATH) if r["incident_id"] == incident_id), None)
                if existing:
                    incident["assigned_grade"] = existing["assigned_grade"]
                    incident["grading_rule"] = existing["grading_rule"]
                    _upsert(GRADED_INCIDENTS_PATH, incident, "incident_id")
                del _open_incidents[segment_id]
                status = "incident_closed"
            else:
                status = "normal"

    return {
        "segment_id": segment_id,
        "detected_route": latest["detected_route"],
        "status": status,
        "isolate_fired": isolate_fired,
        "graded_incident": graded_incident,
    }


def _load_incident_route(incident_id: str) -> str | None:
    for r in _load_json(GRADED_INCIDENTS_PATH):
        if r["incident_id"] == incident_id:
            return r["detected_route"]
    return None
