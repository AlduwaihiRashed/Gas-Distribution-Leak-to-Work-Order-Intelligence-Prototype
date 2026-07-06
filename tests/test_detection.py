"""
M3 detection tests — Part D positive/negative/routing cases.

Runs the real batch pipeline (detect_anomalies.run_pipeline) against the
actual synthetic dataset — the ground-truth labels (leak / sensor_drift /
operational_swing / pressure_anomaly / noise_spike) are already in the CSV,
so this asserts against real data, not a hand-built toy case.
"""

import pandas as pd
import pytest

import detect_anomalies as det


@pytest.fixture(scope="module")
def detection_result(synthetic_telemetry_csv):
    incidents, eval_report, _ = det.run_pipeline(
        csv_path=synthetic_telemetry_csv,
        output_dir="/tmp/l2wo_test_detection_output",
        cfg=det.CFG,
        run_if=False,
        verbose=False,
    )
    return incidents, eval_report


class TestPositiveAndNegativeCases:
    def test_recall_meets_blueprint_target(self, detection_result):
        """Blueprint A.5 / CLAUDE.md: >=90% recall on Grade-1-eligible leak scenarios."""
        _, eval_report = detection_result
        assert eval_report["recall"] >= 0.90

    def test_zero_false_positives_on_trap_cases(self, detection_result):
        """Negative/trap cases (sensor_drift, operational_swing/pressure_anomaly routed
        correctly as hydraulic checks not leaks, noise_spike) must never fire a leak
        incident — this is the whole point of the persistence + magnitude thresholds."""
        _, eval_report = detection_result
        assert eval_report["false_positives"] == 0
        assert eval_report["fp_by_event_type"]["sensor_drift"] == 0
        assert eval_report["fp_by_event_type"]["noise_spike"] == 0

    def test_no_missed_leaks(self, detection_result):
        _, eval_report = detection_result
        assert eval_report["false_negatives"] == 0


class TestORRouting:
    """Blueprint B.2[1] / R1: OR-routing, not AND — single validated signal still fires,
    two corroborating signals escalate."""

    def test_pressure_only_routes_to_hydraulic_check_not_leak(self, detection_result):
        incidents, eval_report = detection_result
        assert eval_report["correct_hydraulic_checks"] > 0
        hydraulic_incidents = [i for i in incidents if i["detected_route"] == "hydraulic_check"]
        assert len(hydraulic_incidents) > 0
        for inc in hydraulic_incidents:
            assert "pressure" in inc["detected_trigger"]
            assert "methane" not in inc["detected_trigger"]
            assert "acoustic" not in inc["detected_trigger"]

    def test_gas_only_routes_to_inspection(self, detection_result):
        incidents, _ = detection_result
        inspection = [i for i in incidents if i["detected_route"] == "inspection"]
        assert len(inspection) > 0
        for inc in inspection:
            assert inc["detected_trigger"] in ("methane", "acoustic", "methane+acoustic")

    def test_both_signals_escalate(self, detection_result):
        incidents, _ = detection_result
        escalations = [i for i in incidents if i["detected_route"] == "escalation"]
        assert len(escalations) > 0
        for inc in escalations:
            assert "pressure" in inc["detected_trigger"]
            assert ("methane" in inc["detected_trigger"] or "acoustic" in inc["detected_trigger"])


class TestPersistenceWindow:
    """A single noisy sample must not fire an incident — only sustained anomalies."""

    def _make_segment_df(self, methane_values, cfg):
        base = {
            "segment_id": "SEG-UNIT", "material": "PE", "install_year": 2000,
            "MAOP_bar": 4.0, "location_class": 1, "hca_flag": False,
            "distance_to_building_m": 100.0, "confinement": "open_row",
            "surface_capping_type": "soil", "pressure_bar": 4.0, "flow_scm_h": 10.0,
            "acoustic_index": 0.05,
        }
        rows = []
        for i, m in enumerate(methane_values):
            rows.append({**base, "timestamp_utc": pd.Timestamp("2026-01-01") + pd.Timedelta(minutes=i), "methane_pct_lel": m})
        return pd.DataFrame(rows)

    def test_single_spike_below_persistence_does_not_fire(self):
        cfg = dict(det.CFG)
        seg = self._make_segment_df([2.0, 2.0, 15.0, 2.0, 2.0], cfg)
        routed = det.compute_routes(seg, cfg)
        assert (routed["detected_route"] == "normal").all(), "a single noisy sample above threshold must not fire an incident"

    def test_sustained_anomaly_fires_at_persistence_n(self):
        cfg = dict(det.CFG)
        n = cfg["persistence_n"]
        seg = self._make_segment_df([2.0, 2.0] + [15.0] * n, cfg)
        routed = det.compute_routes(seg, cfg)
        assert routed.iloc[-1]["detected_route"] != "normal"
        # the (n-1)th anomalous sample should NOT yet have fired
        assert routed.iloc[len(routed) - 2]["detected_route"] == "normal"
