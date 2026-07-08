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

## 7. Step by step — what happens to one incident, from sensor to work order

This is the plain-English walkthrough of the whole pipeline, in the order things actually happen. Use this when you need to explain the system to someone (including yourself, six months from now).

**Step 1 — telemetry comes in.**
Either a CSV file of fake ("synthetic") sensor readings (`src/generate_telemetry.py`), or a real ESP32 sending one reading at a time to `POST /telemetry/ingest`. Either way, one reading looks like: a timestamp, which pipe segment it's from, the gas reading (methane % of the lower explosive limit), an acoustic reading (does it sound like gas escaping), the pipe pressure, and some fixed facts about that segment (what it's made of, how old it is, is it under a building, is it under asphalt or soil, and so on).

**Step 2 — is this reading actually weird? (`src/detect_anomalies.py`)**
No LLM here, just statistics. For each sensor channel, the code checks: is this reading far enough from the normal baseline to count as an anomaly, and has it stayed weird for enough consecutive readings in a row (the "persistence window")? This stops a single noisy reading from setting off an alarm.
Then it routes based on *which* channels are anomalous, using OR logic, not AND logic:
- Gas or noise alone → "inspection" (something might be leaking)
- Pressure drop alone → "hydraulic_check" (probably a SCADA/operational blip, not a leak)
- Gas/noise AND pressure together → "escalation" (this looks serious)

**Step 3 — how bad is it? (`src/grade_leak.py`)**
Also no LLM — a plain if/else decision table, because a life-safety grading decision has to be something a human can audit line by line, not something a model "decided." Rules fire in this order, first match wins:
1. Escalation route → **Grade 1** (hazardous, act now)
2. Inspection route + the ground above the pipe is paved (asphalt/concrete) → **Grade 1** — paving stops gas venting straight up, so it travels sideways underground and can end up inside a nearby building's basement, even for a small leak
3. Inspection route + unpaved ground, but close to a building or high concentration → **Grade 2** (schedule a repair)
4. Inspection route + unpaved, far from anything, low concentration → **Grade 3** (just keep an eye on it)

This is why the exact same leak can be Grade 3 under a field and Grade 1 under a road — the ground cover changes everything.

**Step 3a — Grade 1 only: isolate the pipe, right now, no one asks permission (`src/actuation.py`, `src/live_ingest.py`)**
The instant grading says "Grade 1," the code publishes an MQTT message telling that segment's ESP32 to close its valve (relay/servo on the benchtop rig) and sound a local alarm. This happens in the same process, synchronously, before anything else in the pipeline runs — it does not wait for N8N, it does not wait for the LLM. Nobody approves this step; it is fully automatic, and that is intentional (see "Maturity Level" in `CLAUDE.md` for exactly why that's safe here and would not be safe on a real gas main).
The ESP32 then reports back over MQTT what actually happened to the valve. That confirmation is what makes this a *closed loop* — the dashboard shows "isolated (confirmed)," not just "we sent a command and hope it worked."

**Step 4 — go find the relevant procedure text (`src/retrieve_procedures.py`, backed by `src/build_corpus.py`)**
Still no LLM doing any deciding. The grade and incident details are turned into a search query, and ChromaDB (a vector database) returns the most relevant chunks of text from the procedures/regulations documents in `docs/`. This is RAG — Retrieval-Augmented Generation. It only fetches text; it never grades anything or overrides the grade from Step 3.

**Step 5 — write it up in plain English (`src/synthesize_work_order.py`) — the ONE place an LLM is used**
Ollama (running a local model, currently `gemma4:e2b`) is given: the incident facts, the grade (already decided — the model is told not to change it), and the retrieved procedure text. It writes a proper work order: title, situation summary, step-by-step isolation protocol, required permits, required PPE, hazards nearby, and which procedure chunks it used as citations. The output is forced into a strict JSON shape (a "schema"), so it always comes back in a format the rest of the system can use. If the LLM call fails, times out, or comes back malformed, the code silently falls back to a template work order built straight from the Step 3 grade — banner-flagged `DEGRADED MODE` — so a broken LLM never means "no work order gets created."

**Step 6 — get it in front of a human, automatically (`src/api.py` + N8N)**
The API exposes `/incidents/pending` (graded incidents nobody has created a work order for yet) and `/work-orders/synthesize` (do Step 5, then drop the result into the queue). N8N polls the first endpoint every 10 seconds and calls the second one for anything new — see section 8 below for exactly how. This is fully automatic; nobody has to click a button to get a work order created and into the queue.

**Step 7 — a human decides whether to actually send a crew (`src/api.py`'s `/approve` endpoint, called via N8N's second workflow)**
This is the *only* human approval gate in the whole system, and it is specifically about sending people/vehicles out (physical "dispatch"), not about creating the work order (that already happened automatically in Step 6) and not about the Grade-1 valve isolation (that already happened automatically in Step 3a, with no approval at all).

**Step 8 — show it on the dashboard (`src/dashboard.py`)**
Streamlit reads the current state of the queue and the actuator confirmations and shows one tile per segment: red = Grade 1, amber = Grade 2, green = Grade 3, plus whether a work order exists, whether it's waiting for approval or approved, and — for Grade 1 — whether the valve is confirmed closed yet. The dashboard never recalculates anything; it only displays what earlier steps already decided.

---

## 8. The N8N workflows, node by node

There are two separate workflows imported into N8N (`n8n/l2wo-auto-work-order-routing.json` and `n8n/l2wo-dispatch-approval-gate.json`). Both just call the API on port 8000 — all the actual thinking (grading, LLM calls, RAG) happens in Python, not inside N8N. N8N's whole job here is: poll for new work, call the API, and handle it if the API doesn't answer.

**Important thing to know before reading this:** the Grade-1 valve isolation from Step 3a above is **not** in either of these workflows. It fires directly from Python code (`live_ingest.py` → `actuation.py`) the instant grading happens, before N8N ever polls. N8N only ever *sees* the isolation as a read-only field on a work order (`actuator_confirmed_state`) — it never triggers it and never could, because by the time N8N's 10-second poll would notice the incident, the valve command has usually already been sent (the target for that whole round trip is under 5 seconds).

### Workflow A — "L2WO - Auto Work Order Routing"

This is the "notice new work and handle it" loop. Nobody starts it manually — it just runs on a timer forever.

| Node name | What it actually does |
|---|---|
| **Poll every 10s** | A timer. Every 10 seconds it "ticks" and starts a new run of the workflow. It doesn't carry any data — it's just a heartbeat. |
| **GET pending incidents** | Calls `GET http://host.containers.internal:8000/incidents/pending` on the API. (`host.containers.internal` is just how a podman container says "the machine I'm running on, not myself.") This returns a list of incidents that have been graded but don't have a work order yet. N8N automatically turns that list into one "item" per incident, so everything downstream runs once per incident. If the API is completely unreachable, this node fails and the run goes down the *error* path instead (see below). |
| **Synthesize + auto-route (M7)** | For one incident, calls `POST /work-orders/synthesize` with that incident's ID. On the API side, this is the expensive step: it claims the incident so nothing else can double-process it, calls Ollama to write the work order (falling back to a degraded template internally if Ollama fails), and saves the result into `queue.json` with status `AWAITING_APPROVAL`. As far as N8N is concerned this call *succeeds* even if Ollama failed internally — the API still returns a normal 200 response, just with `degraded_mode: true` inside it. N8N only takes the *error* path here if the API/network itself couldn't be reached at all. |
| **Routed to dashboard queue** | Does nothing by itself — it's just a labelled "we're done, this was the happy path" marker. The actual saving into the queue already happened inside the API call above. |
| **Build per-incident fallback alert** | Only runs if the *synthesize* call itself failed to reach the API (not an Ollama failure — those don't reach here). It takes whatever incident info it still has (id, segment, grade — grabbed from the earlier "GET pending incidents" step) and builds one line of JSON saying "synthesis failed for this specific incident, degraded mode, manual grading still stands." |
| **Build pipeline-outage alert** | Only runs if the very first call — "GET pending incidents" — failed. In that case N8N doesn't even know which incidents exist, so it can't name one; it just writes a generic "the whole pipeline can't be reached right now" alert. |
| **Write alert log (latest state)** | Whichever alert got built above, this node overwrites one log file inside the N8N container (`l2wo_orchestration_alerts.log`) with it. It **overwrites**, not appends — so the file always shows the *current* problem, not a growing history of every past hiccup. |

**Why two separate "something broke" branches (`Build per-incident fallback alert` vs `Build pipeline-outage alert`)?**
Because two different things can go wrong, at two different points, and they need two different messages. If only the *second* HTTP call (synthesize) had error handling, a total outage would kill the run at the very *first* HTTP call and nothing would ever get logged at all — you'd just see silence, which is worse than an alert. So both HTTP nodes have their own error branch, and each one writes the most useful message it's able to given what it still knows at that point.

### Workflow B — "L2WO - Dispatch Approval Gate"

This is the one and only human-approval step in the entire system. It does nothing until a person clicks "Approve" on the dashboard.

| Node name | What it actually does |
|---|---|
| **Approval webhook** | Sits and waits for a `POST` request to `http://localhost:5678/webhook/approve-dispatch` with an incident ID in the body. This is what the dashboard's "Approve" button calls. |
| **Approve physical dispatch (human gate)** | Calls `POST /work-orders/{incident_id}/approve` on the API. On the API side this flips the work order's status from `AWAITING_APPROVAL` to `APPROVED_DISPATCHED` — meaning "a human has now signed off on sending a crew/vehicle." If it's already been approved (or the incident doesn't exist), the API replies with an error (HTTP 409/404) instead of pretending it worked twice. |
| **Respond: dispatched** | If the approve call succeeded, sends a normal 200 JSON response back to whoever clicked the button (usually the dashboard), containing the updated work order. |
| **Respond: approval failed** | If the approve call failed (e.g. someone double-clicked approve), sends back a 502 with the real error message, so the dashboard can show "that didn't work" instead of a false "success." |

### Why does this project have two separate N8N workflows instead of one?

Because they do two completely different jobs, on two completely different triggers, and merging them would blur a line the whole project is built around:

1. **Different triggers.** Workflow A runs on a timer, with nobody watching. Workflow B only runs when a specific human clicks a specific button. Putting both in one workflow would mean one workflow has two unrelated starting points, which N8N doesn't really support cleanly and would just be confusing to read.
2. **Different safety meaning.** Workflow A is the "automatic" half of the system — creating and routing a work order needs no permission at all (the blueprint calls this "detect + action"). Workflow B is the *only* place in the whole system that stops and waits for a person, and it's about a specific, different decision — "should we actually send a crew/vehicle out," not "should this leak get written up." Keeping them as two separate workflows makes that boundary visible just by looking at the file list, instead of hiding it as a branch inside one big workflow.
3. **Blast radius.** If you need to change how approval works, you can open Workflow B and know for certain you can't accidentally break the automatic routing loop, and vice versa. One file, one job, is easier to reason about and easier to demo ("here is the automatic part," "here is the human part") than one workflow doing both.

---

## 9. Why Ollama (a local LLM) instead of a regular Python ML model?

Short answer: **because different parts of this pipeline are solving different kinds of problems, and an LLM is only the right tool for one of them.**

Break the pipeline into its three "smart" steps and look at what each one actually needs to do:

| Step | What kind of problem is this? | What tool fits, and why |
|---|---|---|
| Detection (Step 2) | "Is this number unusual compared to its recent history?" — a numeric, statistical question | Statistics (EWMA/z-score) plus an optional `scikit-learn` `IsolationForest` as a comparison. This is a solved, well-understood kind of problem — you don't need a language model to notice a number is 3 standard deviations from its rolling average. |
| Grading (Step 3) | "Given these known facts (concentration, location, ground cover, HCA flag), which of exactly 3 outcomes applies?" — a small, fixed decision table | Plain Python `if`/`elif` logic. This has to be **deterministic and auditable** — for a life-safety decision, you need to be able to point at the exact rule that fired and say "this is why we called it Grade 1," every single time, with zero randomness. An ML model (even a simple classifier) can't give you that — it gives you a probability, not a rule you can quote back to a regulator. |
| Work-order writing (Step 5) | "Turn these already-decided facts into a clear, readable paragraph a field crew can act on, correctly quoting the right regulation" | **This is the one job a language model is actually good at that a regular ML model isn't: producing fluent, correctly-structured natural language from structured input.** A classifier or regression model doesn't write sentences. This is genuinely a language-generation task, so it's the one place in the whole pipeline where an LLM belongs. |

So the honest framing for an interview is: **we didn't choose "LLM vs ML" once for the whole project — we picked the right tool per step, and it turns out only one of the three steps is actually a language-generation problem.** Using an LLM for detection or grading would have made the safety-critical part of the system *less* trustworthy (non-deterministic, harder to audit, capable of hallucinating a grade), for zero benefit, since nothing about "is this pipe leaking" or "which of 3 buckets does this fall into" needs fluent prose.

**Why Ollama specifically, and why local, and why this particular model:**
- **Local, not a cloud API** — this is a privacy/safety choice. Sensor data about real gas infrastructure locations, and it also matches "the platform's AI layer" convention already used elsewhere in the wider IntelGrid system (see `CLAUDE.md`). No data about pipe locations or leak details ever leaves the machine.
- **The model is not load-bearing.** If Ollama is down, slow, or returns broken JSON, `synthesize_work_order.py` catches that and falls back to a plain-Python template built straight from the deterministic grade — banner-flagged `DEGRADED MODE`. Delete the LLM entirely and the system still produces a correct, graded, work order; it just reads worse. That property is deliberate — see `CLAUDE.md`'s "Architecture: Deterministic Pipeline, Not Agents."
- **Model choice (`gemma4:e2b`) came from an actual bakeoff**, not a guess — 8 models were compared on this machine's GPU (`src/bakeoff_synthesis_models.py`, results in `data/synthesis_output/model_bakeoff.json`). `gemma4:e2b` won on "groundedness" (it actually used the retrieved procedure text with real numbers instead of vague filler) while still finishing in single-digit seconds per incident. Others were rejected for concrete, specific reasons: one model wouldn't reliably follow the required JSON format; another burned its whole token budget on invisible "thinking" and never produced the actual work order; the smallest model sometimes made up citation IDs that didn't exist, which is disqualifying when the project requires 100% real citations.
- **The output is constrained to a JSON schema**, and the citations field is restricted to only the chunk IDs actually retrieved for that specific incident — this is a second safety net against a model inventing a citation that sounds plausible but doesn't exist.

**Why not use a multi-agent framework (CrewAI/AutoGen/LangChain agents) instead of a fixed pipeline?**
Because "detect → grade → dispatch" is a fixed sequence with no real decisions about *what to do next* — there's no planning, no tool selection, no negotiation between multiple actors, which is the actual problem multi-agent frameworks are built to solve. Using one here would only add unpredictability to a safety-critical flow, with no upside. See `CLAUDE.md`'s "Architecture: Deterministic Pipeline, Not Agents" section — this was an explicit, deliberate rejection, not an oversight.

---

## 10. Questions you might get asked about this in an interview (and how to answer them)

**Q: Why isn't grading done with machine learning, if you already use ML for anomaly detection?**
A: Detection is answering "is this number unusual" — a statistical question ML is good at. Grading is answering "which of 3 fixed, legally-grounded categories does this incident fall into" — and for a safety decision like that, you need an answer you can audit rule-by-rule and reproduce exactly every time. A rule engine gives you that; a trained classifier gives you a probability and a much harder story to tell a regulator.

**Q: What happens if Ollama crashes in the middle of a demo?**
A: Nothing breaks. `synthesize_work_order.py` catches the failure, and the API returns a plain-template work order built directly from the already-decided grade, clearly marked `DEGRADED MODE`. The work order is worse to read, but it still exists, still has the right grade, and still gets routed and shown on the dashboard. This is tested directly — see the "resilience" test scenario for forced Ollama failure.

**Q: If Ollama fails, does N8N notice and retry?**
A: No, and that's intentional — an Ollama-only failure is *handled inside the API*, so the HTTP call from N8N still comes back as a normal success (with `degraded_mode: true` in the body). N8N only sees a failure if the API or network is completely unreachable, which is a different, worse problem that does need its own alert.

**Q: Why does Grade-1 isolation skip N8N and the approval step entirely — isn't that dangerous?**
A: On real gas infrastructure it would be, and the project is explicit that this specific autonomy is scoped to the benchtop demo rig only — the "valve" is a relay/servo model with no real-world consequence if it's wrong. Because the target for command-to-confirmation is under 5 seconds, waiting on N8N's 10-second poll or a human clicking approve would blow that budget for the one action where speed matters most. On live infrastructure, autonomous isolation would need a formal functional-safety case (IEC 61511/61508) that this prototype doesn't attempt to provide.

**Q: What's the difference between the two human-facing gates in this system — is there one approval step or two?**
A: There is exactly one approval gate, and it's specifically about physical *dispatch* (sending a crew/vehicle) — not about creating the work order (automatic) and not about Grade-1 isolation (also automatic, no gate at all). It's easy to think there are two gates because there are two automatic actions (work-order creation and Grade-1 isolation) plus the one real gate, but only the dispatch step ever waits on a person.

**Q: Why two n8n workflows instead of one?**
A: They run on entirely different triggers (a timer vs a specific button click) and represent two different safety categories (fully automatic routing vs the system's one human approval gate). Keeping them separate makes that boundary visible in the file list itself, rather than something you have to trace through branches inside one workflow.

**Q: Why RAG instead of just baking the procedures into the prompt, or fine-tuning a model on them?**
A: The procedure corpus needs to be swappable and auditable — you can see exactly which chunk of which document was cited for a given work order, and you can update `docs/` and rebuild the index without retraining anything. RAG also lets the model *cite* real text rather than having to memorize it, which is exactly what "100% of work orders must cite a retrieved chunk" requires.

**Q: How do you stop the LLM from just making up a citation?**
A: Two layers. First, the system prompt tells it every work order must cite at least one retrieved chunk. Second, and more importantly, the JSON schema itself restricts the `citations` field to an enum of only the chunk IDs that were actually retrieved for that specific incident — the model is structurally incapable of citing something that wasn't handed to it, because the parser would reject it. This is not "asking politely" — it's a hard constraint on the model's output shape (this closed a specific bug seen during testing where a model cited a real chunk ID but appended a made-up `#anchor` to it).

**Q: What's the actual latency budget, and does the current model meet it?**
A: End-to-end (sensor to routed work order): under 40 seconds. Grade-1 isolation specifically: under 5 seconds, measured at ~0.4s round-trip against the virtual ESP32 simulator (real hardware not yet flashed — that's explicitly hardware-track work, not blocked, just not reached yet). `gemma4:e2b` synthesis runs in single-digit seconds per incident, well inside the 40s budget — it replaced an earlier model choice (`ministral-3:3b`) that took 112–183 seconds and was rejected on latency alone once the 40s target was set.

**Q: Why is Grade-1 isolation "safe" here but you say it wouldn't be safe on real infrastructure?**
A: Because the actuator here is a relay/servo demonstrating what a valve would do, not an actual gas main shutoff — a wrong auto-isolation just means resetting a benchtop demo. On real infrastructure, the same architecture would need independent voting sensors (not one methane/acoustic/pressure triplet), certified fail-safe actuators, and a proof-tested safety lifecycle (SIL, IEC 61511/61508) before autonomous isolation of an actual gas main would be defensible. Nothing in this prototype claims to meet that bar.

---

## 11. Guidelines for us as owners

- **Test before claiming something works.** This project has already caught real bugs (API crashing on MQTT-down, isolate commands crashing requests, a stale RAG doc contradicting the actual system behavior) purely by actually running things instead of assuming the code was right. Keep doing that.
- **Software track vs hardware track stay separate**, and so does who implements what on the hardware side — see `B_doc.md`'s framing. Don't let firmware/wiring decisions get made in a software session; do them on the bench.
- **The benchtop rig's autonomous isolation is a deliberately scoped exception**, not a general precedent — don't casually extend "no human gate" reasoning to anything else without re-deriving why it was safe here (relay/servo has no real-world consequence) in the first place.
- **Keep `data/` outputs reproducible from the scripts**, not hand-edited — if the demo data looks wrong, regenerate it, don't patch the JSON by hand except for quick resets (§5).
- **Don't commit unless asked.** Nothing in this repo auto-commits; review `git status`/`git diff` before asking for a commit.
