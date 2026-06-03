#!/usr/bin/env python3
"""Tests for package_edge_artifacts.py — extension catalog, justifications, manifest, readme."""

import pytest

from ontology_mapper.package_edge_artifacts import (
    build_extension_justifications,
    build_extension_catalog,
    build_package_manifest,
    build_readme,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
def _matrix(mappings, summary=None):
    """Build a minimal matrix dict."""
    return {"mappings": mappings, "summary": summary or {}}


def _mapping(concept, action, target=None, **extra):
    m = {"sourceConcept": concept, "action": action}
    if target:
        m["targetType"] = target
    m.update(extra)
    return m


@pytest.fixture
def ctx():
    """Minimal PipelineContext stub."""
    class Ctx:
        organization = "testorg"
        source = "testsrc"
        target_ontology = "niem"
        target_version = "6.0"
        edge_package_name = "testorg_testsrc_edge_package"
        agency_package_name = "testorg_testsrc_agency_package"
        description = "niem-aligned edge ontology for testsrc"
        extension_namespace = "https://data.testorg.gov/ontology/testsrc/ext/"
        edge_namespace = "https://data.testorg.gov/ontology/testsrc/edge/"
        label_prefix = "Testorg TESTSRC"
    return Ctx()


# ---------------------------------------------------------------------------
# build_extension_justifications
# ---------------------------------------------------------------------------
class TestBuildExtensionJustifications:
    def test_includes_extend_entries(self):
        matrix = _matrix([
            _mapping("src:A", "extend", "nc:ActivityType", rationale="No match"),
        ])
        md = build_extension_justifications(matrix, "niem", "6.0")
        assert "Extend" in md
        assert "src:A" in md

    def test_includes_augment_entries(self):
        matrix = _matrix([
            _mapping("src:B", "augment", "nc:PersonType", rationale="Adds props"),
        ])
        md = build_extension_justifications(matrix, "niem", "6.0")
        assert "Augment" in md
        assert "src:B" in md

    def test_excludes_reuse_entries(self):
        matrix = _matrix([
            _mapping("src:C", "reuse", "nc:ActivityType"),
        ])
        md = build_extension_justifications(matrix, "niem", "6.0")
        assert "src:C" not in md

    def test_no_matchType_in_output(self):
        """matchType was removed — should not appear in output."""
        matrix = _matrix([
            _mapping("src:A", "extend", "nc:ActivityType", rationale="test"),
        ])
        md = build_extension_justifications(matrix, "niem", "6.0")
        assert "matchType" not in md.lower()
        assert "unknown" not in md.lower()


# ---------------------------------------------------------------------------
# build_extension_catalog
# ---------------------------------------------------------------------------
class TestBuildExtensionCatalog:
    def test_extend_uses_baseType(self):
        matrix = _matrix([
            _mapping("src:A", "extend", "nc:ActivityType",
                     baseType="nc:ObjectType"),
        ])
        catalog = build_extension_catalog(matrix)
        ext = catalog["extensions"][0]
        assert ext["baseType"] == "nc:ObjectType"

    def test_extend_falls_back_to_targetType(self):
        matrix = _matrix([
            _mapping("src:A", "extend", "nc:ActivityType"),
        ])
        catalog = build_extension_catalog(matrix)
        ext = catalog["extensions"][0]
        assert ext["baseType"] == "nc:ActivityType"

    def test_augment_uses_augmentsType(self):
        matrix = _matrix([
            _mapping("src:B", "augment", "nc:PersonType",
                     augmentsType="nc:PersonType",
                     augmentationType="PersonAugmentationType"),
        ])
        catalog = build_extension_catalog(matrix)
        ext = catalog["extensions"][0]
        assert ext["baseType"] == "nc:PersonType"
        assert ext["name"] == "PersonAugmentationType"

    def test_includes_both_extend_and_augment(self):
        matrix = _matrix([
            _mapping("src:A", "extend", "nc:ActivityType"),
            _mapping("src:B", "augment", "nc:PersonType",
                     augmentationType="PersonAugmentationType"),
        ])
        catalog = build_extension_catalog(matrix)
        assert len(catalog["extensions"]) == 2

    def test_excludes_reuse(self):
        matrix = _matrix([
            _mapping("src:C", "reuse", "nc:ActivityType"),
        ])
        catalog = build_extension_catalog(matrix)
        assert len(catalog["extensions"]) == 0


# ---------------------------------------------------------------------------
# build_package_manifest
# ---------------------------------------------------------------------------
class TestBuildPackageManifest:
    def test_reads_action_counts_from_summary(self, ctx):
        matrix = _matrix(
            [_mapping("src:A", "reuse"), _mapping("src:B", "extend"),
             _mapping("src:C", "augment"), _mapping("src:D", "exclude")],
            summary={
                "totalConcepts": 4,
                "actionCounts": {"reuse": 1, "extend": 1, "augment": 1, "exclude": 1},
            },
        )
        manifest = build_package_manifest(ctx, matrix)
        stats = manifest["stats"]
        assert stats["totalConcepts"] == 4
        assert stats["targetMapped"] == 1
        assert stats["targetExtended"] == 1
        assert stats["targetAugmented"] == 1
        assert stats["excluded"] == 1

    def test_falls_back_to_counting_mappings(self, ctx):
        """When summary has no actionCounts, count from mappings."""
        matrix = _matrix([
            _mapping("src:A", "reuse"),
            _mapping("src:B", "augment"),
        ])
        manifest = build_package_manifest(ctx, matrix)
        stats = manifest["stats"]
        assert stats["targetMapped"] == 1
        assert stats["targetAugmented"] == 1
        assert stats["totalConcepts"] == 2

    def test_augment_included_in_total(self, ctx):
        """Augment must be counted in totalConcepts."""
        matrix = _matrix([
            _mapping("src:A", "reuse"),
            _mapping("src:B", "augment"),
            _mapping("src:C", "extend"),
        ])
        manifest = build_package_manifest(ctx, matrix)
        assert manifest["stats"]["totalConcepts"] == 3


# ---------------------------------------------------------------------------
# build_readme
# ---------------------------------------------------------------------------
class TestBuildReadme:
    def test_includes_augment_row(self, ctx):
        matrix = _matrix([
            _mapping("src:A", "reuse"),
            _mapping("src:B", "augment"),
        ])
        readme = build_readme(ctx, matrix)
        assert "Augment" in readme
        assert "| Augment | 1 |" in readme

    def test_reads_action_counts_from_summary(self, ctx):
        matrix = _matrix(
            [_mapping("src:A", "reuse"), _mapping("src:B", "extend")],
            summary={
                "totalConcepts": 2,
                "actionCounts": {"reuse": 1, "extend": 1},
            },
        )
        readme = build_readme(ctx, matrix)
        assert "| Reuse | 1 |" in readme
        assert "| Extend | 1 |" in readme
