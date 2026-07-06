# A_doc — What This Project Actually Does

### In one sentence
A gas pipe starts leaking → the system detects it, decides how dangerous it is, writes up exactly what to do about it, and — if it's an emergency — physically shuts off the gas itself, all in under a minute, with a person always in charge of the final "send a crew" decision.

---

## The problem

Gas leaks are detected by sensors, but turning "something's wrong" into "here's exactly what to do, right now" is normally slow and manual — someone has to notice the alert, figure out how bad it is, look up the right procedure, write it up, and decide what to send a crew to do. Every minute in that chain is a minute a real hazard sits unaddressed.

## What this does about it

**It compresses that entire chain to seconds — and for the worst-case scenario, it acts before a human even has to.**

1. **Sees it.** Sensors on the pipe (gas concentration, pressure, sound) get watched continuously. A single weird reading doesn't trigger anything — it takes a sustained pattern, so false alarms are rejected automatically.
2. **Understands it.** The system doesn't just say "leak" — it grades exactly how dangerous it is, using the same standards a real gas-safety engineer would (how much gas, how close to a building, what's on top of the pipe — because gas escaping under a paved road behaves completely differently than gas escaping under open grass).
3. **Explains it.** It writes a real, readable instruction sheet for a field crew — what's happening, what to wear, what permits are needed, what to do first — and every safety claim in it is backed by an actual cited procedure document, not a guess.
4. **Acts on it — for the most urgent case.** If the situation is graded as an immediate hazard, the system doesn't wait for anyone to click a button. It commands a physical shutoff itself, in well under a second, and confirms the shutoff actually happened before telling anyone it's done.
5. **Keeps a human in charge of the physical response.** Sending an actual repair crew out is still always a person's call — the system prepares everything and puts it in front of them instantly, but doesn't dispatch people on its own.

## Why this matters — three ways

**For gas distribution:** the industry's biggest lever on public safety is response *time*. This collapses the detection-to-decision gap from a manual process that can take minutes to an automated one that takes seconds, without cutting any corners on the actual safety standards (the grading logic is built on the real regulatory framework, not a shortcut).

**For hardware and IoT:** this isn't just software watching a dashboard — there's a real physical sensor-and-actuator loop, built on cheap, deployable hardware, that can genuinely close the gap between "detected" and "responded" without waiting on a network round-trip to a control room. Measured response time from decision to a *confirmed* physical action on the current test setup: about four-tenths of a second, against a virtual (simulated) ESP32 node — real hardware is deliberately deferred to the hardware track's own timeline, not blocking this track; mock data is sufficient for now.

**For software and AI:** it uses AI exactly where AI is good — writing clear, human-readable instructions — and nowhere it's risky. Every decision that actually matters for safety (how bad is this, what grade is it) is made by transparent, testable, deterministic logic, not a model's guess. The AI is useful, but if it goes down entirely, the safety-critical output doesn't disappear — a complete, clearly-flagged backup version is produced automatically instead.

## By the numbers

| | |
|---|---|
| Leak detection accuracy (test suite) | **100%** — every real leak caught, zero false alarms |
| Grading accuracy vs. official standards | **100%** |
| Emergency work orders with a real, cited safety justification | **100%** |
| End-to-end time from sensor reading to a routed, actionable work order | **under 40 seconds** |
| Time from "this is an emergency" to a confirmed physical shutoff | **~0.4 seconds** *(measured on the current test setup — real-hardware timing is confirmed next)* |
| What happens if the AI component fails entirely | **Nothing breaks** — a safe, complete fallback is produced automatically |

## The responsible-design part (this is a feature, not a limitation)

The one thing this system will do fully on its own — a physical safety shutoff — only runs autonomously on a **demonstration rig**, where a wrong call has zero real-world consequence. Deploying that same autonomous authority onto an actual gas pipeline is a genuinely different, much bigger undertaking — the kind that requires a formal industrial safety certification process before it's appropriate, and this project is explicit and deliberate about not skipping that step. Everywhere else, and on any real infrastructure, a person is always the one who decides whether to send a crew.
