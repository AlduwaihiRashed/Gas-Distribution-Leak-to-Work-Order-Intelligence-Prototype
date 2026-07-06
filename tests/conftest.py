"""
Shared fixtures for the Part D scenario suite (blueprint Part D / CLAUDE.md
Evaluation Requirements).

Split philosophy: the deterministic core (detection, grading, retrieval) is
tested with zero external services required — it's the safety-critical
part, and Casey should be able to run `pytest` on a clean checkout and get
a real answer about it. Anything that needs Ollama, the MQTT broker, or a
running API server is marked `live_infra` and auto-skips if that service
isn't reachable, rather than failing the whole suite in an environment
that doesn't have them up.
"""

import socket
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"


def _port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _ollama_up() -> bool:
    return _port_open("localhost", 11434)


def _mqtt_up() -> bool:
    return _port_open("localhost", 1883)


def _api_up() -> bool:
    return _port_open("localhost", 8000)


@pytest.fixture(scope="session")
def ollama_available() -> bool:
    return _ollama_up()


@pytest.fixture(scope="session")
def mqtt_available() -> bool:
    return _mqtt_up()


@pytest.fixture(scope="session")
def api_available() -> bool:
    return _api_up()


@pytest.fixture(scope="session")
def synthetic_telemetry_csv() -> str:
    return str(DATA / "synthetic_telemetry.csv")


@pytest.fixture(scope="session")
def graded_incidents() -> list[dict]:
    import json
    return json.loads((DATA / "grading_output" / "graded_incidents.json").read_text())


@pytest.fixture
def grade1_incident() -> dict:
    """A canonical Grade 1: escalation route (methane+pressure), paved capping, near a building."""
    return {
        "incident_id": "TEST-G1",
        "segment_id": "SEG-TEST",
        "segment_meta": {
            "material": "PE", "install_year": 2008, "MAOP_bar": 4.0,
            "location_class": 3, "hca_flag": True, "distance_to_building_m": 8.0,
            "confinement": "below_pavement", "surface_capping_type": "asphalt",
        },
        "start_utc": "2026-01-01T00:00:00+00:00", "end_utc": "2026-01-01T00:03:00+00:00",
        "duration_samples": 4, "detected_trigger": "methane+pressure",
        "detected_route": "escalation",
        "peak_methane_pct_lel": 37.0, "peak_acoustic_index": 0.8, "min_pressure_bar": 3.5,
        "label_event": "leak", "label_grade": 1,
        "assigned_grade": 1, "grading_rule": "multi-signal corroboration (gas + pressure) -> immediate hazard",
    }


@pytest.fixture
def grade3_incident() -> dict:
    """A canonical Grade 3: inspection route, unpaved, open right-of-way, low concentration."""
    return {
        "incident_id": "TEST-G3",
        "segment_id": "SEG-TEST",
        "segment_meta": {
            "material": "steel", "install_year": 1990, "MAOP_bar": 5.0,
            "location_class": 1, "hca_flag": False, "distance_to_building_m": 120.0,
            "confinement": "open_row", "surface_capping_type": "soil",
        },
        "start_utc": "2026-01-01T00:00:00+00:00", "end_utc": "2026-01-01T00:03:00+00:00",
        "duration_samples": 4, "detected_trigger": "methane",
        "detected_route": "inspection",
        "peak_methane_pct_lel": 8.0, "peak_acoustic_index": 0.2, "min_pressure_bar": 5.0,
        "label_event": "leak", "label_grade": 3,
        "assigned_grade": 3, "grading_rule": "unpaved, low concentration, away from occupancy -> monitor/re-evaluate",
    }
