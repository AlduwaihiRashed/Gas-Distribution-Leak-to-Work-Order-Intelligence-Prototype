"""
M8 — HTTP API fronting the pipeline for N8N orchestration (M5 in the blueprint).

The pipeline stages ([1]-[4]) are plain Python/CLI scripts that read/write
JSON files — there was nothing for N8N to call. This exposes the one action
N8N needs to automate: given a graded incident, synthesize its work order
(M7) and drop it straight into the dashboard queue. That's the whole
"auto-create + auto-route" step (blueprint R5) — there is no separate
"create" vs "route" call, because splitting them would reintroduce a manual
trigger in between, which is exactly what R5 rules out.

The only endpoint that gates on a human is POST /work-orders/{id}/approve —
it authorizes physical *dispatch* (crew/vehicle), never creation, routing,
or the Grade-1 isolation described below. This is the maturity-level
boundary for the dispatch track (L3/L4, not L5 autonomous control) made
operational.

**Grade-1 physical isolation (blueprint D7/R8, benchtop rig only) has no
human gate at all** — see `live_ingest.py`. The instant a live sensor
reading grades Grade 1, `live_ingest.ingest_reading` fires the isolate
command synchronously, before this API even returns. That path does not
go through this file's queue/approval logic; it happens earlier, in
grading, on purpose (see CLAUDE.md's "bypasses N8N's polling cadence").
This file only *reports* the resulting actuator state, merged onto each
work-order entry from `actuation.py`'s confirmation store.

Run with: uvicorn api:app --app-dir src --host 0.0.0.0 --port 8000
"""

import json
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).parent))
import actuation  # noqa: E402
import live_ingest  # noqa: E402
from synthesize_work_order import CFG as SYNTH_CFG, synthesize  # noqa: E402

GRADED_INCIDENTS_PATH = Path("data/grading_output/graded_incidents.json")
CITATIONS_PATH = Path("data/retrieval_output/retrieved_citations.json")
QUEUE_PATH = Path("data/work_order_queue/queue.json")

IN_PROGRESS = "IN_PROGRESS"                    # synthesis claimed but not finished yet
AWAITING_APPROVAL = "AWAITING_APPROVAL"       # auto-created + auto-routed; not yet dispatched
APPROVED_DISPATCHED = "APPROVED_DISPATCHED"    # human approved physical dispatch

@asynccontextmanager
async def _lifespan(app: FastAPI):
    client = actuation.start_confirmation_listener()
    yield
    client.loop_stop()
    client.disconnect()


app = FastAPI(title="L2WO pipeline API", lifespan=_lifespan)
_queue_lock = Lock()


def _with_actuator_state(entry: dict) -> dict:
    """Merges the live actuator-confirmation store onto a queue entry.
    Read-time merge, not write-time — the confirmation can legitimately
    arrive before, during, or after the work-order entry itself exists
    (isolation is synchronous at grading time; work-order creation waits
    on the LLM and, for N8N-routed grades, the poll cycle), so there is no
    safe ordering to write it in."""
    state = actuation.get_actuator_state(entry["incident_id"])
    if state:
        entry = {
            **entry,
            "actuator_commanded": state.get("actuator_commanded", False),
            "actuator_confirmed_state": state.get("actuator_confirmed_state", "unknown"),
            "actuator_command_latency_s": state.get("actuator_command_latency_s"),
        }
    return entry


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_queue() -> dict:
    if not QUEUE_PATH.exists():
        return {}
    return json.loads(QUEUE_PATH.read_text())


def _save_queue(queue: dict) -> None:
    QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    QUEUE_PATH.write_text(json.dumps(queue, indent=2))


def _load_incident(incident_id: str) -> dict:
    incidents = {i["incident_id"]: i for i in json.loads(GRADED_INCIDENTS_PATH.read_text())}
    if incident_id not in incidents:
        raise HTTPException(404, f"unknown incident_id: {incident_id}")
    inc = incidents[incident_id]
    if inc.get("assigned_grade") is None:
        raise HTTPException(422, f"{incident_id} has no assigned_grade (hydraulic_check route, not a leak)")
    return inc


def _load_citations(incident_id: str) -> list[dict]:
    records = {r["incident_id"]: r["citations"] for r in json.loads(CITATIONS_PATH.read_text())}
    return records.get(incident_id, [])


class SynthesizeRequest(BaseModel):
    incident_id: str


class TelemetryReading(BaseModel):
    """One ESP32 sample. Per-segment static metadata is required on every
    reading (not sent once and cached) — matches the hardware guide's §3
    field list and keeps live_ingest.py's buffer self-contained."""
    timestamp_utc: str
    segment_id: str
    material: str
    install_year: int
    MAOP_bar: float
    location_class: int
    hca_flag: bool
    distance_to_building_m: float
    confinement: str
    surface_capping_type: str
    pressure_bar: float
    flow_scm_h: Optional[float] = None
    methane_pct_lel: float
    acoustic_index: float


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/telemetry/ingest")
def ingest_telemetry(reading: TelemetryReading):
    """Live ESP32 ingestion (blueprint R8). Runs the reading through the
    same deterministic detection+grading the batch CSV path uses. If this
    reading is what confirms a Grade-1 anomaly, the isolate command has
    already fired (synchronously, inside `live_ingest.ingest_reading`)
    by the time this endpoint returns — see live_ingest.py's module
    docstring for exactly when."""
    return live_ingest.ingest_reading(reading.model_dump())


@app.get("/incidents/pending")
def pending_incidents():
    """Graded incidents not yet in the work-order queue — what a trigger polls."""
    incidents = json.loads(GRADED_INCIDENTS_PATH.read_text())
    with _queue_lock:
        queued_ids = set(_load_queue().keys())
    return [
        {"incident_id": i["incident_id"], "segment_id": i["segment_id"], "grade": i["assigned_grade"]}
        for i in incidents
        if i.get("assigned_grade") is not None and i["incident_id"] not in queued_ids
    ]


@app.post("/work-orders/synthesize")
def synthesize_and_route(req: SynthesizeRequest):
    """Auto-create + auto-route (blueprint R5): the single action N8N calls
    the moment a leak is graded. No separate step exists to only 'create'
    without routing into the queue — synthesize() already fails safe to a
    degraded template internally, so this call always produces something to
    route, never nothing.

    Claims the incident (status IN_PROGRESS) before the slow LLM call so an
    overlapping poll — e.g. N8N's schedule trigger firing again before a
    large backlog finishes — can't see it as still-pending and fire a second,
    redundant synthesis call. Without this, concurrent Ollama calls contend
    for the same GPU/model and latency can drift past the 40s budget."""
    incident = _load_incident(req.incident_id)

    with _queue_lock:
        queue = _load_queue()
        if req.incident_id in queue:
            raise HTTPException(409, f"{req.incident_id} is already {queue[req.incident_id]['status']}")
        queue[req.incident_id] = {"incident_id": req.incident_id, "status": IN_PROGRESS}
        _save_queue(queue)

    citations = _load_citations(req.incident_id)
    actuator_state = actuation.get_actuator_state(req.incident_id)
    result = synthesize(incident, citations, SYNTH_CFG, actuator_state)
    entry = {
        **result,
        "status": AWAITING_APPROVAL,
        "routed_at": _now(),
        "approved_at": None,
    }

    with _queue_lock:
        queue = _load_queue()
        queue[req.incident_id] = entry
        _save_queue(queue)

    return _with_actuator_state(entry)


@app.get("/work-orders")
def list_work_orders():
    with _queue_lock:
        queue = _load_queue()
    return [_with_actuator_state(e) for e in queue.values()]


@app.get("/work-orders/{incident_id}")
def get_work_order(incident_id: str):
    with _queue_lock:
        queue = _load_queue()
    if incident_id not in queue:
        raise HTTPException(404, f"no queued work order for {incident_id}")
    return _with_actuator_state(queue[incident_id])


@app.post("/work-orders/{incident_id}/approve")
def approve_dispatch(incident_id: str):
    """The one human gate for the dispatch track: authorizes crew/vehicle
    dispatch. Never gates creation or routing — those already happened
    automatically. Does not gate Grade-1 isolation either (blueprint D7/
    R8) — that fires with no human involvement at all, well before this
    endpoint is ever called; see the module docstring."""
    with _queue_lock:
        queue = _load_queue()
        if incident_id not in queue:
            raise HTTPException(404, f"no queued work order for {incident_id}")
        entry = queue[incident_id]
        if entry["status"] != AWAITING_APPROVAL:
            raise HTTPException(409, f"{incident_id} is not awaiting approval (status={entry['status']})")
        entry["status"] = APPROVED_DISPATCHED
        entry["approved_at"] = _now()
        _save_queue(queue)
    return _with_actuator_state(entry)
