#!/usr/bin/env python3
"""Tests for validate_edge_package.py — cross-reference validation helpers."""

import pytest
import json
import subprocess
import sys


@pytest.mark.parametrize("defect", [None, "syntax", "shacl", "valid-cmf", "cmf-unbound"])
def test_cli_reports_failure_and_exit_status(tmp_path, defect):
    """Real CLI, real parsing/validation, and synthetic files only."""
    pkg = tmp_path / "edge-package"
    for directory in ("ontology", "shapes", "kg/import"):
        (pkg / directory).mkdir(parents=True, exist_ok=True)
    (tmp_path / ".mapper-state.json").write_text(json.dumps({"inputs": {
        "organization": "test", "source": "sample", "target_ontology": "example", "target_version": "1"}}))
    (tmp_path / "concept-inventory.json").write_text('{"classes": []}')
    (tmp_path / "mapping-matrix.json").write_text('{"mappings": []}')
    (tmp_path / "decision-log.json").write_text('{"decisions": []}')
    (pkg / "kg/schema.cypher").write_text("RETURN 1;")
    (pkg / "kg/import/internal-to-edge.json").write_text('{"transforms": []}')
    (pkg / "kg/import/loader-config.json").write_text('{}')
    (pkg / "ontology/smallclaims-core.ttl").write_text(
        "not turtle" if defect == "syntax" else "<urn:item> a <urn:Example> .")
    (pkg / "shapes/sample.ttl").write_text(
        '@prefix sh: <http://www.w3.org/ns/shacl#> . '
        '<urn:S> a sh:NodeShape; sh:targetClass <urn:Example>; '
        f'sh:property [sh:path <urn:value>; sh:minCount {1 if defect == "shacl" else 0}] .')
    if defect in {"valid-cmf", "cmf-unbound"}:
        from ontology_mapper.pipeline_context import load_context
        cmf = _write_cmf(tmp_path, num_classes=1, num_props=1, num_augs=1)
        content = cmf.read_text(encoding="utf-8")
        if defect == "cmf-unbound":
            content = content.replace('edge.prop0" xsi:nil', 'edge.missing" xsi:nil')
        (pkg / "cmf").mkdir()
        (pkg / "cmf" / f"{load_context(str(tmp_path)).cmf_model_stem}.cmf").write_text(content, encoding="utf-8")
    result = subprocess.run([sys.executable, "-m", "ontology_mapper.validate_edge_package", "--run-dir", str(tmp_path)],
                            capture_output=True, text=True)
    report = json.loads((tmp_path / "validation-report.json").read_text())
    expected_pass = defect in {None, "valid-cmf"}
    assert report["allPassed"] is expected_pass
    assert result.returncode == (0 if expected_pass else 1), result.stdout + result.stderr
    if defect in {"valid-cmf", "cmf-unbound"}:
        check = next(c for c in report["checks"] if c["check"] == "cmf-consistency")
        assert check["status"] == ("pass" if expected_pass else "FAIL")

from ontology_mapper.validate_edge_package import (
    check_cmf_consistency,
    check_codebook_drift,
    check_schema_labels,
    check_seed_consistency,
    check_transform_sources,
    extract_active_labels,
    validate_cmf_schema,
    _hash_definition,
)


# ---------------------------------------------------------------------------
# extract_active_labels
# ---------------------------------------------------------------------------
class TestExtractActiveLabels:
    def test_extracts_reuse_extend_augment(self):
        mappings = [
            {"sourceConcept": "src:Permit", "action": "reuse"},
            {"sourceConcept": "src:Agency", "action": "extend"},
            {"sourceConcept": "src:Person", "action": "augment"},
            {"sourceConcept": "src:Deleted", "action": "exclude"},
        ]
        labels = extract_active_labels(mappings)
        assert labels == {"Permit", "Agency", "Person"}

    def test_excludes_excluded(self):
        mappings = [{"sourceConcept": "src:Foo", "action": "exclude"}]
        assert extract_active_labels(mappings) == set()

    def test_empty_mappings(self):
        assert extract_active_labels([]) == set()


# ---------------------------------------------------------------------------
# check_schema_labels
# ---------------------------------------------------------------------------
class TestCheckSchemaLabels:
    def test_all_labels_match(self):
        schema = """\
CREATE CONSTRAINT Permit_identifier IF NOT EXISTS
  FOR (n:Permit) REQUIRE n.identifier IS UNIQUE;

CREATE CONSTRAINT Agency_identifier IF NOT EXISTS
  FOR (n:Agency) REQUIRE n.identifier IS UNIQUE;
"""
        errors = check_schema_labels(schema, {"Permit", "Agency"})
        assert errors == []

    def test_unknown_label_detected(self):
        schema = """\
CREATE CONSTRAINT Permit_identifier IF NOT EXISTS
  FOR (n:Permit) REQUIRE n.identifier IS UNIQUE;

CREATE CONSTRAINT Ghost_identifier IF NOT EXISTS
  FOR (n:Ghost) REQUIRE n.identifier IS UNIQUE;
"""
        errors = check_schema_labels(schema, {"Permit"})
        assert len(errors) == 1
        assert "Ghost" in errors[0]

    def test_index_labels_checked(self):
        schema = """\
CREATE INDEX Permit_name IF NOT EXISTS
  FOR (n:Permit) ON (n.displayName);

CREATE INDEX Unknown_name IF NOT EXISTS
  FOR (n:Unknown) ON (n.name);
"""
        errors = check_schema_labels(schema, {"Permit"})
        assert len(errors) == 1
        assert "Unknown" in errors[0]

    def test_empty_schema(self):
        errors = check_schema_labels("// empty schema", {"Permit"})
        assert errors == []


# ---------------------------------------------------------------------------
# check_seed_consistency
# ---------------------------------------------------------------------------
class TestCheckSeedConsistency:
    def test_consistent_seed(self):
        seed = """\
CREATE (:Permit {identifier: "P-001", type: "building"});
CREATE (:Agency {identifier: "A-001", name: "Planning"});

MATCH (a:Permit {identifier: "P-001"})
MATCH (b:Agency {identifier: "A-001"})
CREATE (a)-[:SUBMITTED_TO]->(b);
"""
        created, matched, errors = check_seed_consistency(seed)
        assert created == {"Permit", "Agency"}
        assert matched == {"Permit", "Agency"}
        assert errors == []

    def test_unmatched_label(self):
        seed = """\
CREATE (:Permit {identifier: "P-001"});

MATCH (a:Permit {identifier: "P-001"})
MATCH (b:Ghost {identifier: "G-001"})
CREATE (a)-[:HAS]->(b);
"""
        created, matched, errors = check_seed_consistency(seed)
        assert "Ghost" in matched
        assert "Ghost" not in created
        assert len(errors) == 1
        assert "Ghost" in errors[0]

    def test_no_relationships(self):
        seed = """\
CREATE (:Permit {identifier: "P-001"});
"""
        created, matched, errors = check_seed_consistency(seed)
        assert created == {"Permit"}
        assert matched == set()
        assert errors == []

    def test_no_seed_comment_only(self):
        seed = "// No seed data file found."
        created, matched, errors = check_seed_consistency(seed)
        assert created == set()
        assert matched == set()
        assert errors == []


# ---------------------------------------------------------------------------
# check_transform_sources
# ---------------------------------------------------------------------------
class TestCheckTransformSources:
    def test_all_sources_match(self):
        transforms = {"transforms": [
            {"sourceType": "src:Permit", "targetLabel": "Permit"},
            {"sourceType": "src:Agency", "targetLabel": "Agency"},
        ]}
        errors = check_transform_sources(transforms, {"src:Permit", "src:Agency"})
        assert errors == []

    def test_unknown_source_detected(self):
        transforms = {"transforms": [
            {"sourceType": "src:Permit", "targetLabel": "Permit"},
            {"sourceType": "src:Ghost", "targetLabel": "Ghost"},
        ]}
        errors = check_transform_sources(transforms, {"src:Permit"})
        assert len(errors) == 1
        assert "src:Ghost" in errors[0]

    def test_empty_transforms(self):
        errors = check_transform_sources({"transforms": []}, {"src:A"})
        assert errors == []

    def test_missing_transforms_key(self):
        errors = check_transform_sources({}, {"src:A"})
        assert errors == []


# ---------------------------------------------------------------------------
# check_cmf_consistency
# ---------------------------------------------------------------------------

# Minimal CMF XML template for testing
_CMF_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<Model xmlns="https://docs.oasis-open.org/niemopen/ns/specification/cmf/1.0/"
       xmlns:structures="https://docs.oasis-open.org/niemopen/ns/model/structures/6.0/"
       xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <Namespace structures:id="edge">
    <NamespaceURI>http://redvale.gov/dbpi/edge#</NamespaceURI>
    <NamespacePrefixText>edge</NamespacePrefixText>
    <NamespaceCategoryCode>EXTENSION</NamespaceCategoryCode>
    {augmentation_records}
  </Namespace>
  {classes}
  {properties}
</Model>
"""

_CMF_CLASS = """\
  <Class structures:id="{class_id}">
    <Name>{name}</Name>
    <Namespace structures:ref="edge" xsi:nil="true"/>
  </Class>
"""

_CMF_DATA_PROP = """\
  <DataProperty structures:id="{prop_id}">
    <Name>{name}</Name>
    <Namespace structures:ref="edge" xsi:nil="true"/>
  </DataProperty>
"""

_CMF_AUG_RECORD = """\
    <AugmentationRecord>
      <Class structures:ref="{class_ref}" xsi:nil="true"/>
      <DataProperty structures:ref="{prop_ref}" xsi:nil="true"/>
      <MinOccursQuantity>0</MinOccursQuantity>
      <MaxOccursQuantity>unbounded</MaxOccursQuantity>
    </AugmentationRecord>
"""


def _write_cmf(tmp_path, num_classes=2, num_props=1, num_augs=0):
    """Write a minimal CMF XML file and return its path."""
    classes = "".join(
        _CMF_CLASS.format(class_id=f"edge.Type{i}", name=f"Type{i}")
        for i in range(num_classes)
    )
    properties = "".join(
        _CMF_DATA_PROP.format(prop_id=f"edge.prop{i}", name=f"prop{i}")
        for i in range(num_props)
    )
    aug_records = "".join(
        _CMF_AUG_RECORD.format(class_ref="edge.Type0", prop_ref="edge.prop0")
        for i in range(num_augs)
    )
    content = _CMF_TEMPLATE.format(
        classes=classes, properties=properties, augmentation_records=aug_records,
    )
    cmf_path = tmp_path / "test.cmf"
    cmf_path.write_text(content, encoding="utf-8")
    return cmf_path


class TestCheckCmfConsistency:
    def test_reference_binding_does_not_depend_on_structures_prefix_spelling(self, tmp_path):
        path = _write_cmf(tmp_path, num_classes=1, num_props=1, num_augs=1)
        text = path.read_text(encoding="utf-8").replace("edge.prop0\" xsi:nil", "edge.missing\" xsi:nil")
        path.write_text(text.replace("structures:", "s:").replace("xmlns:structures=", "xmlns:s="), encoding="utf-8")
        assert validate_cmf_schema(path) == []
        assert any("edge.missing" in e for e in check_cmf_consistency(path, [], {"http://redvale.gov/dbpi/edge#"}))

    def test_valid_cmf_no_errors(self, tmp_path):
        cmf_path = _write_cmf(tmp_path, num_classes=2, num_props=1)
        mappings = [
            {"sourceConcept": "src:A", "action": "reuse"},
            {"sourceConcept": "src:B", "action": "extend"},
        ]
        errors = check_cmf_consistency(cmf_path, mappings, {"http://redvale.gov/dbpi/edge#"})
        assert errors == []

    def test_too_few_classes(self, tmp_path):
        cmf_path = _write_cmf(tmp_path, num_classes=1, num_props=1)
        mappings = [
            {"sourceConcept": "src:A", "action": "reuse"},
            {"sourceConcept": "src:B", "action": "extend"},
        ]
        errors = check_cmf_consistency(cmf_path, mappings, {"http://redvale.gov/dbpi/edge#"})
        assert len(errors) == 1
        assert "classes" in errors[0].lower()

    def test_augment_without_records(self, tmp_path):
        cmf_path = _write_cmf(tmp_path, num_classes=1, num_props=1, num_augs=0)
        mappings = [
            {"sourceConcept": "src:A", "action": "reuse"},
            {"sourceConcept": "src:B", "action": "augment"},
        ]
        errors = check_cmf_consistency(cmf_path, mappings, {"http://redvale.gov/dbpi/edge#"})
        assert any("augment" in e.lower() for e in errors)

    def test_augment_with_records_ok(self, tmp_path):
        cmf_path = _write_cmf(tmp_path, num_classes=1, num_props=1, num_augs=2)
        mappings = [
            {"sourceConcept": "src:A", "action": "reuse"},
            {"sourceConcept": "src:B", "action": "augment"},
        ]
        errors = check_cmf_consistency(cmf_path, mappings, {"http://redvale.gov/dbpi/edge#"})
        assert errors == []

    def test_no_properties_error(self, tmp_path):
        cmf_path = _write_cmf(tmp_path, num_classes=2, num_props=0)
        mappings = [
            {"sourceConcept": "src:A", "action": "reuse"},
            {"sourceConcept": "src:B", "action": "extend"},
        ]
        errors = check_cmf_consistency(cmf_path, mappings, {"http://redvale.gov/dbpi/edge#"})
        assert any("no properties" in e.lower() for e in errors)

    def test_malformed_xml(self, tmp_path):
        cmf_path = tmp_path / "bad.cmf"
        cmf_path.write_text("<broken xml", encoding="utf-8")
        errors = check_cmf_consistency(cmf_path, [], {"http://redvale.gov/dbpi/edge#"})
        assert len(errors) == 1
        assert "parse error" in errors[0].lower()

    def test_excluded_actions_not_counted(self, tmp_path):
        cmf_path = _write_cmf(tmp_path, num_classes=1, num_props=1)
        mappings = [
            {"sourceConcept": "src:A", "action": "reuse"},
            {"sourceConcept": "src:B", "action": "exclude"},
            {"sourceConcept": "src:C", "action": "exclude"},
        ]
        errors = check_cmf_consistency(cmf_path, mappings, {"http://redvale.gov/dbpi/edge#"})
        assert errors == []


# ---------------------------------------------------------------------------
# validate_cmf_schema
# ---------------------------------------------------------------------------

class TestValidateCmfSchema:
    def test_valid_cmf_passes(self, tmp_path):
        cmf_path = _write_cmf(tmp_path, num_classes=1, num_props=1)
        errors = validate_cmf_schema(cmf_path)
        assert errors == []

    def test_invalid_cmf_reports_errors(self, tmp_path):
        """Missing required NamespaceCategoryCode triggers XSD error."""
        content = """\
<?xml version="1.0" encoding="UTF-8"?>
<Model xmlns="https://docs.oasis-open.org/niemopen/ns/specification/cmf/1.0/"
       xmlns:structures="https://docs.oasis-open.org/niemopen/ns/model/structures/6.0/">
  <Namespace structures:id="edge">
    <NamespaceURI>http://example.com/edge#</NamespaceURI>
    <NamespacePrefixText>edge</NamespacePrefixText>
  </Namespace>
</Model>
"""
        cmf_path = tmp_path / "bad.cmf"
        cmf_path.write_text(content, encoding="utf-8")
        errors = validate_cmf_schema(cmf_path)
        assert len(errors) >= 1
        assert any("NamespaceCategoryCode" in e for e in errors)

    def test_malformed_xml(self, tmp_path):
        cmf_path = tmp_path / "broken.cmf"
        cmf_path.write_text("<broken xml", encoding="utf-8")
        errors = validate_cmf_schema(cmf_path)
        assert len(errors) == 1
        assert "parse error" in errors[0].lower()


# ---------------------------------------------------------------------------
# check_codebook_drift
# ---------------------------------------------------------------------------
def _catalog_with_types(types, properties=None):
    """Build a minimal catalog for drift testing."""
    catalog = {"types": types, "propertyIndex": {}}
    if properties:
        for qp, defn in properties.items():
            ns = qp.split(":")[0]
            if ns not in catalog["propertyIndex"]:
                catalog["propertyIndex"][ns] = {"properties": [], "propertyCount": 0}
            catalog["propertyIndex"][ns]["properties"].append({
                "name": qp.split(":")[-1],
                "qualifiedProperty": qp,
                "definition": defn,
                "containingTypes": [],
            })
            catalog["propertyIndex"][ns]["propertyCount"] += 1
    return catalog


class TestCheckCodebookDrift:

    def test_no_drift(self):
        defn = "A data type for a person."
        h = _hash_definition(defn)
        catalog = _catalog_with_types([
            {"qname": "nc:PersonType", "definition": defn},
        ])
        mappings = [{
            "sourceConcept": "src:Person",
            "targetType": "nc:PersonType",
            "targetDefinitionHash": h,
            "propertyMappings": [],
        }]
        errors = check_codebook_drift(mappings, catalog)
        assert errors == []

    def test_type_definition_changed(self):
        old_defn = "A data type for a person."
        new_defn = "A data type for an individual."
        old_hash = _hash_definition(old_defn)
        catalog = _catalog_with_types([
            {"qname": "nc:PersonType", "definition": new_defn},
        ])
        mappings = [{
            "sourceConcept": "src:Person",
            "targetType": "nc:PersonType",
            "targetDefinitionHash": old_hash,
            "propertyMappings": [],
        }]
        errors = check_codebook_drift(mappings, catalog)
        assert len(errors) == 1
        assert "definition changed" in errors[0]
        assert "nc:PersonType" in errors[0]

    def test_type_not_found(self):
        catalog = _catalog_with_types([])
        mappings = [{
            "sourceConcept": "src:Person",
            "targetType": "nc:PersonType",
            "targetDefinitionHash": "abc123",
            "propertyMappings": [],
        }]
        errors = check_codebook_drift(mappings, catalog)
        assert len(errors) == 1
        assert "not found" in errors[0]

    def test_property_no_drift(self):
        prop_defn = "A name of a person."
        prop_hash = _hash_definition(prop_defn)
        catalog = _catalog_with_types(
            [{"qname": "nc:PersonType", "definition": "A person."}],
            properties={"nc:PersonName": prop_defn},
        )
        mappings = [{
            "sourceConcept": "src:Person",
            "targetType": "nc:PersonType",
            "targetDefinitionHash": _hash_definition("A person."),
            "propertyMappings": [{
                "sourceProperty": "src:name",
                "targetPath": "nc:PersonName",
                "targetDefinitionHash": prop_hash,
            }],
        }]
        errors = check_codebook_drift(mappings, catalog)
        assert errors == []

    def test_property_definition_changed(self):
        old_prop_defn = "A name of a person."
        new_prop_defn = "A full name of an individual."
        catalog = _catalog_with_types(
            [{"qname": "nc:PersonType", "definition": "A person."}],
            properties={"nc:PersonName": new_prop_defn},
        )
        mappings = [{
            "sourceConcept": "src:Person",
            "targetType": "nc:PersonType",
            "targetDefinitionHash": _hash_definition("A person."),
            "propertyMappings": [{
                "sourceProperty": "src:name",
                "targetProperty": "nc:PersonName",
                "targetDefinitionHash": _hash_definition(old_prop_defn),
            }],
        }]
        errors = check_codebook_drift(mappings, catalog)
        assert len(errors) == 1
        assert "nc:PersonName" in errors[0]
        assert "definition changed" in errors[0]

    def test_property_not_found(self):
        catalog = _catalog_with_types(
            [{"qname": "nc:PersonType", "definition": "A person."}],
        )
        mappings = [{
            "sourceConcept": "src:Person",
            "targetType": "nc:PersonType",
            "targetDefinitionHash": _hash_definition("A person."),
            "propertyMappings": [{
                "sourceProperty": "src:name",
                "targetProperty": "nc:GhostProperty",
                "targetDefinitionHash": "abc123",
            }],
        }]
        errors = check_codebook_drift(mappings, catalog)
        assert len(errors) == 1
        assert "not found" in errors[0]

    def test_null_hash_skipped(self):
        catalog = _catalog_with_types([
            {"qname": "nc:PersonType", "definition": "A person."},
        ])
        mappings = [{
            "sourceConcept": "src:Person",
            "targetType": "nc:PersonType",
            "targetDefinitionHash": None,
            "propertyMappings": [],
        }]
        errors = check_codebook_drift(mappings, catalog)
        assert errors == []

    def test_no_target_type_skipped(self):
        catalog = _catalog_with_types([])
        mappings = [{
            "sourceConcept": "src:New",
            "targetType": None,
            "targetDefinitionHash": None,
            "propertyMappings": [],
        }]
        errors = check_codebook_drift(mappings, catalog)
        assert errors == []

    def test_undecided_property_skipped(self):
        catalog = _catalog_with_types(
            [{"qname": "nc:PersonType", "definition": "A person."}],
        )
        mappings = [{
            "sourceConcept": "src:Person",
            "targetType": "nc:PersonType",
            "targetDefinitionHash": _hash_definition("A person."),
            "propertyMappings": [{
                "sourceProperty": "src:x",
                "targetProperty": "[undecided]",
                "targetDefinitionHash": "abc123",
            }],
        }]
        errors = check_codebook_drift(mappings, catalog)
        assert errors == []

    def test_empty_mappings(self):
        catalog = _catalog_with_types([])
        errors = check_codebook_drift([], catalog)
        assert errors == []

    def test_multiple_drift_errors(self):
        catalog = _catalog_with_types([
            {"qname": "nc:PersonType", "definition": "Changed."},
            {"qname": "j:CourtEventType", "definition": "Also changed."},
        ])
        mappings = [
            {
                "sourceConcept": "src:Person",
                "targetType": "nc:PersonType",
                "targetDefinitionHash": _hash_definition("Original person."),
                "propertyMappings": [],
            },
            {
                "sourceConcept": "src:Event",
                "targetType": "j:CourtEventType",
                "targetDefinitionHash": _hash_definition("Original event."),
                "propertyMappings": [],
            },
        ]
        errors = check_codebook_drift(mappings, catalog)
        assert len(errors) == 2


class TestStaleValidationReport:
    """A report certifies the artifacts as they were when it ran."""

    def test_a_report_older_than_the_package_names_the_newer_file(self, tmp_path):
        import os
        from ontology_mapper.validate_edge_package import stale_against_package

        report = tmp_path / "validation-report.json"
        report.write_text("{}", encoding="utf-8")
        pkg = tmp_path / "edge-package" / "ontology"
        pkg.mkdir(parents=True)
        artifact = pkg / "core.ttl"
        artifact.write_text("# later", encoding="utf-8")
        stamp = report.stat().st_mtime_ns
        os.utime(artifact, ns=(stamp + 10_000_000, stamp + 10_000_000))

        assert "core.ttl" in stale_against_package(report, tmp_path / "edge-package")

    def test_stage_8s_own_output_does_not_make_the_report_stale(self, tmp_path):
        """governance/ is finalize's output, written after Stage 7 ran. Counting
        it made a second `om-finalize` refuse its own first run."""
        import os
        from ontology_mapper.validate_edge_package import stale_against_package

        pkg = tmp_path / "edge-package"
        (pkg / "ontology").mkdir(parents=True)
        (pkg / "ontology" / "core.ttl").write_text("# stage 6", encoding="utf-8")
        report = tmp_path / "validation-report.json"
        report.write_text("{}", encoding="utf-8")
        stamp = (pkg / "ontology" / "core.ttl").stat().st_mtime_ns
        os.utime(report, ns=(stamp + 10_000_000, stamp + 10_000_000))

        (pkg / "governance").mkdir()
        manifest = pkg / "governance" / "version-manifest.json"
        manifest.write_text("{}", encoding="utf-8")
        later = report.stat().st_mtime_ns + 10_000_000
        os.utime(manifest, ns=(later, later))

        assert stale_against_package(report, pkg) is None

    def test_a_report_newer_than_the_package_is_current(self, tmp_path):
        import os
        from ontology_mapper.validate_edge_package import stale_against_package

        pkg = tmp_path / "edge-package" / "ontology"
        pkg.mkdir(parents=True)
        (pkg / "core.ttl").write_text("# earlier", encoding="utf-8")
        report = tmp_path / "validation-report.json"
        report.write_text("{}", encoding="utf-8")
        stamp = (pkg / "core.ttl").stat().st_mtime_ns
        os.utime(report, ns=(stamp + 10_000_000, stamp + 10_000_000))

        assert stale_against_package(report, tmp_path / "edge-package") is None

    def test_a_missing_package_is_not_covered(self, tmp_path):
        """A report with recorded digests and no package directory was read
        as covering it: verify said "covers the package as validated" and
        finalize published a package holding only its governance files."""
        from ontology_mapper.validate_edge_package import stale_against_package

        report = tmp_path / "validation-report.json"
        report.write_text('{"validatedArtifacts": {"ontology/core.ttl": "x"}}',
                          encoding="utf-8")
        missing = tmp_path / "edge-package"
        assert stale_against_package(report, missing) == str(missing)


class TestDriftOnALegacyFullIriTarget:
    """A matrix saved before selections were canonicalized holds a target's
    full IRI; it names the catalog class, so it is not missing from it."""

    def test_a_full_iri_target_is_looked_up_by_its_catalog_qname(self):
        from ontology_mapper.validate_edge_package import check_codebook_drift
        catalog = {"namespaces": {"nc": "https://example.org/nc/"},
                   "types": [{"qname": "nc:PersonType", "definition": "A person."}]}
        entry = {"sourceConcept": "src:Person", "targetType": "https://example.org/nc/PersonType"}
        assert check_codebook_drift([entry], catalog) == []

    def test_an_iri_outside_the_catalog_is_still_reported(self):
        from ontology_mapper.validate_edge_package import check_codebook_drift
        catalog = {"namespaces": {"nc": "https://example.org/nc/"}, "types": []}
        entry = {"sourceConcept": "src:Person", "targetType": "https://elsewhere.test/Thing"}
        assert "not found in catalog" in check_codebook_drift([entry], catalog)[0]


class TestDriftOnAMissingTarget:
    """A target that left the catalog is drift whether or not the matrix
    recorded a fingerprint for it."""

    def test_a_target_absent_from_the_catalog_is_reported_without_a_hash(self):
        errors = check_codebook_drift(
            [{"sourceConcept": "src:A", "targetType": "nc:GoneType",
              "targetDefinitionHash": None, "propertyMappings": []}],
            _catalog_with_types([{"qname": "nc:PersonType", "definition": "A person."}]))
        assert errors == ["src:A: target type nc:GoneType not found in catalog"]


class TestTheReportSpeaksByContent:
    """A validation report certifies file contents, not a moment in time."""

    def _package(self, tmp_path):
        pkg = tmp_path / "edge-package"
        (pkg / "ontology").mkdir(parents=True)
        (pkg / "ontology" / "core.ttl").write_text("# first", encoding="utf-8")
        (pkg / "package-manifest.json").write_text("{}", encoding="utf-8")
        return pkg

    def _report(self, tmp_path, pkg):
        from ontology_mapper.validate_edge_package import artifact_digests
        report = tmp_path / "validation-report.json"
        report.write_text(json.dumps({"validatedArtifacts": artifact_digests(pkg)}),
                          encoding="utf-8")
        return report

    def test_a_rewrite_inside_one_timestamp_tick_is_still_named(self, tmp_path):
        """The defect a clock cannot see: regenerating the package takes less
        than a filesystem timestamp tick, so the report looks newer than the
        files it should have refused."""
        import os
        from ontology_mapper.validate_edge_package import stale_against_package

        pkg = self._package(tmp_path)
        report = self._report(tmp_path, pkg)
        artifact = pkg / "ontology" / "core.ttl"
        artifact.write_text("# regenerated", encoding="utf-8")
        stamp = report.stat().st_mtime_ns
        os.utime(artifact, ns=(stamp, stamp))

        assert stale_against_package(report, pkg).endswith("core.ttl")

    def test_an_unchanged_package_is_current(self, tmp_path):
        from ontology_mapper.validate_edge_package import stale_against_package

        pkg = self._package(tmp_path)
        report = self._report(tmp_path, pkg)
        assert stale_against_package(report, pkg) is None

    def test_a_deleted_artifact_is_named(self, tmp_path):
        from ontology_mapper.validate_edge_package import stale_against_package

        pkg = self._package(tmp_path)
        report = self._report(tmp_path, pkg)
        (pkg / "ontology" / "core.ttl").unlink()
        assert stale_against_package(report, pkg).endswith("core.ttl")

    def test_stage_8_own_output_is_not_evidence_of_staleness(self, tmp_path):
        """`governance/` and the root manifest are finalize's own work, so a
        second finalize must not read its first run as an invalidated report."""
        from ontology_mapper.validate_edge_package import stale_against_package

        pkg = self._package(tmp_path)
        report = self._report(tmp_path, pkg)
        (pkg / "governance").mkdir()
        (pkg / "governance" / "version-manifest.json").write_text(
            '{"currentVersion": "1.0.0"}', encoding="utf-8")
        (pkg / "package-manifest.json").write_text(
            '{"finalizedAt": "now"}', encoding="utf-8")

        assert stale_against_package(report, pkg) is None


class TestGovernanceFilesStage7Validates:
    """`governance/` is not all Stage 8's: Stage 6b writes the decision log
    there and Stage 7's decision-log check reads it."""

    def _package(self, tmp_path):
        pkg = tmp_path / "edge-package"
        (pkg / "ontology").mkdir(parents=True)
        (pkg / "ontology" / "core.ttl").write_text("# core", encoding="utf-8")
        (pkg / "governance").mkdir()
        (pkg / "governance" / "decision-log.json").write_text(
            '{"decisions": []}', encoding="utf-8")
        (pkg / "package-manifest.json").write_text("{}", encoding="utf-8")
        return pkg

    def _report(self, tmp_path, pkg):
        from ontology_mapper.validate_edge_package import artifact_digests
        report = tmp_path / "validation-report.json"
        report.write_text(json.dumps({"validatedArtifacts": artifact_digests(pkg)}),
                          encoding="utf-8")
        return report

    def test_a_decision_log_replaced_after_validation_is_named(self):
        """Stage 7 counts the decisions in this file. Excluding the whole
        `governance/` directory let Stage 8 publish a PASS beside a log that
        was rewritten after the count."""
        import tempfile
        from pathlib import Path
        from ontology_mapper.validate_edge_package import stale_against_package

        tmp_path = Path(tempfile.mkdtemp())
        pkg = self._package(tmp_path)
        report = self._report(tmp_path, pkg)
        (pkg / "governance" / "decision-log.json").write_text(
            '{"decisions": [{"concept": "src:A"}]}', encoding="utf-8")

        assert "decision-log.json" in stale_against_package(report, pkg)

    def test_stage_8_own_governance_files_are_still_not_staleness(self):
        import tempfile
        from pathlib import Path
        from ontology_mapper.validate_edge_package import stale_against_package

        tmp_path = Path(tempfile.mkdtemp())
        pkg = self._package(tmp_path)
        report = self._report(tmp_path, pkg)
        for name, body in (("version-manifest.json", "{}"),
                           ("lineage-manifest.json", "{}"),
                           ("validation-report.json", "{}"),
                           ("change-impact.md", "# impact")):
            (pkg / "governance" / name).write_text(body, encoding="utf-8")
        (pkg / "package-manifest.json").write_text(
            '{"finalizedAt": "now"}', encoding="utf-8")

        assert stale_against_package(report, pkg) is None
