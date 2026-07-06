# Gas Distribution Leak-to-Work-Order (L2WO) Intelligence Prototype

A linear, mostly-deterministic pipeline that turns gas-distribution sensor anomalies into graded, code-cited emergency work orders — with exactly one LLM step, and a benchtop hardware loop that can physically isolate a Grade-1 leak with no human in the loop.

**Read next, by what you need:**
| Doc | For |
|---|---|
| [`A_doc.md`](A_doc.md) | The 5-minute version — what this does and why it matters, no jargon |
| [`C_doc.md`](C_doc.md) | The software/AI walkthrough — pipeline, tech stack, decisions, results |
| [`B_doc.md`](B_doc.md) | The hardware/IoT/SCADA walkthrough — edge node, protocols, safety boundary |
| [`I_doc.md`](I_doc.md) | Operations — how to start/stop/reset/test everything |
| [`docs/gas-leak-l2wo-prototype-blueprint.md`](docs/gas-leak-l2wo-prototype-blueprint.md) | Full design rationale, decision log, evaluation plan |
| [`docs/hardware-implementation-guide.md`](docs/hardware-implementation-guide.md) | Wiring diagrams, BOM, firmware contract |
| [`CLAUDE.md`](CLAUDE.md) | Claude Code / repo conventions |

```
Real sensors (ESP32) OR synthetic telemetry (CSV)
        │
        ▼
[1] Anomaly detection (deterministic + ML)  →  OR-routing by signal urgency
        ▼
[2] Leak-grade rule engine (deterministic)  →  Grade 1 (hazardous) / 2 (scheduled) / 3 (monitor)
        │
        ├── Grade 1 ──▶ [2a] Autonomous physical isolation (benchtop rig only — no human gate)
        ▼
[3] RAG retrieval over procedure corpus (ChromaDB)
        ▼
[4] Work-order synthesis (ONE local Ollama call, degrades safely if it fails)
        ▼
[5] N8N: auto-create + auto-route → dashboard queue; human approval gates physical dispatch
        ▼
[6] Non-technical dashboard (Streamlit) — red/amber/green per segment
```

## Team

Two people work both tracks together — **Rashed** (computer engineer, AI/software-leaning) and **Mohammed** (electrical engineer, hardware-leaning) — supervised separately per domain: **Casey** on software/AI, **Bilal** on hardware. The hardware track happens hands-on, in the office.

## Quickstart

Requires: Python 3.10+, [Ollama](https://ollama.com) running locally, [podman](https://podman.io) (or Docker) for n8n/mosquitto.

```bash
pip install -r requirements.txt   # or see "Dependencies" below

# 1. Generate synthetic telemetry + run the deterministic pipeline
python src/generate_telemetry.py
python src/detect_anomalies.py
python src/grade_leak.py
python src/build_corpus.py          # one-time: embed docs/ into ChromaDB
python src/retrieve_procedures.py
python src/synthesize_work_order.py # needs Ollama up, model: gemma4:e2b

# 2. Bring up supporting infra
podman run -d --name mosquitto -p 1883:1883 ... # see docs/hardware-implementation-guide.md §3
podman run -d --name n8n -p 5678:5678 -v n8n_data:/home/node/.n8n docker.io/n8nio/n8n
# import n8n/*.json via the n8n UI (Workflows → Import from File)

# 3. Start the API (fronts the pipeline for N8N + the dashboard)
uvicorn api:app --app-dir src --host 0.0.0.0 --port 8000

# 4. Start the dashboard
streamlit run src/dashboard.py
```

Then open the dashboard at `http://localhost:8501` and n8n at `http://localhost:5678`.

## Running the tests

```bash
pytest
```

38 tests, covering the blueprint's Part D scenario suite: detection (positive/negative/routing/persistence-window cases), grading (positive cases + the soil-vs-asphalt fidelity case), RAG citation coverage, synthesis resilience (forced Ollama failure), the API's auto-create/auto-route + approval-gate behavior, and actuation (broker-down resilience + live round-trip). Tests needing Ollama, MQTT, or a live API are marked `live_infra` and skip automatically if that service isn't reachable — the deterministic core (detection/grading/retrieval, the safety-critical part) runs with zero external dependencies.

## Repo layout

| Path | What |
|---|---|
| `src/generate_telemetry.py` | Synthetic sensor data generator |
| `src/detect_anomalies.py` | M3 — DQ + anomaly detection + OR-routing |
| `src/grade_leak.py` | M4 — deterministic leak-grade rule engine |
| `src/build_corpus.py` / `retrieve_procedures.py` | M5/M6 — RAG corpus + retrieval |
| `src/synthesize_work_order.py` | M7 — the one LLM call, with a degraded-template fallback |
| `src/bakeoff_synthesis_models.py` | Reusable model bakeoff harness |
| `src/api.py` | M8 — HTTP API fronting the pipeline for N8N + the dashboard |
| `src/live_ingest.py` | M9 — streams real ESP32 telemetry through the same detect/grade/retrieve logic as the batch path |
| `src/actuation.py` | M9 — MQTT isolate command + confirmation (the Grade-1 closed loop) |
| `src/simulate_esp32.py` | Virtual ESP32 node, for testing the actuation loop without hardware |
| `src/dashboard.py` | M10 — Streamlit non-technical monitoring dashboard |
| `esp32_firmware/` | Real ESP32 firmware — **draft for the hardware track to review**, untested on physical hardware |
| `n8n/` | Exported N8N workflows + node reference |
| `docs/` | Blueprint, hardware guide, RAG source docs |
| `tests/` | pytest suite |
| `data/` | Pipeline outputs at each stage (regenerated by the scripts above) |

## Current results (synthetic batch, `data/*/evaluation.json`)

Detection: precision 1.0, recall 1.0, F1 1.0. Grading accuracy: 100% vs ground truth. Citation coverage: 100%. Grade-1 isolation round-trip (virtual ESP32): ~0.4s, against a 5s target — **real-hardware validation intentionally deferred to the hardware track (see blueprint B.5); mock data is sufficient for now**.

## Maturity / safety boundary

L3 (recommendation, human-approved dispatch) for the software track — work-order creation/routing is automatic, but sending a crew is always human-approved. **Grade-1 physical isolation is fully autonomous on the benchtop rig only** (blueprint D7/R8) — the actuator models a valve, it doesn't control one. A live gas-main deployment of this architecture would still require a formal SIL (IEC 61511/61508) safety case before autonomous isolation is appropriate there. See `CLAUDE.md`'s Maturity Level section and the blueprint's decision log (Part H) for the full reasoning.
