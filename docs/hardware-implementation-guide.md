# Hardware Implementation Guide — Benchtop Sensor + Actuator Rig

**Status (2026-07-02):** in scope, per supervisor direction (blueprint R8/D7). This replaces the earlier "technician handoff brief, kept out of the codebase" version of this document — the hardware path is now part of the prototype, not deferred past it.

**Scope boundary — read this before wiring anything.** This rig is a **benchtop demonstration**, not a connection to live gas-distribution infrastructure. Its "valve" is a relay/servo model, not a real shutoff valve on a real gas main. That distinction is what makes fully autonomous Grade-1 isolation (no human gate) an appropriate thing to build and demonstrate here — see the Maturity Level section of `CLAUDE.md` and blueprint D7/G.3. A live deployment of this same architecture is a different, much harder problem requiring a formal SIL (IEC 61511/61508) safety case, independent voting sensors, and certified actuators. Nothing in this guide substitutes for that.

## 1. Board choice: ESP32 (not STM32, not Raspberry Pi)

| Option | Verdict | Why |
|---|---|---|
| **ESP32** | **Chosen**, per-segment sensor+actuator node | WiFi built in (no separate radio module, unlike STM32); dual-core, enough onboard ADC channels for analog methane/pressure/acoustic sensors; GPIO/PWM to drive a relay or servo; cheap enough to deploy one per segment |
| STM32 | Rejected as the node | Excellent real-time/GPIO characteristics, but needs a separate WiFi/Ethernet module to report anywhere — extra BOM cost and integration work for no benefit at this scale |
| Raspberry Pi | Rejected as the node, viable as a **gateway** | Non-RTOS Linux makes tight-latency GPIO sampling and actuation timing worse than a microcontroller; makes more sense as an aggregator running the pipeline itself if the rig later grows to several ESP32 nodes |

## 2. Per-segment node — components

- **ESP32 dev board** (e.g. ESP32-WROOM-32 DevKit)
- **Methane sensor** — MQ-series analog gas sensor (or better, an infrared %LEL sensor if available) → ESP32 ADC pin
- **Pressure sensor** — analog pressure transducer (0-5V or 4-20mA with a shunt) → ESP32 ADC pin
- **Acoustic sensor** — piezo contact mic or small electret mic module → ESP32 ADC pin (simple envelope/RMS reading is enough; this is not a leak-noise correlator)
- **Actuator** — relay module driving a small solenoid or servo that **models** the segment's shutoff valve (open/closed position, not a real gas-rated valve)
- **Local alarm** — buzzer + LED/beacon, driven independently of the valve-model relay, for the always-safe-to-automate "reversible mitigation" action (see §5)
- 5V/3.3V power (USB or bench supply)

## 3. Communication: HTTP for telemetry, MQTT for the isolate command

Two different channels, deliberately, because they have different latency requirements:

- **Telemetry (ESP32 → pipeline): HTTP POST**, roughly once per sampling interval, to the API's ingestion endpoint. Simple, and telemetry isn't on the tight latency budget — detection/grading already runs on a persistence window, not a single sample.
- **Isolate command (pipeline → ESP32) and actuator confirmation (ESP32 → pipeline): MQTT.** The 5-second isolation-latency target (blueprint B.5, R8) rules out polling — a push-based broker is what gets the command to the board without waiting on a poll interval. A lightweight local broker (e.g. Mosquitto, run the same way n8n is — via podman) is a new piece of infrastructure this introduces; document it as such rather than pretending it's free.

Per-segment MQTT topics:
- `l2wo/{segment_id}/isolate` — API publishes here the instant grading assigns Grade 1; retained message so a reconnecting ESP32 picks up a missed command.
- `l2wo/{segment_id}/actuator_state` — ESP32 publishes `{"state": "isolated" | "open", "at": "<timestamp>"}` after actually moving the relay/servo, not before. The API subscribes and writes this into the work-order queue as `actuator_confirmed_state` — **this confirmation leg is what makes the loop closed rather than fire-and-forget** (see `CLAUDE.md` Architecture section).

## 4. API-side integration contract (implemented — `src/api.py`, `src/live_ingest.py`, `src/actuation.py`)

- `POST /telemetry/ingest` — one reading, **all fields required on every call** (no "sent once, cached" static metadata — matches §3's field list): `segment_id, timestamp_utc, pressure_bar, methane_pct_lel, acoustic_index, material, install_year, MAOP_bar, location_class, hca_flag, distance_to_building_m, confinement, surface_capping_type` (`flow_scm_h` optional). Feeds the same `detect_anomalies.py`/`grade_leak.py` logic the synthetic CSV path uses (no separate "real" detection rules — see `live_ingest.py`'s module docstring for the exact act-at-persistence-confirmation design).
- On grading a segment **Grade 1**: publishes to `l2wo/{segment_id}/isolate` synchronously, in-process, before work-order synthesis runs — this is what bypasses N8N's 10s poll cadence (see `CLAUDE.md`). Measured round-trip in testing (virtual ESP32, `src/simulate_esp32.py`): ~0.4s, well inside the 5s target.
- Subscribes to `l2wo/+/actuator_state`; on message, updates `data/work_order_queue/actuator_state.json`, merged at *read* time (not write time — see `api.py`'s `_with_actuator_state`) onto every work-order response as `actuator_commanded`, `actuator_confirmed_state`, `actuator_command_latency_s` (blueprint Appendix A2).
- The synthesis prompt (`synthesize_work_order.py`) is told the actuator's confirmed state when available, so the generated work order says isolation is already done rather than instructing a crew to isolate an already-isolated segment.
- If no confirmation arrives within a timeout, mark `actuator_confirmed_state: "unknown"` and banner-flag it — **this failure must never block or delay work-order creation/routing** (blueprint B.2[2a]).

## 5. Safety notes (still apply on a benchtop rig — this is good practice, not just for live infrastructure)

- **Fail-safe default position.** Decide and document what the relay/servo does on power loss or WiFi disconnect (loss of signal should not be indistinguishable from "safe"). Mirror real ESD (emergency shutdown) valve convention: fail toward the safe state, not toward "stay open because we lost the connection."
- **Isolation is upstream-gated, not raw-sensor-gated.** The actuator only fires off an already-graded Grade 1 (persistence window + magnitude threshold already applied, blueprint B.2[1]) — never directly off a single noisy ADC reading.
- **The alarm/beacon and the valve-model relay are independent outputs.** A wiring fault or relay failure on the valve model shouldn't also silence the local alarm — keep them on separate GPIO/driver circuits.
- Standard electrical/breadboard safety applies (no mains voltage on the bench rig; treat any real gas sensor calibration gas/canister per its own MSDS).

## 6. What this guide is not

It is not a field-deployment or hazardous-area installation guide. Hazardous-area electrical classification (intrinsically safe wiring near real gas), sensor placement on a live segment, and permit-to-work all remain the domain of a qualified technician and site safety procedures if this ever moves toward real infrastructure — see blueprint G.3 for the (still gated) path there.
