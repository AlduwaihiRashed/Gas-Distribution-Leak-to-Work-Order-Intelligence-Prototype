# Gas Distribution Leak-to-Work-Order (L2WO) Intelligence Prototype
### Internship Project Blueprint — Brief, Technical Design, Delivery Plan, Report Structure & CV Framing

> **One-line CV summary:** Built an offline, standards-grounded prototype that turns gas-distribution sensor anomalies into graded, code-cited emergency work orders — combining deterministic leak grading (PNGRB/OISD/GPTC) with RAG over procedural documents and a single local-LLM synthesis step, orchestrated end-to-end in N8N.

This blueprint is written to serve three readers at once: the **company** scoping the internship, the **university** marking the report, and a future **employer** reading the CV line. It deliberately corrects the common mistake of framing this as a "team of AI agents." It is a **linear, mostly-deterministic safety pipeline with exactly one LLM step**, which is what a real gas utility would accept.

---

## PART A — Company Project Brief (the "ask")

### A.1 Background & strategic context
The IntelGrid analytics platform currently covers **power and water** utilities; the gas vertical is greenfield (the analytics ecosystem reference lists *no* live gas use-cases yet). The platform's documented flagship pattern is the **Asset Failure → Field Action Intelligence Pipeline** (wiki §5.1): *ML alert → procedure lookup → structured work order → field feedback → wiki learning*. This internship seeds the gas vertical by implementing that pattern for the single highest-stakes gas use-case: **leak detection → severity grading → emergency work order** (wiki §3.2.2; TOGAF Value Stream 4, *Respond to Gas Emergency*).

The strategic hooks already exist in the gas Enterprise Architecture:
- **Safety Excellence:** zero public incidents, sub-30-minute emergency response.
- **Digital Transformation:** AI-driven pipeline integrity & leak detection.
- **Operational Excellence:** reduce unplanned outages, faster dispatch.

### A.2 Problem statement
Field leak response is bottlenecked between *detection* and *action*. Raw acoustic/methane/SCADA signals produce noisy alerts; converting a confirmed anomaly into a correctly **graded** incident and a **code-compliant, dispatch-ready work order** is manual, slow, and inconsistent. The goal is a prototype that compresses that gap while remaining **auditable and human-approved** — not autonomous.

### A.3 Objectives (SMART)
1. Detect leak-consistent anomalies in (synthetic) gas telemetry using **per-signal validation and urgency-based routing** — a single validated signal raises the appropriate workflow, and two corroborating signals escalate — so single-sensor noise is suppressed without missing real single-channel leaks.
2. Assign a **deterministic leak grade (1/2/3)** using a transparent rule engine keyed to recognised standards — *not* an LLM guess.
3. Retrieve the **exact procedural / regulatory text** that justifies the grade and response, with every output **citing its source chunk**.
4. Synthesise a **dispatch-ready work order** (incident facts + grade + cited procedure + crew instructions) in one local-LLM call.
5. Orchestrate the full flow in **N8N** and validate it against a **scripted scenario suite** with reported precision/recall and grading accuracy.
6. Demonstrate genuine closed-loop physical response on a **benchtop hardware rig**: Grade 1 triggers autonomous actuator isolation with no human gate, confirmed by sensor feedback — proving the architecture can act, not just recommend, for the one grade where time is the binding constraint (R8).

### A.4 Scope

**In scope**
- One pressure zone / a small set of distribution segments.
- Synthetic SCADA + sensor data with injected, labelled leak and non-leak events, **plus a benchtop hardware rig (ESP32 sensor + actuator nodes per segment) for live demonstration (R8)**.
- Detection, grading, retrieval, work-order synthesis, **automatic work-order routing (detect + action, R5)**, **autonomous physical isolation on Grade 1 with sensor-confirmed feedback (benchtop rig, R8)**, orchestration, evaluation.
- A **non-technical monitoring dashboard** (Streamlit) — red/amber/green per-segment status mapped to Grade 1/2/3, plain-language readings, and an action/dispatch/actuator-state indicator (R6, R8) — and a clean GitHub repository.

**Explicitly out of scope** (these guardrails are a feature, not a gap)
- **No autonomous valve isolation on live gas-distribution infrastructure.** The benchtop rig's actuator (relay/servo) models a valve; it is not connected to a real gas main. A live deployment of this same architecture would still require a formal SIL (IEC 61511/61508) safety case before autonomous isolation is appropriate there — see D7/R8.
- No live OT/SCADA connection to real utility infrastructure; no real customer or asset data.
- No multi-zone localisation beyond a coarse segment-level estimate.
- No production hardening, HA, or security accreditation.

### A.5 Success / acceptance criteria
- ≥ 90% recall on Grade-1 (hazardous) scenarios in the test suite, with documented false-positive rate on the non-leak scenarios.
- 100% of generated work orders cite at least one real retrieved chunk (zero ungrounded safety claims).
- Grading accuracy reported against ground-truth labels with a confusion matrix.
- **End-to-end response time < 40 seconds** per incident (detect → grade → retrieve → synthesise → routed to dashboard), measured at the demo's default accuracy setting (B.5).
- End-to-end run reproducible from `make demo` / a single N8N trigger, and the work order is **auto-routed to the dashboard queue with no manual step to initiate it** (detect + action, R5) — human approval remains required only before physical dispatch.

### A.6 Stakeholders (lightweight RACI)
| Role | Interest | Involvement |
|---|---|---|
| Gas Domain / Analytics lead | Sponsor; fit to platform roadmap | Accountable |
| Field operations SME | Realism of grading & work-order content | Consulted |
| Data engineering | Pipeline & stack alignment (no tool sprawl) | Consulted |
| Intern | Build & report | Responsible |
| University supervisor | Academic rigour & assessment | Informed |

### A.7 Constraints & assumptions
- Offline / local-first inference (privacy-preserving, mirrors the platform's Ollama choice).
- Reuse the existing house stack — **no CrewAI/AutoGen/Airflow**; N8N + ChromaDB + Ollama only.
- ~12 weeks, single developer.

### A.8 Enterprise Architecture alignment (TOGAF mapping)
| TOGAF layer | This prototype touches |
|---|---|
| **Strategy** | Safety Excellence (sub-30-min response); Digital Transformation (AI leak detection) |
| **Business** | Value Stream 4 *Respond to Gas Emergency*; capabilities *Emergency Response & Gas Escapes*, *Hazardous Area Classification*, *Permit to Work* |
| **Information** | Data domains: Asset, Gas Quality, Integrity & Safety, Operations, Geospatial (HCA / High Consequence Area) |
| **Application** | SCADA/GCS, Leak Detection System, PIMS, Work & Field Management, AI/ML |
| **Technology** | Time-series/historian data, local LLM inference, OT/ICS security context (IEC 62443) — discussed even though the prototype is offline |

---

## PART B — Technical Design

### B.1 Design philosophy — a deterministic pipeline, not a "team of AI agents"
The original proposal framed this as three autonomous AI agents on a multi-agent framework (CrewAI/AutoGen/LangChain agents). That framing was rejected on engineering and safety grounds, and the rationale is stated explicitly here because it is the single most important design decision in the project.

*Detect → grade → dispatch* is a **fixed, linear sequence.** It involves no open-ended planning, no dynamic tool selection, and no negotiation between actors — which are the only capabilities multi-agent frameworks exist to provide. Imposing such a framework here would add latency, cost, and **non-determinism to a life-safety flow** in exchange for no functional benefit. Worse, the "agent" framing tends to place an LLM *inside* the detection and grading decisions, where a single hallucination becomes a mis-graded gas leak.

The adopted architecture inverts that. Every safety-bearing decision — anomaly confirmation and leak grading — is **deterministic, rule-based, and auditable.** The LLM is used for exactly one task, at the very end, where natural-language generation is the genuine value-add: turning an *already-decided* incident into a readable field work order. Remove the LLM entirely and the system still produces a correct, graded, code-cited work order (this is enforced by the fail-safe branch in B.2[5]). That property — the LLM being **useful but not load-bearing** — is the whole point of the design.

```
 Real sensors (ESP32 nodes, benchtop rig) OR synthetic telemetry (CSV / stream)
        │
        ▼
 [1] Data-quality & anomaly detection      ← deterministic + light ML, NO LLM
        │   (per-signal validation; OR-routing by urgency; both signals ⇒ escalate)
        ▼
 [2] Leak-grade rule engine                ← deterministic decision table, NO LLM
        │   (concentration, location, confinement, surface capping, HCA, migration)
        │
        ├── Grade 1 ──▶ [2a] Autonomous physical isolation (benchtop rig, R8)
        │                    NO human gate; fires synchronously at grading time,
        │                    bypasses N8N and the LLM entirely; ESP32 confirms
        │                    actuator state back to the API (closes the loop)
        ▼
 [3] RAG retrieval over procedure corpus    ← ChromaDB; fetch the *text*, not the decision
        │   (returns cited chunks for the assigned grade)
        ▼
 [4] Work-order synthesis                   ← ONE local-LLM call (Ollama)
        │   (incident + grade + cited procedure → readable work order)
        ▼
 [5] N8N: auto-create + auto-route work order → dashboard queue + human-approval gate before physical dispatch
        │   (detect + action, R5 — routing itself is automatic; only physical dispatch waits on approval)
        ▼
 [6] Non-technical dashboard                ← red/amber/green per segment (Grade 1/2/3) + action/actuator status (R6, R8)
```

Whole-flow budget: **stages [1]–[5] complete in < 40 seconds** per incident at the default accuracy setting (B.5). Stage [2a] has its own, much tighter budget (B.5) since it runs synchronously ahead of the LLM and outside N8N's polling cadence.

### B.2 Component specifications

**[1] Data quality + anomaly detection (no LLM).**
- A lightweight DQ check first (range validation, dedup by `segment+timestamp`, UTC normalisation) — mirrors the platform's bronze→silver data-quality layer. Use `pandera` or a few Great Expectations checks.
- Per-signal detectors: rolling **EWMA / z-score on the pressure derivative** (rate of pressure drop), plus magnitude thresholds on methane (% LEL) and the acoustic index.
- **Routing logic — OR, not AND (corrected after review).** In a real low/medium-pressure distribution network the channels are physically decoupled: a regulator-station pressure sensor only registers a localised leak if it is a catastrophic rupture, and a local methane sensor never sees the regulated pressure drop. Requiring *both* signals (an AND gate) would therefore miss exactly the small near-building leaks that most often become Grade 1. The pipeline instead routes by signal and urgency:
  - **Methane (or acoustic) signal alone →** raise a leak **inspection** work order.
  - **Pressure-drop signal alone →** raise a **hydraulic / SCADA anomaly** check (treated as an operational event, not a leak emergency).
  - **Both signals together →** **escalate immediately** toward Grade 1.
- **False-alarm control is retained per-branch, not via cross-signal gating:** each channel must clear a **persistence window** (anomaly sustained ≥ N samples) and a magnitude threshold before its branch fires, so a single noisy reading or a legitimate operational pressure swing does not raise an alert. This relocates the original "corroboration" idea from *gating the incident* to *escalating the grade*.
- Optional stretch: `IsolationForest` as a multivariate comparator, reported as an ablation against the rule baseline.
- Output: a structured incident payload (JSON) tagged with the triggering channel(s) and the route taken.

**[2] Leak-grade rule engine (no LLM).**
- A transparent decision table producing **Grade 1 / 2 / 3** from: gas concentration relative to the lower flammable limit (methane LEL ≈ 5% vol), **location** (inside/near a building vs open right-of-way), **confinement**, **surface capping type**, **migration potential**, and **HCA / proximity-to-occupancy** flags.
- **Surface capping is a first-class grading input (added after review).** Under GPTC / 49 CFR 192 migration logic, ground cover can dominate the grade: a small leak venting through **soil or grass** may be Grade 3, while the *identical* leak under **asphalt or concrete** is forced to migrate laterally underground and can track into nearby basements — making it an immediate **Grade 1**. A rule engine without this variable cannot compute code-compliant grades in paved areas.
- Grade semantics (GPTC / 49 CFR 192 lineage): **Grade 1** = hazardous, immediate action; **Grade 2** = non-hazardous now, scheduled repair; **Grade 3** = minor, monitor/re-evaluate.
- Every grade decision is logged with the rule that fired — fully auditable.

**[2a] Autonomous physical isolation — the one action with no human gate (added post-review, R8).**
- On the **benchtop hardware rig only** (per-segment ESP32 node — see G.2/hardware guide): the instant the rule engine assigns **Grade 1**, the API sends an isolate command directly to that segment's ESP32, which drives a relay/servo modeling the shutoff valve and a local alarm/beacon. This call is synchronous and happens in-process at grading time — it does not wait for N8N's poll cycle or for work-order synthesis, because those add latency the one time latency is least acceptable.
- **Closed loop, not fire-and-forget:** the ESP32 reports the actuator's *actual resulting state* back to the API (not just "command sent"), which is what the dashboard shows. A command with no confirmation would be an open loop wearing a closed-loop's clothes.
- **Scope boundary, stated plainly:** this is safe to fully automate specifically because the benchtop rig's actuator is a demonstration model, not a live gas main. See D7/R8 and the Maturity Level discussion in G.3 — autonomous isolation of real gas-distribution infrastructure is a different, much harder problem requiring a formal SIL safety case, and nothing here should be read as a substitute for one.
- Grade 2/3 never trigger this stage; they proceed to work-order creation/routing exactly as before, with human-approved dispatch as the mechanism for physical response.
- If the ESP32/actuator is unreachable, the isolation attempt fails safely (i.e. it fails to act, it does not fail to *report*): the failure is logged and banner-flagged, and — critically — it never blocks or delays the rest of the pipeline (retrieval, synthesis, work-order routing). Isolation failing must not mean the incident goes unrecorded.

**[3] RAG knowledge base.**
- Corpus: the gas TOGAF EA, standard operating procedures, hazardous-area classification notes, and the relevant standard excerpts. Chunk → embed (local embeddings) → **ChromaDB**.
- Retrieval returns the procedural/regulatory chunks tied to the assigned grade and to isolation/PPE/permit requirements. **RAG fetches text to cite; it never decides the grade.**

**[4] Work-order synthesis — the single LLM step.**
- A local model via **Ollama** (privacy-preserving; matches the platform's AI layer) takes the incident payload + assigned grade + retrieved chunks and drafts a dispatch-ready work order: incident time/location, priority, isolation protocol, required permit-to-work, PPE, proximity hazards, and a crew summary.
- Constrained prompt: the model may only use supplied facts and retrieved text, and must attach citations. Output validated against a JSON schema.

**[5] Orchestration + fail-safe.**
- **N8N** wires [1]→[5]. **Detect + action (added after review, R5):** the moment a leak is graded, N8N **automatically creates and routes the work order into the dashboard queue** — no manual step is needed to initiate that. The human-approval node sits **after** routing, gating physical *dispatch* (crew/vehicle mobilisation), which is where the maturity boundary L3→L4 actually lives for the dispatch track (D6 still governs this — a technician being sent out is not the same action as stage [2a]'s automated relay, and dispatch approval is unaffected by R8/D7). This keeps the *dispatch* half of the system at "recommendation with visible, automatic action," not autonomous physical control — see [2a] and G.3 for where physical autonomy does now apply (Grade-1 isolation on the benchtop rig only). On a 👎 / correction, capture the lesson and append it to the vector store (the wiki's feedback-driven self-improvement pattern) — a small, demonstrable closed loop.
- **Deterministic fail-safe branch (added after review).** Local LLMs via Ollama can time out, run out of memory, or emit invalid JSON when forced into a schema. In a naive linear flow an LLM-node failure would crash the workflow and produce **no work order at all** — unacceptable for a safety pipeline. N8N's *Continue-On-Fail* / error output therefore catches any Ollama failure and routes to a **pre-templated Markdown work order** built directly from the deterministic incident payload + rule-engine grade, banner-flagged `DEGRADED MODE — template only, LLM unavailable`. Because grading already happened upstream, the safety-critical output still flows; only the prose polish is lost. This is the architecture's *LLM-not-load-bearing* principle made operational.

**[6] Non-technical monitoring dashboard (added after review, R6).**
- **Streamlit** app, audience is explicitly **non-technical** (a supervisor or dispatcher, not an engineer reading raw telemetry).
- One tile per segment/sensor group, colour-coded to the grade it would produce or has produced: **red = Grade 1**, **amber = Grade 2**, **green = Grade 3** — no numeric grade or raw units required to read the state.
- Readings shown in plain language (e.g. "gas level: high, near a building" rather than `methane_pct_lel: 62`).
- Each tile shows an **action indicator** — whether a work order has been auto-created/routed for that incident and whether it is still awaiting human approval or has been dispatched.
- Reads directly off the same incident/grade/work-order payloads produced by [1]–[5]; the dashboard never re-derives a grade itself (keeps grading single-sourced and auditable, consistent with D3).
- Visual language: a dark monitoring-console aesthetic (Nord palette) — dark panels, frost-blue chrome, aurora-coloured grade badges, monospace HUD readouts on IDs/timestamps/KPI values. Purely presentational; the red/amber/green grade semantics above are unchanged by it.

### B.3 Technology stack (house-aligned, deliberately minimal)
| Concern | Choice | Why this and not the alternative |
|---|---|---|
| Language / data | Python, Pandas, NumPy | Standard |
| Data quality | pandera / Great Expectations (subset) | Mirrors platform DQ layer |
| Anomaly detection | scikit-learn + statistical baseline | No LLM in the hot path |
| Rule engine | Plain Python decision table | Deterministic, auditable, safe |
| Vector DB | **ChromaDB** | Already in platform stack |
| Embeddings + LLM | **Ollama (local)** | Privacy-preserving; platform standard |
| Orchestration | **N8N** (with error-output fail-safe branch) | Platform standard — *not* Airflow/CrewAI/AutoGen |
| Edge hardware | **ESP32** sensor + actuator node (R8) | WiFi-native (no separate radio module, unlike STM32); dual-core with onboard ADC for analog sensors and GPIO/PWM for relay/servo actuation; cheap enough to deploy one per segment. Raspberry Pi considered and rejected as the *node* (weaker real-time GPIO sampling than a microcontroller) but is a reasonable *gateway* choice if aggregating several ESP32 nodes later |
| Demo UI | Streamlit — non-technical red/amber/green dashboard (R6) | Realistic for an internship demo; readable by a non-engineer |
| Repo / tests | GitHub, pytest | Reproducibility |

### B.4 Standards & compliance (corrected)
- **ASME B31.8** — *design/construction/integrity* code. Its **Location Class 1–4** governs the **design factor via population density**; it does **not** define leak-response grades. Cite it only for design/MAOP context.
- **Leak grading (1/2/3)** — from operator procedures / **GPTC Guide** under **49 CFR 192**, not from B31.8.
- **Surface cover & migration** — GPTC/192 leak-migration criteria treat ground cover (paving vs. open soil), and secondarily frost and saturation, as primary grade *escalators*, because they govern whether escaping gas vents safely upward or tracks laterally into structures. This is why the grading engine encodes `surface_capping_type`.
- **India / CGD context** — **PNGRB** technical & safety standards (T4S) and **OISD** guidelines (e.g. OISD-226) are the operative regime; align the rule engine and report to these, consistent with the platform's gas regulatory coverage (PNGRB, OISD, BIS).
- Getting these distinctions right is itself a graded part of the report and a credibility signal to any domain reviewer.

### B.5 Non-functional requirements (added after review, R4; extended R8)
- **Latency budget: < 40 seconds end-to-end** per incident, from raw telemetry hitting stage [1] to a routed work order landing in the dashboard queue (stage [5]). This is a hard target for the demo path, not an aspiration.
- **Physical isolation latency (R8): target < 5 seconds** from grade assignment to the isolate command reaching the ESP32, separate from and much tighter than the 40s work-order budget above — this is the one path that deliberately bypasses N8N's polling cadence and the LLM to hit that number. Report actual sensor-confirmed round-trip time (command sent → actuator state change reported back), not just command-sent time. **Measured against a virtual ESP32 node (`src/simulate_esp32.py` — no physical board attached to the dev environment; see hardware guide §6): ~0.4s command→confirmation, comfortably inside target.** This is a software-loop measurement, not a validated real-actuator timing — re-measure once physical hardware is flashed and wired.
  **STATUS (2026-07-04): real-hardware validation deliberately deferred, not blocked.** Mock/simulated telemetry via `simulate_esp32.py` is sufficient for the current phase of the software/AI track; flashing `esp32_firmware/l2wo_node.ino` onto a physical board and re-measuring against it is hardware-track work (Bilal/Mohammed, done hands-on in the office — see `CLAUDE.md`'s Project split note) and will happen when that phase is reached, not on this track's timeline.
- **Configurable accuracy variable.** Expose accuracy/speed as a tunable parameter rather than a fixed constant, so the tradeoff is demonstrable — candidates: the detection persistence window (samples required before an anomaly fires), RAG retrieval `top-k`, or the Ollama model/quality tier used for synthesis. Report latency at more than one setting to show the tradeoff explicitly (feeds Part D's "Latency per stage" metric and the ablation study).
- **The Step 4 model decision is reopened, not settled.** `ministral-3:3b` was chosen via a 7-model bakeoff under the earlier assumption that sub-30-*minute* was the real target (§A.3 previously) — at 112-183s/incident it no longer fits a 40s *end-to-end* budget and must be revisited. Options: swap to a smaller/faster local model as the default demo-path setting (documented as the "high-speed" accuracy tier) while keeping ministral-3 available as an optional "high-accuracy" offline tier behind the configurable variable; shorten the prompt/context; or pre-warm the model. This is open implementation work — track under task "Enforce <40s end-to-end response time" — and the bakeoff should be re-run with latency as a hard constraint, not just JSON validity/groundedness.

---

## PART C — Delivery Plan (6 milestones · ~12 weeks · 2-week sprints)

| # | Sprint objective | Key tasks | Deliverable | Acceptance criteria |
|---|---|---|---|---|
| **M1** | Foundations & EA alignment | Standards review (B31.8 vs GPTC vs PNGRB/OISD); map scope to TOGAF layers & wiki §5.1; pick stack | Architecture block diagram + 2-page spec | Supervisor signs off on scope, standards table, and "pipeline-not-agents" rationale |
| **M2** | Synthetic data + knowledge base | Generate labelled SCADA/sensor dataset with leak & non-leak (drift/transient) events; chunk + embed procedures into ChromaDB | Versioned dataset + queryable vector store | Dataset contains labelled edge cases; retrieval returns relevant chunks for sample queries |
| **M3** | Detection with false-alarm control | DQ checks; EWMA/z-score baseline; per-signal persistence/threshold validation; **OR urgency-routing** (methane/acoustic→inspection, pressure→hydraulic check, both→Grade-1 escalation); (optional) IsolationForest ablation | Detection module + routed incident JSON | Single-channel leaks still detected; legitimate pressure swings and single-sensor noise rejected; per-branch FP rate reported |
| **M4** | Deterministic grading + grounded retrieval | Build leak-grade decision table; bind each grade to retrieved procedure chunks with citations | Rule engine + retrieval layer | Grading is reproducible & logged; every grade returns a real cited chunk (no ungrounded output) |
| **M5** | Work-order synthesis + orchestration | Single Ollama synthesis call with schema validation; wire end-to-end in N8N with human-approval gate; **error-output fail-safe → degraded template work order**; feedback-to-wiki loop | End-to-end N8N flow → Markdown/JSON work order | One-trigger run produces a valid, cited work order; approval gate present; **forcing an Ollama failure still yields a banner-flagged degraded work order**; correct routing per signal (see Part D) |
| **M6** | Validation, hardening & report | Run scenario suite; confusion matrix; precision/recall & grading accuracy; finalise repo, README, report | GitHub repo + final report (PDF) + demo | Metrics reported honestly; reproducible; limitations & safety section complete |
| **M7** | Benchtop hardware integration (R8, added post-M6) | Build/wire per-segment ESP32 sensor+actuator node; API ingestion + isolate-command endpoints; firmware for sensor reporting and actuator confirmation | ESP32 firmware + API hardware endpoints + working benchtop rig | Grade 1 on a live sensor reading triggers isolation with no human gate in < 5s; actuator's confirmed state (not just command-sent) reaches the dashboard; failure of the ESP32/actuator is banner-flagged and never blocks work-order creation/routing |

---

## PART D — Evaluation & Validation Plan (the academic backbone)

Build a **scenario suite** of labelled cases and report results quantitatively — this is what turns "a demo" into "an evaluated prototype."

- **Positive cases:** Grade-1 (near-building, high concentration, confined), Grade-2 (sub-surface, away from occupancy), Grade-3 (minor, open ROW).
- **Negative / trap cases:** sensor drift, legitimate operational pressure change, single-signal noise below the persistence threshold.
- **Routing cases:** methane-only event (expect *inspection* WO), pressure-only event (expect *hydraulic/SCADA check*), both-signal event (expect *Grade-1 escalation*).
- **Resilience case:** force an Ollama failure mid-run and confirm a banner-flagged **degraded** work order is still produced.
- **Grading-fidelity case:** identical leak under `soil` vs `asphalt` must yield Grade 3 vs Grade 1 respectively (surface-capping logic).
- **Latency-SLA case (R4):** run the full suite at each configured accuracy setting and confirm end-to-end time stays **< 40 seconds**; report the accuracy/latency tradeoff across settings rather than a single number.
- **Action-routing case (R5):** confirm the work order is auto-created and lands in the dashboard queue with no manual trigger, and that it is visibly distinguishable from "awaiting approval" vs "dispatched."
- **Physical-isolation case (R8):** Grade 1 on the benchtop rig fires the isolate command with **no human gate**, and the actuator's *confirmed* state (not just "command sent") reaches the dashboard within the 5s target (B.5). Grade 2/3 must **never** trigger isolation. Forcing the ESP32/actuator unreachable must produce a banner-flagged failure that does **not** block or delay work-order creation/routing — isolation failing must never mean the incident goes unrecorded.
- **Metrics:**
  - Detection: precision, recall, F1; **false-positive rate** on negative cases.
  - Grading: accuracy + confusion matrix vs ground-truth grade labels.
  - Grounding: % of work orders with valid citations (target 100%).
  - Latency per stage (shows LLM is off the hot path) and **total end-to-end latency against the 40s budget, at each accuracy setting**.
  - **Isolation reliability (R8):** % of Grade-1 cases where the actuator's confirmed state matches the commanded state, and the command→confirmation latency distribution.
- **Ablation:** rule baseline vs +IsolationForest; with/without the per-branch persistence window — demonstrates *why* the false-alarm logic matters.

The most convincing demo slide is the **routing test**: an isolated **methane spike with no pressure drop** must raise a leak **inspection** work order — neither ignored nor auto-escalated to a Grade-1 emergency — while a **pressure drop with no gas reading** raises a hydraulic/SCADA check rather than a leak dispatch. Demonstrating the *right response for each signal* is more meaningful than a single accept/reject threshold, and it directly reflects the OR-routing correction.

---

## PART E — University Report Structure (chapter-by-chapter)

A standard internship/dissertation skeleton, ~25–40 pages depending on requirements:

1. **Abstract** — problem, approach, key result (one quantified sentence).
2. **Introduction** — background, problem statement, aim, SMART objectives, scope & limitations.
3. **Background & Standards Review** — gas leak detection methods (acoustic/methane/mass-balance); RAG fundamentals; agent vs. pipeline trade-offs; **standards: ASME B31.8 (design) vs GPTC/49 CFR 192 (grading) vs PNGRB/OISD (regime)**; TOGAF/EA framing.
4. **Requirements & Methodology** — functional & non-functional requirements; design decisions with justification (especially *why a deterministic pipeline, not agents*; *why the LLM is not in the grading path*); EA mapping.
5. **System Design & Architecture** — pipeline diagram, component contracts, data flow / sequence diagram, mapping each component to its TOGAF layer.
6. **Implementation** — synthetic data generation, DQ + detection, rule engine, RAG, synthesis prompt, N8N orchestration; code excerpts.
7. **Evaluation & Results** — scenario suite, metrics, confusion matrix, ablation, latency; honest discussion of failures.
8. **Discussion** — limitations; safety & human-in-the-loop rationale; OT/IT boundary and IEC 62443 context; data realism caveats.
9. **Conclusion & Future Work** — staged, *responsible* roadmap (see G.3): benchtop-rig autonomous isolation is real and demonstrated (R8/D7), but explicitly distinct from live-infrastructure auto-isolation, which stays future work behind a formal SIL case — no reckless "the benchtop demo means we're ready for a live gas main."
10. **References** — standards, papers, platform docs.
11. **Appendices** — data dictionary, prompt templates, sample work order, repo link.

---

## PART F — CV Framing (internship-level, quantified)

**Project title (CV header):**
> *Gas Distribution Leak-to-Work-Order Intelligence Prototype — local-LLM + RAG, standards-grounded, N8N-orchestrated*

**Bullet options (pick 2–3, adjust numbers to your real results):**
- Designed and built an offline prototype that converts gas-distribution sensor anomalies into **code-cited, dispatch-ready emergency work orders**, mapped to a TOGAF enterprise architecture and the platform's Asset-Failure→Field-Action pattern.
- Kept the **safety-critical decisions deterministic** — multi-signal anomaly detection with false-alarm suppression and a transparent leak-grade (1/2/3) rule engine — using the LLM **only** for final work-order synthesis, eliminating ungrounded safety output.
- Implemented **RAG over procedural/regulatory documents in ChromaDB with local Ollama inference**, achieving **100% source-cited** outputs and ~**XX% recall on Grade-1 scenarios** across a labelled test suite.
- Orchestrated the end-to-end flow in **N8N** with a human-approval gate and a feedback-to-knowledge-base loop, and validated it with a confusion matrix, precision/recall, and ablation studies.
- Closed the loop with a **benchtop ESP32 sensor+actuator rig**: Grade-1 incidents trigger autonomous physical isolation with sensor-confirmed feedback in under XXs, no human gate — explicitly scoped as a demonstration control loop, with the live-infrastructure safety-case boundary (SIL/IEC 61511) stated and understood, not glossed over.

**Skills surfaced:** Python, RAG, ChromaDB, Ollama/local LLMs, N8N, time-series anomaly detection, scikit-learn, data-quality engineering, enterprise-architecture (TOGAF) alignment, gas safety standards (ASME B31.8 / GPTC / PNGRB / OISD), embedded systems (ESP32, sensor/actuator integration), closed-loop control system design, evaluation & testing.

---

## PART G — Risks, Limitations, Safety & Future Work

### G.1 Risks (with mitigations)
| Risk | Mitigation |
|---|---|
| Synthetic data unrealistic | Inject literature-based leak signatures + labelled negatives; state caveat |
| LLM hallucinating a procedure | Grading is deterministic; LLM constrained to retrieved text + schema validation |
| Tool sprawl / non-integration | Reuse house stack only (N8N/ChromaDB/Ollama) |
| Local-LLM node failure (timeout / OOM / invalid JSON) | N8N error-output fail-safe emits a degraded, template-only work order from the deterministic grade; safety output never lost |
| Missed single-channel leak (decoupled sensors) | OR urgency-routing — any one validated signal raises the appropriate workflow |
| Over-claiming autonomy | Physical autonomy (R8) is scoped explicitly to the benchtop rig and stated as such everywhere it's described; never represented as ready for live gas infrastructure without a formal SIL case |
| False-positive Grade-1 triggers the actuator unnecessarily (R8) | Same false-alarm controls that protect grading (persistence window + magnitude threshold, B.2[1]) sit upstream of isolation — isolation only fires off an already-graded Grade 1, not a raw sensor spike |
| Real sensor hardware drifts/miscalibrates differently than synthetic data assumes (R8) | Benchtop rig is explicitly a demonstration of the *control loop*, not a validated field-calibration; flagged plainly in G.2, not hidden behind the demo |
| ESP32/actuator unreachable during a Grade-1 event (R8) | Isolation failure is banner-flagged and logged but never blocks or delays work-order creation/routing (B.2[2a]) — the informational safety output still flows even if the physical action can't |

### G.2 Honest limitations
Offline and single-zone; coarse localisation; synthetic data as the primary evaluated path; no OT integration to real utility SCADA or security accreditation; **real sensor + actuator hardware now exists as a benchtop demonstration rig (R8, `docs/hardware-implementation-guide.md`), but it is not field-calibrated, not connected to live gas infrastructure, and does not carry any formal safety certification** — treat its autonomous-isolation behavior as a control-loop demonstration, not a production capability. These are appropriate for an internship prototype and should be stated plainly rather than hidden.

### G.3 Responsible future work (staged, not reckless)
Two independent maturity tracks now apply, and they should not be conflated:
- **Software/dispatch track:** L3 (recommendation) → **L4** (one-click human-approved dispatch, work-order creation/routing already automatic per R5) — unchanged by R8.
- **Physical-actuation track:** **L5 achieved on the benchtop rig (R8)** — Grade 1 triggers real, sensor-confirmed autonomous isolation, with no human gate, on demonstration hardware. **L5 on live gas-distribution infrastructure remains explicitly future work**, gated behind a formal SIL safety case (IEC 61511/61508), independent voting sensors, certified actuators, and OT guardrails — none of which this internship's scope or timeline can deliver, and none of which should be implied as "close" just because the benchtop version works.

Other extensions: real historian integration, acoustic-localisation modelling, multilingual voice-to-work-order for field crews, ILI/corrosion data fusion, and scaling the benchtop rig to multiple segments.

---

## PART H — Design Decisions & Review Log

This section records the key design decisions and the review feedback that shaped them, so the reasoning behind the prototype is transparent and traceable. Each entry states what was decided, the alternative that was rejected, and why.

### H.1 Core architectural decisions
| # | Decision | Rejected alternative | Rationale |
|---|---|---|---|
| D1 | Linear deterministic pipeline | Multi-agent framework (CrewAI / AutoGen / LangChain agents) | No planning or autonomy is required; agents add non-determinism and latency to a life-safety flow and tend to put an LLM inside safety decisions |
| D2 | LLM used only for final work-order prose | LLM-driven anomaly detection and severity classification | Detection is deterministic/ML; grading is a bounded code decision. An LLM in these paths risks mis-grading a real leak |
| D3 | RAG fetches procedure text to *cite*, never to decide the grade | RAG severity classification "from retrieved context" | Eliminates ungrounded safety output; the grade stays reproducible and logged |
| D4 | Standards corrected — B31.8 = design only; grading from GPTC / 49 CFR 192; PNGRB/OISD as the operative regime | Using ASME B31.8 "Location Class 1–3" as the leak grade | B31.8 Location Class is a population-density *design factor*, not a leak-response grade — a domain error a reviewer would catch |
| D5 | House stack only: N8N + ChromaDB + Ollama | Adding CrewAI / AutoGen / Airflow | Avoids tool sprawl and non-integration with the existing platform |
| D6 | Recommendation-only (maturity L3), explicit human approval | Roadmapping toward autonomous valve isolation | Auto-isolation is L5 and needs a formal safety case / SIL assessment; reckless to imply for a prototype. **Refined, not overturned, by D7** — the SIL requirement still stands for any *live* gas infrastructure |
| D7 | Autonomous Grade-1 isolation on a **benchtop demonstration rig**, no human gate (R8) | Extending full autonomous isolation to live gas infrastructure without a safety case | The rig's actuator (relay/servo) models a valve rather than controlling one, so an incorrect auto-isolation has no real-world consequence — this is what makes full autonomy appropriate *here* without contradicting D6's reasoning, which is about consequence, not about the word "autonomous" in the abstract |

### H.2 Supervisor review — notes incorporated
| # | Supervisor note | Action taken | Refinement applied |
|---|---|---|---|
| R1 | Detection should be **OR with urgency routing**, not a ≥2-signal AND gate — in distribution, the pressure and methane sensors are physically decoupled | Adopted: methane/acoustic alone → inspection WO; pressure alone → hydraulic/SCADA check; both → Grade-1 escalation (B.2[1]) | Retained **per-signal persistence + threshold validation** on each branch so pure OR does not reintroduce single-sensor false alarms; updated the evaluation to *routing* tests (Part D) |
| R2 | Add **`surface_capping_type`** — paving vs. soil dictates gas migration and can flip Grade 3 → Grade 1 under GPTC/192 | Adopted as a first-class grading input (B.2[2], B.4) and added to the schema (Appendix A) | Noted optional `ground_state` (frost/saturation) as a stretch variable, not required for the core prototype |
| R3 | **Harden N8N** — an Ollama failure must not crash the flow and drop the work order | Adopted: error-output fail-safe branch emitting a degraded template work order (B.2[5], stack table, risk register) | Added a visible `DEGRADED MODE` banner and a dedicated resilience test (Part D); framed it as the operational proof of the *LLM-not-load-bearing* principle |

All three review notes were assessed as technically sound and adopted in full. The refinements in the right-hand column are conservative additions that preserve the original intent while closing secondary gaps (single-sensor noise, frost migration, degraded-output visibility).

### H.3 Supervisor review round 2 — notes incorporated
| # | Supervisor note | Action taken | Refinement applied |
|---|---|---|---|
| R4 | End-to-end response time must be **< 40 seconds**, with a **configurable accuracy variable** to trade speed vs. precision | Adopted as a hard NFR (A.5, B.5); the current ~2-min synthesis call (ministral-3) no longer fits the budget for the live demo path and must be replaced/reduced or moved off the interactive path | Configurable variable exposed as a pipeline parameter (e.g. detection persistence window, retrieval top-k, or LLM model/quality tier) rather than a fixed constant, so the accuracy/latency tradeoff is demonstrable, not hard-coded |
| R5 | The prototype's goal is **detect + action**, not detect-only | Adopted, scoped to stay within the existing L3/L4 safety boundary (does not reverse D6): work-order creation and routing into the dispatch queue/dashboard now fires **automatically** the instant a leak is graded, with no manual trigger to *start* that step. Human approval remains the gate before physical dispatch/valve isolation | Reframed B.2[5] and the demo narrative so "action" is visibly demonstrated end-to-end (grade → auto-created, auto-routed work order → queued for approval), not just the detection/grading steps |
| R6 | Need a **dashboard** that lets a **non-technical** viewer read every sensor's status at a glance — red (Grade 1) / amber (Grade 2) / green (Grade 3) — and see whether action has been taken | Adopted; expands the existing "minimal demo UI (Streamlit)" scope item (A.4) into a full dashboard spec (B.2[6]) | Plain-language readouts per segment (no raw sensor codes/units), colour-coded status tiles, and a per-incident action/dispatch indicator |
| R7 | A real deployment needs a **hardware-level implementation path** | Out of scope for Claude/this codebase by explicit instruction; delivered instead as a standalone **~300-word technician handoff brief** (`docs/hardware-implementation-guide.md`) for the user to walk through with a field technician | Keeps the prototype software-only and synthetic-data-based per A.4/A.7, while giving the user a concrete next step outside the repo |

R5 is the one note that touches a locked architectural decision (D6); it was scoped deliberately to *not* reverse it — see the clarification in R5's "Action taken" column.

### H.4 Supervisor review round 3 — notes incorporated (2026-07-02)
| # | Supervisor note | Action taken | Refinement applied |
|---|---|---|---|
| R8 | The prototype should be a genuine **closed loop with physical response** — a real actuator (output) driven by the sensor data (input) — and for **Grade 1** specifically, the system should be capable of taking urgent action on its own, since time is the constraint that matters most. A **hardware side** is planned; recommend an approach (STM32 / ESP32 / Raspberry Pi). | Adopted, with an explicit scope boundary: full autonomous Grade-1 isolation, no human gate, built and demonstrated on a **benchtop hardware rig**. Recommended and adopted **ESP32** as the per-segment sensor+actuator node (D7, B.2[2a], B.3). Isolation reports actuator-confirmed state back to the API, satisfying "closed loop" rather than "command sent." | **This is the one note that partially reverses a locked decision (D6), not just extends it** — done deliberately and stated as such (D7), scoped to the benchtop rig only. A live gas-main deployment of the same architecture is unchanged by R8 and still requires the formal SIL safety case D6 described; G.3's future-work roadmap now tracks the software/dispatch maturity path (L3→L4) and the physical-actuation maturity path (benchtop L5 achieved; live L5 still gated) separately so the two are never conflated in the report |

---

## Appendix A — Synthetic telemetry schema (suggested)
`timestamp_utc, segment_id, material, install_year, MAOP_bar, location_class, hca_flag, distance_to_building_m, confinement, surface_capping_type, pressure_bar, flow_scm_h, methane_pct_lel, acoustic_index, trigger_channel, route, label_event, label_grade`

`surface_capping_type ∈ {soil, grass, asphalt, concrete}` — drives lateral-migration risk in the grading engine (paved cover ⇒ escalation toward Grade 1). `trigger_channel` / `route` record which signal(s) fired and the urgency branch taken. Optional extension: `ground_state ∈ {normal, frozen, saturated}` for frost/rain migration effects.

**Queue/actuator fields (added R8):** the work-order queue entry also carries `actuator_commanded ∈ {true, false}`, `actuator_confirmed_state ∈ {isolated, open, unknown}`, and `actuator_command_latency_s` for Grade-1 incidents on the benchtop rig — populated by the ESP32's confirmation report, not by the command itself, per the closed-loop requirement in B.2[2a].

## Appendix B — Sample work-order skeleton (LLM output target)
Incident ID · Detected (UTC) · Segment & location · **Grade (1/2/3)** · Priority · Isolation status — **Grade 1: "Autonomously isolated at HH:MM:SS, confirmed by segment actuator" (no approval language — it already happened)**; **Grade 2/3: "Recommend isolating Valve V-401 — *human approval required*"** (dispatch, not isolation, since Grade 2/3 never trigger the actuator) · Required permit-to-work · PPE · Proximity hazards · Crew summary · **Cited sources** (procedure/standard chunks).

## Appendix C — Synthesis prompt contract (sketch)
*System:* "You draft gas emergency work orders. Use ONLY the incident facts and retrieved procedure text provided. Do not invent regulations. Cite every procedural claim. Output valid JSON matching the schema." *User:* `{incident_payload, assigned_grade, retrieved_chunks}`.

---
*Prepared as an internship-grade blueprint. Architecture intentionally favours determinism and auditability over autonomy, consistent with a life-safety gas-distribution context.*
