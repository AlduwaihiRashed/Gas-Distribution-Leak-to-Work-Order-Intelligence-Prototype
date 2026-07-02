# Just To Be On Track

**1. What we did already**
- Step 1: made fake but realistic pipe sensor data (pressure, gas %, sound), cleaned it up, and wrote code that watches it and flags anything that looks like a leak. One weird sensor alone gets a smaller alert, two weird sensors together get a bigger alert. Caught every real leak with zero false alarms.
- Step 2: built a simple rulebook that turns each flagged leak into Grade 1 (emergency), 2 (scheduled repair), or 3 (monitor) based on gas amount, location, and ground cover (paved surfaces trap gas and force Grade 1 even at low readings). 100% match against our test answers.
- Step 3: built the "lookup the rulebook" step. We chunked our safety/procedure documents, turned them into searchable vectors (ChromaDB), and now every graded leak automatically pulls the real procedure text that justifies its grade — so the work order can cite something real instead of just stating a grade with no explanation. Along the way we found our source documents didn't actually have real leak-response procedures in them (just architecture diagrams), so we wrote a proper procedures reference doc and added it to the searchable corpus.
- Step 4 (partial): decided which local AI model will write the actual work order text. We tested 7 different local models head-to-head on a real example and picked **ministral-3** — it gave the most complete, accurate answers (around 2 minutes per work order, which is totally fine since this only runs once per incident, not live/interactively).

**2. Things to go learn before the interview**
Gas leak grading rules (GPTC, 49 CFR 192, PNGRB, OISD), why ASME B31.8 is NOT the grading standard, EWMA/z-score anomaly detection, IsolationForest basics, RAG + ChromaDB, Ollama/local LLMs, N8N orchestration, and why we avoided multi-agent AI frameworks.

**3. Next step**
Finish step 4 — write the code that actually calls the AI model to turn a graded leak + its cited procedures into a real, readable work order (with a safety net: if the AI fails, a plain template work order still comes out, so nothing ever silently disappears).

**4. Supervisor notes to fold in (2026-07-01)**
- Whole thing (detect → grade → work order) has to finish in **under 40 seconds**, and there should be a variable I can turn to trade accuracy for speed. Problem: ministral-3 alone takes ~2 minutes, so I need a faster model (or a "fast mode" setting) for the live demo, and can keep ministral-3 as a slower "high-accuracy" option.
- The goal isn't just "detect a leak" — it's "detect **and act**." Clarified with supervisor's intent in mind: the system should auto-build and auto-queue the work order the second a leak is graded, no manual button to make that happen. A person still has to approve before anything physical happens (isolating a valve etc.) — so this doesn't change the "no autonomous action" safety promise, it just means the work-order step can't be something I demo by hand-triggering it.
- Need a **dashboard** a non-engineer could read in 5 seconds: red = Grade 1, amber = Grade 2, green = Grade 3, per segment, plus whether a work order has already gone out for it.
- Real hardware installation is out of scope for me to build — see `docs/hardware-implementation-guide.md` for the ~300-word brief to walk through with a technician (sensor types, how their data gets into the pipeline, safety/permit stuff that's on them not me).
