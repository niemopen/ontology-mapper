#!/usr/bin/env python3
"""Tests for verify_stage_outputs.py — post-stage artifact verification."""

import json
import pytest
from pathlib import Path

from runner_tools.verify_stage_outputs import (
    verify, _check, _file_check, _load_json, VALID_STAGES,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_json(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")


def _write_state(run_dir, stages=None, inputs=None):
    state = {"stages": stages or {}, "inputs": inputs or {}}
    _write_json(run_dir / ".mapper-state.json", state)


# ---------------------------------------------------------------------------
# _check / _file_check helpers
# ---------------------------------------------------------------------------

class TestCheckHelpers:
    def test_check_pass(self):
        c = _check("test", True, "ok")
        assert c["status"] == "pass"
        assert c["name"] == "test"

    def test_check_fail(self):
        c = _check("test", False, "bad")
        assert c["status"] == "fail"

    def test_check_severity_default(self):
        c = _check("test", False)
        assert c["severity"] == "error"

    def test_check_severity_warning(self):
        c = _check("test", False, severity="warning")
        assert c["severity"] == "warning"

    def test_file_check_missing(self, tmp_path):
        c = _file_check("test", tmp_path / "nonexistent.json")
        assert c["status"] == "fail"
        assert "Missing" in c["detail"]

    def test_file_check_empty(self, tmp_path):
        p = tmp_path / "empty.json"
        p.write_text("")
        c = _file_check("test", p)
        assert c["status"] == "fail"
        assert "Empty" in c["detail"]

    def test_file_check_exists(self, tmp_path):
        p = tmp_path / "data.json"
        p.write_text('{"key": 1}')
        c = _file_check("test", p)
        assert c["status"] == "pass"


class TestLoadJson:
    def test_load_valid(self, tmp_path):
        p = tmp_path / "data.json"
        _write_json(p, {"a": 1})
        assert _load_json(p) == {"a": 1}

    def test_load_missing(self, tmp_path):
        assert _load_json(tmp_path / "nope.json") is None

    def test_load_invalid_json(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("not json")
        assert _load_json(p) is None


# ---------------------------------------------------------------------------
# Stage 1 verification
# ---------------------------------------------------------------------------

class TestVerifyStage1:
    def test_pass(self, tmp_path):
        _write_state(tmp_path, stages={"1": {"status": "completed"}})
        _write_json(tmp_path / "source-inventory.json", {
            "input_package": "test", "total_files": 5, "input_type": "owl"
        })
        result = verify(tmp_path, "1")
        assert result["summary"]["fail"] == 0

    def test_missing_inventory(self, tmp_path):
        _write_state(tmp_path, stages={"1": {"status": "completed"}})
        result = verify(tmp_path, "1")
        fails = [c for c in result["checks"] if c["status"] == "fail"]
        assert any("source_inventory" in c["name"] for c in fails)

    def test_stage_not_completed(self, tmp_path):
        _write_state(tmp_path, stages={"1": {"status": "running"}})
        _write_json(tmp_path / "source-inventory.json", {
            "input_package": "test", "total_files": 5, "input_type": "owl"
        })
        result = verify(tmp_path, "1")
        fails = [c for c in result["checks"] if c["status"] == "fail"]
        assert any("state_stage_completed" in c["name"] for c in fails)


# ---------------------------------------------------------------------------
# Stage 2 verification
# ---------------------------------------------------------------------------

class TestVerifyStage2:
    def test_pass(self, tmp_path):
        _write_state(tmp_path)
        _write_json(tmp_path / "concept-inventory.json", {
            "summary": {"classCount": 15},
            "classes": [{"qname": f"src:C{i}"} for i in range(15)],
        })
        result = verify(tmp_path, "2")
        assert result["summary"]["fail"] == 0

    def test_missing_inventory(self, tmp_path):
        _write_state(tmp_path)
        result = verify(tmp_path, "2")
        fails = [c for c in result["checks"] if c["status"] == "fail"]
        assert any("concept_inventory" in c["name"] for c in fails)


# ---------------------------------------------------------------------------
# Stage 3 verification
# ---------------------------------------------------------------------------

class TestVerifyStage3:
    def _setup_stage3(self, tmp_path, alignment=None):
        _write_state(tmp_path)
        if alignment is not None:
            _write_json(tmp_path / "alignment-report.json", alignment)

    def test_pass(self, tmp_path):
        alignment = {
            "matchingMethod": "semantic",
            "entries": [{
                "sourceConcept": "src:Person",
                "action": "reuse",
                "rationale": "Direct match",
                "targetType": "nc:PersonType",
            }],
        }
        self._setup_stage3(tmp_path, alignment=alignment)
        result = verify(tmp_path, "3")
        assert result["summary"]["fail"] == 0

    def test_missing_alignment_report(self, tmp_path):
        self._setup_stage3(tmp_path)
        result = verify(tmp_path, "3")
        fails = [c for c in result["checks"]
                 if c["status"] == "fail" and "alignment_report" in c["name"]]
        assert len(fails) >= 1

    def test_incomplete_entries_fail(self, tmp_path):
        alignment = {
            "matchingMethod": "semantic",
            "entries": [{"sourceConcept": "src:P", "action": "", "rationale": ""}],
        }
        self._setup_stage3(tmp_path, alignment=alignment)
        result = verify(tmp_path, "3")
        fails = [c for c in result["checks"]
                 if c["status"] == "fail" and c["name"] == "alignment_entries_complete"]
        assert len(fails) == 1

    def test_wrong_matching_method(self, tmp_path):
        alignment = {
            "matchingMethod": "keyword",
            "entries": [{"sourceConcept": "src:P", "action": "reuse", "rationale": "ok"}],
        }
        self._setup_stage3(tmp_path, alignment=alignment)
        result = verify(tmp_path, "3")
        fails = [c for c in result["checks"]
                 if c["status"] == "fail" and c["name"] == "alignment_matching_method"]
        assert len(fails) == 1


# ---------------------------------------------------------------------------
# Stage 4 verification
# ---------------------------------------------------------------------------

class TestVerifyStage4:
    def _matrix(self, mappings, action_counts=None):
        summary = {
            "totalConcepts": len(mappings),
            "actionCounts": action_counts or {},
            "propertyStats": {
                "total": 0, "reuseProperty": 0, "createProperty": 0,
            },
        }
        return {
            "mappings": mappings,
            "summary": summary,
            "actions": {},
            "typePatterns": {},
            "targetOntology": "niem",
            "targetVersion": "6.0",
        }

    def test_pass(self, tmp_path):
        _write_state(tmp_path)
        m = {
            "sourceConcept": "src:A", "action": "reuse",
            "reviewStatus": "pending-review", "rationale": "Direct match",
            "targetType": "nc:ActivityType", "targetPath": "nc:ActivityType",
        }
        _write_json(tmp_path / "mapping-matrix.json",
                     self._matrix([m], {"reuse": 1}))
        _write_json(tmp_path / "decision-log.json", {})
        _write_json(tmp_path / "generation-audit.json", {})
        result = verify(tmp_path, "4")
        errors = [c for c in result["checks"]
                  if c["status"] == "fail" and c["severity"] == "error"]
        assert len(errors) == 0

    def test_scaffolding_extend_missing_fields(self, tmp_path):
        _write_state(tmp_path)
        m = {
            "sourceConcept": "src:A", "action": "extend",
            "reviewStatus": "pending-review", "rationale": "Extend needed",
            "targetType": "nc:ActivityType", "targetPath": "nc:ActivityType",
            # missing extensionType and baseType
        }
        _write_json(tmp_path / "mapping-matrix.json",
                     self._matrix([m], {"extend": 1}))
        _write_json(tmp_path / "decision-log.json", {})
        _write_json(tmp_path / "generation-audit.json", {})
        result = verify(tmp_path, "4")
        fails = [c for c in result["checks"]
                 if c["name"] == "matrix_scaffolding_consistent"
                 and c["status"] == "fail"]
        assert len(fails) == 1


# ---------------------------------------------------------------------------
# Stage 5 verification
# ---------------------------------------------------------------------------

class TestVerifyStage5:
    def test_all_accepted(self, tmp_path):
        _write_state(tmp_path)
        _write_json(tmp_path / "human-review-decisions.json", {})
        _write_json(tmp_path / "mapping-matrix.json", {
            "mappings": [{"sourceConcept": "src:A", "reviewStatus": "approved"}],
        })
        result = verify(tmp_path, "5")
        assert result["summary"]["fail"] == 0

    def test_pending_review_fails(self, tmp_path):
        _write_state(tmp_path)
        _write_json(tmp_path / "human-review-decisions.json", {})
        _write_json(tmp_path / "mapping-matrix.json", {
            "mappings": [{"sourceConcept": "src:A", "reviewStatus": "pending-review"}],
        })
        result = verify(tmp_path, "5")
        fails = [c for c in result["checks"]
                 if c["status"] == "fail" and c["name"] == "all_classes_accepted"]
        assert len(fails) == 1


# ---------------------------------------------------------------------------
# verify() dispatch
# ---------------------------------------------------------------------------

class TestVerifyDispatch:
    def test_unknown_stage(self, tmp_path):
        _write_state(tmp_path)
        result = verify(tmp_path, "99")
        assert "error" in result

    def test_result_structure(self, tmp_path):
        _write_state(tmp_path)
        _write_json(tmp_path / "source-inventory.json", {
            "input_package": "test", "total_files": 1, "input_type": "owl"
        })
        result = verify(tmp_path, "1")
        assert "stage" in result
        assert "runDir" in result
        assert "timestamp" in result
        assert "checks" in result
        assert "summary" in result

    def test_valid_stages_constant(self):
        assert "1" in VALID_STAGES
        assert "6a" in VALID_STAGES
        assert "8" in VALID_STAGES
