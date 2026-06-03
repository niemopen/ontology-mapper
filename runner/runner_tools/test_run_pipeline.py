"""Tests for runner_tools/run_pipeline.py."""

import json
import subprocess
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from runner_tools.run_pipeline import (
    REVIEW_ACTION_SCHEMA,
    StageError,
    StageTimer,
    VerificationError,
    _build_pending_summary,
    _build_review_prompt,
    _dispatch_review_action,
    _read_json,
    _resolve_concept,
    _stage_metric,
    load_state,
    print_summary,
    run_cmd,
    verify_stage,
)


# ---------------------------------------------------------------------------
# StageTimer
# ---------------------------------------------------------------------------

class TestStageTimer:
    def test_formats_seconds(self):
        t = StageTimer("1", elapsed=2.345)
        assert t.formatted == "2.3s"

    def test_formats_minutes(self):
        t = StageTimer("3", elapsed=125.0)
        assert t.formatted == "2m 5s"

    def test_context_manager(self):
        with StageTimer("test") as t:
            time.sleep(0.05)
        assert t.elapsed > 0


# ---------------------------------------------------------------------------
# run_cmd
# ---------------------------------------------------------------------------

class TestRunCmd:
    @patch("runner_tools.run_pipeline.subprocess.run")
    def test_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="ok\n", stderr="")
        result = run_cmd("1", ["echo", "hello"])
        assert result == "ok\n"

    @patch("runner_tools.run_pipeline.subprocess.run")
    def test_raises_on_failure(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="bad thing")
        with pytest.raises(StageError, match="Stage 1"):
            run_cmd("1", ["false"])


# ---------------------------------------------------------------------------
# verify_stage
# ---------------------------------------------------------------------------

class TestVerifyStage:
    @patch("runner_tools.run_pipeline.verify")
    def test_passes_clean(self, mock_verify):
        mock_verify.return_value = {
            "stage": "1",
            "checks": [{"status": "pass", "severity": "error", "checkId": "1", "message": "ok"}],
            "summary": {"total": 1, "pass": 1, "fail": 0, "warn": 0},
        }
        result = verify_stage(Path("/fake"), "1")
        assert result["summary"]["pass"] == 1

    @patch("runner_tools.run_pipeline.verify")
    def test_raises_on_error_failures(self, mock_verify):
        mock_verify.return_value = {
            "stage": "1",
            "checks": [{"status": "fail", "severity": "error", "checkId": "1", "message": "missing file"}],
            "summary": {"total": 1, "pass": 0, "fail": 1, "warn": 0},
        }
        with pytest.raises(VerificationError, match="missing file"):
            verify_stage(Path("/fake"), "1")

    @patch("runner_tools.run_pipeline.verify")
    def test_warnings_pass(self, mock_verify):
        mock_verify.return_value = {
            "stage": "1",
            "checks": [
                {"status": "pass", "severity": "error", "checkId": "1", "message": "ok"},
                {"status": "fail", "severity": "warning", "checkId": "2", "message": "minor"},
            ],
            "summary": {"total": 2, "pass": 1, "fail": 0, "warn": 1},
        }
        result = verify_stage(Path("/fake"), "1")
        assert result["summary"]["warn"] == 1

    @patch("runner_tools.run_pipeline.verify")
    def test_raises_on_verify_error_key(self, mock_verify):
        mock_verify.return_value = {"error": "Unknown stage: 99"}
        with pytest.raises(VerificationError, match="Unknown stage"):
            verify_stage(Path("/fake"), "99")


# ---------------------------------------------------------------------------
# load_state
# ---------------------------------------------------------------------------

class TestLoadState:
    def test_loads_json(self, tmp_path):
        state = {"inputs": {"organization": "test"}, "stages": {}}
        (tmp_path / ".mapper-state.json").write_text(json.dumps(state), encoding="utf-8")
        result = load_state(tmp_path)
        assert result["inputs"]["organization"] == "test"

    def test_raises_if_missing(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_state(tmp_path)


# ---------------------------------------------------------------------------
# _read_json
# ---------------------------------------------------------------------------

class TestReadJson:
    def test_reads_existing(self, tmp_path):
        p = tmp_path / "data.json"
        p.write_text('{"key": "value"}', encoding="utf-8")
        assert _read_json(p) == {"key": "value"}

    def test_returns_none_if_missing(self, tmp_path):
        assert _read_json(tmp_path / "nope.json") is None


# ---------------------------------------------------------------------------
# _stage_metric
# ---------------------------------------------------------------------------

class TestStageMetric:
    def test_stage_1_metric(self, tmp_path):
        (tmp_path / "source-inventory.json").write_text(
            json.dumps({"total_files": 27, "input_type": "owl"}),
            encoding="utf-8",
        )
        result = _stage_metric(tmp_path, "1")
        assert "27 files" in result
        assert "owl" in result

    def test_stage_2_metric(self, tmp_path):
        (tmp_path / "concept-inventory.json").write_text(
            json.dumps({"summary": {"classCount": 10, "objectPropertyCount": 15, "datatypePropertyCount": 10}}),
            encoding="utf-8",
        )
        result = _stage_metric(tmp_path, "2")
        assert "10 classes" in result
        assert "25 properties" in result

    def test_stage_3_metric(self, tmp_path):
        (tmp_path / "alignment-report.json").write_text(
            json.dumps({"entries": [
                {"properties": [{"a": 1}, {"b": 2}]},
                {"properties": [{"c": 3}]},
            ]}),
            encoding="utf-8",
        )
        result = _stage_metric(tmp_path, "3")
        assert "2 types" in result
        assert "3 properties" in result

    def test_stage_4_metric(self, tmp_path):
        (tmp_path / "mapping-matrix.json").write_text(
            json.dumps({"summary": {"actionCounts": {"reuse": 5, "extend": 3}}}),
            encoding="utf-8",
        )
        result = _stage_metric(tmp_path, "4")
        assert "5 reuse" in result or "reuse" in result

    def test_stage_missing_artifact(self, tmp_path):
        result = _stage_metric(tmp_path, "1")
        assert result == ""


# ---------------------------------------------------------------------------
# StageError / VerificationError
# ---------------------------------------------------------------------------

class TestExceptions:
    def test_stage_error_message(self):
        e = StageError("3", "something broke")
        assert "Stage 3" in str(e)
        assert e.stage == "3"

    def test_verification_error_is_stage_error(self):
        e = VerificationError("7", "check failed")
        assert isinstance(e, StageError)
        assert e.stage == "7"


# ---------------------------------------------------------------------------
# preflight
# ---------------------------------------------------------------------------

class TestPreflight:
    @patch("runner_tools.run_pipeline.Path")
    def test_missing_input_package(self, mock_path_cls):
        """Preflight raises if input package doesn't exist."""
        mock_path_instance = MagicMock()
        mock_path_instance.exists.return_value = False
        mock_path_cls.return_value = mock_path_instance

        from runner_tools.run_pipeline import preflight
        with patch.dict("sys.modules", {
            "ontology_mapper.build_strategy_reports": MagicMock(
                resolve_catalog_path=MagicMock(return_value=Path("/fake/catalog.json"))
            ),
            "ontology_mapper.vector_index": MagicMock(
                index_exists=MagicMock(return_value=True)
            ),
        }):
            with pytest.raises(StageError, match="Pre-flight"):
                preflight("/nonexistent/path", "niem", "6.0")


# ---------------------------------------------------------------------------
# Stage 5: _resolve_concept
# ---------------------------------------------------------------------------

def _make_pending():
    """Create sample pending items for testing."""
    return [
        {"sourceConcept": "src:PersonType", "action": "reuse",
         "targetType": "nc:PersonType", "reviewStatus": "pending-review"},
        {"sourceConcept": "src:AddressType", "action": "extend",
         "targetType": None, "reviewStatus": "pending-review",
         "extensionType": "ext:AddressType", "baseType": "nc:AddressType"},
        {"sourceConcept": "src:DocumentType", "action": "augment",
         "targetType": "nc:DocumentType", "reviewStatus": "pending-review",
         "augmentationType": "ext:DocumentTypeAugmentation",
         "augmentsType": "nc:DocumentType"},
    ]


class TestResolveConceptLookup:
    def test_exact_match(self):
        pending = _make_pending()
        entry = _resolve_concept(pending, "src:PersonType")
        assert entry["sourceConcept"] == "src:PersonType"

    def test_suffix_match(self):
        pending = _make_pending()
        entry = _resolve_concept(pending, "AddressType")
        assert entry["sourceConcept"] == "src:AddressType"

    def test_case_insensitive_suffix(self):
        pending = _make_pending()
        entry = _resolve_concept(pending, "documenttype")
        assert entry["sourceConcept"] == "src:DocumentType"

    def test_not_found(self):
        pending = _make_pending()
        assert _resolve_concept(pending, "NoSuchType") is None


# ---------------------------------------------------------------------------
# Stage 5: _build_pending_summary
# ---------------------------------------------------------------------------

class TestBuildPendingSummary:
    def test_contains_concepts(self):
        pending = _make_pending()
        summary = _build_pending_summary(pending)
        assert "src:PersonType" in summary
        assert "src:AddressType" in summary

    def test_contains_action_groups(self):
        pending = _make_pending()
        summary = _build_pending_summary(pending)
        assert "Reuse" in summary
        assert "Extend" in summary


# ---------------------------------------------------------------------------
# Stage 5: _build_review_prompt
# ---------------------------------------------------------------------------

class TestBuildReviewPrompt:
    def test_includes_user_input(self):
        prompt = _build_review_prompt("some summary", "approve PersonType")
        assert "approve PersonType" in prompt
        assert "some summary" in prompt

    def test_includes_action_descriptions(self):
        prompt = _build_review_prompt("", "test")
        assert "approve_all" in prompt
        assert "change_target" in prompt
        assert "resolve_property" in prompt


# ---------------------------------------------------------------------------
# Stage 5: _dispatch_review_action
# ---------------------------------------------------------------------------

class TestDispatchReviewAction:
    def _make_context(self, tmp_path):
        pending = _make_pending()
        matrix = {"mappings": pending, "summary": {"actionCounts": {}}}
        dec_log = {"decisions": []}
        return matrix, dec_log, pending

    def test_approve_single(self, tmp_path):
        matrix, dec_log, pending = self._make_context(tmp_path)
        action = {"action": "approve", "concept": "PersonType"}
        msg, applied, _ = _dispatch_review_action(
            action, tmp_path, matrix, dec_log, pending, None)
        assert len(applied) == 1
        assert applied[0]["sourceConcept"] == "src:PersonType"
        assert pending[0]["reviewStatus"] == "accepted"

    def test_approve_not_found(self, tmp_path):
        matrix, dec_log, pending = self._make_context(tmp_path)
        action = {"action": "approve", "concept": "NoSuchType"}
        msg, applied, _ = _dispatch_review_action(
            action, tmp_path, matrix, dec_log, pending, None)
        assert len(applied) == 0
        assert "not found" in msg.lower()

    def test_detail(self, tmp_path):
        matrix, dec_log, pending = self._make_context(tmp_path)
        action = {"action": "detail", "concept": "PersonType"}
        msg, applied, _ = _dispatch_review_action(
            action, tmp_path, matrix, dec_log, pending, None)
        assert len(applied) == 0
        assert "src:PersonType" in msg
        assert "reuse" in msg

    def test_approve_all(self, tmp_path):
        matrix, dec_log, pending = self._make_context(tmp_path)
        action = {"action": "approve_all"}
        msg, applied, _ = _dispatch_review_action(
            action, tmp_path, matrix, dec_log, pending, None)
        assert len(applied) == 3
        for entry in pending:
            assert entry["reviewStatus"] == "accepted"

    def test_approve_all_blocked_by_must_decide(self, tmp_path):
        matrix, dec_log, pending = self._make_context(tmp_path)
        # Add a human-must-decide property to one entry
        pending[0]["propertyMappings"] = [{
            "sourceProperty": "foo",
            "action": "human-must-decide",
            "reviewStatus": "pending-review",
        }]
        action = {"action": "approve_all"}
        msg, applied, _ = _dispatch_review_action(
            action, tmp_path, matrix, dec_log, pending, None)
        assert len(applied) == 0
        assert "cannot" in msg.lower() or "Cannot" in msg

    def test_resolve_property(self, tmp_path):
        matrix, dec_log, pending = self._make_context(tmp_path)
        pending[0]["propertyMappings"] = [{
            "sourceProperty": "personName",
            "action": "human-must-decide",
            "reviewStatus": "pending-review",
        }]
        action = {
            "action": "resolve_property",
            "concept": "PersonType",
            "source_property": "personName",
            "property_action": "reuse-property",
            "target_property": "nc:PersonName",
        }
        msg, applied, _ = _dispatch_review_action(
            action, tmp_path, matrix, dec_log, pending, None)
        assert len(applied) == 1
        prop = pending[0]["propertyMappings"][0]
        assert prop["action"] == "reuse-property"
        assert prop["reviewStatus"] == "accepted"

    def test_search_action(self, tmp_path):
        """Search action calls catalog_search."""
        matrix, dec_log, pending = self._make_context(tmp_path)
        action = {"action": "search", "query": "Person"}

        mock_catalog = {"types": [], "properties": []}
        cascade = ("niem", mock_catalog)

        with patch("ontology_mapper.catalog_search.search_catalog") as mock_search:
            mock_search.return_value = {"types": [], "properties": []}
            msg, applied, _ = _dispatch_review_action(
                action, tmp_path, matrix, dec_log, pending, cascade)
        assert "no results" in msg.lower() or "No results" in msg

    def test_unknown_action(self, tmp_path):
        matrix, dec_log, pending = self._make_context(tmp_path)
        action = {"action": "do_magic"}
        msg, applied, _ = _dispatch_review_action(
            action, tmp_path, matrix, dec_log, pending, None)
        assert "unknown" in msg.lower()


# ---------------------------------------------------------------------------
# Stage 5: REVIEW_ACTION_SCHEMA
# ---------------------------------------------------------------------------

class TestReviewActionSchema:
    def test_schema_is_valid(self):
        """Schema has required structure for claude -p --json-schema."""
        assert REVIEW_ACTION_SCHEMA["type"] == "object"
        assert "action" in REVIEW_ACTION_SCHEMA["properties"]
        assert REVIEW_ACTION_SCHEMA["required"] == ["action"]
        assert REVIEW_ACTION_SCHEMA["additionalProperties"] is False

    def test_all_actions_defined(self):
        actions = REVIEW_ACTION_SCHEMA["properties"]["action"]["enum"]
        expected = {"approve", "approve_all", "detail", "change_target",
                    "resolve_property", "search"}
        assert set(actions) == expected


# ---------------------------------------------------------------------------
# Stage 5: _stage_metric for stage 5
# ---------------------------------------------------------------------------

class TestStage5Metric:
    def test_all_accepted(self, tmp_path):
        mx = {"mappings": [
            {"sourceConcept": "a", "action": "reuse", "reviewStatus": "accepted"},
            {"sourceConcept": "b", "action": "extend", "reviewStatus": "accepted"},
        ]}
        (tmp_path / "mapping-matrix.json").write_text(json.dumps(mx), encoding="utf-8")
        result = _stage_metric(tmp_path, "5")
        assert "2 concepts reviewed" in result

    def test_some_pending(self, tmp_path):
        mx = {"mappings": [
            {"sourceConcept": "a", "action": "reuse", "reviewStatus": "accepted"},
            {"sourceConcept": "b", "action": "extend", "reviewStatus": "pending-review"},
        ]}
        (tmp_path / "mapping-matrix.json").write_text(json.dumps(mx), encoding="utf-8")
        result = _stage_metric(tmp_path, "5")
        assert "1 pending" in result
        assert "1 accepted" in result
