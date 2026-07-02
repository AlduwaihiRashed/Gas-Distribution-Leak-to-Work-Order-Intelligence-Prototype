# Gas Leak Response Procedures & Regulatory Reference Digest

> **Provenance note:** this is a synthesized reference digest prepared for the L2WO prototype's
> RAG corpus. It summarizes well-established, publicly known gas-distribution leak-grading and
> emergency-response practice under the standard families the blueprint cites — the **GPTC Guide**
> (Gas Piping Technology Committee) leak-classification scheme adopted industry-wide under
> **49 CFR Part 192 Subpart M (Maintenance)**, and India/CGD-context safety practice under
> **PNGRB Technical Standards & Safety (T4S)** and **OISD-226**. It is written for retrieval-citation
> purposes in a prototype and is not a verbatim reproduction of any single regulatory text — a
> production system would embed the actual regulator-issued PDFs/clauses instead.

## 1. Leak Grade Classification Criteria

Gas distribution leaks are classified into three grades based on hazard potential, following the
GPTC Guide classification adopted under 49 CFR Part 192 Subpart M leak-survey and repair
requirements:

- **Grade 1 — existing or probable hazard, requires immediate action.** Any leak that represents
  an existing or probable hazard to persons or property and requires immediate repair or
  continuous action until the condition is no longer hazardous. Triggers include: gas
  concentration at or above a significant fraction of the lower explosive limit (LEL, ~5% vol
  methane in air) in a confined space or structure; gas migrating into or under a building;
  multiple corroborating signals (pressure loss with confirmed gas presence) indicating an
  uncontrolled release.
- **Grade 2 — non-hazardous at time of detection, justifies scheduled repair.** The leak is
  recognized as non-hazardous at the time of detection but justifies scheduled repair based on
  probable future hazard, including proximity to occupied structures or High Consequence Areas
  (HCA), or elevated gas concentration trending toward hazardous levels.
- **Grade 3 — non-hazardous, monitor.** The leak is not hazardous at the time of detection and can
  reasonably be expected to remain non-hazardous, typically low-concentration leaks in open
  right-of-way, away from structures, venting freely to atmosphere.

## 2. Surface Capping & Migration Guidance

Ground cover over a leaking pipe is a primary grade escalator, independent of leak magnitude,
because it governs whether escaping gas vents safely upward or migrates laterally underground:

- **Soil / grass / unpaved cover:** permeable to gas; a leak typically vents vertically to
  atmosphere and disperses, which is why an unpaved leak away from occupancy is usually Grade 3
  even at moderate concentration.
- **Asphalt / concrete / paved cover:** impermeable; escaping gas cannot vent vertically and
  instead migrates laterally underground, often for tens of meters, following the path of least
  resistance (utility trenches, sewer lines, building foundations) until it finds an entry point
  into a structure. A leak under pavement must be treated as **Grade 1 regardless of measured
  surface concentration**, because the absence of a strong surface reading does not rule out gas
  accumulating in a nearby basement or utility vault.
- Confinement type (`below_pavement` vs `open_row`) should be read together with capping type:
  below-pavement confinement combined with paved capping is the highest-migration-risk
  configuration and always escalates to Grade 1 under this scheme.

## 3. Immediate Response Procedure — Grade 1 (Hazardous)

1. **Eliminate ignition sources** in the affected area immediately: no smoking, no electrical
   switches, no vehicle ignition within the hazard radius.
2. **Evacuate and ventilate** any structure where gas has migrated or is suspected to have
   migrated (paved-capping cases); open doors/windows if safe to do so; do not use powered
   ventilation equipment that could itself be an ignition source.
3. **Establish isolation:** on a segment with an actuator-equipped node, isolation fires
   automatically the instant the segment is graded 1 — this is the one action in the response
   chain that does not wait for human confirmation, because it is the action most sensitive to
   delay. Automated isolation of this kind is only appropriate where the actuator has no
   real-world consequence if it fires incorrectly (a benchtop/demonstration rig) or where the
   segment sits behind a certified safety-instrumented system per a formal SIL assessment (IEC
   61511/61508) — neither of which should be assumed for a given segment without checking. On
   any other segment, dispatch crew to the nearest upstream and downstream isolation valves and
   isolate the segment per the segment's MAOP and valve-spacing record.
4. **Continuous atmosphere monitoring** at the leak site and in any structure within the migration
   radius using intrinsically safe gas detectors until concentration is confirmed below 20% of
   LEL and trending down.
5. **Notify emergency services and gas control center** immediately; declare a gas emergency per
   the utility's emergency response plan; target response time is sub-30-minute arrival on site.
6. **Human approval gate:** field crew dispatch — mobilising personnel and vehicles to the site
   for repair, confirmation, and follow-up work — requires human confirmation before execution
   (maturity level L3/L4). This gate does **not** apply to the automated segment isolation in
   step 3, which is deliberately outside the approval requirement given how time-sensitive a
   Grade 1 event is; it applies to every subsequent physical action a person performs on site.

## 4. Scheduled Repair Procedure — Grade 2

1. Schedule excavation and repair within the utility's documented Grade 2 repair window
   (commonly within a defined number of months per the operator's leak-management plan, prioritized
   by proximity to occupancy and trend in concentration).
2. Re-survey the leak location at a defined interval (e.g. every 1–3 months) until repaired, to
   confirm it has not progressed toward Grade 1 conditions (e.g. rising concentration, or a change
   in surface capping such as new paving).
3. If proximity to a building or HCA is the escalating factor, consider interim mitigation
   (venting, barrier fencing, tenant notification) pending scheduled repair.

## 5. Monitoring Procedure — Grade 3

1. Log the leak location and re-evaluate on the utility's standard periodic leak-survey cycle.
2. No immediate excavation required; include in routine main-replacement/rehabilitation planning
   if recurrent at the same segment.
3. Re-grade immediately if any subsequent survey shows elevated concentration, new construction
   changing surface capping (e.g. paving over a previously open right-of-way), or new occupancy
   within the HCA proximity threshold.

## 6. PPE Requirements for Field Crews

- Intrinsically safe, calibrated combustible-gas detector (LEL meter) carried at all times in the
  hazard zone.
- Flame-resistant (FR) clothing; no synthetic fabrics that generate static discharge.
- Non-sparking tools within any classified hazardous area.
- Respiratory protection escalation: standard PPE below 10% LEL; supplied-air or SCBA required
  above 10% LEL or in any confined space with unconfirmed atmosphere.
- Multi-gas monitor (LEL, O2, H2S, CO) required for confined-space or below-grade entry (vaults,
  basements, manholes near the leak).

## 7. Permit-to-Work Requirements

- **Hot work permit** required for any welding, cutting, or spark-generating activity within the
  hazardous area classification zone around an active or recently isolated leak.
- **Confined space entry permit** required for any entry into a vault, basement, manhole, or
  trench where gas may have migrated or accumulated; requires atmosphere testing (LEL, O2, toxics)
  before and continuously during entry.
- **Isolation / lockout-tagout** of the segment's valves must be verified and tagged before repair
  work begins; a second-person verification of zero-energy (zero-pressure, purged) state is
  required before excavation reaches the pipe.
- Permits require sign-off before crew dispatch proceeds from "recommended" to "in progress" — this
  is the operational expression of the human-approval gate at maturity level L3/L4. It governs
  crew dispatch, not the automated segment isolation described in §3, which is deliberately
  outside this gate.

## 8. Hazardous Area Classification (HCA) & Notification

- A **High Consequence Area (HCA)** flag indicates population density, occupied structures, or
  identified sites (schools, hospitals) within the potential impact radius of a worst-case release
  on that segment, per PNGRB T4S and OISD-226 CGD safety guidance.
- Any Grade 1 or escalating Grade 2 leak within an HCA requires proactive notification of the
  affected occupants/facility and, for public-safety-relevant leaks, coordination with local fire
  and emergency services in addition to internal gas-control notification.
- Distance-to-building thresholds (e.g. ≤20m) are used as a proxy for HCA proximity when a formal
  HCA polygon flag is not independently available for a given segment.

## 9. Reference Standards Index

| Standard family | Scope in this digest |
|---|---|
| GPTC Guide for Gas Transmission and Distribution Piping Systems | Leak grade classification (Grade 1/2/3), industry-adopted under 49 CFR 192 |
| 49 CFR Part 192, Subpart M — Maintenance | Leak survey, repair, and continuing surveillance requirements (U.S. federal baseline) |
| PNGRB Technical Standards & Safety (T4S) | India CGD (City Gas Distribution) technical & safety regulations |
| OISD-226 | Oil Industry Safety Directorate guideline on CGD piping system design, layout, and safety practice |

> **Not applicable here:** ASME B31.8 governs pipeline *design, construction, and integrity*
> (Location Class 1–4, design factor by population density) — it does not define leak-response
> grades and is intentionally excluded from this response-procedure digest.
