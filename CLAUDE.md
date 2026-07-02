# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is the **Gas Distribution Leak-to-Work-Order (L2WO) Intelligence Prototype** — an internship project for the IntelGrid/Esyasoft analytics platform. It seeds the gas vertical by implementing the platform's flagship pattern: *sensor anomaly → severity grading → emergency work order*.

The full blueprint lives in `docs/gas-leak-l2wo-prototype-blueprint.md`. The `docs/utility-analytics-ecosystem-wiki.md` is the cross-utility reference wiki for the IntelGrid platform.

## Architecture: Deterministic Pipeline, Not Agents

The most important design decision: this is a **linear, mostly-deterministic safety pipeline with exactly one LLM step**. Multi-agent frameworks (CrewAI, AutoGen, LangChain agents) were explicitly rejected — they add non-determinism to a life-safety flow.

```
Synthetic telemetry (CSV)
        │
        ▼
[1] Data quality + anomaly detection   ← deterministic rules + statistical ML, NO LLM
        │   OR-routing by signal urgency
        ▼
[2] Leak-grade rule engine             ← deterministic decision table, NO LLM
        │   Grades: 1 (hazardous/immediate), 2 (scheduled repair), 3 (monitor)
        ▼
[3] RAG retrieval over procedure corpus ← ChromaDB; fetches cited text, never decides grade
        │
        ▼
[4] Work-order synthesis               ← ONE local Ollama call
        │
        ▼
[5] N8N: auto-create + auto-route work order → dashboard queue; human approval gates physical dispatch only
        │
        ▼
[6] Non-technical dashboard             ← red/amber/green per segment (Grade 1/2/3) + action status
```

The LLM is **useful but not load-bearing**: if Ollama fails, an N8N error-output branch emits a degraded template work order from the deterministic grade, banner-flagged `DEGRADED MODE`. The safety output never drops.

**Detect + action, not detect-only:** work-order creation and routing into the dashboard queue is automatic the instant a leak is graded — no manual trigger to *start* that step. Human approval is still required, but only before physical dispatch/valve isolation (see Maturity Level below) — this does not make the system autonomous.

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
| Orchestration | **N8N** (not Airflow/CrewAI/AutoGen) — auto-routes work orders on grade, human approval only before physical dispatch |
| Demo UI | Streamlit — non-technical red/amber/green dashboard |
| Tests | pytest |

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

Target metrics: ≥90% recall on Grade-1 scenarios; 100% of work orders cite at least one retrieved chunk; end-to-end latency < 40s at the default accuracy setting.

## Dashboard

Streamlit UI aimed at a **non-technical** viewer (dispatcher/supervisor, not an engineer). Per-segment tiles, colour-coded **red = Grade 1, amber = Grade 2, green = Grade 3**, plain-language readings (no raw sensor codes), plus an action indicator showing whether a work order has been auto-created/routed and whether it's awaiting approval or dispatched. The dashboard reads existing incident/grade/work-order payloads — it never re-derives a grade.

## Hardware Path (not implemented in this repo)

`docs/hardware-implementation-guide.md` is a short technician-facing brief on moving from synthetic CSV telemetry to real sensor hardware (pressure/methane/acoustic sensors, RTU/gateway options, required data fields). It's intentionally kept out of the codebase — this prototype stays synthetic-data-only.

## Maturity Level

The prototype is **L3 (recommendation only)** — human approval gate required before *physical dispatch*. Work-order creation and routing to the dashboard queue is automatic on grading (detect + action), which is still within L3/L4 — it is not autonomous physical control. Auto-isolation (L5) is explicitly out of scope and requires a formal SIL safety case.
