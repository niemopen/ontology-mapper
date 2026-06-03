"""Tests for orchestrator_service.runner."""

import json
import pytest
from pathlib import Path

from orchestrator_service.runner import (
    collect_pending_files,
    load_context,
    read_file,
    write_evaluation,
    _save_orchestration_config,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def run_dir(tmp_path):
    """Create a minimal run directory with search results."""
    types_dir = tmp_path / "search-results" / "types"
    props_dir = tmp_path / "search-results" / "properties"
    types_dir.mkdir(parents=True)
    props_dir.mkdir(parents=True)

    # Type files
    for name, status in [("dbpi_Address", "pending"), ("dbpi_Person", "evaluated")]:
        (types_dir / f"{name}.json").write_text(json.dumps({
            "status": status,
            "kind": "type",
            "source": {"qname": name.replace("_", ":")},
            "candidates": [],
            "evaluation": None,
        }), encoding="utf-8")

    # Property files
    for name in ["dbpi_streetName", "dbpi_cityName"]:
        (props_dir / f"{name}.json").write_text(json.dumps({
            "status": "pending",
            "kind": "property",
            "source": {"qname": name.replace("_", ":")},
            "candidates": [],
            "evaluation": None,
        }), encoding="utf-8")

    # Alignment report placeholder
    (tmp_path / "alignment-report.json").write_text(json.dumps({
        "actions": {"reuse": "Use as-is.", "extend": "Create extension."},
        "typePatterns": {"object": "Container types."},
    }), encoding="utf-8")

    return tmp_path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCollectPendingFiles:
    def test_returns_types_then_properties(self, run_dir):
        files = collect_pending_files(run_dir)
        names = [f.stem for f in files]
        # Types come first (sorted), then properties (sorted)
        assert names == [
            "dbpi_Address", "dbpi_Person",
            "dbpi_cityName", "dbpi_streetName",
        ]

    def test_all_are_json_files(self, run_dir):
        files = collect_pending_files(run_dir)
        assert all(f.suffix == ".json" for f in files)

    def test_empty_directory(self, tmp_path):
        files = collect_pending_files(tmp_path)
        assert files == []

    def test_missing_properties_dir(self, run_dir):
        import shutil
        shutil.rmtree(run_dir / "search-results" / "properties")
        files = collect_pending_files(run_dir)
        assert len(files) == 2  # only types


class TestLoadContext:
    def test_loads_actions_and_patterns(self, run_dir):
        ctx = load_context(run_dir)
        assert "reuse" in ctx.actions
        assert "object" in ctx.type_patterns

    def test_missing_report_exits(self, tmp_path):
        with pytest.raises(SystemExit):
            load_context(tmp_path)


class TestReadFile:
    def test_reads_json(self, run_dir):
        path = run_dir / "search-results" / "types" / "dbpi_Address.json"
        doc = read_file(path)
        assert doc["kind"] == "type"
        assert doc["source"]["qname"] == "dbpi:Address"


class TestWriteBack:
    def test_sets_status_and_writes_back(self, run_dir):
        path = run_dir / "search-results" / "types" / "dbpi_Address.json"
        doc = read_file(path)
        evaluation = {"sourceConcept": "dbpi:Address", "rationale": "test"}
        write_evaluation(path, doc, evaluation)

        reloaded = json.loads(path.read_text(encoding="utf-8"))
        assert reloaded["status"] == "evaluated"
        assert reloaded["evaluation"]["rationale"] == "test"

    def test_provenance_fields_survive_write(self, run_dir):
        """Provenance fields added by evaluator are persisted in the file."""
        path = run_dir / "search-results" / "types" / "dbpi_Address.json"
        doc = read_file(path)
        evaluation = {
            "sourceConcept": "dbpi:Address",
            "rationale": "test rationale here",
            "evaluatedAt": "2026-04-09T12:00:00+00:00",
            "evaluatedBy": "claude:sonnet",
            "candidateCount": 5,
        }
        write_evaluation(path, doc, evaluation)

        reloaded = json.loads(path.read_text(encoding="utf-8"))
        ev = reloaded["evaluation"]
        assert ev["evaluatedAt"] == "2026-04-09T12:00:00+00:00"
        assert ev["evaluatedBy"] == "claude:sonnet"
        assert ev["candidateCount"] == 5


# ---------------------------------------------------------------------------
# Tests: orchestration config
# ---------------------------------------------------------------------------

class TestSaveOrchestrationConfig:
    def _make_state_file(self, run_dir):
        """Create a minimal .mapper-state.json."""
        from ontology_mapper.pipeline import PipelineState, state_path_for
        state = PipelineState.new(organization="test")
        # Override run_id to match our tmp dir name
        state_path = state_path_for(run_dir)
        state.save(state_path)
        return state_path

    def test_writes_config_to_state(self, tmp_path):
        state_path = self._make_state_file(tmp_path)
        _save_orchestration_config(tmp_path, "claude", "sonnet", 24, 1)

        data = json.loads(state_path.read_text(encoding="utf-8"))
        config = data["orchestration_config"]
        assert config["evaluatorProvider"] == "claude"
        assert config["evaluatorModel"] == "sonnet"
        assert config["evaluatorConcurrency"] == 24
        assert config["maxRetries"] == 1

    def test_preserves_existing_state(self, tmp_path):
        state_path = self._make_state_file(tmp_path)
        _save_orchestration_config(tmp_path, "claude", "opus", 8, 2)

        data = json.loads(state_path.read_text(encoding="utf-8"))
        assert "run_id" in data
        assert "created_at" in data
        assert data["orchestration_config"]["evaluatorModel"] == "opus"
        assert data["orchestration_config"]["evaluatorProvider"] == "claude"

    def test_overwrites_previous_config(self, tmp_path):
        state_path = self._make_state_file(tmp_path)
        _save_orchestration_config(tmp_path, "claude", "sonnet", 24, 1)
        _save_orchestration_config(tmp_path, "codex", "gpt-5.5", 8, 2)

        data = json.loads(state_path.read_text(encoding="utf-8"))
        assert data["orchestration_config"]["evaluatorProvider"] == "codex"
        assert data["orchestration_config"]["evaluatorModel"] == "gpt-5.5"
        assert data["orchestration_config"]["evaluatorConcurrency"] == 8

    def test_no_state_file_is_noop(self, tmp_path):
        """If no state file exists, silently skip."""
        _save_orchestration_config(tmp_path, "claude", "sonnet", 24, 1)
        # No crash, no file created

    def test_existing_state_without_config_field(self, tmp_path):
        """State files from older runs may lack orchestration_config."""
        from ontology_mapper.pipeline import state_path_for
        state_path = state_path_for(tmp_path)
        state_path.parent.mkdir(parents=True, exist_ok=True)
        # Write a minimal state without orchestration_config
        old_state = {
            "run_id": "test_123",
            "created_at": "2026-04-09T00:00:00",
            "updated_at": "2026-04-09T00:00:00",
            "inputs": {},
            "stages": {},
            "highest_completed": None,
            "current_stage": None,
        }
        state_path.write_text(json.dumps(old_state), encoding="utf-8")

        _save_orchestration_config(tmp_path, "claude", "sonnet", 24, 1)

        data = json.loads(state_path.read_text(encoding="utf-8"))
        assert data["orchestration_config"]["evaluatorModel"] == "sonnet"
        assert data["orchestration_config"]["evaluatorProvider"] == "claude"
