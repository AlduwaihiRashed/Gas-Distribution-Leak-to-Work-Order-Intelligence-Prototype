"""
M9 actuation tests — the Grade-1 closed loop (blueprint D7/R8).

publish_isolate's "must not raise even if the broker is down" behavior is
tested with the broker genuinely unreachable (a bad port) — that's the one
actuation test that needs no live infra at all. The full round-trip
(command -> confirmation) needs the MQTT broker up and is marked
live_infra.
"""

import json
from pathlib import Path

import pytest

import actuation


@pytest.fixture
def isolated_state_store(tmp_path, monkeypatch):
    path = tmp_path / "actuator_state.json"
    monkeypatch.setattr(actuation, "ACTUATOR_STATE_PATH", path)
    return path


class TestPublishIsolateResilience:
    """This is the bug found while writing this suite: an unreachable broker
    used to raise out of publish_isolate and crash the calling request —
    which, since publish_isolate runs after the incident is already graded
    and recorded, meant an MQTT hiccup could 500 an otherwise-successful
    /telemetry/ingest call. Fixed to record the failure instead."""

    def test_unreachable_broker_does_not_raise(self, isolated_state_store, monkeypatch):
        monkeypatch.setattr(actuation, "MQTT_PORT", 1)  # nothing listens on port 1
        result = actuation.publish_isolate("SEG-X", "INC-X", timeout_s=0.5)
        assert result["actuator_commanded"] is False
        assert "command_error" in result

    def test_unreachable_broker_still_records_state(self, isolated_state_store, monkeypatch):
        monkeypatch.setattr(actuation, "MQTT_PORT", 1)
        actuation.publish_isolate("SEG-X", "INC-X", timeout_s=0.5)
        state = actuation.get_actuator_state("INC-X")
        assert state is not None
        assert state["actuator_confirmed_state"] == "unknown"


class TestActuatorStateStore:
    def test_get_actuator_state_returns_none_when_never_commanded(self, isolated_state_store):
        assert actuation.get_actuator_state("never-seen") is None


class FakeMQTTMessage:
    def __init__(self, payload: dict):
        self.payload = json.dumps(payload).encode()


class TestConfirmationIdempotency:
    """Regression test: a duplicate/replayed actuator_state message for an
    already-confirmed incident (e.g. a simulator or ESP32 reconnecting and
    re-reading the retained isolate command) used to overwrite the correct
    confirmed_at/latency with time elapsed since the original command —
    turning a real ~0.4s result into a bogus multi-minute one. The first
    confirmation must be the one that sticks."""

    def test_second_confirmation_does_not_overwrite_first(self, isolated_state_store, monkeypatch):
        monkeypatch.setattr(actuation, "MQTT_PORT", 1)
        actuation.publish_isolate("SEG-X", "INC-DUP", timeout_s=0.5)

        msg = FakeMQTTMessage({"incident_id": "INC-DUP", "segment_id": "SEG-X", "state": "isolated"})
        actuation._on_confirmation(None, None, msg)
        first = actuation.get_actuator_state("INC-DUP")
        assert first["confirmed_at"] is not None
        assert first["actuator_command_latency_s"] is not None

        actuation._on_confirmation(None, None, msg)
        second = actuation.get_actuator_state("INC-DUP")
        assert second["confirmed_at"] == first["confirmed_at"]
        assert second["actuator_command_latency_s"] == first["actuator_command_latency_s"]


@pytest.mark.live_infra
class TestLiveRoundTrip:
    """Requires mosquitto up on localhost:1883. publish_isolate talks to the
    REAL broker (only ACTUATOR_STATE_PATH is isolated by the fixture, not
    MQTT_HOST/PORT) — if a real ESP32/simulator happens to be running and
    subscribed to l2wo/+/isolate (as it is during a live demo session in
    this dev environment), it WILL respond, and the real API process's own
    listener WILL write that confirmation into the real
    data/work_order_queue/actuator_state.json, not this test's isolated
    copy. That cross-talk is real and was caught by running this suite
    against a live demo — clean up the known key explicitly rather than
    assert a specific outcome that depends on what else is running."""

    def test_isolate_command_is_publishable(self, mqtt_available, isolated_state_store):
        if not mqtt_available:
            pytest.skip("MQTT broker not reachable on localhost:1883")
        try:
            result = actuation.publish_isolate("SEG-LIVE-TEST", "INC-LIVE-TEST")
            assert result["actuator_commanded"] is True
        finally:
            real_path = Path("data/work_order_queue/actuator_state.json")
            if real_path.exists():
                state = json.loads(real_path.read_text())
                if state.pop("INC-LIVE-TEST", None) is not None:
                    real_path.write_text(json.dumps(state, indent=2))
