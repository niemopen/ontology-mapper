#!/usr/bin/env python3
"""Tests for package_edge_artifacts.py — extension catalog, justifications, manifest, readme."""

import pathlib
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
    m = {"sourceConcept": concept, "action": action, "reviewStatus": "accepted"}
    if target:
        m["targetType"] = target
    m.update(extra)
    return m


def _catalog(matrix):
    from pathlib import Path
    from ontology_mapper.pipeline_context import PipelineContext
    context = PipelineContext(Path("run"), Path("run/edge-package"), "example", "source", "niem", "6.0")
    inventory = {"classes": [{"qname": m["sourceConcept"], "iri": "urn:source#" + m["sourceConcept"].split(":")[-1]}
                             for m in matrix["mappings"]], "objectProperties": [], "datatypeProperties": []}
    return build_extension_catalog(matrix, context, inventory, {})


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
    def test_created_properties_are_full_iris_and_belong_to_each_owner(self, tmp_path):
        from ontology_mapper.pipeline_context import PipelineContext
        context = PipelineContext(tmp_path, tmp_path / "edge-package", "sample", "source", "niem", "6.0")
        inventory = {
            "classes": [{"qname": "src:A", "iri": "urn:source#A"},
                        {"qname": "src:B", "iri": "urn:source#B"}],
            "datatypeProperties": [{"qname": "src:value"}, {"qname": "extra:code"}],
            "objectProperties": [],
            "namespaceMap": {"https://source.example/extra#": "extra:"},
        }
        properties = [
            {"sourceProperty": "src:value", "action": "create-property", "reviewStatus": "accepted"},
            {"sourceProperty": "extra:code", "action": "create-property", "reviewStatus": "accepted"},
            {"sourceProperty": "src:reused", "action": "reuse-property", "reviewStatus": "accepted", "targetProperty": "nc:Name"},
            {"sourceProperty": "src:pending", "action": "create-property", "reviewStatus": "pending-review"},
        ]
        matrix = _matrix([_mapping("src:A", "extend", "nc:RecordType", propertyMappings=properties),
                          _mapping("src:B", "augment", "nc:RecordType", propertyMappings=properties)])
        catalog = build_extension_catalog(matrix, context, inventory, {"extra": "https://target.example/extra/"})
        for entry in catalog["extensions"]:
            assert entry["extensionIRI"].startswith(context.extension_namespace)
            assert entry["sourceConceptIRI"] in {"urn:source#A", "urn:source#B"}
            assert entry["properties"] == sorted([
                context.extension_namespace + "value", "https://source.example/extra#code"])

    def test_extend_uses_baseType(self):
        matrix = _matrix([
            _mapping("src:A", "extend", "nc:ActivityType",
                     baseType="nc:ObjectType"),
        ])
        catalog = _catalog(matrix)
        ext = catalog["extensions"][0]
        assert ext["baseType"] == "nc:ObjectType"

    def test_extend_falls_back_to_targetType(self):
        matrix = _matrix([
            _mapping("src:A", "extend", "nc:ActivityType"),
        ])
        catalog = _catalog(matrix)
        ext = catalog["extensions"][0]
        assert ext["baseType"] == "nc:ActivityType"

    def test_augment_uses_augmentsType(self):
        matrix = _matrix([
            _mapping("src:B", "augment", "nc:PersonType",
                     augmentsType="nc:PersonType",
                     augmentationType="PersonAugmentationType"),
        ])
        catalog = _catalog(matrix)
        ext = catalog["extensions"][0]
        assert ext["baseType"] == "nc:PersonType"
        assert ext["name"] == "PersonAugmentationType"

    def test_includes_both_extend_and_augment(self):
        matrix = _matrix([
            _mapping("src:A", "extend", "nc:ActivityType"),
            _mapping("src:B", "augment", "nc:PersonType",
                     augmentationType="PersonAugmentationType"),
        ])
        catalog = _catalog(matrix)
        assert len(catalog["extensions"]) == 2

    def test_excludes_reuse(self):
        matrix = _matrix([
            _mapping("src:C", "reuse", "nc:ActivityType"),
        ])
        catalog = _catalog(matrix)
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

def test_component_identities_survive_a_namespace_without_a_separator():
    """`urn:example:model` + `value` is `urn:example:model:value`, not
    `urn:example:modelvalue` — and every identity the extension catalog writes
    reads back to the name it was built from."""
    from ontology_mapper.generation_utils import component_iri, local_name

    for namespace in ("urn:example:model", "urn:example:model#", "https://example.test/ns",
                      "https://example.test/ns/", "https://example.test/ns#"):
        iri = component_iri(namespace, "value")
        assert iri != namespace + "value" or namespace[-1] in "/#:"
        assert local_name(iri) == "value"


class TestCreatedPropertyNamespaces:
    """The extension catalog is the one artifact built by walking the
    decisions rather than the inventory, so it alone meets a recorded
    property name the resolver could not resolve."""

    def _inventory(self):
        return {"classes": [{"qname": "src:Thing", "iri": "https://src.test/ns#Thing"}],
                "namespaceMap": {"https://src.test/ns#": "src:",
                                 "https://abc.test/ns#": "abc:"},
                "objectProperties": [],
                "datatypeProperties": [{"qname": "src:flag"}, {"qname": "abc:flag"}]}

    def _context(self):
        from pathlib import Path
        from ontology_mapper.pipeline_context import PipelineContext
        return PipelineContext(Path("run"), Path("run/edge-package"),
                               "example", "source", "niem", "6.0")

    def _matrix_with(self, source_property):
        return _matrix([_mapping("src:Thing", "extend", "nc:PersonType",
                                 baseType="nc:PersonType",
                                 propertyMappings=[{"sourceProperty": source_property,
                                                    "action": "create-property",
                                                    "reviewStatus": "accepted"}])])

    def test_a_decision_naming_an_unbound_prefix_is_reported_not_indexed(self):
        """`property_qname_resolver` returns an ambiguous name unchanged, so
        a prefix bound to no namespace reaches the catalog. It cannot invent
        an IRI for it, and dying on the dict lookup names no decision.
        """
        with pytest.raises(ValueError, match="cannot qualify"):
            build_extension_catalog(self._matrix_with("legacy:flag"),
                                    self._context(), self._inventory(), {})

    def test_a_decision_naming_a_declared_property_still_mints_its_iri(self):
        """The legitimate flow: a bound source prefix keeps its namespace."""
        catalog = build_extension_catalog(self._matrix_with("abc:flag"),
                                          self._context(), self._inventory(), {})
        assert catalog["extensions"][0]["properties"] == ["https://abc.test/ns#flag"]


class TestUnqualifiableDecisionsAreCountedPerRun:
    """The reviewer reopens review once, not once per offending mapping."""

    def test_every_offending_mapping_is_named_in_one_refusal(self):
        from pathlib import Path
        from ontology_mapper.pipeline_context import PipelineContext
        context = PipelineContext(Path("run"), Path("run/edge-package"),
                                  "example", "source", "niem", "6.0")
        inventory = {"classes": [{"qname": "src:A", "iri": "https://src.test/ns#A"},
                                 {"qname": "src:B", "iri": "https://src.test/ns#B"}],
                     "namespaceMap": {"https://src.test/ns#": "src:"},
                     "objectProperties": [],
                     "datatypeProperties": [{"qname": "src:flag"},
                                            {"qname": "abc:flag"}]}
        def _entry(concept, source_property):
            return _mapping(concept, "extend", "nc:PersonType",
                            baseType="nc:PersonType",
                            propertyMappings=[{"sourceProperty": source_property,
                                               "action": "create-property",
                                               "reviewStatus": "accepted"}])
        matrix = _matrix([_entry("src:A", "ghost1:flag"),
                          _entry("src:B", "ghost2:flag")])
        with pytest.raises(ValueError) as caught:
            build_extension_catalog(matrix, context, inventory, {})
        message = str(caught.value)
        assert message.startswith("2 accepted created-property")
        assert "src:A" in message and "src:B" in message
