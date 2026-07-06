/*
 * L2WO benchtop node firmware — ESP32, per segment.
 *
 * STATUS: written to match the documented API/MQTT contract in
 * docs/hardware-implementation-guide.md, but NOT tested on physical
 * hardware — no ESP32 board is attached to the dev environment this was
 * written in. src/simulate_esp32.py stands in for this firmware in all
 * software testing done so far.
 *
 * OWNERSHIP: this is a starting draft for Mohammed (hardware/electrical)
 * and Bilal to compile, flash, calibrate, and finalize on the bench — not
 * a validated artifact. Every TODO below (sensor calibration curves, NTP
 * timestamping) is a placeholder specifically left for that review, not
 * an oversight.
 *
 * Responsibilities:
 *   1. Sample methane/pressure/acoustic sensors, POST each reading to the
 *      API's /telemetry/ingest (HTTP — telemetry is not latency-critical).
 *   2. Subscribe to l2wo/{SEGMENT_ID}/isolate (MQTT, retained) and, on an
 *      isolate command, drive the relay/servo modeling the shutoff valve
 *      AND the independent alarm/beacon circuit.
 *   3. Publish the *actual resulting* actuator state to
 *      l2wo/{SEGMENT_ID}/actuator_state — only after the relay/servo has
 *      physically moved, not on command receipt. This confirmation is
 *      what closes the loop (see CLAUDE.md's Architecture section).
 *
 * Fail-safe: on WiFi/MQTT disconnect, the relay defaults to ISOLATED
 * (fail toward the safe state), matching standard ESD valve convention —
 * loss of signal must not be indistinguishable from "safe."
 */

#include <WiFi.h>
#include <PubSubClient.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>

// ---- Per-node configuration (fill in per segment) ----
const char* WIFI_SSID     = "CHANGE_ME";
const char* WIFI_PASSWORD = "CHANGE_ME";
const char* API_HOST      = "http://CHANGE_ME:8000";     // host.containers.internal equivalent on the LAN
const char* MQTT_HOST     = "CHANGE_ME";
const uint16_t MQTT_PORT  = 1883;
const char* SEGMENT_ID    = "SEG-001";                     // matches synthetic_telemetry.csv segment ids

// Static segment metadata — sent with every reading per the API contract
// (docs/hardware-implementation-guide.md §4); pull real values from asset
// records for a live segment.
const char* MATERIAL             = "PE";
const int   INSTALL_YEAR         = 2008;
const float MAOP_BAR             = 4.0;
const int   LOCATION_CLASS       = 3;
const bool  HCA_FLAG             = true;
const float DISTANCE_TO_BUILDING = 8.0;
const char* CONFINEMENT          = "below_pavement";
const char* SURFACE_CAPPING      = "asphalt";

// ---- Pins ----
const int PIN_METHANE_ADC  = 34;
const int PIN_PRESSURE_ADC = 35;
const int PIN_ACOUSTIC_ADC = 32;
const int PIN_RELAY_VALVE  = 25;   // drives the relay/servo modeling the shutoff valve
const int PIN_ALARM_BUZZER = 26;   // independent circuit from the relay above, on purpose
const int PIN_ALARM_LED    = 27;

const unsigned long SAMPLE_INTERVAL_MS = 1000;

WiFiClient wifiClient;
PubSubClient mqtt(wifiClient);
unsigned long lastSampleAt = 0;

// ---------------------------------------------------------------------
// Fail-safe: default the valve-model relay to ISOLATED whenever we don't
// have a live, connected state to prove otherwise.
// ---------------------------------------------------------------------
void setValveIsolated(bool isolated) {
  digitalWrite(PIN_RELAY_VALVE, isolated ? HIGH : LOW);
}

void setAlarm(bool on) {
  digitalWrite(PIN_ALARM_BUZZER, on ? HIGH : LOW);
  digitalWrite(PIN_ALARM_LED, on ? HIGH : LOW);
}

// ---------------------------------------------------------------------
// MQTT: isolate command in, confirmed state out
// ---------------------------------------------------------------------
void publishActuatorState(const char* incidentId, const char* state) {
  StaticJsonDocument<256> doc;
  doc["incident_id"] = incidentId;
  doc["segment_id"] = SEGMENT_ID;
  doc["state"] = state;
  // NOTE: real firmware should stamp a synced time (NTP); left as a
  // placeholder here since untested.
  doc["at"] = "TODO_NTP_TIMESTAMP";

  char payload[256];
  serializeJson(doc, payload);

  char topic[64];
  snprintf(topic, sizeof(topic), "l2wo/%s/actuator_state", SEGMENT_ID);
  mqtt.publish(topic, payload, false);
}

void onMqttMessage(char* topic, byte* payload, unsigned int length) {
  StaticJsonDocument<256> doc;
  DeserializationError err = deserializeJson(doc, payload, length);
  if (err) return;

  const char* incidentId = doc["incident_id"] | "";

  // Drive both outputs — independent circuits, so a fault in one doesn't
  // silence the other (docs/hardware-implementation-guide.md §5).
  setValveIsolated(true);
  setAlarm(true);

  // Only confirm AFTER physically actuating, not on command receipt —
  // this is what makes the loop closed rather than fire-and-forget.
  publishActuatorState(incidentId, "isolated");
}

void connectMqtt() {
  char topic[64];
  snprintf(topic, sizeof(topic), "l2wo/%s/isolate", SEGMENT_ID);

  while (!mqtt.connected()) {
    if (mqtt.connect(SEGMENT_ID)) {
      mqtt.subscribe(topic, 1);
    } else {
      delay(1000);
    }
  }
}

// ---------------------------------------------------------------------
// HTTP: routine telemetry (not latency-critical, unlike the MQTT path above)
// ---------------------------------------------------------------------
void postTelemetry(float pressureBar, float methanePctLel, float acousticIndex) {
  HTTPClient http;
  http.begin(String(API_HOST) + "/telemetry/ingest");
  http.addHeader("Content-Type", "application/json");

  StaticJsonDocument<512> doc;
  doc["timestamp_utc"] = "TODO_NTP_TIMESTAMP";
  doc["segment_id"] = SEGMENT_ID;
  doc["material"] = MATERIAL;
  doc["install_year"] = INSTALL_YEAR;
  doc["MAOP_bar"] = MAOP_BAR;
  doc["location_class"] = LOCATION_CLASS;
  doc["hca_flag"] = HCA_FLAG;
  doc["distance_to_building_m"] = DISTANCE_TO_BUILDING;
  doc["confinement"] = CONFINEMENT;
  doc["surface_capping_type"] = SURFACE_CAPPING;
  doc["pressure_bar"] = pressureBar;
  doc["methane_pct_lel"] = methanePctLel;
  doc["acoustic_index"] = acousticIndex;

  String body;
  serializeJson(doc, body);
  http.POST(body);
  http.end();
}

float readMethanePctLel() {
  int raw = analogRead(PIN_METHANE_ADC);
  return (raw / 4095.0) * 100.0;  // TODO: real sensor calibration curve, not a linear placeholder
}

float readPressureBar() {
  int raw = analogRead(PIN_PRESSURE_ADC);
  return (raw / 4095.0) * 10.0;   // TODO: real transducer calibration
}

float readAcousticIndex() {
  int raw = analogRead(PIN_ACOUSTIC_ADC);
  return raw / 4095.0;            // TODO: real envelope/RMS processing, not a raw sample
}

void setup() {
  pinMode(PIN_RELAY_VALVE, OUTPUT);
  pinMode(PIN_ALARM_BUZZER, OUTPUT);
  pinMode(PIN_ALARM_LED, OUTPUT);
  setValveIsolated(true);  // fail-safe default until we prove we're connected and normal
  setAlarm(false);

  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  while (WiFi.status() != WL_CONNECTED) delay(500);

  setValveIsolated(false); // connected — release to normal open position

  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  mqtt.setCallback(onMqttMessage);
  connectMqtt();
}

void loop() {
  if (!mqtt.connected()) {
    setValveIsolated(true);  // fail-safe: lost the command channel -> isolate
    connectMqtt();
  }
  mqtt.loop();

  if (millis() - lastSampleAt >= SAMPLE_INTERVAL_MS) {
    lastSampleAt = millis();
    postTelemetry(readPressureBar(), readMethanePctLel(), readAcousticIndex());
  }
}
