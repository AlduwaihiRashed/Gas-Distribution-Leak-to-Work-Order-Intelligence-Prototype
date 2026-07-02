# Hardware Implementation Guide (for the field technician)

This prototype currently runs on **synthetic** telemetry (a CSV that mimics pressure, methane %LEL, and acoustic sensors). Moving it to a real pipe segment means replacing that CSV with a live feed from actual field hardware, without changing the detection/grading/work-order logic itself. Use this as the starting agenda for a conversation with your technician — it is a summary, not a wiring spec.

**1. Sensors to source, per segment**
- **Pressure transducer** at the regulator station or segment inlet (matches the `pressure_bar` field).
- **Methane sensor** (infrared point or open-path, rated for %LEL) placed near known risk points — building entries, valve pits, paved crossings — matching `methane_pct_lel`.
- **Acoustic/leak-noise sensor or correlator** clamped to the pipe or nearby, matching `acoustic_index`.
- Confirm each sensor outputs a value on a schedule compatible with the pipeline's sampling assumptions (the code currently expects roughly one reading per sensor per interval, not a raw waveform).

**2. Getting data off the sensor and into the pipeline**
- Most industrial sensors talk **4-20mA, RS-485/Modbus, or a vendor telemetry unit (RTU)**. The technician needs to confirm which protocol each chosen sensor uses.
- You'll need a **data logger/RTU or edge gateway** that reads the sensor(s) and can forward readings — either to a local file the pipeline reads (simplest, matches today's CSV ingestion) or to a message queue/API endpoint that step [1] can poll.
- Ask the technician about existing SCADA/telemetry infrastructure on the segment — there may already be a system that can be tapped instead of installing new loggers.

**3. Fields that must be supplied per reading**
`timestamp_utc, segment_id, pressure_bar, methane_pct_lel, acoustic_index` — plus static per-segment metadata that doesn't change per reading (`material, install_year, MAOP_bar, location_class, hca_flag, distance_to_building_m, confinement, surface_capping_type`), which can be entered once from GIS/asset records rather than sensed live.

**4. Safety and installation**
- Sensor placement, hazardous-area electrical classification (e.g. intrinsically safe wiring near gas), and permit-to-work all fall under the technician's domain expertise — defer entirely to them and site safety procedures.
- Start with **one instrumented segment** as a pilot before scaling, matching the prototype's existing single-zone scope.
