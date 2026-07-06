# C_doc — Software & AI Walkthrough

## What this is

A pipeline that takes raw gas-pipeline sensor readings and turns them into a graded, cited, dispatch-ready emergency work order — automatically, in seconds, with exactly one point where an LLM touches the process. Everything that decides *how dangerous is this* is plain deterministic code. The LLM's only job is writing the work order once that decision is already made.

That's the core design bet: a linear pipeline, not an agent framework. Three-agent, LangChain-style setups were considered and rejected early — they add non-determinism and latency to something where a wrong answer is a life-safety issue, and they tend to tempt you into putting an LLM *inside* the actual grading decision, which is exactly where you don't want one guessing.

## The pipeline, stage by stage

**1. Anomaly detection.** Reads pressure, methane %LEL, and acoustic index per pipe segment. Each signal gets its own detector — an EWMA baseline for pressure (a very slow-adapting rolling average, so a real drop stands out against it), simple thresholds for methane and acoustic. Critically, this uses **OR-routing, not AND**: methane or acoustic alone raises a leak inspection; pressure alone raises a hydraulic/SCADA check (not a leak — pressure drops without a gas signal usually mean something operational, not a leak); both together escalates hard toward Grade 1. The reasoning: in a real distribution network these sensors are physically decoupled, so requiring both to agree would miss exactly the small near-building leaks that matter most. Each signal still needs to hold for several consecutive samples (a persistence window) before it fires, so one noisy reading can't trigger anything.

**2. Grading.** A plain Python decision table, not a model. Grade 1 = immediate hazard, Grade 2 = scheduled repair, Grade 3 = monitor — using gas concentration, proximity to buildings, HCA (high consequence area) flags, and — the detail that actually matters most — **surface capping type**. The identical leak, at the identical concentration, is Grade 3 under open soil (vents upward safely) and Grade 1 under asphalt (traps and migrates sideways into basements). Getting this one variable wrong would silently produce wrong grades regardless of how good the sensors are, so it's tested explicitly (soil vs. asphalt, same leak, must diverge) — not just hoped-for.

**3. RAG retrieval.** ChromaDB, local embeddings, no external API calls. Given a grade and its context, this fetches the actual regulatory/procedure text that justifies the response — it never influences the grade itself, only cites evidence for it. Every graded incident retrieves real cited text; there's no ungrounded safety claim anywhere in a work order.

**4. Work-order synthesis — the one LLM call.** Takes the incident, the grade, and the retrieved citations, and writes a readable, structured work order (situation summary, isolation steps, PPE, permit requirements, crew instructions) constrained to a JSON schema so it's always structurally valid. If the LLM call fails for any reason — timeout, OOM, garbage output — a pure-Python fallback builds a banner-flagged, safety-complete template work order straight from the deterministic grade. Remove the LLM entirely and the system still produces a correct, graded, cited work order. That property — useful but never load-bearing — is the whole point.

**5. Orchestration.** N8N wires the auto-create-and-route step: the moment a leak is graded, the work order is created and dropped into the dashboard queue automatically, no manual trigger. The only human gate in this half of the system is approving physical *dispatch* — sending a crew — which sits after routing, not before it. A separate, parallel path (see below) handles Grade-1 physical isolation with no human gate at all, and deliberately doesn't go through N8N because N8N's poll cadence is too slow for that.

**6. The closed loop.** For a benchtop hardware rig: the instant a segment is graded Grade 1, an isolate command fires over MQTT synchronously, before the LLM call even starts. The physical node (or a software stand-in used for testing) reports back the *actual resulting* state — not just that a command was sent — which is what makes this a real closed loop instead of fire-and-forget. This bypasses the LLM and N8N's poll cycle entirely, because the one action where speed matters most shouldn't wait on either.

**7. Dashboard.** Streamlit, red/amber/green per segment, plain-language summaries (not raw sensor codes), an approval button, and — where relevant — a live actuator-confirmation indicator. It reads the queue and displays it; it never recomputes a grade itself.

## Tech stack

| Layer | Choice | Why |
|---|---|---|
| Data / detection | Python, Pandas, NumPy, pandera, scikit-learn | Standard, auditable, no ML in the safety-critical path beyond simple thresholds |
| Vector store | ChromaDB | Local, no external calls |
| LLM | Ollama (local) | Privacy-preserving, swappable model |
| Orchestration | N8N | Visual, house-standard, not a heavier framework than the problem needs |
| API | FastAPI | Thin layer fronting the pipeline for N8N and the dashboard |
| Actuation transport | MQTT (Mosquitto) | Push-based — a poll-based channel can't hit sub-5-second latency |
| Dashboard | Streamlit | Fast to build, good enough for a non-technical live view |
| Tests | pytest | 38 tests across the whole scenario suite |

## What actually got measured (not aspirational)

- **Detection:** precision 1.0, recall 1.0, F1 1.0, zero false positives across every negative/trap case (sensor drift, operational pressure swings, single noisy readings below threshold).
- **Grading:** 100% accuracy against ground truth, including the soil-vs-asphalt fidelity case.
- **Retrieval:** 100% of gradable incidents get a real citation above the minimum relevance score.
- **Synthesis:** across an 8-model local bakeoff, `gemma4:e2b` won on groundedness while staying fast; 100% valid JSON, 100% correctly cited, 5.3s–8.4s per work order (avg 7.3s) — well inside the 40-second end-to-end budget.
- **Isolation round-trip:** ~0.4 seconds from command to confirmed state (measured against a software-simulated node; real-hardware timing is still to be validated).

## A few decisions worth knowing the reasoning behind

- **Why not an agent framework at all?** No planning or tool selection is actually needed here — it's a fixed sequence. Agents would add latency and non-determinism for zero functional benefit, and historically tend to end up making safety decisions nobody explicitly signed off on.
- **Why is the model choice reopened from an earlier pick?** An earlier bakeoff optimized for output quality alone and picked a model that took ~2 minutes per work order — fine under a very loose budget, not fine once the real target became under 40 seconds end-to-end. The bakeoff was rerun with latency as a hard constraint, not an afterthought, and settled differently.
- **Why does the citation schema constrain the model to an enum of real chunk IDs** instead of letting it write freeform citation text? Because the earlier freeform version let a model cite the right document but hallucinate a fake anchor onto it — technically wrong, easy to miss. Constraining the output space closed that gap entirely rather than trying to catch it after the fact.
- **Why does the synthesis prompt get told the actuator's confirmed state?** Without it, a work order for an already-isolated segment would still read "dispatch crew to isolate" — not wrong, exactly, but redundant and confusing next to a dashboard that already shows it's done. Telling the model what already happened produces a work order that matches reality.
