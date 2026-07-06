"""
M7 synthesis tests — resilience case (blueprint Part D: "force an Ollama
failure mid-run and confirm a banner-flagged degraded work order is still
produced") plus a live end-to-end synthesis check when Ollama is up.
"""

import pytest

import synthesize_work_order as synth


class TestDegradedFallback:
    """Pure Python, no LLM involved — must always produce something."""

    def test_degraded_work_order_is_banner_flagged(self, grade1_incident):
        wo = synth.degraded_work_order(grade1_incident, reason="simulated Ollama outage")
        assert wo["degraded_mode"] is True
        assert "DEGRADED MODE" in wo["title"]
        assert wo["degraded_reason"] == "simulated Ollama outage"

    def test_degraded_work_order_has_all_required_fields(self, grade1_incident):
        wo = synth.degraded_work_order(grade1_incident, reason="x")
        schema = synth.build_schema([])
        for field in schema["required"]:
            assert field in wo, f"degraded fallback missing required field: {field}"

    def test_synthesize_falls_back_on_unreachable_model(self, grade1_incident):
        """The actual resilience case: point synthesize() at a model that can't
        possibly exist and confirm it still returns a complete, banner-flagged
        work order rather than raising."""
        bad_cfg = dict(synth.CFG)
        bad_cfg["model"] = "this-model-does-not-exist:latest"
        result = synth.synthesize(grade1_incident, citations=[], cfg=bad_cfg)
        assert result["work_order"]["degraded_mode"] is True
        assert result["grade"] == 1
        assert result["priority"] == "IMMEDIATE"


class TestCitationSchema:
    def test_schema_constrains_citations_to_known_chunk_ids(self):
        chunk_ids = ["doc_sec1_0", "doc_sec2_0"]
        schema = synth.build_schema(chunk_ids)
        assert schema["properties"]["citations"]["items"]["enum"] == chunk_ids

    def test_empty_chunk_list_falls_back_to_free_string_schema(self):
        schema = synth.build_schema([])
        assert schema["properties"]["citations"]["items"] == {"type": "string"}


@pytest.mark.live_infra
class TestLiveSynthesis:
    def test_real_synthesis_produces_valid_cited_work_order(self, ollama_available, grade1_incident):
        if not ollama_available:
            pytest.skip("Ollama not reachable on localhost:11434")

        citations = [{
            "chunk_id": "test_chunk_0",
            "source_doc": "test.md",
            "location": "Test Section",
            "text": "Grade 1 leaks require immediate isolation and notification of emergency services.",
            "score": 0.9,
        }]
        result = synth.synthesize(grade1_incident, citations, synth.CFG)
        assert result["work_order"]["degraded_mode"] is False
        assert set(result["work_order"]["citations"]) <= {"test_chunk_0"}
        assert result["latency_s"] < synth.CFG["timeout_s"]
