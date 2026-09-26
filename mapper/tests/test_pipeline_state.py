"""Tests for pipeline state management and stage definitions."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ontology_mapper.pipeline import (
    STAGE_MAP,
    STAGE_ORDER,
    STAGES,
    PipelineState,
    StageResult,
    StageSpec,
    catalog_exists,
    check_inputs_for_stage,
    discover_catalogs,
    stage_index,
)


# ---------------------------------------------------------------------------
# StageSpec tests
# ---------------------------------------------------------------------------


class TestStageSpec:
    """Tests for stage definitions and StageSpec dataclass."""

    def test_all_eight_stages_exist(self):
        assert len(STAGES) == 8

    def test_stage_map_has_all_stages(self):
        assert len(STAGE_MAP) == 8
        for stage in STAGES:
            assert stage.number in STAGE_MAP
            assert STAGE_MAP[stage.number] is stage

    def test_stage_numbers_are_1_through_8(self):
        numbers = sorted(s.number for s in STAGES)
        assert numbers == ["1", "2", "3", "4", "5", "6", "7", "8"]

    def test_sort_key_ordering(self):
        assert STAGES[0].sort_key == (1,)
        assert STAGES[4].sort_key == (5,)
        assert STAGES[7].sort_key == (8,)
        # Verify sort_key produces correct ordering
        sorted_stages = sorted(STAGES, key=lambda s: s.sort_key)
        for i, stage in enumerate(sorted_stages):
            assert stage.number == str(i + 1)

    def test_stage_5_requires_human_review(self):
        assert STAGE_MAP["5"].requires_human_review is True

    def test_other_stages_do_not_require_human_review(self):
        for number in ["1", "2", "3", "4", "6", "7", "8"]:
            assert STAGE_MAP[number].requires_human_review is False

    def test_each_stage_has_nonempty_fields(self):
        for stage in STAGES:
            assert stage.name, f"Stage {stage.number} has empty name"
            assert stage.description, f"Stage {stage.number} has empty description"
            assert stage.inputs, f"Stage {stage.number} has empty inputs"
            assert stage.outputs, f"Stage {stage.number} has empty outputs"


# ---------------------------------------------------------------------------
# StageResult tests
# ---------------------------------------------------------------------------


class TestStageResult:
    """Tests for the StageResult dataclass."""

    def test_construct_with_required_fields(self):
        result = StageResult(stage="1", status="completed", started_at="2026-01-01T00:00:00Z")
        assert result.stage == "1"
        assert result.status == "completed"
        assert result.started_at == "2026-01-01T00:00:00Z"

    def test_optional_fields_default_correctly(self):
        result = StageResult(stage="2", status="pending", started_at="2026-01-01T00:00:00Z")
        assert result.completed_at is None
        assert result.error is None
        assert result.artifacts == []
        assert result.notes is None


# ---------------------------------------------------------------------------
# PipelineState tests
# ---------------------------------------------------------------------------


class TestPipelineStateNew:
    """Tests for PipelineState.new() factory."""

    def test_new_creates_state_with_timestamp_run_id(self):
        state = PipelineState.new()
        # run_id should be a bare timestamp like "20260404-120000"
        assert state.run_id
        assert "_" not in state.run_id  # no org prefix
        assert state.created_at
        assert state.updated_at
        assert state.stages == {}
        assert state.highest_completed is None
        assert state.current_stage is None

    def test_new_with_organization_includes_prefix(self):
        state = PipelineState.new(organization="redvale")
        assert state.run_id.startswith("redvale_")


class TestPipelineStateSaveLoad:
    """Tests for save/load roundtrip."""

    def test_roundtrip_preserves_all_fields(self, tmp_path: Path):
        state = PipelineState.new(organization="testorg")
        state.inputs["source"] = "dbpi"
        result = StageResult(
            stage="1",
            status="completed",
            started_at="2026-01-01T00:00:00Z",
            completed_at="2026-01-01T00:01:00Z",
            artifacts=["inventory.json"],
            notes="test note",
        )
        state.record_stage(result)

        path = tmp_path / "state.json"
        state.save(path)

        loaded = PipelineState.load(path)
        assert loaded.run_id == state.run_id
        assert loaded.created_at == state.created_at
        assert loaded.inputs == {"source": "dbpi"}
        assert loaded.highest_completed == "1"
        assert loaded.current_stage == "1"
        assert loaded.stages["1"]["status"] == "completed"
        assert loaded.stages["1"]["artifacts"] == ["inventory.json"]
        assert loaded.stages["1"]["notes"] == "test note"

    def test_save_creates_parent_directories(self, tmp_path: Path):
        state = PipelineState.new()
        path = tmp_path / "nested" / "dir" / "state.json"
        state.save(path)
        assert path.exists()


class TestPipelineStateRecordStage:
    """Tests for record_stage behavior."""

    def test_completed_result_updates_highest_completed(self):
        state = PipelineState.new()
        result = StageResult(stage="1", status="completed", started_at="2026-01-01T00:00:00Z")
        state.record_stage(result)
        assert state.highest_completed == "1"
        assert state.current_stage == "1"

    def test_failed_result_does_not_update_highest_completed(self):
        state = PipelineState.new()
        # Complete stage 1 first
        state.record_stage(StageResult(stage="1", status="completed", started_at="t"))
        # Fail stage 2
        state.record_stage(StageResult(stage="2", status="failed", started_at="t", error="boom"))
        assert state.highest_completed == "1"
        assert state.current_stage == "2"

    def test_highest_completed_tracks_maximum(self):
        state = PipelineState.new()
        state.record_stage(StageResult(stage="1", status="completed", started_at="t"))
        state.record_stage(StageResult(stage="2", status="completed", started_at="t"))
        state.record_stage(StageResult(stage="3", status="completed", started_at="t"))
        assert state.highest_completed == "3"


class TestPipelineStateStageStatus:
    """Tests for stage_status method."""

    def test_returns_status_for_recorded_stage(self):
        state = PipelineState.new()
        state.record_stage(StageResult(stage="1", status="completed", started_at="t"))
        assert state.stage_status("1") == "completed"

    def test_returns_none_for_unrecorded_stage(self):
        state = PipelineState.new()
        assert state.stage_status("5") is None


class TestPipelineStateNextStage:
    """Tests for next_stage method."""

    def test_returns_1_for_fresh_state(self):
        state = PipelineState.new()
        assert state.next_stage() == "1"

    def test_returns_correct_next_after_completions(self):
        state = PipelineState.new()
        state.record_stage(StageResult(stage="1", status="completed", started_at="t"))
        assert state.next_stage() == "2"
        state.record_stage(StageResult(stage="2", status="completed", started_at="t"))
        assert state.next_stage() == "3"

    def test_returns_none_when_all_stages_complete(self):
        state = PipelineState.new()
        for i in range(1, 9):
            state.record_stage(StageResult(stage=str(i), status="completed", started_at="t"))
        assert state.next_stage() is None


class TestPipelineStateCanJumpTo:
    """Tests for can_jump_to method."""

    def test_stage_1_always_allowed(self):
        state = PipelineState.new()
        assert state.can_jump_to("1") is True

    def test_fresh_state_only_allows_stage_1(self):
        state = PipelineState.new()
        assert state.can_jump_to("1") is True
        assert state.can_jump_to("2") is False
        assert state.can_jump_to("3") is False

    def test_allows_stages_up_to_highest_plus_one(self):
        state = PipelineState.new()
        state.record_stage(StageResult(stage="1", status="completed", started_at="t"))
        state.record_stage(StageResult(stage="2", status="completed", started_at="t"))
        state.record_stage(StageResult(stage="3", status="completed", started_at="t"))
        # Can jump to 1, 2, 3 (completed), and 4 (next)
        assert state.can_jump_to("1") is True
        assert state.can_jump_to("2") is True
        assert state.can_jump_to("3") is True
        assert state.can_jump_to("4") is True
        # Cannot jump beyond
        assert state.can_jump_to("5") is False
        assert state.can_jump_to("8") is False


# ---------------------------------------------------------------------------
# stage_index tests
# ---------------------------------------------------------------------------


class TestStageIndex:
    """Tests for the stage_index helper."""

    def test_returns_correct_indices(self):
        for i in range(8):
            assert stage_index(str(i + 1)) == i

    def test_raises_for_invalid_stage(self):
        with pytest.raises(ValueError):
            stage_index("99")
        with pytest.raises(ValueError):
            stage_index("0")


# ---------------------------------------------------------------------------
# STAGE_ORDER tests
# ---------------------------------------------------------------------------


class TestStageOrder:
    """Tests for the STAGE_ORDER constant."""

    def test_contains_eight_entries(self):
        assert len(STAGE_ORDER) == 8

    def test_is_in_correct_order(self):
        assert STAGE_ORDER == ["1", "2", "3", "4", "5", "6", "7", "8"]


# ---------------------------------------------------------------------------
# discover_catalogs / catalog_exists tests
# ---------------------------------------------------------------------------


class TestCatalogDiscovery:
    """Tests for catalog discovery functions."""

    def test_discover_catalogs_finds_niem(self):
        catalogs = discover_catalogs()
        ontologies = [ont for ont, ver in catalogs]
        assert "niem" in ontologies
        # Verify niem 6.0 specifically
        assert ("niem", "6.0") in catalogs

    def test_catalog_exists_niem(self):
        assert catalog_exists("niem", "6.0") is True

    def test_catalog_exists_nonexistent(self):
        assert catalog_exists("nonexistent", "1.0") is False


# ---------------------------------------------------------------------------
# check_inputs_for_stage
# ---------------------------------------------------------------------------


class TestCheckInputsForStage:
    def test_stage_1_needs_org_source_path(self):
        state = PipelineState.new()
        assert check_inputs_for_stage(state, "1") is False

    def test_stage_1_satisfied(self):
        state = PipelineState.new()
        state.inputs["organization"] = "redvale"
        state.inputs["source"] = "dbpi"
        state.inputs["input_package_path"] = "sources/redvale_dbpi_agency_package"
        assert check_inputs_for_stage(state, "1") is True

    def test_stage_3_needs_target(self):
        state = PipelineState.new()
        state.inputs["organization"] = "redvale"
        state.inputs["source"] = "dbpi"
        state.inputs["input_package_path"] = "sources/redvale_dbpi_agency_package"
        assert check_inputs_for_stage(state, "3") is False

    def test_stage_2_no_extra_inputs(self):
        state = PipelineState.new()
        state.inputs["organization"] = "redvale"
        state.inputs["source"] = "dbpi"
        state.inputs["input_package_path"] = "sources/redvale_dbpi_agency_package"
        assert check_inputs_for_stage(state, "2") is True


import argparse
from ontology_mapper import pipeline


def test_rerun_ingest_writes_only_to_explicit_copy(tmp_path, monkeypatch):
    live_root = tmp_path / "live"
    monkeypatch.setattr(pipeline, "RUNS_ROOT", live_root)
    source = tmp_path / "source" / "input"
    source.mkdir(parents=True)
    (source / "sample.csv").write_text("name\nSample\n", encoding="utf-8")
    state = pipeline.PipelineState.new("example")
    state.inputs = {"organization": "example", "source": "sample",
                    "input_package_path": str(source.parent),
                    "target_ontology": "example", "target_version": "1"}
    live = live_root / state.run_id
    live.mkdir(parents=True)
    inventory = live / "source-inventory.json"
    inventory.write_text("untouched", encoding="utf-8")
    copy = tmp_path / "scratch-copy"
    state_path = copy / ".mapper-state.json"
    state.save(state_path)
    original_keys = set(json.loads(state_path.read_text()))

    assert pipeline.cmd_rerun(argparse.Namespace(run_dir=str(copy), stage="1")) == 0
    assert inventory.read_text() == "untouched"
    assert json.loads((copy / "source-inventory.json").read_text())["total_files"] == 1
    saved = json.loads(state_path.read_text())
    assert saved["stages"]["1"]["artifacts"] == [str(copy / "source-inventory.json")]
    assert set(saved) == original_keys


def test_new_state_uses_configured_runs_root(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "RUNS_ROOT", tmp_path)
    state = pipeline.PipelineState.new()
    assert pipeline._get_run_dir(state) == tmp_path / state.run_id


def _finalized_state():
    state = pipeline.PipelineState.new()
    for stage in STAGE_ORDER:
        state.record_stage(StageResult(stage=stage, status="completed",
                                       started_at="t0", completed_at="t1"))
    return state


def _finalized_package(pkg):
    gov = pkg / "governance"
    gov.mkdir(parents=True)
    for name in ("validation-report.json", "version-manifest.json",
                 "lineage-manifest.json"):
        (gov / name).write_text('{"allPassed": true}', encoding="utf-8")
    (gov / "change-impact.md").write_text("All validation checks passed.\n", encoding="utf-8")
    (gov / "decision-log.json").write_text("{}", encoding="utf-8")  # Stage 6b's
    (pkg / "package-manifest.json").write_text(
        json.dumps({"name": "sample", "version": "1.0.0", "finalizedAt": "t2"}),
        encoding="utf-8")


def test_reopen_takes_back_completion_from_that_stage_on():
    state = _finalized_state()
    state.reopen("7")
    assert [state.stage_status(s) for s in STAGE_ORDER] == ["completed"] * 6 + ["pending"] * 2
    assert state.stages["8"]["completed_at"] is None
    assert state.highest_completed == "6"
    assert state.next_stage() == "7"
    state.reopen("1")
    assert state.highest_completed is None


def test_reopen_leaves_a_run_that_never_reached_the_stage_alone():
    state = pipeline.PipelineState.new()
    for stage in ("1", "2", "3"):
        state.record_stage(StageResult(stage=stage, status="completed", started_at="t0"))
    state.reopen("7")
    assert state.highest_completed == "3"
    assert "7" not in state.stages


def test_withdraw_conclusions_removes_only_what_stage_8_wrote(tmp_path):
    from ontology_mapper.validate_edge_package import STAGE_8_OUTPUTS

    pkg = tmp_path / "edge-package"
    _finalized_package(pkg)
    (tmp_path / "validation-report.json").write_text('{"allPassed": true}', encoding="utf-8")
    state = _finalized_state()
    pipeline.withdraw_conclusions(state, tmp_path, pkg, "7")
    assert not (tmp_path / "validation-report.json").exists()
    for name in STAGE_8_OUTPUTS:
        if name != "package-manifest.json":
            assert not (pkg / name).exists(), name
    manifest = json.loads((pkg / "package-manifest.json").read_text(encoding="utf-8"))
    # Stage 8's release version is taken back with its stamp; Stage 6 wrote
    # the draft version, and leaving 1.0.0 published an unfinalized package.
    assert manifest == {"name": "sample", "version": "0.1.0"}
    assert (pkg / "governance" / "decision-log.json").exists()
    assert state.stage_status("7") == "pending"
    # Idempotent: a second withdrawal over an unstamped package changes nothing.
    pipeline.withdraw_conclusions(state, tmp_path, pkg, "7")
    assert json.loads((pkg / "package-manifest.json").read_text(encoding="utf-8")) == manifest


def test_regenerating_a_finalized_package_withdraws_its_certificate(tmp_path, monkeypatch):
    """Stage 6 through `om-pipeline rerun --stage 6`, the path both drivers take."""
    monkeypatch.setattr(pipeline, "execute_stage", lambda state, number: StageResult(
        stage=number, status="failed", started_at="t0", error="generation refused"))
    state = _finalized_state()
    state.inputs = {"organization": "example", "source": "sample",
                    "input_package_path": str(tmp_path),
                    "target_ontology": "niem", "target_version": "6.0"}
    state_path = tmp_path / ".mapper-state.json"
    state.save(state_path)
    _finalized_package(tmp_path / "edge-package")

    assert pipeline.cmd_rerun(argparse.Namespace(run_dir=str(tmp_path), stage="6")) == 1
    saved = json.loads(state_path.read_text(encoding="utf-8"))
    assert {s: saved["stages"][s]["status"] for s in ("6", "7", "8")} == {
        "6": "failed", "7": "pending", "8": "pending"}
    assert not (tmp_path / "edge-package" / "governance" / "validation-report.json").exists()
    assert "finalizedAt" not in json.loads(
        (tmp_path / "edge-package" / "package-manifest.json").read_text(encoding="utf-8"))


def test_record_stage_failure_keeps_the_start(tmp_path):
    state = _finalized_state()
    state.save(tmp_path / ".mapper-state.json")
    pipeline.record_stage_failure(tmp_path, "7", "SOME CHECKS FAILED")
    saved = json.loads((tmp_path / ".mapper-state.json").read_text(encoding="utf-8"))
    assert saved["stages"]["7"]["status"] == "failed"
    assert saved["stages"]["7"]["started_at"] == "t0"
    assert saved["stages"]["7"]["error"] == "SOME CHECKS FAILED"
