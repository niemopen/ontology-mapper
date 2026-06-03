#!/usr/bin/env python3
"""Tests for quality_gates.py and pipeline_config.py"""

import pytest
from ontology_mapper.quality_gates import check_decisions, format_warnings
from ontology_mapper.pipeline_config import DEFAULTS, load_config


# ═══════════════════════════════════════════════════════════════════════════
# Pipeline Config
# ═══════════════════════════════════════════════════════════════════════════

class TestPipelineConfig:
    def test_defaults_complete(self):
        """All expected keys are present in defaults."""
        expected_keys = [
            "property_composition_max_depth",
        ]
        for key in expected_keys:
            assert key in DEFAULTS, f"Missing default: {key}"

    def test_load_config_returns_defaults_without_state(self, tmp_path):
        """When no state file exists, load_config returns defaults."""
        cfg = load_config(tmp_path / "nonexistent.json")
        assert cfg == DEFAULTS

    def test_load_config_merges_overrides(self, tmp_path):
        """Overrides in state file are merged with defaults."""
        state_file = tmp_path / ".mapper-state.json"
        state_file.write_text('{"thresholds": {"property_composition_max_depth": 3}}')
        cfg = load_config(state_file)
        assert cfg["property_composition_max_depth"] == 3

    def test_unknown_override_ignored(self, tmp_path):
        """Unknown keys in overrides are silently ignored."""
        state_file = tmp_path / ".mapper-state.json"
        state_file.write_text('{"thresholds": {"nonexistent_key": 999}}')
        cfg = load_config(state_file)
        assert "nonexistent_key" not in cfg


# ═══════════════════════════════════════════════════════════════════════════
# Decision Quality Gates
# ═══════════════════════════════════════════════════════════════════════════

class TestCheckDecisions:
    def test_empty_matrix_error(self):
        warnings = check_decisions({"totalConcepts": 0})
        assert len(warnings) == 1
        assert warnings[0]["code"] == "QG-001"

    def test_healthy_distribution_no_warnings(self):
        summary = {
            "totalConcepts": 10,
            "actionCounts": {"reuse": 4, "extend": 5, "augment": 1},
            "propertyStats": {"total": 5, "reuseProperty": 3, "createProperty": 2},
        }
        warnings = check_decisions(summary)
        assert len(warnings) == 0

    def test_action_count_mismatch_errors(self):
        summary = {
            "totalConcepts": 10,
            "actionCounts": {"reuse": 3, "extend": 3},  # 6, not 10
        }
        warnings = check_decisions(summary)
        codes = [w["code"] for w in warnings]
        assert "QG-002" in codes

    def test_matching_counts_no_warning(self):
        summary = {
            "totalConcepts": 6,
            "actionCounts": {"reuse": 2, "extend": 4},
        }
        warnings = check_decisions(summary)
        assert len(warnings) == 0

    def test_property_stats_mismatch_warns(self):
        summary = {
            "totalConcepts": 2,
            "actionCounts": {"reuse": 1, "extend": 1},
            "propertyStats": {"total": 10, "reuseProperty": 3, "createProperty": 5},
        }
        warnings = check_decisions(summary)
        codes = [w["code"] for w in warnings]
        assert "QG-003" in codes

    def test_property_stats_consistent(self):
        summary = {
            "totalConcepts": 2,
            "actionCounts": {"reuse": 1, "extend": 1},
            "propertyStats": {"total": 8, "reuseProperty": 3, "createProperty": 5},
        }
        warnings = check_decisions(summary)
        assert len(warnings) == 0

    def test_no_property_stats_no_warning(self):
        """Missing propertyStats entirely is not a QG-003 error."""
        summary = {
            "totalConcepts": 1,
            "actionCounts": {"reuse": 1},
        }
        warnings = check_decisions(summary)
        assert len(warnings) == 0


# ═══════════════════════════════════════════════════════════════════════════
# Warning Formatting
# ═══════════════════════════════════════════════════════════════════════════

class TestFormatWarnings:
    def test_empty_warnings_returns_empty(self):
        assert format_warnings([]) == ""

    def test_format_includes_code_and_message(self):
        warnings = [{
            "severity": "warning",
            "code": "QG-R-010",
            "message": "Test message",
            "detail": "Test detail",
        }]
        result = format_warnings(warnings)
        assert "QG-R-010" in result
        assert "Test message" in result
        assert "Test detail" in result

    def test_format_counts_severities(self):
        warnings = [
            {"severity": "error", "code": "E", "message": "e", "detail": None},
            {"severity": "warning", "code": "W", "message": "w", "detail": None},
            {"severity": "info", "code": "I", "message": "i", "detail": None},
        ]
        result = format_warnings(warnings)
        assert "1 errors" in result
        assert "1 warnings" in result
        assert "1 info" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
