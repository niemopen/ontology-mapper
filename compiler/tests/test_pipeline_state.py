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
