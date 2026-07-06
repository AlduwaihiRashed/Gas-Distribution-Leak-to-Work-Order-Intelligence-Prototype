"""
M9 — Physical isolation actuation (benchtop rig only — see CLAUDE.md Maturity
Level and blueprint D7/R8 before touching this file).

MQTT, not HTTP polling, for the command/confirmation channel: the target is
<5s from grade assignment to a confirmed actuator state (blueprint B.5), and
a poll-based channel can't hit that reliably. Telemetry ingestion stays HTTP
(see api.py) — only the isolate command and its confirmation go over MQTT,
per the hardware guide's split.

Per-segment topics:
  l2wo/{segment_id}/isolate         API -> ESP32, retained, {incident_id, segment_id, commanded_at}
  l2wo/{segment_id}/actuator_state  ESP32 -> API, {incident_id, segment_id, state, at}

`publish_isolate` is synchronous and fire-and-forget from the caller's side
(it does not block waiting for confirmation) — the confirmation arrives
asynchronously via `start_confirmation_listener` and is merged into the
queue at read time (api.py), because isolation is deliberately not allowed
to block or delay work-order creation/routing (blueprint B.2[2a]).
"""

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import paho.mqtt.client as mqtt

MQTT_HOST = "localhost"
MQTT_PORT = 1883
ACTUATOR_STATE_PATH = Path("data/work_order_queue/actuator_state.json")

_state_lock = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_state() -> dict:
    if not ACTUATOR_STATE_PATH.exists():
        return {}
    return json.loads(ACTUATOR_STATE_PATH.read_text())


def _save_state(state: dict) -> None:
    ACTUATOR_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    ACTUATOR_STATE_PATH.write_text(json.dumps(state, indent=2))


def publish_isolate(segment_id: str, incident_id: str, timeout_s: float = 3.0) -> dict:
    """Fires the isolate command synchronously, in-process, at grading time —
    this is the call that bypasses N8N's poll cadence and the LLM entirely.
    Records `commanded_at` immediately so latency can be measured once the
    confirmation arrives, whenever that is.

    If the broker itself is unreachable, this must not raise: the incident
    has already been graded and written to graded_incidents.json by the
    caller before this runs, and an MQTT hiccup must never take that
    safety record down with it (blueprint B.2[2a], hardware guide §4).
    Records `actuator_commanded: False` instead so the failure is visible,
    not silent."""
    commanded_at = time.monotonic()
    commanded_at_iso = _now()

    entry = {
        "segment_id": segment_id,
        "actuator_commanded": False,
        "commanded_at": commanded_at_iso,
        "commanded_at_monotonic": commanded_at,
        "actuator_confirmed_state": "unknown",
        "confirmed_at": None,
        "actuator_command_latency_s": None,
    }
    try:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        client.connect(MQTT_HOST, MQTT_PORT, keepalive=10)
        payload = json.dumps({
            "incident_id": incident_id,
            "segment_id": segment_id,
            "commanded_at": commanded_at_iso,
        })
        client.publish(f"l2wo/{segment_id}/isolate", payload, qos=1, retain=True)
        client.loop(timeout=timeout_s)
        client.disconnect()
        entry["actuator_commanded"] = True
    except OSError as exc:
        entry["command_error"] = str(exc)

    with _state_lock:
        state = _load_state()
        state[incident_id] = entry
        _save_state(state)

    return entry


def get_actuator_state(incident_id: str) -> dict | None:
    with _state_lock:
        return _load_state().get(incident_id)


def _on_confirmation(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode())
    except (json.JSONDecodeError, UnicodeDecodeError):
        return
    incident_id = payload.get("incident_id")
    if not incident_id:
        return

    with _state_lock:
        state = _load_state()
        entry = state.get(incident_id)
        if entry is None:
            # confirmation arrived with no matching commanded entry (e.g. API
            # restarted and lost in-memory state) — record what we can anyway,
            # so a confirmation is never silently dropped.
            entry = {"segment_id": payload.get("segment_id"), "actuator_commanded": True,
                      "commanded_at": None, "commanded_at_monotonic": None}
        # Only the first confirmation for a given incident should set the
        # timing fields. A duplicate/replayed message on this topic (e.g. a
        # simulator or ESP32 that reconnects, re-reads the *retained*
        # l2wo/{segment}/isolate command, and re-publishes its confirmation)
        # must not overwrite an already-recorded latency with time elapsed
        # since the original command — that produced a bogus multi-minute
        # "latency" for an incident that actually confirmed in ~0.4s.
        if entry.get("confirmed_at") is None:
            entry["actuator_confirmed_state"] = payload.get("state", "unknown")
            entry["confirmed_at"] = _now()
            if entry.get("commanded_at_monotonic") is not None:
                entry["actuator_command_latency_s"] = round(time.monotonic() - entry["commanded_at_monotonic"], 3)
        state[incident_id] = entry
        _save_state(state)


def _on_connect(client, userdata, flags, reason_code, properties=None):
    if reason_code == 0:
        client.subscribe("l2wo/+/actuator_state", qos=1)


def start_confirmation_listener() -> mqtt.Client:
    """Runs in a background thread for the lifetime of the API process.

    Uses connect_async + loop_start rather than the blocking connect() —
    if the broker is down when the API starts, a blocking connect() raises
    and (since this runs from a FastAPI startup handler) takes the *entire*
    API down with it, including all the Grade 2/3 work-order functionality
    that has nothing to do with MQTT. connect_async lets paho's network
    loop retry in the background instead; the API serves everything else
    normally and actuation confirmations just start working once the
    broker becomes reachable."""
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_message = _on_confirmation
    client.on_connect = _on_connect
    client.connect_async(MQTT_HOST, MQTT_PORT, keepalive=60)
    client.loop_start()
    return client
