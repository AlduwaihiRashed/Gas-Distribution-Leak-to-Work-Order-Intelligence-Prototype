# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is the **Gas Distribution Leak-to-Work-Order (L2WO) Intelligence Prototype** — an internship project for the IntelGrid/Esyasoft analytics platform. It seeds the gas vertical by implementing the platform's flagship pattern: *sensor anomaly → severity grading → emergency work order*.

The full blueprint lives in `docs/gas-leak-l2wo-prototype-blueprint.md`. The `docs/utility-analytics-ecosystem-wiki.md` is the cross-utility reference wiki for the IntelGrid platform.

## Architecture: Deterministic Pipeline, Not Agents

The most important design decision: this is a **linear, mostly-deterministic safety pipeline with exactly one LLM step**. Multi-agent frameworks (CrewAI, AutoGen, LangChain agents) were explicitly rejected — they add non-determinism to a life-safety flow.

```
Real sensors (ESP32 nodes) OR synthetic telemetry (CSV)
        │
        ▼
[1] Data quality + anomaly detection   ← deterministic rules + statistical ML, NO LLM
        │   OR-routing by signal urgency
        ▼
[2] Leak-grade rule engine             ← deterministic decision table, NO LLM
        │   Grades: 1 (hazardous/immediate), 2 (scheduled repair), 3 (monitor)
        │
        ├── Grade 1 ──▶ [2a] Autonomous physical actuation ← NO human gate, benchtop rig only (see below)
        │                    isolate valve (relay/servo) + local alarm; ESP32 confirms actuator
        │                    state back to the API, closing the loop
        ▼
[3] RAG retrieval over procedure corpus ← ChromaDB; fetches cited text, never decides grade
        │
        ▼
[4] Work-order synthesis               ← ONE local Ollama call
        │
        ▼
[5] N8N: auto-create + auto-route work order → dashboard queue; human approval gates physical *dispatch* (crew/vehicle), not the Grade-1 isolation above
        │
        ▼
[6] Non-technical dashboard             ← red/amber/green per segment (Grade 1/2/3) + action status + actuator state
```

The LLM is **useful but not load-bearing**: if Ollama fails, an N8N error-output branch emits a degraded template work order from the deterministic grade, banner-flagged `DEGRADED MODE`. The safety output never drops. Note that stage [2a] (physical isolation) does not depend on the LLM at all — it fires directly off the deterministic grade, before synthesis even runs, so an Ollama outage never delays the one action where speed matters most.

**Detect + action, not detect-only:** work-order creation and routing into the dashboard queue is automatic the instant a leak is graded — no manual trigger to *start* that step. Grade 1 additionally triggers autonomous physical isolation (stage [2a], benchtop rig — see Maturity Level below) with no human gate at all, because for a Grade 1 leak time is the constraint that matters most. Human approval is still required before physical *dispatch* (sending a crew/vehicle) for Grade 2/3 and for the follow-up crew response on Grade 1.

**This is a genuine closed loop, not fire-and-forget.** Detect → grade → (Grade 1: actuate) → the ESP32 reports the actuator's actual post-action state (valve closed, pressure trending down) back through the API → the dashboard reflects confirmed isolation, not just a command that was sent. A command with no confirmation is not a closed loop; the confirmation leg is what makes it one.

**Latency budget: < 40 seconds end-to-end** (stage [1] through stage [5] landing in the dashboard queue), with a **configurable accuracy variable** (e.g. detection persistence window, RAG top-k, or Ollama model/quality tier) to trade accuracy against speed. The current synthesis model (ministral-3, ~2 min/work order) does not fit this budget as-is — reconciling this is open work (see blueprint B.5).

## Tech Stack (house-aligned — do not introduce alternatives)

| Concern | Choice |
|---|---|
| Language / data | Python, Pandas, NumPy |
| Data quality | `pandera` or Great Expectations |
| Anomaly detection | scikit-learn (EWMA/z-score baseline; optional IsolationForest ablation) |
| Rule engine | Plain Python decision table |
| Vector DB | **ChromaDB** |
| Embeddings + LLM | **Ollama (local)** — privacy-preserving |
| Orchestration | **N8N** (not Airflow/CrewAI/AutoGen) — auto-routes work orders on grade, human approval only before physical *dispatch* |
| Edge hardware | **ESP32** sensor + actuator node (benchtop rig) — WiFi-native (no separate radio module needed, unlike STM32), dual-core, onboard ADC for analog methane/pressure/acoustic sensors, GPIO/PWM to drive a relay or servo modeling the isolation valve, plus a local alarm/beacon |
| Demo UI | Streamlit — non-technical red/amber/green dashboard |
| Tests | pytest |

**Grade-1 physical isolation bypasses N8N's polling cadence on purpose.** N8N's auto-routing workflow polls every 10s — fine for creating and routing a work order, but too slow for the one action where time is the constraint that matters most. The isolation command is fired synchronously, in-process, the moment grading assigns Grade 1 — not queued behind N8N's next tick. N8N still owns work-order creation/routing/approval exactly as before; it is not in the isolation path at all.

## Key Domain Rules

**Anomaly detection uses OR-routing, not AND:**
- Methane or acoustic alone → raise a leak *inspection* work order
- Pressure drop alone → raise a *hydraulic/SCADA anomaly* check
- Both signals together → escalate toward Grade 1

Each channel requires a **persistence window** (anomaly sustained ≥ N samples) + magnitude threshold before firing, so single noisy readings don't trigger.

**Grading inputs (from GPTC / 49 CFR 192, PNGRB, OISD — not ASME B31.8):**
- Gas concentration relative to LEL (~5% vol for methane)
- Location: inside/near building vs. open right-of-way
- Confinement and surface capping type (`soil`, `grass`, `asphalt`, `concrete`)
- HCA flag and migration potential

Surface capping is critical: the same leak under `asphalt` (Grade 1 — gas tracks into basements) vs. `soil` (Grade 3 — vents safely upward).

**Synthetic telemetry schema:** `timestamp_utc, segment_id, material, install_year, MAOP_bar, location_class, hca_flag, distance_to_building_m, confinement, surface_capping_type, pressure_bar, flow_scm_h, methane_pct_lel, acoustic_index, trigger_channel, route, label_event, label_grade`

## RAG Corpus

The `docs/` folder contains the knowledge base to embed into ChromaDB:
- `gas-utility-ea-togaf.pdf` — gas enterprise architecture
- `power-utility-enterprise-architecture-togaf 3.pdf` — power EA (cross-reference)
- `water-utility-ea-togaf.pdf` — water EA (cross-reference)
- `utility-analytics-ecosystem-wiki (1).md` — full platform wiki

RAG retrieves procedure/regulatory text to *cite* in work orders. It never influences grading decisions.

## Evaluation Requirements

The scenario suite must include:
- Grade 1/2/3 positive cases
- Negative/trap cases: sensor drift, operational pressure swings, below-threshold noise
- Routing cases: methane-only (expect inspection WO), pressure-only (expect hydraulic check), both (expect Grade-1 escalation)
- Resilience: forced Ollama failure → degraded work order still produced
- Grading-fidelity: identical leak under `soil` vs `asphalt` must yield Grade 3 vs Grade 1
- Actuation: Grade 1 → isolate command fires with no human gate, and the actuator's *confirmed* state (not just command-sent) shows up in the queue/dashboard; Grade 2/3 → no actuation fires; forced ESP32/actuator unreachable → banner-flagged, work order still auto-created/routed (isolation failing must never suppress the rest of the safety output)

Target metrics: ≥90% recall on Grade-1 scenarios; 100% of work orders cite at least one retrieved chunk; end-to-end latency < 40s at the default accuracy setting.

## Dashboard

Streamlit UI aimed at a **non-technical** viewer (dispatcher/supervisor, not an engineer). Per-segment tiles, colour-coded **red = Grade 1, amber = Grade 2, green = Grade 3**, plain-language readings (no raw sensor codes), plus an action indicator showing whether a work order has been auto-created/routed and whether it's awaiting approval or dispatched, and — for Grade 1 — whether the segment's actuator has *confirmed* isolation (not just that a command was sent). The dashboard reads existing incident/grade/work-order/actuator payloads — it never re-derives a grade and never re-decides an isolation.

## Hardware Path (benchtop rig, in scope as of 2026-07-02)

`docs/hardware-implementation-guide.md` is now the real implementation guide, not a kept-out-of-repo brief. Per-segment edge node: **ESP32**, chosen over STM32 (needs a separate radio module for connectivity) and Raspberry Pi (weaker real-time GPIO sampling; better suited as a gateway aggregating several ESP32 nodes than as the sensor/actuator node itself). Each node reads methane/pressure/acoustic sensors, reports over WiFi to the API, and — for Grade 1 only — receives and executes an isolate command by driving a relay/servo that models the segment's shutoff valve, plus a local alarm/beacon. The ESP32 reports the actuator's resulting state back to the API, which is what makes this a closed loop rather than a fire-and-forget command.

**This is a benchtop/demo rig, not live gas-distribution infrastructure.** The relay/servo models a valve; it does not control one. That distinction is what makes full autonomous isolation acceptable to build and demonstrate here — see Maturity Level.

## Maturity Level

Two different maturity levels apply depending on what the actuator is wired to, and conflating them would misrepresent the prototype's actual safety readiness:

- **On the benchtop demo rig (this prototype, current scope):** Grade 1 triggers **fully autonomous physical isolation** — no human gate, no approval step, fired synchronously at grading time. This is intentional: the rig's "valve" is a relay/servo demonstration model, so an incorrect auto-isolation has no real-world consequence beyond the demo needing a reset. This lets the prototype demonstrate genuine closed-loop detect-and-act behavior, which is the point of the hardware phase.
- **On live gas-distribution infrastructure (out of scope, not this prototype):** the identical architecture would still be **L5 autonomous control** in the real sense, and autonomous isolation of an actual gas main requires a formal SIL (IEC 61511/61508) safety case — independent voting sensors (not a single methane/acoustic/pressure triplet), certified fail-safe actuators, and a proof-tested functional safety lifecycle. Nothing built here satisfies that, and nothing here should be represented as ready to wire into a real gas main without it.

Work-order creation/routing to the dashboard queue remains automatic on grading (detect + action) for all grades. Human approval remains required before physical *dispatch* (sending a crew/vehicle) — that gate is unchanged by the actuation work above; it governs the follow-up crew response, not the immediate benchtop isolation.
