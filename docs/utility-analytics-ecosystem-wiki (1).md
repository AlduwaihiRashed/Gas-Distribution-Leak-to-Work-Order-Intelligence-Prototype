# Utility Analytics Ecosystem — Complete Reference Wiki
## All Use-Cases, Workflows, and Data Architecture for Power, Gas & Water Utilities

> **Purpose:** A single reference for every analytical use-case, workflow, and data pipeline component
> needed to serve a utility customer or employee without leaving the IntelGrid ecosystem.
> Cross-references the TOGAF EA files (power, gas, water) for capability alignment.

---

## Table of Contents

1. [Data Pipeline Architecture](#1-data-pipeline-architecture)
2. [Power Utility Use-Cases](#2-power-utility-use-cases)
3. [Gas Utility Use-Cases](#3-gas-utility-use-cases)
4. [Water Utility Use-Cases](#4-water-utility-use-cases)
5. [Cross-Utility Horizontal Use-Cases](#5-cross-utility-horizontal-use-cases)
6. [Business Process & Workflow Automation](#6-business-process--workflow-automation)
7. [LLM & AI Integration Patterns](#7-llm--ai-integration-patterns)
8. [Regulatory & Compliance Coverage](#8-regulatory--compliance-coverage)
9. [Customer-Facing Use-Cases](#9-customer-facing-use-cases)
10. [Future Roadmap Candidates](#10-future-roadmap-candidates)

---

## 1. Data Pipeline Architecture

### 1.1 Source Systems by Utility Type

#### Power Utility Source Systems

| System | Data Type | Frequency | Volume/Day | Priority |
|--------|-----------|-----------|------------|----------|
| AMI / Smart Meters (MDMS) | Interval energy readings (kWh, kVAh, kVArh), tamper events, outage flags | 15-min or 30-min | 10M–500M records | Critical |
| SCADA / EMS | Voltage, current, frequency, MW/MVAR flows, breaker status, transformer temperatures | 2s–5s real-time | 1B+ time-series points | Critical |
| OMS (Outage Management) | Outage events, restoration times, affected customers, crew dispatch | Event-driven | 1K–50K events | High |
| GIS (Spatial) | Network topology, asset locations, service territory, cable routes | Weekly + on change | 500MB–5GB | High |
| EAM / ERP (SAP/Maximo) | Work orders, asset master, maintenance history, spare parts inventory | Hourly / daily | 100K–1M records | High |
| CIS / CRM | Customer accounts, billing addresses, tariff codes, service requests | Daily | 50K–500K records | High |
| Billing System | Monthly consumption, billing amounts, payment status, AR aging | Monthly + daily | 100K–2M records | Medium |
| Metering Lab | Test bench results, meter accuracy certificates | On-event | 1K–10K records | Medium |
| WOMS (Work Order Mgmt) | Field crew assignments, inspection results, fault locations | Daily | 10K–100K records | Medium |
| Weather API (IMD/OpenWeather) | Temperature, humidity, wind speed, solar irradiance, rainfall | Hourly | 50K records | Medium |
| Protection Relay (IEDs) | Fault waveforms, relay trip events, disturbance records | Event-driven | 1K–10K events | High |
| LT/HT Metering (Distribution) | Feeder energy, DTR energy, substation demand | 15-min | 5M–50M records | Critical |
| EV Charging Stations | Charging sessions, kWh dispensed, connector status | Real-time | 100K–1M records | Low-Medium |
| Solar/DER Meters | Generation output, inverter status, grid export | 5-min | 1M–10M records | Medium |

#### Gas Utility Source Systems

| System | Data Type | Frequency | Volume/Day | Priority |
|--------|-----------|-----------|------------|----------|
| SCADA / DCS | Pipeline pressure, flow rates, compressor status, valve positions, gas quality (BTU, specific gravity) | 5s–30s | 500M time-series | Critical |
| AMI Gas Meters | Consumption intervals, tamper events, low battery | 15-min or hourly | 1M–50M records | Critical |
| MDMS (Gas) | Validated consumption, settlement data | Hourly / daily | 500K–5M records | High |
| GIS (Pipeline) | Pipeline routes, material, age, operating pressure, coating type | Weekly | 1GB–10GB | High |
| ILI (In-Line Inspection) | Corrosion anomalies, wall thickness, deformation data | Periodic (annual/bi-annual) | 10GB per run | High |
| Cathodic Protection Monitoring | Pipe-to-soil potential readings, rectifier output | Daily | 100K–1M records | High |
| LDAR (Leak Detection) | Methane sensor readings, acoustic sensor alerts | Continuous | 10M records | Critical |
| OMS (Gas) | Leak incidents, emergency shutdowns, restoration | Event-driven | 1K–10K events | Critical |
| EAM / ERP | Work orders, pipe replacement records, maintenance history | Daily | 50K–500K records | High |
| CIS | Customer accounts, gas connections, tariff codes | Daily | 10K–200K records | High |
| Odorization System | Odorizer injection rates, gas odor readings at test points | Hourly | 10K–100K records | High |
| Compressor Stations | Fuel gas consumption, power draw, vibration, bearing temperatures | 1-min | 500M records | High |
| Gas Control (SCADA) | Dispatch instructions, linepack, storage levels | Real-time | 100M records | Critical |
| Laboratory (Gas Quality) | Chromatograph results, BTU content, H2S, CO2 levels | Daily | 1K–10K records | High |

#### Water Utility Source Systems

| System | Data Type | Frequency | Volume/Day | Priority |
|--------|-----------|-----------|------------|----------|
| AMI Water Meters | Interval consumption (m³/L), reverse flow, tamper events, burst detection | 15-min or hourly | 1M–20M records | Critical |
| SCADA (Distribution) | Pressure zone readings, pump status, reservoir levels, valve positions, chlorine residual | 30s–5min | 200M time-series | Critical |
| SCADA (Treatment Plant) | Raw water turbidity, coagulant dosing, filtration rates, clearwell levels, UV dose | 1-min | 500M records | Critical |
| MDMS (Water) | Validated consumption, district meter readings, bulk supply meters | Hourly | 500K–5M records | High |
| GIS (Network) | Pipe routes, material, diameter, age, valve locations, pressure zone boundaries | Weekly | 2GB–20GB | High |
| WOMS | Repair tickets, burst locations, crew dispatch, pipe replacement jobs | Daily | 10K–100K records | High |
| Laboratory (Water Quality) | E.coli counts, turbidity, pH, chlorine, fluoride, heavy metals, PFAS | Daily | 1K–10K records | Critical |
| EAM / ERP | Asset records, pump maintenance, chemical inventory | Daily | 50K–200K records | High |
| LIMS (Lab Info Mgmt) | Sample tracking, analytical results, regulatory reporting data | Daily | 1K–5K records | High |
| CIS | Customer accounts, connection sizes, meter data, billing | Daily | 10K–200K records | High |
| Wastewater SCADA | Influent flow, DO levels, blower operation, effluent quality, sludge levels | 1-min | 300M records | High |
| Rainfall / Weather | Rainfall intensity, storm events (affects sewer inflow) | 5-min | 50K records | High |
| CCTV Pipe Inspection | Video footage + condition grade annotations | Periodic | 50GB per campaign | Medium |
| Smart Hydrants / PRVs | Pressure readings, flow measurements, transient events | 1-min | 50M records | Medium |

---

### 1.2 Ingestion Technology Selection Guide

| Scenario | Recommended Tool | Why |
|----------|-----------------|-----|
| Real-time SCADA streaming (OPC-UA, Modbus) | Apache NiFi + Apache Kafka | NiFi has native OPC-UA processor; Kafka handles high-throughput time-series |
| AMI meter data (15-min intervals, batch) | Apache NiFi or Airbyte | NiFi for protocol flexibility; Airbyte for MDMS vendor connectors |
| ERP/EAM (SAP, Maximo) JDBC pull | Airbyte | Pre-built connectors for SAP, Oracle, SQL Server |
| CIS/CRM (Salesforce, CC&B, SAP ISU) | Airbyte | Native connectors available |
| IoT sensors (MQTT) | MQTT Broker → Apache Kafka | MQTT is the standard IoT protocol; Kafka buffers and scales |
| Weather APIs (REST) | Apache NiFi InvokeHTTP | Simple REST polling on schedule |
| GIS systems (ESRI, QGIS) | NiFi or custom REST extractor | GIS uses REST APIs or file exports |
| Laboratory results (CSV, LIMS) | Apache NiFi (GetFile / GetSFTP) | Simple file-based ingestion |
| Event-driven (OMS alerts) | Kafka + Kafka Connect | WebSocket or webhook source → Kafka topic |
| Historical backfill (TB-scale) | Apache Spark + Airbyte | Parallel JDBC extraction with partitioning |
| ILI pipe inspection data | Custom Python + NiFi | Vendor-specific formats (ROSEN, GE PII) need custom parsers |
| Change Data Capture (CDC) from RDBMS | Debezium → Kafka | Zero-impact real-time CDC without polling |

---

### 1.3 Full Data Pipeline Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                          SOURCE SYSTEMS                                          │
│  SCADA/RTU  |  AMI/MDMS  |  GIS  |  EAM/ERP  |  CIS/CRM  |  Lab  |  Weather  │
└──────┬──────────────┬──────────────────────────────────────────────────────────┘
       │              │
       ▼              ▼
┌──────────────────────────────────────────────────────────────────┐
│                     INGESTION LAYER                               │
│                                                                   │
│  Real-time Stream          Batch/Micro-batch      Event-driven   │
│  ┌─────────────┐          ┌──────────────┐       ┌───────────┐  │
│  │ Apache Kafka│          │ Apache NiFi  │       │  Debezium │  │
│  │ (streaming) │          │ (ETL/ELT)    │       │  (CDC)    │  │
│  │ MQTT Broker │          │ Airbyte      │       │  Webhooks │  │
│  │ OPC-UA      │          │ (connectors) │       │  Kafka    │  │
│  └──────┬──────┘          └──────┬───────┘       └─────┬─────┘  │
│         └────────────────────────┴──────────────────────┘        │
└──────────────────────────────┬───────────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────────┐
│                    RAW / BRONZE LAYER                             │
│  Immutable, partitioned by source + date, as-is ingestion        │
│  Format: Parquet (batch) + Apache Iceberg (streaming)            │
│  Storage: Data Lake (ADLS Gen2 / S3 / MinIO local)               │
│  Retention: 7–10 years (regulatory requirement)                  │
│  Catalog: Apache Atlas or DataHub (lineage tracking)             │
└──────────────────────────────┬───────────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────────┐
│                  DATA QUALITY LAYER                               │
│                                                                   │
│  Completeness    │ Missing reading detection, gap filling alerts  │
│  Validity        │ Range checks: V∈[200,260], flow∈[0,Qmax]     │
│  Consistency     │ CT ratio validation, meter-DT reconciliation   │
│  Timeliness      │ Arrival within SLA window (e.g. <2hr for AMI) │
│  Uniqueness      │ Deduplication by meter+timestamp key           │
│  Accuracy        │ Cross-validation with reference meters         │
│  Lineage         │ Source system, ingestion timestamp, version    │
│                                                                   │
│  Tools: Great Expectations / Soda Core / dbt tests               │
│  Alerting: PagerDuty / email / N8N workflow on quality failure   │
└──────────────────────────────┬───────────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────────┐
│                   SILVER / CLEANSED LAYER                         │
│  Quality-checked, deduplicated, normalized timestamps (UTC)       │
│  MDM (Master Data Management) applied: canonical asset IDs        │
│  Missing value imputation: forward-fill (operational), ML-fill   │
│  Unit standardization: all energy in kWh, all pressure in bar    │
│  Format: Parquet with Delta Lake / Apache Iceberg for ACID        │
│  Compute: Apache Spark (batch) + Apache Flink (streaming)         │
└──────────────────────────────┬───────────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────────┐
│                    GOLD / CURATED LAYER                           │
│  Business-ready aggregations, pre-joined datasets, KPI tables    │
│                                                                   │
│  Domain Marts:                                                    │
│  • asset_health_mart    (FAA scores, failure probabilities)       │
│  • energy_loss_mart     (AT&C loss, feeder/DTR rankings)         │
│  • theft_detection_mart (anomaly scores, case statuses)          │
│  • customer_360_mart    (consumption profiles, segments)          │
│  • load_forecast_mart   (actuals vs forecast, MAPE rolling)      │
│  • water_quality_mart   (compliance status, parameter trends)     │
│  • finance_mart         (revenue, AR aging, RDSS tracker)        │
│                                                                   │
│  Compute: dbt (transformation) + Apache Spark                     │
│  Scheduling: Apache Airflow or N8N                               │
└──────────────────────────────┬───────────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────────┐
│                    SEMANTIC LAYER                                  │
│  Business metric definitions, role-based access, KPI catalog      │
│                                                                   │
│  Metrics defined once, used everywhere:                           │
│  • AT&C Loss % = (Energy Input - Energy Billed) / Energy Input   │
│  • FAA Factor = Σ(stress_factor × age_weight) per asset           │
│  • NRW % = (System Input Volume - Authorized Consumption) / Input│
│  • SAIDI = Σ(Customers affected × Duration) / Total Customers    │
│  • SAIFI = Σ(Customers interrupted) / Total Customers            │
│  • CAIDI = SAIDI / SAIFI                                          │
│                                                                   │
│  Tools: dbt Semantic Layer / Apache Superset / Cube.dev           │
│  Role mapping: Field Tech < Analyst < Manager < Regulator        │
└──────────────────────────────┬───────────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────────┐
│                   VISUALIZATION LAYER                             │
│                                                                   │
│  Operational    │ Real-time SCADA dashboards, alert queues        │
│  Analytical     │ Trend analysis, cohort comparisons, drill-down │
│  Executive      │ KPI scorecards, rolling averages, RAG status   │
│  Regulatory     │ Auto-formatted compliance reports (PDF/XML)     │
│  Field Mobile   │ Work order app, map-based asset viewer          │
│                                                                   │
│  Tools: Apache Superset (open source) / Power BI / Grafana        │
│         Custom React dashboards (Uniserv frontend)                │
└──────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────────┐
│              AI / LLM LAYER (IntelGrid Copilot)                  │
│                                                                   │
│  NL to SQL     → Query any gold layer table in plain English      │
│  RAG / Wiki    → TOGAF procedures, regulatory docs, field lessons│
│  ML Models     → Domain-specific predictive models               │
│  N8N Workflows → Orchestrate alert → action → feedback loops     │
│  Ollama (Local)→ Privacy-preserving inference for OT data        │
└──────────────────────────────────────────────────────────────────┘
```

---

### 1.4 Data Governance Components

| Component | Purpose | Tool Options |
|-----------|---------|-------------|
| Data Catalog | Discover datasets, understand lineage | Apache Atlas, DataHub, OpenMetadata |
| MDM | Canonical asset/customer IDs across systems | Informatica MDM, custom UUID service |
| Data Lineage | Track data from source to dashboard | OpenLineage, DataHub, Apache Atlas |
| Data Quality | Automated checks with alerting | Great Expectations, Soda Core, dbt tests |
| Data Contracts | Schema versioning between producers & consumers | Protobuf, Avro schema registry |
| Access Control | Role-based data access | Apache Ranger, column-level masking |
| Audit Logging | Who accessed what data and when | Immutable audit log (append-only) |
| Retention Policy | Automatic archival/deletion by data age | Lifecycle policies (S3, ADLS) |
| PII/Sensitivity Tagging | Mark customer data, financial data | DataHub tags, column-level classification |

---

## 2. Power Utility Use-Cases

### 2.1 Currently in Uniserv

| Use-Case | Module | Model/Method | Status |
|----------|--------|-------------|--------|
| Theft / NTL Detection | Theft Detection | ML anomaly + rule-based | Live |
| Load Forecasting | Load Forecasting | LightGBM / custom model | Live |
| Asset Health Scoring | Asset Health | FAA factor calculation | Live |
| Energy Loss Analysis | Energy Loss | AT&C loss computation, feeder ranking | Live |
| Appliance Disaggregation | NILM | LightGBM appliance identification | Live |
| Finance Analytics | Finance Service | SQL aggregations + LLM Q&A | Live |
| Smart Meter Ops | SMOC | gpt-oss-20b advisory + digital twin | Live |

### 2.2 Near-Term Integration Candidates (Power)

#### 2.2.1 Distribution Transformer Failure Prediction
- **Problem:** DTRs fail unexpectedly, causing outages; replacement takes 4-24 hours
- **Data:** FAA factor, load history, ambient temperature, age, oil test results, overload events
- **Model:** Gradient Boosting (failure probability per DTR per 30/60/90 days)
- **Output:** Ranked replacement/inspection priority list with estimated time-to-failure
- **Existing hook:** Asset Health module FAA scores → extend with failure probability
- **TOGAF reference:** Asset & Network Operations → Predictive Maintenance

#### 2.2.2 Feeder / Distribution Automation Optimization
- **Problem:** Fault isolation and supply restoration takes 30-90 min manually
- **Data:** SCADA topology, breaker/switch positions, load flow data
- **Model:** Network optimization + rule engine for FLISR (Fault Location, Isolation, Service Restoration)
- **Output:** Optimal switching sequence to restore maximum customers in minimum time
- **TOGAF reference:** Grid Operations → Outage Management & Restoration

#### 2.2.3 Voltage Optimization (CVR — Conservation Voltage Reduction)
- **Problem:** Utilities can reduce energy consumption 1-3% by lowering voltage within limits without affecting customers
- **Data:** Voltage profiles across feeders, customer load sensitivity, SCADA setpoints
- **Model:** Power flow simulation + ML to predict CVR savings per feeder
- **Output:** Optimal voltage setpoints per substation/feeder with expected energy savings
- **TOGAF reference:** Energy Management → Demand-Side Management

#### 2.2.4 Power Quality Monitoring & Analysis
- **Problem:** Harmonics, voltage sags/swells cause equipment damage and consumer complaints
- **Data:** PQ meter waveform data (THD, flicker, sag/swell events)
- **Model:** Waveform classification (FFT + ML), source identification
- **Output:** PQ event classification, affected customer list, probable source asset
- **TOGAF reference:** Asset & Network Operations → Power Quality Management

#### 2.2.5 EV Load Impact Prediction
- **Problem:** Unmanaged EV charging creates local overloads on LT feeders
- **Data:** EV registration data, charging station telemetry, feeder capacity headroom
- **Model:** Spatial load growth model + EV adoption curve
- **Output:** Feeder upgrade priority list, demand response trigger thresholds
- **TOGAF reference:** Grid Modernization → EV Integration

#### 2.2.6 Solar / DER Impact Analysis
- **Problem:** High solar penetration causes reverse power flows and voltage violations
- **Data:** DER connection data, GIS, solar generation profiles, SCADA voltage
- **Model:** Power flow with DER scenarios, voltage violation probability
- **Output:** DER hosting capacity map per feeder, curtailment recommendations
- **TOGAF reference:** Energy Management → Renewable Integration

#### 2.2.7 Demand Response Management
- **Problem:** Peak demand drives high cost and infrastructure strain
- **Data:** Customer demand profiles, DR program enrollment, weather, price signals
- **Model:** Customer response curve estimation + portfolio optimization
- **Output:** Optimal DR dispatch instructions per event, expected peak reduction
- **TOGAF reference:** Customer Operations → Demand-Side Management

#### 2.2.8 Cable Ampacity & Dynamic Rating
- **Problem:** Static cable ratings are conservative — weather-based dynamic ratings can unlock 20-30% more capacity
- **Data:** Underground cable temperatures (if instrumented), ambient, load current, soil thermal resistivity
- **Model:** IEC 60287 thermal model + real-time recalculation
- **Output:** Real-time ampacity ratings per cable section, overload risk alerts
- **TOGAF reference:** Asset & Network Operations → Network Capacity Management

#### 2.2.9 SAIDI / SAIFI / CAIDI Prediction and Improvement
- **Problem:** Reliability indices are reported reactively; no proactive improvement roadmap
- **Data:** Historical outage records, asset condition, weather, tree trimming logs
- **Model:** Regression on reliability drivers, scenario simulation
- **Output:** Predicted reliability indices by feeder, intervention ROI ranking
- **TOGAF reference:** Asset & Network Operations → Reliability Management

#### 2.2.10 Protection Relay Coordination Audit
- **Problem:** Incorrect relay settings cause cascading trips; manual audits are rare
- **Data:** Relay settings files (IEDs), network topology, fault current calculations
- **Model:** Rule-based coordination check + ML anomaly on settings
- **Output:** Miscoordination alerts with recommended setting corrections
- **TOGAF reference:** Grid Operations → Protection & Control Management

---

## 3. Gas Utility Use-Cases

### 3.1 Currently in Uniserv
- None yet (platform focused on power and water utilities so far)

### 3.2 Integration Candidates (Gas)

#### 3.2.1 Pipeline Integrity Risk Scoring
- **Problem:** 1000s of km of pipeline; prioritizing inspection is manual and subjective
- **Data:** Pipeline age, material, operating pressure, coating condition, soil type (GIS), ILI results, historical failure locations
- **Model:** Multi-factor risk scoring (probability of failure × consequence of failure)
- **Output:** Risk-ranked pipeline segment map, inspection priority queue
- **TOGAF reference:** Asset & Pipeline Integrity → Pipeline Risk Assessment

#### 3.2.2 Leak Detection & Localization
- **Problem:** Gas leaks are life-safety critical; acoustic and methane sensors need intelligent filtering to reduce false alarms
- **Data:** Acoustic sensor waveforms, methane sensor readings, SCADA pressure drops, wind direction
- **Model:** ML event classifier (leak vs. noise vs. third-party damage), localization algorithm
- **Output:** Leak probability + estimated location (within 50-100m), urgency classification
- **TOGAF reference:** Safety & Emergency → Leak Detection & Emergency Response

#### 3.2.3 Corrosion Rate Modeling
- **Problem:** Steel pipelines corrode at different rates depending on soil chemistry, CP effectiveness, coating age
- **Data:** Cathodic protection readings, soil resistivity, ILI wall thickness measurements, historical corrosion rates
- **Model:** Time-series regression on corrosion rate per segment, failure probability curve
- **Output:** Predicted failure year per segment, CP system effectiveness ranking
- **TOGAF reference:** Asset & Pipeline Integrity → Corrosion Management

#### 3.2.4 Gas Demand Forecasting (Weather-Coupled)
- **Problem:** Gas demand is highly weather-sensitive (heating load); poor forecasting wastes linepack and costs penalties
- **Data:** Historical daily send-out, degree days, customer mix (residential vs industrial), economic indicators
- **Model:** LSTM / Prophet with temperature covariates, separate models by season
- **Output:** Day-ahead and week-ahead demand forecast per pressure zone, linepack guidance
- **TOGAF reference:** Gas Supply & Procurement → Demand Forecasting

#### 3.2.5 Compressor Efficiency Optimization
- **Problem:** Compressor stations consume 1-3% of throughput gas as fuel; inefficient operation wastes millions
- **Data:** Compressor curves, suction/discharge pressures, flow rates, fuel gas consumption, ambient temperature
- **Model:** Thermodynamic efficiency model + genetic algorithm for dispatch optimization
- **Output:** Optimal compressor run/stop schedule, expected fuel savings per station
- **TOGAF reference:** Transmission & High-Pressure Operations → Compressor Station Management

#### 3.2.6 Gas Quality Monitoring & BTU Management
- **Problem:** Gas quality varies by source; consumers with BTU-sensitive equipment need consistent quality
- **Data:** Chromatograph results (BTU, Wobbe index, H2S, CO2, C2+), blending ratios
- **Model:** Real-time quality prediction at delivery points given source blending
- **Output:** BTU compliance alerts, optimal blending recommendations
- **TOGAF reference:** Gas Supply & Procurement → Gas Quality Management

#### 3.2.7 Odorization Level Optimization
- **Problem:** Under-odorization is a safety violation; over-odorization wastes expensive odorant
- **Data:** Odorizer injection rates, pipeline flow, test point odor readings (ppm), temperature (evaporation rate)
- **Model:** Dispersion model calibrated to field measurements
- **Output:** Optimal injection rate per odorizer station, compliance gap alerts
- **TOGAF reference:** Safety & Emergency → Odorization Management

#### 3.2.8 Non-Technical Loss (Gas Theft) Detection
- **Problem:** Gas theft exists but is harder to detect than electrical theft; unaccounted-for-gas can be 2-8%
- **Data:** Meter readings, pressure surveys, SCADA balance, delivery/offtake comparison
- **Model:** Mass balance anomaly detection by pressure zone, consumer-level pattern analysis
- **Output:** Suspect meter list ranked by theft probability, reconciliation dashboard
- **TOGAF reference:** Distribution Network → Network Loss Management

---

## 4. Water Utility Use-Cases

### 4.1 Currently in Uniserv
| Use-Case | Module | Status |
|----------|--------|--------|
| Water Distribution Digital Twin | Digital Twin | Live (basic) |

### 4.2 Integration Candidates (Water)

#### 4.2.1 Non-Revenue Water (NRW) Analytics
- **Problem:** NRW of 20-40% is common; finding where water is lost requires district metering analysis
- **Data:** District Meter Area (DMA) flow balances, pressure readings, customer meter data, pipe age/material
- **Model:** Water balance calculation, ML burst prediction, step-test localization
- **Output:** NRW % by DMA, priority DMAs for active leakage control, burst probability per pipe segment
- **TOGAF reference:** Distribution Network → NRW Control & Leakage Management

#### 4.2.2 Water Quality Compliance Monitoring
- **Problem:** E.coli, turbidity, chlorine residual must stay within limits 24/7; reactive detection risks public health
- **Data:** Online turbidity sensors, chlorine analyzers, pH probes, lab results (E.coli, metals, PFAS)
- **Model:** Statistical process control (SPC) on sensor streams, ML forecasting of residual chlorine decay
- **Output:** Real-time compliance status, predicted compliance breach (hours ahead), automatic sample trigger alerts
- **TOGAF reference:** Water Source & Treatment → Water Quality Management

#### 4.2.3 Burst Detection & Pipe Failure Prediction
- **Problem:** Pipe bursts cause property damage, boil-water notices, and NRW spikes
- **Data:** Pressure transient sensors, flow meters, acoustic loggers, pipe material/age/diameter, soil data, historical burst records
- **Model:** Transient analysis for burst detection (minutes), statistical pipe failure prediction model (months)
- **Output:** Real-time burst alerts with GPS location estimate, ranked replacement priority list
- **TOGAF reference:** Distribution Network → Infrastructure Resilience & Pipe Integrity

#### 4.2.4 Pump Scheduling Optimization
- **Problem:** Pumping is 60-70% of a water utility's energy cost; off-peak pumping is cheaper but requires storage
- **Data:** Reservoir levels, pump curves, energy tariff schedules (ToU), demand forecast, pump health
- **Model:** Mixed-integer linear programming (MILP) with tariff and demand constraints
- **Output:** Optimal pump on/off schedule for next 24-48 hours, expected energy cost vs baseline
- **TOGAF reference:** Distribution Network → Energy Efficiency & Pump Management

#### 4.2.5 Treatment Plant Process Optimization (Coagulation / Chlorination)
- **Problem:** Chemical dosing is often operator-tuned and wasteful; raw water variability requires constant adjustment
- **Data:** Jar test results, raw water turbidity/pH/alkalinity/temperature, settled water turbidity, coagulant dose rates
- **Model:** ML model (raw water characteristics → optimal coagulant dose), PID loop enhancement
- **Output:** Real-time coagulant dose recommendation, predicted settled turbidity, chemical cost savings
- **TOGAF reference:** Water Source & Treatment → Treatment Process Optimization

#### 4.2.6 Water Demand Forecasting
- **Problem:** Over-production wastes energy; under-production risks pressure failures
- **Data:** Historical demand, weather (temperature, rainfall), population data, day-of-week, seasonal patterns
- **Model:** SARIMA / Prophet / LSTM with weather covariates, per-zone models
- **Output:** 24-hour and 7-day demand forecast per pressure zone, production scheduling guidance
- **TOGAF reference:** Distribution Network → Demand Management & Forecasting

#### 4.2.7 Wastewater Influent Prediction
- **Problem:** Sudden influent spikes overwhelm treatment capacity; predictive warning improves process stability
- **Data:** Rainfall intensity, historical influent flow patterns, sewer level sensors, industrial discharge notifications
- **Model:** Rainfall-to-runoff model + ML influent predictor (3-6 hour ahead)
- **Output:** Predicted influent flow and load (BOD, TSS) with confidence interval, blower pre-start alerts
- **TOGAF reference:** Wastewater & Environmental → WWTP Operations

#### 4.2.8 Drought Risk & Water Security Planning
- **Problem:** Multi-year drought stress requires scenario planning for supply restrictions
- **Data:** Reservoir storage curves, groundwater levels, rainfall forecasts (seasonal), demand trajectory
- **Model:** Mass balance simulation with ensemble weather scenarios, supply/demand gap modeling
- **Output:** Days of supply remaining under each scenario, trigger points for restriction levels
- **TOGAF reference:** Water Source & Treatment → Water Source Security & Resilience

---

## 5. Cross-Utility Horizontal Use-Cases

These apply to Power AND Gas AND Water utilities.

### 5.1 Asset Failure → Field Action Intelligence Pipeline (N8N + LLM Wiki)
**[The selected prototype problem — see main plan file]**
- ML alert → TOGAF procedure lookup → structured work order → field feedback → wiki learning
- Applicable to: transformer failures (power), pipeline integrity (gas), pump failures (water)

### 5.2 Regulatory Compliance Intelligence
- **Problem:** Utilities must file hundreds of reports annually; content comes from multiple systems
- **Data:** SCADA data, lab results, billing data, asset records
- **N8N role:** Scheduled workflow to auto-collect, aggregate, and pre-format regulatory reports
- **LLM Wiki role:** Regulatory document wiki (CERC, MoEF, NERC, EPA, BIS standards) → natural language Q&A
- **Output:** Auto-drafted regulatory reports, compliance gap alerts, Q&A on regulations
- **TOGAF reference:** Regulatory & Compliance → Regulatory Reporting

### 5.3 Work Order Lifecycle Management
- **Problem:** Work orders are created in EAM but field execution, outcome, and lessons learned are siloed
- **Data:** Work order data (EAM/Maximo), GPS field logs, completion photos, technician notes
- **N8N role:** Orchestrate WO creation → assignment → field update → closure → feedback capture
- **LLM role:** Auto-summarize completion notes, extract lessons, classify failure modes
- **Output:** Closed-loop work order with linked field lesson, mean-time-to-repair analytics
- **TOGAF reference:** Asset & Network Operations → Work Order Management

### 5.4 Consumer 360 — Unified Customer Intelligence
- **Problem:** Customer data is fragmented across billing, CRM, meter, complaint, and field systems
- **Data:** Billing history, consumption profile, service requests, complaints, demographics, credit score (if available), channel preferences
- **Model:** Customer segmentation (clustering), churn prediction, credit risk, electrification propensity
- **Output:** Single customer view, action queue for each segment (e.g., "126 high-value customers at churn risk — offer solar net metering")
- **TOGAF reference:** Customer Operations → Customer Lifecycle Management

### 5.5 Field Crew Optimization
- **Problem:** Field crew routing and scheduling is manual; priority conflicts cause SLA breaches
- **Data:** Work order locations (GIS), crew locations (GPS), skill matrices, vehicle availability, parts inventory
- **Model:** Vehicle routing problem (VRP) solver, priority-weighted scheduling
- **Output:** Optimized daily route for each crew, ETA predictions, SLA breach early warning
- **TOGAF reference:** Workforce Management → Field Force Management

### 5.6 Predictive Spare Parts Management
- **Problem:** Critical spares are either over-stocked (capital tied up) or under-stocked (extended outages during failures)
- **Data:** Asset failure predictions, historical spare consumption, lead times, criticality ratings
- **Model:** Multi-echelon inventory optimization tied to asset failure probabilities
- **Output:** Optimal reorder quantities per spare, urgent procurement alerts when failure risk rises
- **TOGAF reference:** Asset & Network Operations → Asset Lifecycle Management

### 5.7 Sustainability & ESG Analytics
- **Problem:** ESG reporting is manual, inconsistent, and covers only a subset of true environmental impact
- **Data:** Energy consumption (Scope 1/2/3), water consumption, chemical usage, fleet fuel, waste data
- **Model:** Emissions factor calculation, trend forecasting, benchmark comparison
- **Output:** Automated ESG dashboard (GHG emissions, water intensity, waste diversion rate), regulatory disclosure drafts
- **TOGAF reference:** Environmental Stewardship → Sustainability Management

### 5.8 Revenue Assurance & AT&C Loss Tracker
- **Problem:** AT&C loss (Aggregate Technical & Commercial) is the primary financial KPI; root causes span multiple systems
- **Data:** Energy input (SCADA), energy billed (billing), energy collected (payments), theft cases, metering errors
- **Formula:** AT&C Loss% = (1 - Collection Efficiency × (1 - Distribution Loss%)) × 100
- **Model:** Loss decomposition (technical vs commercial vs collection), feeder-wise attribution
- **Output:** Real-time AT&C loss dashboard, loss reduction action plan ranked by ROI
- **TOGAF reference:** Financial Management → Revenue Assurance & AT&C Loss Reduction

---

## 6. Business Process & Workflow Automation

### 6.1 N8N Workflow Catalog (Planned)

| Workflow | Trigger | Steps | Output |
|----------|---------|-------|--------|
| Asset Alert → Work Order | ML alert exceeds threshold | Classify → Wiki lookup → Draft WO → Assign crew | Structured work order in EAM |
| Negative Feedback → Wiki Update | 👎 feedback submitted | Extract lesson → Embed → Store in ChromaDB | Updated knowledge base |
| Regulatory Report Auto-Draft | Monthly cron | Collect data → Aggregate → LLM draft → Review queue | Draft report PDF |
| New Customer Onboarding | CIS new connection event | Verify → Credit check → Schedule meter installation → Welcome comms | Onboarding work order + comms |
| High-Value Customer At-Risk Alert | Churn model score > 0.7 | Customer 360 lookup → Draft retention offer → Route to CSR | CSR action queue item |
| Emergency Leak Response | LDAR sensor + SCADA pressure drop | Classify urgency → Isolate valve (if auto) → Dispatch crew → Notify regulator | Emergency work order + notification |
| Meter Tampering Response | Smart meter tamper event + ML confirmation | Alert → Evidence package → Legal workflow → Field inspection | Tampering case file |
| Outage Notification | OMS outage confirmed | Customer count → SMS/IVR blast → Estimate restoration → Update status page | Customer notifications |
| Planned Maintenance Communication | Work order scheduled 7 days ahead | Customer list → Personalized notifications → Confirmation tracking | Communication audit trail |
| Quality Failure Alert | Lab result out of spec | Notify ops → Check nearby sample points → Draft regulatory notification | Alert chain + regulatory draft |

### 6.2 Process Automation Maturity Model

| Level | Description | Examples |
|-------|-------------|---------|
| L1 — Data Collection | Automated data gathering, no decisions | AMI data ingestion, SCADA archival |
| L2 — Alerting | Threshold-based notifications | Overload alerts, quality breach SMS |
| L3 — Recommendation | AI suggests action, human decides | Work order draft, optimal dose recommendation |
| L4 — Assisted Execution | AI prepares, human approves with one click | Pre-filled regulatory report, pre-routed work order |
| L5 — Autonomous Execution | AI decides and acts within defined guardrails | Auto-restore switching (FLISR), auto-dispatch for P1 leaks |

---

## 7. LLM & AI Integration Patterns

### 7.1 Pattern 1: NL to SQL (Existing in Uniserv)
- User types natural language query → LLM generates SQL → executes against gold layer → returns structured result
- **Enhancement:** Add query validation layer (N8N) to catch dangerous queries before execution
- **Enhancement:** Add result explainer (LLM narrates the numbers in plain English)

### 7.2 Pattern 2: RAG over Domain Wiki (Prototype)
- TOGAF HTML files + regulatory documents + field lessons → ChromaDB
- Query → embedding → semantic search → LLM with retrieved context → grounded answer
- **Key advantage:** Zero hallucination on procedures because the LLM cites its source chunks

### 7.3 Pattern 3: Multi-Agent Orchestration (Future)
```
User Query: "Why is AT&C loss high on Feeder F-07 this month?"
     ↓
Router Agent (qwen3:0.6b — fast intent classification)
     ├── SQL Agent → query energy_loss_mart for F-07 loss trend
     ├── Wiki Agent → retrieve feeder maintenance history from wiki
     ├── Anomaly Agent → check if any theft cases on F-07 this month
     └── Synthesis Agent (larger model) → combine all findings into coherent explanation
```

### 7.4 Pattern 4: Feedback-Driven Self-Improvement (Prototype)
- Negative feedback → LLM extracts lesson → append to ChromaDB as new chunk
- Future similar queries retrieve the lesson alongside base TOGAF content
- **No model retraining required** — purely retrieval augmentation
- **Measurable:** Track "queries that hit field lesson chunks" as a KPI

### 7.5 Pattern 5: Document Intelligence (Future)
- Upload regulatory circular / vendor manual / maintenance bulletin
- LLM extracts key provisions, updates wiki, tags affected assets/processes
- Field engineer can query: "What changed in the latest CERC order about metering accuracy?"

### 7.6 Pattern 6: Voice-to-Work-Order (Future)
- Field engineer speaks notes into mobile → STT transcription → LLM structures into work order update
- Closes the digital literacy gap for rural field staff
- Language support: Hindi, Marathi, Tamil, Telugu (multilingual Ollama models)

---

## 8. Regulatory & Compliance Coverage

### 8.1 Power Utility Regulations (India)

| Regulation | Area | Reporting Frequency | Data Required |
|------------|------|--------------------|-|
| CERC Metering Standards | Meter accuracy, data transmission | On installation + annual | Meter test certificates, MDMS data |
| State SERC Orders | Tariff, supply standards, consumer rights | As mandated | Billing data, outage records |
| RDSS (Revamped Distribution Sector Scheme) | AT&C loss reduction, smart metering | Monthly/quarterly | AT&C loss, metering %age, feeder data |
| BIS IS 16444 | Smart meter standards | On installation | Meter type, firmware version |
| NERC (International) | Grid reliability, cybersecurity | Ongoing + incident reporting | SCADA events, protection settings |
| IEC 61968/61970 (CIM) | Interoperability standards | N/A (design-time) | Network model data |

### 8.2 Water Utility Regulations (India)

| Regulation | Area | Reporting |
|------------|------|-----------|
| BIS 10500 | Drinking water quality standards | Daily / on-event |
| Environment Protection Act | Effluent discharge standards | Monthly + incident |
| CPCB Guidelines | Wastewater quality | Quarterly |
| State Water Authority Regulations | Supply standards, NRW targets | Annual |

### 8.3 Gas Utility Regulations (India)

| Regulation | Area | Reporting |
|------------|------|-----------|
| PNGRB (Pipeline & Natural Gas Regulatory Board) | Pipeline safety, authorization | Annual + incident |
| Oil Mines Regulations | Well safety, pressure testing | Ongoing |
| BIS Standards for CNG / PNG | Gas quality at delivery point | Monthly |
| OISD Guidelines | Operational safety for gas facilities | Annual safety audit |

---

## 9. Customer-Facing Use-Cases

### 9.1 Self-Service Portal Intelligence
- **Chatbot for bill enquiry:** NL query → NL-to-SQL on billing mart → plain English answer
- **Outage self-reporting:** Customer reports outage → geo-clustered with nearby reports → OMS integration
- **Connection request tracking:** Status of new connection / meter upgrade / load enhancement application
- **Energy audit tool:** Consumer inputs appliance list → NILM-style consumption breakdown → energy saving tips

### 9.2 Proactive Customer Communications
- **Planned outage notifications:** Auto-generated, personalized, multilingual
- **High bill alert:** Usage spike detected → proactive alert with consumption breakdown
- **Leak alert (water):** AMI detects continuous flow at unusual hour → SMS alert ("possible leak at your property")
- **Payment reminder:** AR aging model identifies at-risk accounts → personalized reminder

### 9.3 Consumer Insight Products (B2B2C)
- **Energy benchmarking:** "Your consumption is 23% higher than similar homes in your area"
- **Time-of-use optimization:** "Shifting your heavy appliances to off-peak saves ₹240/month"
- **Solar suitability score:** Based on rooftop area (GIS), solar irradiance, consumption profile
- **Water efficiency score (water utility):** Household water use vs neighborhood benchmark

---

## 10. Future Roadmap Candidates

### 10.1 High Impact, Medium Effort
| Use-Case | Impact | Effort | Utility |
|----------|--------|--------|---------|
| Automated regulatory report drafting | High | Medium | All |
| Field crew route optimization | High | Medium | All |
| Multilingual voice-to-work-order | High | Medium | All |
| Pipeline integrity risk map | High | Medium | Gas |
| Water quality early warning | High | Medium | Water |

### 10.2 High Impact, High Effort
| Use-Case | Impact | Effort | Utility |
|----------|--------|--------|---------|
| Distribution FLISR (auto-restore) | Very High | High | Power |
| Multi-agent Q&A orchestration | High | High | All |
| ILI data ingestion & ML analysis | High | High | Gas |
| CCTV pipe condition AI (Computer Vision) | High | High | Water |
| DER hosting capacity map | High | High | Power |

### 10.3 Emerging Technology Integration
| Technology | Utility Application | Timeline |
|------------|--------------------|-|
| Digital Twin (real-time) | Live network simulation for what-if scenarios | 2-3 years |
| Edge AI (on-device inference) | Local anomaly detection on smart meters/RTUs | 2-3 years |
| Federated Learning | Cross-utility model training without sharing raw data | 3-5 years |
| Quantum Optimization | Large-scale network optimization (transmission planning) | 5+ years |
| Blockchain for Energy Trading | P2P energy markets between prosumers | 3-5 years |
| AR for Field Engineers | Overlay asset data on physical equipment via headset | 2-3 years |

---

## Appendix A: Data Dictionary (Key Metrics)

| Metric | Formula | Unit | Source |
|--------|---------|------|--------|
| AT&C Loss | (1 - CE × (1 - DL%)) × 100 | % | SCADA + Billing |
| SAIDI | Σ(Ci × Di) / CT | Minutes | OMS |
| SAIFI | Σ(Ci) / CT | Interruptions | OMS |
| CAIDI | SAIDI / SAIFI | Minutes/interruption | OMS |
| FAA Factor | Σ(stress_factor_i × weight_i) | Dimensionless | EAM + SCADA |
| NRW % | (Input - Authorized) / Input × 100 | % | DMA meters |
| Daily MAPE | Σ|Actual-Forecast|/Actual / N × 100 | % | MDMS + Forecast |
| Pipeline Risk Score | PoF × CoF | Index (0-100) | GIS + ILI + History |
| BTU Content | Gas chromatograph weighted average | BTU/scf | Lab/Chromatograph |
| Chlorine Residual | Online analyzer reading | mg/L | SCADA water quality |

---

## Appendix B: Technology Stack Summary

| Layer | Open Source Options | Enterprise Options |
|-------|--------------------|-|
| Streaming Ingestion | Apache Kafka, Apache Flink | AWS Kinesis, Azure Event Hubs |
| Batch Ingestion | Apache NiFi, Airbyte | Informatica, Talend |
| Raw/Bronze Storage | MinIO + Parquet + Iceberg | ADLS Gen2, S3 |
| Transformation | Apache Spark, dbt | Databricks, Snowflake |
| Data Quality | Great Expectations, Soda Core | Collibra, Ataccama |
| Data Catalog | Apache Atlas, DataHub | Collibra, Alation |
| Orchestration | Apache Airflow, N8N | Azure Data Factory |
| Semantic Layer | dbt Semantic Layer, Cube.dev | AtScale, Kyvos |
| Visualization | Apache Superset, Grafana | Power BI, Tableau |
| ML Platform | MLflow + custom serving | Azure ML, Vertex AI |
| LLM Inference | Ollama (local), vLLM | Azure OpenAI, Bedrock |
| Vector DB | ChromaDB, Qdrant, Weaviate | Pinecone, Azure AI Search |
| Workflow Automation | N8N | Power Automate, Zapier |

---

*Last updated: May 2026 | Maintained by: IntelGrid / Esyasoft*
*Cross-reference: power-utility-enterprise-architecture-togaf.html, gas-utility-ea-togaf.html, water-utility-ea-togaf.html*
