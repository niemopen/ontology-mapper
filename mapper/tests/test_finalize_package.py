#!/usr/bin/env python3
"""Tests for finalize_package.py — Stage 8 governance artifacts."""

import json
import pytest
from pathlib import Path
from datetime import datetime, timezone

from ontology_mapper.finalize_package import (
    _count_actions,
    _load_stage_timings,
    _total_duration,
    build_version_manifest,
    build_lineage_manifest,
    build_change_impact,
    reconcile_manifest,
)
from ontology_mapper.pipeline_context import PipelineContext


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ctx(tmp_path, source="dbpi", organization="redvale"):
    run_dir = tmp_path / "run"
    pkg_dir = run_dir / "edge-package"
    pkg_dir.mkdir(parents=True)
    return PipelineContext(
        run_dir=run_dir,
        pkg_dir=pkg_dir,
        organization=organization,
        source=source,
        target_ontology="niem",
        target_version="6.0",
        input_package_path=str(tmp_path / "sources" / "pkg"),
    )


def _make_matrix(actions):
    """Build a matrix from a list of (concept, action) tuples."""
    return {"mappings": [
        {"sourceConcept": concept, "action": action}
        for concept, action in actions
    ]}


def _make_state(stage_timings):
    """Build a minimal pipeline state dict with stage timing."""
    stages = {}
    for num, started, completed, status in stage_timings:
        stages[str(num)] = {
            "stage": str(num),
            "status": status,
            "started_at": started,
            "completed_at": completed,
            "notes": "",
        }
    return {"stages": stages}


# ---------------------------------------------------------------------------
# _count_actions
# ---------------------------------------------------------------------------

class TestCountActions:
    def test_counts_all_action_types(self):
        mappings = [
            {"action": "reuse"}, {"action": "reuse"},
            {"action": "extend"},
            {"action": "augment"},
            {"action": "exclude"}, {"action": "exclude"}, {"action": "exclude"},
        ]
        counts = _count_actions(mappings)
        assert counts == {"reuse": 2, "extend": 1, "augment": 1, "exclude": 3}

    def test_empty_mappings(self):
        assert _count_actions([]) == {}

    def test_single_action(self):
        assert _count_actions([{"action": "reuse"}]) == {"reuse": 1}


# ---------------------------------------------------------------------------
# _load_stage_timings / _total_duration
# ---------------------------------------------------------------------------

class TestStageTiming:
    def test_load_timings(self):
        state = _make_state([
            ("1", "2026-04-04T10:00:00+00:00", "2026-04-04T10:00:05+00:00", "completed"),
            ("2", "2026-04-04T10:01:00+00:00", "2026-04-04T10:01:30+00:00", "completed"),
        ])
        timings = _load_stage_timings(state)
        assert len(timings) == 2
        assert timings[0]["stage"] == "1"
        assert timings[0]["durationSeconds"] == 5.0
        assert timings[1]["durationSeconds"] == 30.0

    def test_null_completed_at(self):
        state = _make_state([
            ("1", "2026-04-04T10:00:00+00:00", None, "pending"),
        ])
        timings = _load_stage_timings(state)
        assert timings[0]["durationSeconds"] is None

    def test_total_duration(self):
        timings = [
            {"startedAt": "2026-04-04T10:00:00+00:00", "completedAt": "2026-04-04T10:00:05+00:00"},
            {"startedAt": "2026-04-04T10:01:00+00:00", "completedAt": "2026-04-04T10:05:00+00:00"},
        ]
        total = _total_duration(timings)
        # From 10:00:00 to 10:05:00 = 300 seconds
        assert total == 300.0

    def test_total_duration_no_data(self):
        assert _total_duration([]) is None
        assert _total_duration([{"startedAt": None, "completedAt": None}]) is None


# ---------------------------------------------------------------------------
# build_version_manifest
# ---------------------------------------------------------------------------

class TestBuildVersionManifest:
    def test_basic_structure(self, tmp_path):
        ctx = _make_ctx(tmp_path)
        matrix = _make_matrix([
            ("src:A", "reuse"), ("src:B", "extend"),
            ("src:C", "augment"), ("src:D", "exclude"),
        ])
        vm = build_version_manifest(ctx, matrix)
        assert vm["currentVersion"] == "1.0.0"
        assert vm["targetOntology"] == "niem"
        assert vm["targetVersion"] == "6.0"
        history = vm["generationHistory"][0]
        assert history["conceptCount"] == 4
        assert history["mappingStats"] == {
            "reuse": 1, "extend": 1, "augment": 1, "exclude": 1,
        }

    def test_includes_timing_when_state_provided(self, tmp_path):
        ctx = _make_ctx(tmp_path)
        matrix = _make_matrix([("src:A", "reuse")])
        state = _make_state([
            ("1", "2026-04-04T10:00:00+00:00", "2026-04-04T10:00:05+00:00", "completed"),
        ])
        vm = build_version_manifest(ctx, matrix, state)
        assert "pipelineTiming" in vm
        assert vm["pipelineTiming"]["stages"][0]["durationSeconds"] == 5.0

    def test_no_timing_without_state(self, tmp_path):
        ctx = _make_ctx(tmp_path)
        matrix = _make_matrix([("src:A", "reuse")])
        vm = build_version_manifest(ctx, matrix)
        assert "pipelineTiming" not in vm


# ---------------------------------------------------------------------------
# build_lineage_manifest
# ---------------------------------------------------------------------------

class TestBuildLineageManifest:
    def test_tracks_ontology_files(self, tmp_path):
        ctx = _make_ctx(tmp_path)
        ont_dir = ctx.pkg_dir / "ontology"
        ont_dir.mkdir(parents=True)
        (ont_dir / "dbpi-edge-core.ttl").write_text("# core", encoding="utf-8")
        matrix = _make_matrix([("src:A", "reuse", )])
        # Fix matrix format for lineage
        matrix["mappings"][0]["targetType"] = "nc:PersonType"

        lineage = build_lineage_manifest(ctx, matrix)
        assert len(lineage["artifacts"]) >= 1
        paths = [a["artifactPath"] for a in lineage["artifacts"]]
        assert any("ontology/" in p for p in paths)

    def test_empty_package(self, tmp_path):
        ctx = _make_ctx(tmp_path)
        matrix = _make_matrix([("src:A", "reuse")])
        lineage = build_lineage_manifest(ctx, matrix)
        assert lineage["artifacts"] == []


# ---------------------------------------------------------------------------
# build_change_impact
# ---------------------------------------------------------------------------

class TestBuildChangeImpact:
    def test_includes_summary(self):
        matrix = _make_matrix([
            ("src:A", "reuse"), ("src:B", "extend"), ("src:C", "exclude"),
        ])
        md = build_change_impact(matrix, None, None)
        assert "Total concepts" in md
        assert "Extension Impact" in md

    def test_includes_validation_failures(self):
        matrix = _make_matrix([("src:A", "reuse")])
        validation = {
            "allPassed": False,
            "failCount": 1,
            "checks": [{"check": "turtle-syntax", "status": "FAIL", "details": "parse error"}],
        }
        md = build_change_impact(matrix, validation, None)
        assert "1 validation check(s) failed" in md
        assert "turtle-syntax" in md

    def test_includes_audit_warnings(self):
        matrix = _make_matrix([("src:A", "extend")])
        audit = {"findings": [{
            "severity": "warning",
            "concept": "src:A",
            "message": "Missing baseType",
        }]}
        md = build_change_impact(matrix, None, audit)
        assert "Generation Warnings" in md
        assert "Missing baseType" in md

    def test_no_extensions_skips_section(self):
        matrix = _make_matrix([("src:A", "reuse")])
        md = build_change_impact(matrix, None, None)
        assert "Extension Impact" not in md


# ---------------------------------------------------------------------------
# reconcile_manifest
# ---------------------------------------------------------------------------

class TestReconcileManifest:
    def test_adds_finalized_at(self, tmp_path):
        pkg = tmp_path / "edge-package"
        pkg.mkdir()
        manifest = {"name": "test_pkg", "generatedAt": "2026-04-04T00:00:00Z"}
        (pkg / "package-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

        matrix = _make_matrix([("src:A", "reuse"), ("src:B", "augment")])
        assert reconcile_manifest(pkg, matrix) is True

        result = json.loads((pkg / "package-manifest.json").read_text(encoding="utf-8"))
        assert "finalizedAt" in result
        assert result["version"] == "1.0.0"

    def test_action_counts_include_augment(self, tmp_path):
        pkg = tmp_path / "edge-package"
        pkg.mkdir()
        (pkg / "package-manifest.json").write_text("{}", encoding="utf-8")

        matrix = _make_matrix([
            ("src:A", "reuse"), ("src:B", "extend"),
            ("src:C", "augment"), ("src:D", "exclude"),
        ])
        reconcile_manifest(pkg, matrix)

        result = json.loads((pkg / "package-manifest.json").read_text(encoding="utf-8"))
        assert result["stats"]["totalConcepts"] == 4
        assert result["stats"]["actionCounts"] == {
            "reuse": 1, "extend": 1, "augment": 1, "exclude": 1,
        }

    def test_returns_false_when_no_manifest(self, tmp_path):
        assert reconcile_manifest(tmp_path, _make_matrix([])) is False
