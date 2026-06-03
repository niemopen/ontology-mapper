#!/usr/bin/env python3
"""Tests for validate_edge_package.py — cross-reference validation helpers."""

import pytest

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
        _CMF_AUG_RECORD.format(class_ref=f"nc.PersonType", prop_ref=f"edge.augProp{i}")
        for i in range(num_augs)
    )
    content = _CMF_TEMPLATE.format(
        classes=classes, properties=properties, augmentation_records=aug_records,
    )
    cmf_path = tmp_path / "test.cmf"
    cmf_path.write_text(content, encoding="utf-8")
    return cmf_path


class TestCheckCmfConsistency:
    def test_valid_cmf_no_errors(self, tmp_path):
        cmf_path = _write_cmf(tmp_path, num_classes=2, num_props=1)
        mappings = [
            {"sourceConcept": "src:A", "action": "reuse"},
            {"sourceConcept": "src:B", "action": "extend"},
        ]
        errors = check_cmf_consistency(cmf_path, mappings)
        assert errors == []

    def test_too_few_classes(self, tmp_path):
        cmf_path = _write_cmf(tmp_path, num_classes=1, num_props=1)
        mappings = [
            {"sourceConcept": "src:A", "action": "reuse"},
            {"sourceConcept": "src:B", "action": "extend"},
        ]
        errors = check_cmf_consistency(cmf_path, mappings)
        assert len(errors) == 1
        assert "classes" in errors[0].lower()

    def test_augment_without_records(self, tmp_path):
        cmf_path = _write_cmf(tmp_path, num_classes=1, num_props=1, num_augs=0)
        mappings = [
            {"sourceConcept": "src:A", "action": "reuse"},
            {"sourceConcept": "src:B", "action": "augment"},
        ]
        errors = check_cmf_consistency(cmf_path, mappings)
        assert any("augment" in e.lower() for e in errors)

    def test_augment_with_records_ok(self, tmp_path):
        cmf_path = _write_cmf(tmp_path, num_classes=1, num_props=1, num_augs=2)
        mappings = [
            {"sourceConcept": "src:A", "action": "reuse"},
            {"sourceConcept": "src:B", "action": "augment"},
        ]
        errors = check_cmf_consistency(cmf_path, mappings)
        # No augmentation error (class count matches 1 reuse)
        assert not any("augment" in e.lower() for e in errors)

    def test_no_properties_error(self, tmp_path):
        cmf_path = _write_cmf(tmp_path, num_classes=2, num_props=0)
        mappings = [
            {"sourceConcept": "src:A", "action": "reuse"},
            {"sourceConcept": "src:B", "action": "extend"},
        ]
        errors = check_cmf_consistency(cmf_path, mappings)
        assert any("no properties" in e.lower() for e in errors)

    def test_malformed_xml(self, tmp_path):
        cmf_path = tmp_path / "bad.cmf"
        cmf_path.write_text("<broken xml", encoding="utf-8")
        errors = check_cmf_consistency(cmf_path, [])
        assert len(errors) == 1
        assert "parse error" in errors[0].lower()

    def test_excluded_actions_not_counted(self, tmp_path):
        cmf_path = _write_cmf(tmp_path, num_classes=1, num_props=1)
        mappings = [
            {"sourceConcept": "src:A", "action": "reuse"},
            {"sourceConcept": "src:B", "action": "exclude"},
            {"sourceConcept": "src:C", "action": "exclude"},
        ]
        errors = check_cmf_consistency(cmf_path, mappings)
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
