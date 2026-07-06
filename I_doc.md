# I_doc — Operations Guide

Everything you and Mohammed need to run, reset, and reason about this prototype day to day. Deep technical explanations live in `C_doc.md` (software/AI) and `B_doc.md` (hardware); this doc is about *doing*, not *understanding*.

---

## 1. What's actually running, at a glance

| Service | Port | Started by | Purpose |
|---|---|---|---|
| API (`src/api.py`) | 8000 | `uvicorn` | Fronts the whole pipeline — N8N and the dashboard both talk to this |
| Dashboard (`src/dashboard.py`) | 8501 | `streamlit run` | The red/amber/green monitoring screen |
| N8N | 5678 | `podman` | Auto-routing + approval-gate workflows |
| Mosquitto (MQTT) | 1883 | `podman` | Isolate command + actuator confirmation channel |
| Ollama | 11434 | system service | Local LLM, one call per work order |
| ESP32 simulator (`src/simulate_esp32.py`) | — | `python3` | Stand-in for real hardware, only needed until Mohammed has a board flashed |

Nothing here needs the internet. Everything is local.

## 2. Cold start — bringing the whole thing up from nothing

```bash
cd Gas-Distribution-Leak-to-Work-Order-Intelligence-Prototype
pip install -r requirements.txt

# Infra containers (once — they persist across reboots via named volumes)
podman run -d --name mosquitto -p 1883:1883 -v mosquitto_data:/mosquitto/data \
  --entrypoint sh docker.io/library/eclipse-mosquitto:latest \
  -c "printf 'listener 1883\nallow_anonymous true\npersistence true\npersistence_location /mosquitto/data/\n' > /mosquitto/config/mosquitto.conf && exec mosquitto -c /mosquitto/config/mosquitto.conf"

podman run -d --name n8n -p 5678:5678 -v n8n_data:/home/node/.n8n docker.io/n8nio/n8n:latest
# first time only: open http://localhost:5678, create the owner account,
# then Workflows → Import from File → both files in n8n/

# Deterministic pipeline (only needed once, or after changing synthetic_telemetry.csv)
python src/generate_telemetry.py
python src/detect_anomalies.py
python src/grade_leak.py
python src/build_corpus.py          # embeds docs/ into ChromaDB — see §5 if you ever re-run this
python src/retrieve_procedures.py

# API — this is the one thing everything else depends on
uvicorn api:app --app-dir src --host 0.0.0.0 --port 8000

# Dashboard (separate terminal)
streamlit run src/dashboard.py

# Only if testing the actuation loop without real hardware attached
python src/simulate_esp32.py
```

If `podman ps` already shows `mosquitto`/`n8n` up from a previous session, `podman start mosquitto n8n` instead of `run`.

## 3. Day-to-day: starting/stopping individual pieces

- **Just want the dashboard working?** You need the API up (port 8000) — nothing else. N8N/mosquitto/Ollama being down just means the *demo data already in the queue* is all you'll see; new incidents won't get created or isolated.
- **Just want to demo the closed loop (Grade 1 → auto-isolate)?** Need: API + mosquitto + either a real ESP32 or `simulate_esp32.py`. N8N and the dashboard are optional for this specific demo.
- **Just want to demo dispatch approval?** Need: API + N8N (the approval webhook lives there, not in the API directly).
- **Restarting the API** (e.g. after a code change): kill the `uvicorn` process, re-run the start command. It picks up code changes on restart, not live.
- **Rebuilding the RAG corpus** (after editing anything in `docs/`): run `python src/build_corpus.py` again, **then restart the API** — it holds a ChromaDB collection handle from startup and won't see the rebuilt corpus otherwise. This bit us once; see `docs/hardware-implementation-guide.md` isn't the relevant doc, it's a plain code fact worth remembering here.

## 4. How to disable auto-isolation (if you need to demo/test without it firing)

There's no config flag for this yet — the honest way to disable it today is to not run `simulate_esp32.py` and not have a real board attached. The API will still *command* isolation (MQTT publish) when a Grade 1 fires, it just won't get a confirmation, and the dashboard will show "commanded but unconfirmed" instead of "isolated." Grading and work-order creation are unaffected either way — isolation failing never blocks the rest of the pipeline, on purpose.

## 5. Resetting demo data to a clean state

Everything the dashboard shows lives in plain JSON files. To wipe and start over:

```bash
rm -f data/work_order_queue/queue.json data/work_order_queue/actuator_state.json
# to also clear any live-ingested test incidents from the graded/citation files,
# see the cleanup one-liner pattern in git log around 2026-07-02 — filter
# graded_incidents.json / retrieved_citations.json to drop any incident_id
# starting with "LIVE-" that you don't want kept.
```

The batch demo incidents (`INC-0001`..`INC-0008`) come back automatically next time you run `detect_anomalies.py` → `grade_leak.py` → `retrieve_procedures.py`.

## 6. Running the tests

```bash
pytest
```

38 tests. The ones needing Ollama/MQTT/a live API skip automatically if that service isn't up — you don't need everything running to get a meaningful pass/fail on the safety-critical core (detection + grading). If you touch `detect_anomalies.py`, `grade_leak.py`, or `synthesize_work_order.py`, run this before trusting your change.

## 7. Guidelines for us as owners

- **Test before claiming something works.** This project has already caught real bugs (API crashing on MQTT-down, isolate commands crashing requests, a stale RAG doc contradicting the actual system behavior) purely by actually running things instead of assuming the code was right. Keep doing that.
- **Software track vs hardware track stay separate**, and so does who implements what on the hardware side — see `B_doc.md`'s framing. Don't let firmware/wiring decisions get made in a software session; do them on the bench.
- **The benchtop rig's autonomous isolation is a deliberately scoped exception**, not a general precedent — don't casually extend "no human gate" reasoning to anything else without re-deriving why it was safe here (relay/servo has no real-world consequence) in the first place.
- **Keep `data/` outputs reproducible from the scripts**, not hand-edited — if the demo data looks wrong, regenerate it, don't patch the JSON by hand except for quick resets (§5).
- **Don't commit unless asked.** Nothing in this repo auto-commits; review `git status`/`git diff` before asking for a commit.
