"""
M8 API tests — auto-create+auto-route (R5), the human-approval gate, and
the concurrency fix (claim-before-synthesize) from the n8n integration
session. Uses a temp queue/incidents directory so this never touches the
real demo data in data/work_order_queue/.

Needs the API importable (chromadb corpus built — same requirement as
test_retrieval.py) but does NOT need Ollama or MQTT up for most tests:
synthesize() is monkeypatched to the pure-Python degraded path so these
run fast and offline. The one test that needs a live Ollama is marked.
"""

import json

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def api_module(tmp_path, monkeypatch):
    import api as api_mod

    incidents_path = tmp_path / "graded_incidents.json"
    citations_path = tmp_path / "retrieved_citations.json"
    queue_path = tmp_path / "queue.json"

    incidents_path.write_text(json.dumps([
        {
            "incident_id": "T-G1", "segment_id": "SEG-T1", "assigned_grade": 1,
            "grading_rule": "test", "detected_route": "escalation",
            "segment_meta": {"material": "PE", "install_year": 2008, "MAOP_bar": 4.0,
                              "location_class": 3, "hca_flag": True, "distance_to_building_m": 8.0,
                              "confinement": "below_pavement", "surface_capping_type": "asphalt"},
            "start_utc": "2026-01-01T00:00:00+00:00", "end_utc": "2026-01-01T00:01:00+00:00",
            "peak_methane_pct_lel": 30.0, "peak_acoustic_index": 0.7, "min_pressure_bar": 3.6,
        },
        {
            "incident_id": "T-HYD", "segment_id": "SEG-T2", "assigned_grade": None,
            "grading_rule": "hydraulic check, not a leak", "detected_route": "hydraulic_check",
            "segment_meta": {}, "start_utc": "x", "end_utc": "x",
            "peak_methane_pct_lel": 0, "peak_acoustic_index": 0, "min_pressure_bar": 3.0,
        },
    ]))
    citations_path.write_text(json.dumps([
        {"incident_id": "T-G1", "citations": [{"chunk_id": "c1", "source_doc": "d", "location": "l", "text": "t", "score": 0.9}]},
    ]))

    monkeypatch.setattr(api_mod, "GRADED_INCIDENTS_PATH", incidents_path)
    monkeypatch.setattr(api_mod, "CITATIONS_PATH", citations_path)
    monkeypatch.setattr(api_mod, "QUEUE_PATH", queue_path)

    def fake_synthesize(incident, citations, cfg, actuator_state=None):
        return {
            "incident_id": incident["incident_id"], "segment_id": incident["segment_id"],
            "grade": incident["assigned_grade"], "priority": "IMMEDIATE",
            "model": "fake", "latency_s": 0.01,
            "work_order": {"title": "t", "situation_summary": "s", "isolation_protocol": [],
                            "permit_to_work_required": False, "ppe_required": [], "proximity_hazards": [],
                            "crew_summary": "c", "citations": ["c1"], "degraded_mode": False},
        }
    monkeypatch.setattr(api_mod, "synthesize", fake_synthesize)
    monkeypatch.setattr(api_mod.actuation, "get_actuator_state", lambda incident_id: None)

    return api_mod


@pytest.fixture
def client(api_module):
    with TestClient(api_module.app) as c:
        yield c


class TestPendingIncidents:
    def test_hydraulic_check_incidents_excluded(self, client):
        """Only gradable (assigned_grade is not None) incidents are ever pending —
        a hydraulic/SCADA check is not a leak and never gets a work order."""
        r = client.get("/incidents/pending")
        ids = [i["incident_id"] for i in r.json()]
        assert "T-G1" in ids
        assert "T-HYD" not in ids


class TestAutoCreateAutoRoute:
    def test_synthesize_creates_and_routes_in_one_call(self, client):
        """Blueprint R5: no separate create-then-route step."""
        r = client.post("/work-orders/synthesize", json={"incident_id": "T-G1"})
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "AWAITING_APPROVAL"
        assert body["work_order"]["degraded_mode"] is False

        # and it's now visible via GET, immediately, no separate "route" step
        r2 = client.get("/work-orders/T-G1")
        assert r2.status_code == 200
        assert r2.json()["status"] == "AWAITING_APPROVAL"

    def test_double_synthesize_returns_409_not_duplicate(self, client):
        """The concurrency fix: an incident already IN_PROGRESS/queued can't be
        claimed twice — this is what stopped n8n's overlapping polls from
        firing duplicate Ollama calls."""
        r1 = client.post("/work-orders/synthesize", json={"incident_id": "T-G1"})
        assert r1.status_code == 200
        r2 = client.post("/work-orders/synthesize", json={"incident_id": "T-G1"})
        assert r2.status_code == 409

    def test_unknown_incident_404s(self, client):
        r = client.post("/work-orders/synthesize", json={"incident_id": "NOPE"})
        assert r.status_code == 404

    def test_hydraulic_check_incident_rejected(self, client):
        r = client.post("/work-orders/synthesize", json={"incident_id": "T-HYD"})
        assert r.status_code == 422


class TestApprovalGate:
    def test_approve_flips_status_and_stamps_time(self, client):
        client.post("/work-orders/synthesize", json={"incident_id": "T-G1"})
        r = client.post("/work-orders/T-G1/approve")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "APPROVED_DISPATCHED"
        assert body["approved_at"] is not None

    def test_double_approve_is_409_not_silent_success(self, client):
        client.post("/work-orders/synthesize", json={"incident_id": "T-G1"})
        client.post("/work-orders/T-G1/approve")
        r = client.post("/work-orders/T-G1/approve")
        assert r.status_code == 409

    def test_approve_before_synthesize_404s(self, client):
        r = client.post("/work-orders/T-G1/approve")
        assert r.status_code == 404

    def test_approval_never_touches_creation_or_routing(self, client):
        """The approval gate governs dispatch only — creation/routing already
        happened by the time this is callable at all (blueprint D6: dispatch
        gate is distinct from the auto-create/route step)."""
        r = client.post("/work-orders/synthesize", json={"incident_id": "T-G1"})
        created_at = r.json()["routed_at"]
        client.post("/work-orders/T-G1/approve")
        r2 = client.get("/work-orders/T-G1")
        assert r2.json()["routed_at"] == created_at  # unchanged by approval
