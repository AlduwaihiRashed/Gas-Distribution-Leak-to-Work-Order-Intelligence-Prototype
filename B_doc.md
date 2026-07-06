# B_doc — Hardware, IoT & SCADA Walkthrough

## What this is

A benchtop rig that closes the loop between gas-leak sensing and physical response: methane, pressure, and acoustic sensors feed a detection pipeline that grades a leak per standard gas-utility classification (Grade 1/2/3, GPTC lineage under 49 CFR 192, aligned to PNGRB/OISD for CGD context), and — for Grade 1 only — an ESP32-class edge node autonomously actuates a relay/servo modeling the segment's shutoff valve, with no human confirmation step, and reports the *actual resulting* state back so the response is verifiably closed, not just commanded.

**The one thing to understand before anything else:** this is a demonstration rig, not a connection to a live gas main. The relay/servo *models* a valve; it doesn't control one. That distinction is the entire reason full autonomous isolation is appropriate to build and demonstrate here — see the SIL note at the end.

## Grading logic the hardware acts on

Grade assignment is a deterministic decision table, not a model, using:
- Gas concentration relative to LEL (lower explosive limit, ~5% vol methane)
- Proximity to occupied structures / HCA (High Consequence Area) flags
- **Surface capping** — the variable most people underweight. The identical leak vents safely upward through open soil (Grade 3) but is forced to migrate laterally underground under asphalt or concrete, tracking toward basements and utility vaults (Grade 1), *regardless of the surface reading*. A grading system that ignores this can't produce code-compliant grades on paved segments.

Grade 1 is the only grade that triggers hardware action. Grade 2/3 route to a human-approved dispatch workflow — no actuator involvement at all.

## Edge node architecture

**Board: ESP32**, chosen over STM32 (needs a separate radio module — extra BOM and integration cost for no benefit at this scale) and Raspberry Pi (non-RTOS Linux gives worse real-time GPIO timing than a microcontroller; better suited as a gateway aggregating several ESP32 nodes than as the sensor node itself).

**Per-segment node:**
- Methane sensor (MQ-series or infrared %LEL) → ADC
- Pressure transducer → ADC
- Acoustic/piezo sensor → ADC
- Relay module driving a solenoid/servo (the valve model)
- Independent alarm circuit (buzzer + LED) — **deliberately on a separate GPIO/driver from the valve relay**, so a relay fault can't also silence the alarm

```
Methane ──ADC──┐
Pressure ──ADC──┤   ESP32     ├── GPIO ── Relay (valve model) ── Solenoid/servo
Acoustic ──ADC──┘   node       └── GPIO ── Buzzer + LED (independent circuit)
                     │
                   WiFi
```

Full pin table and wiring diagram: `docs/hardware-implementation-guide.md` §2.1.

## Communication design

Two channels, deliberately split by latency requirement:

- **Telemetry (node → pipeline): HTTP POST**, roughly one reading per sampling interval. Not latency-critical — detection already requires a persistence window (several consecutive readings), not a single sample, so there's no reason to push this over a lower-latency channel.
- **Isolate command + confirmation: MQTT.** A ≤5-second target from grade assignment to a *confirmed* actuator state rules out polling — a push-based broker (Mosquitto) is what makes that latency achievable. Per-segment topics: `l2wo/{segment}/isolate` (retained, so a reconnecting node picks up a missed command) and `l2wo/{segment}/actuator_state` (published only *after* the relay has physically moved — this confirmation leg is what makes the response verifiably closed rather than a fire-and-forget command).

```
ESP32 node ──HTTP──▶ API ──▶ detection + grading (deterministic)
                              │ Grade 1 only
                              ▼
                     MQTT broker ──isolate──▶ ESP32 node
                              ▲                    │ actuate
                              └──actuator_state─────┘
```

N8N is not in this path anywhere — the isolate command is fired synchronously from the grading step itself, ahead of any orchestration layer's poll cycle.

## Fail-safe design

- **Default-to-isolated on loss of signal.** WiFi or MQTT disconnect drives the relay to the isolated position, mirroring standard emergency shutdown (ESD) valve convention — loss of connectivity must never be indistinguishable from "confirmed safe."
- **Isolation is gated upstream, not on raw sensor noise.** The actuator only fires off an already-graded Grade 1 (persistence window + magnitude threshold already applied at the detection stage) — never directly off a single ADC sample.
- **A command failure is visible, not silent.** If the broker or node is unreachable, the failure is flagged in the returned state rather than raised as an error that could suppress the rest of the pipeline — the informational/work-order side of the system keeps functioning even if the physical action can't be confirmed.

## The SIL boundary — read this before assuming this scales to live infrastructure

Autonomous isolation with zero human gate is *only* appropriate on this rig because the actuator has no real-world consequence if it fires on a false positive. Deploying the same architecture against an actual gas main would put it in Safety Instrumented System (SIS) territory under IEC 61511/61508: independent voting sensor architecture (not a single methane/pressure/acoustic triplet), certified fail-safe actuators, a proof-tested functional safety lifecycle. None of that exists here, and nothing in this rig should be read as a step toward skipping it — it's a control-loop demonstration, not a field-deployable safety system.
