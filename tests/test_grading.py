"""
M4 grading tests — Part D positive cases + the grading-fidelity case.
"""

import copy

import grade_leak as grader


class TestGradeAssignment:
    def test_escalation_route_is_always_grade_1(self, grade1_incident):
        grade, rule = grader.grade_incident(grade1_incident, grader.CFG)
        assert grade == 1
        assert "escalation" in rule.lower() or "immediate" in rule.lower()

    def test_hydraulic_check_has_no_grade(self):
        inc = {"detected_route": "hydraulic_check", "segment_meta": {}}
        grade, rule = grader.grade_incident(inc, grader.CFG)
        assert grade is None

    def test_unpaved_far_low_concentration_is_grade_3(self, grade3_incident):
        grade, _ = grader.grade_incident(grade3_incident, grader.CFG)
        assert grade == 3

    def test_unpaved_near_building_escalates_to_grade_2(self, grade3_incident):
        inc = copy.deepcopy(grade3_incident)
        inc["segment_meta"]["distance_to_building_m"] = 5.0  # within building_proximity_m threshold
        grade, _ = grader.grade_incident(inc, grader.CFG)
        assert grade == 2


class TestGradingFidelity:
    """Part D's explicit fidelity case: an IDENTICAL leak differing only by
    surface_capping_type must yield Grade 3 (soil) vs Grade 1 (asphalt) —
    this is the whole reason surface_capping_type is a first-class grading
    input (blueprint B.2[2])."""

    def test_soil_vs_asphalt_same_leak_different_grade(self, grade3_incident):
        soil_inc = copy.deepcopy(grade3_incident)
        soil_inc["segment_meta"]["surface_capping_type"] = "soil"

        asphalt_inc = copy.deepcopy(grade3_incident)
        asphalt_inc["segment_meta"]["surface_capping_type"] = "asphalt"

        soil_grade, _ = grader.grade_incident(soil_inc, grader.CFG)
        asphalt_grade, _ = grader.grade_incident(asphalt_inc, grader.CFG)

        assert soil_grade == 3
        assert asphalt_grade == 1
        assert soil_grade != asphalt_grade

    def test_concrete_capping_also_forces_grade_1(self, grade3_incident):
        inc = copy.deepcopy(grade3_incident)
        inc["segment_meta"]["surface_capping_type"] = "concrete"
        grade, _ = grader.grade_incident(inc, grader.CFG)
        assert grade == 1

    def test_grass_capping_behaves_like_soil_not_paved(self, grade3_incident):
        inc = copy.deepcopy(grade3_incident)
        inc["segment_meta"]["surface_capping_type"] = "grass"
        grade, _ = grader.grade_incident(inc, grader.CFG)
        assert grade == 3


class TestGradingAccuracyAgainstGroundTruth:
    def test_full_batch_grading_accuracy(self, graded_incidents):
        """Cross-check against the actual detection_output/incidents.json ->
        grade_leak.py run already on disk — every gradable incident's
        assigned_grade must match its ground-truth label_grade. Only checks
        incidents from the batch/CSV path (source != "live") — the live
        telemetry test incidents mixed into this file during manual testing
        carry no ground-truth label at all, by design."""
        mismatches = []
        for inc in graded_incidents:
            if inc.get("source") == "live":
                continue
            truth = grader._clean_label(inc.get("label_grade"))
            if truth is None:
                continue
            if inc["assigned_grade"] != truth:
                mismatches.append(inc["incident_id"])
        assert mismatches == [], f"grading mismatches vs ground truth: {mismatches}"
