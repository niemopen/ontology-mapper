#!/usr/bin/env python3
"""Tests for generation_audit.py — matrix integrity checks before generation."""

import pytest
from ontology_mapper.generation_audit import audit_generation


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════

def _inv(classes=None, obj_props=None, dt_props=None):
    """Build a minimal concept inventory."""
    return {
        "classes": classes or [],
        "objectProperties": obj_props or [],
        "datatypeProperties": dt_props or [],
        "shaclShapes": [],
    }


def _matrix(mappings, target_ontology="niem"):
    """Build a minimal mapping matrix."""
    return {
        "targetOntology": target_ontology,
        "targetVersion": "6.0",
        "mappings": mappings,
    }


def _mapping(concept, action="reuse", target_type="nc:ThingType",
             property_mappings=None, **kwargs):
    """Build a minimal mapping entry."""
    m = {
        "sourceConcept": concept,
        "action": action,
        "targetType": target_type,
    }
    if property_mappings is not None:
        m["propertyMappings"] = property_mappings
    m.update(kwargs)
    return m


def _prop_mapping(source, action="reuse-property", target=None):
    return {
        "sourceProperty": source,
        "action": action,
        "targetProperty": target,
    }


def _find(findings, code):
    """Filter findings by code."""
    return [f for f in findings if f["code"] == code]


# ═══════════════════════════════════════════════════════════════════════════
# GA-001: Active class with zero source properties
# ═══════════════════════════════════════════════════════════════════════════

class TestGA001:

    def test_flags_reuse_with_zero_properties(self):
        inv = _inv(classes=[{"qname": "x:Empty"}])
        matrix = _matrix([_mapping("x:Empty")])
        findings = _find(audit_generation(inv, matrix), "GA-001")
        assert len(findings) == 1
        assert "zero source properties" in findings[0]["message"]

    def test_no_flag_when_properties_exist(self):
        inv = _inv(
            classes=[{"qname": "x:Case"}],
            obj_props=[{"qname": "x:hasJudge", "domain": ["x:Case"], "range": []}],
        )
        matrix = _matrix([_mapping("x:Case")])
        findings = _find(audit_generation(inv, matrix), "GA-001")
        assert len(findings) == 0

    def test_counts_datatype_properties(self):
        inv = _inv(
            classes=[{"qname": "x:Case"}],
            dt_props=[{"qname": "x:caseNum", "domain": ["x:Case"], "range": []}],
        )
        matrix = _matrix([_mapping("x:Case")])
        findings = _find(audit_generation(inv, matrix), "GA-001")
        assert len(findings) == 0

    def test_flags_augment_with_zero_properties(self):
        inv = _inv(classes=[{"qname": "x:Empty"}])
        matrix = _matrix([_mapping("x:Empty", action="augment",
                                   augmentationType="x-edge:EmptyAugType",
                                   augmentsType="nc:ThingType")])
        findings = _find(audit_generation(inv, matrix), "GA-001")
        assert len(findings) == 1
        assert "Augment" in findings[0]["message"]


# ═══════════════════════════════════════════════════════════════════════════
# GA-002: Augment action on non-NIEM flow
# ═══════════════════════════════════════════════════════════════════════════

class TestGA002:

    def test_flags_augment_on_owl(self):
        inv = _inv()
        matrix = _matrix(
            [_mapping("x:Thing", action="augment",
                      augmentationType="x-edge:ThingAugType",
                      augmentsType="folio:ThingType")],
            target_ontology="sali-folio",
        )
        findings = _find(audit_generation(inv, matrix), "GA-002")
        assert len(findings) == 1
        assert "not NIEM" in findings[0]["message"]

    def test_no_flag_on_niem(self):
        inv = _inv()
        matrix = _matrix(
            [_mapping("x:Thing", action="augment",
                      augmentationType="x-edge:ThingAugType",
                      augmentsType="nc:ThingType")],
            target_ontology="niem",
        )
        findings = _find(audit_generation(inv, matrix), "GA-002")
        assert len(findings) == 0

    def test_no_flag_for_reuse_on_owl(self):
        inv = _inv()
        matrix = _matrix([_mapping("x:Thing")], target_ontology="sali-folio")
        findings = _find(audit_generation(inv, matrix), "GA-002")
        assert len(findings) == 0


# ═══════════════════════════════════════════════════════════════════════════
# GA-003: Augment entry with zero reuse-properties
# ═══════════════════════════════════════════════════════════════════════════

class TestGA003:

    def test_flags_all_create_properties(self):
        inv = _inv()
        matrix = _matrix([_mapping(
            "x:Person", action="augment",
            augmentationType="x-edge:PersonAugType",
            augmentsType="nc:PersonType",
            property_mappings=[
                _prop_mapping("x:foo", action="create-property"),
                _prop_mapping("x:bar", action="create-property"),
            ],
        )])
        findings = _find(audit_generation(inv, matrix), "GA-003")
        assert len(findings) == 1
        assert "none are reuse-property" in findings[0]["message"]

    def test_no_flag_when_reuse_properties_exist(self):
        inv = _inv()
        matrix = _matrix([_mapping(
            "x:Person", action="augment",
            augmentationType="x-edge:PersonAugType",
            augmentsType="nc:PersonType",
            property_mappings=[
                _prop_mapping("x:name", action="reuse-property", target="nc:PersonName"),
                _prop_mapping("x:foo", action="create-property"),
            ],
        )])
        findings = _find(audit_generation(inv, matrix), "GA-003")
        assert len(findings) == 0

    def test_no_flag_when_no_property_mappings(self):
        """Empty property mappings is caught by GA-001/GA-004, not GA-003."""
        inv = _inv()
        matrix = _matrix([_mapping(
            "x:Person", action="augment",
            augmentationType="x-edge:PersonAugType",
            augmentsType="nc:PersonType",
        )])
        findings = _find(audit_generation(inv, matrix), "GA-003")
        assert len(findings) == 0

    def test_no_flag_for_extend(self):
        inv = _inv()
        matrix = _matrix([_mapping(
            "x:Thing", action="extend",
            extensionType="x-edge:ThingType",
            baseType="nc:ThingType",
            property_mappings=[_prop_mapping("x:foo", action="create-property")],
        )])
        findings = _find(audit_generation(inv, matrix), "GA-003")
        assert len(findings) == 0


# ═══════════════════════════════════════════════════════════════════════════
# GA-004: Concept with source properties but no property mappings
# ═══════════════════════════════════════════════════════════════════════════

class TestGA004:

    def test_flags_missing_property_mappings(self):
        inv = _inv(
            classes=[{"qname": "x:Case"}],
            obj_props=[{"qname": "x:hasJudge", "domain": ["x:Case"], "range": []}],
        )
        matrix = _matrix([_mapping("x:Case")])  # no propertyMappings key
        findings = _find(audit_generation(inv, matrix), "GA-004")
        assert len(findings) == 1
        assert "lost between Stage 3 and Stage 4" in findings[0]["message"]

    def test_no_flag_when_property_mappings_present(self):
        inv = _inv(
            classes=[{"qname": "x:Case"}],
            obj_props=[{"qname": "x:hasJudge", "domain": ["x:Case"], "range": []}],
        )
        matrix = _matrix([_mapping(
            "x:Case",
            property_mappings=[_prop_mapping("x:hasJudge", target="j:Judge")],
        )])
        findings = _find(audit_generation(inv, matrix), "GA-004")
        assert len(findings) == 0

    def test_no_flag_when_zero_source_properties(self):
        """Zero source properties is GA-001, not GA-004."""
        inv = _inv(classes=[{"qname": "x:Empty"}])
        matrix = _matrix([_mapping("x:Empty")])
        findings = _find(audit_generation(inv, matrix), "GA-004")
        assert len(findings) == 0


# ═══════════════════════════════════════════════════════════════════════════
# GA-005: Scaffolding consistency
# ═══════════════════════════════════════════════════════════════════════════

class TestGA005:

    def test_extend_missing_extension_type(self):
        inv = _inv()
        matrix = _matrix([_mapping("x:Thing", action="extend", baseType="nc:ThingType")])
        findings = _find(audit_generation(inv, matrix), "GA-005")
        assert len(findings) == 1
        assert "extensionType" in findings[0]["message"]

    def test_extend_missing_base_type(self):
        inv = _inv()
        matrix = _matrix([_mapping("x:Thing", action="extend",
                                   extensionType="x-edge:ThingType")])
        findings = _find(audit_generation(inv, matrix), "GA-005")
        assert len(findings) == 1

    def test_extend_complete_scaffolding(self):
        inv = _inv()
        matrix = _matrix([_mapping("x:Thing", action="extend",
                                   extensionType="x-edge:ThingType",
                                   baseType="nc:ThingType")])
        findings = _find(audit_generation(inv, matrix), "GA-005")
        assert len(findings) == 0

    def test_augment_missing_augmentation_type(self):
        inv = _inv()
        matrix = _matrix([_mapping("x:Person", action="augment",
                                   augmentsType="nc:PersonType")])
        findings = _find(audit_generation(inv, matrix), "GA-005")
        assert len(findings) == 1
        assert "augmentationType" in findings[0]["message"]

    def test_augment_complete_scaffolding(self):
        inv = _inv()
        matrix = _matrix([_mapping("x:Person", action="augment",
                                   augmentationType="x-edge:PersonAugType",
                                   augmentsType="nc:PersonType")])
        findings = _find(audit_generation(inv, matrix), "GA-005")
        assert len(findings) == 0

    def test_reuse_with_unexpected_scaffolding(self):
        inv = _inv()
        matrix = _matrix([_mapping("x:Case", action="reuse",
                                   extensionType="x-edge:CaseType")])
        findings = _find(audit_generation(inv, matrix), "GA-005")
        assert len(findings) == 1
        assert "should not be present" in findings[0]["message"]

    def test_reuse_clean(self):
        inv = _inv()
        matrix = _matrix([_mapping("x:Case", action="reuse")])
        findings = _find(audit_generation(inv, matrix), "GA-005")
        assert len(findings) == 0


# ═══════════════════════════════════════════════════════════════════════════
# GA-006: Unresolved human-must-decide properties
# ═══════════════════════════════════════════════════════════════════════════

class TestGA006:

    def test_flags_unresolved_human_must_decide(self):
        inv = _inv()
        matrix = _matrix([_mapping(
            "x:Case", action="reuse",
            property_mappings=[
                _prop_mapping("x:caseNum", action="reuse-property", target="j:CaseNumberText"),
                _prop_mapping("x:judge", action="human-must-decide"),
            ],
        )])
        findings = _find(audit_generation(inv, matrix), "GA-006")
        assert len(findings) == 1
        assert "x:judge" in findings[0]["message"]
        assert findings[0]["severity"] == "error"

    def test_no_flag_when_all_resolved(self):
        inv = _inv()
        matrix = _matrix([_mapping(
            "x:Case", action="reuse",
            property_mappings=[
                _prop_mapping("x:caseNum", action="reuse-property", target="j:CaseNumberText"),
                _prop_mapping("x:filingDate", action="create-property"),
            ],
        )])
        findings = _find(audit_generation(inv, matrix), "GA-006")
        assert len(findings) == 0

    def test_no_flag_when_no_property_mappings(self):
        inv = _inv()
        matrix = _matrix([_mapping("x:Case", action="reuse")])
        findings = _find(audit_generation(inv, matrix), "GA-006")
        assert len(findings) == 0

    def test_multiple_unresolved_listed(self):
        inv = _inv()
        matrix = _matrix([_mapping(
            "x:Case", action="reuse",
            property_mappings=[
                _prop_mapping("x:judge", action="human-must-decide"),
                _prop_mapping("x:clerk", action="human-must-decide"),
            ],
        )])
        findings = _find(audit_generation(inv, matrix), "GA-006")
        assert len(findings) == 1
        assert "2 unresolved" in findings[0]["message"]
        assert "x:judge" in findings[0]["message"]
        assert "x:clerk" in findings[0]["message"]


# ═══════════════════════════════════════════════════════════════════════════
# Clean matrix — no findings
# ═══════════════════════════════════════════════════════════════════════════

class TestGA007:

    def test_augment_mismatched_augments_type(self):
        inv = _inv()
        matrix = _matrix([_mapping(
            "x:Case", action="augment", target_type="nc:PersonType",
            augmentationType="CaseAugmentationType",
            augmentsType="nc:CaseType",
        )])
        findings = _find(audit_generation(inv, matrix), "GA-007")
        assert len(findings) == 1
        assert findings[0]["severity"] == "error"
        assert "nc:CaseType" in findings[0]["message"]
        assert "nc:PersonType" in findings[0]["message"]

    def test_extend_mismatched_base_type(self):
        inv = _inv()
        matrix = _matrix([_mapping(
            "x:Case", action="extend", target_type="nc:PersonType",
            extensionType="CaseType",
            baseType="nc:CaseType",
        )])
        findings = _find(audit_generation(inv, matrix), "GA-007")
        assert len(findings) == 1
        assert findings[0]["severity"] == "error"

    def test_extend_null_target_no_finding(self):
        """Extend from root (null targetType) — baseType is structures:ObjectType, no mismatch."""
        inv = _inv()
        matrix = _matrix([_mapping(
            "x:Case", action="extend", target_type=None,
            extensionType="CaseType",
            baseType="structures:ObjectType",
        )])
        findings = _find(audit_generation(inv, matrix), "GA-007")
        assert len(findings) == 0

    def test_no_finding_when_consistent(self):
        inv = _inv()
        matrix = _matrix([
            _mapping("x:Case", action="augment", target_type="nc:CaseType",
                     augmentationType="CaseAugmentationType",
                     augmentsType="nc:CaseType"),
            _mapping("x:Person", action="extend", target_type="nc:PersonType",
                     extensionType="PersonType",
                     baseType="nc:PersonType"),
            _mapping("x:Thing", action="reuse"),
        ])
        findings = _find(audit_generation(inv, matrix), "GA-007")
        assert len(findings) == 0


class TestCleanMatrix:

    def test_no_findings_for_well_formed_matrix(self):
        inv = _inv(
            classes=[{"qname": "x:Case"}, {"qname": "x:Person"}],
            obj_props=[
                {"qname": "x:hasJudge", "domain": ["x:Case"], "range": []},
                {"qname": "x:personName", "domain": ["x:Person"], "range": []},
            ],
        )
        matrix = _matrix([
            _mapping("x:Case", action="reuse", property_mappings=[
                _prop_mapping("x:hasJudge", target="j:Judge"),
            ]),
            _mapping("x:Person", action="augment",
                     target_type="nc:PersonType",
                     augmentationType="x-edge:PersonAugType",
                     augmentsType="nc:PersonType",
                     property_mappings=[
                         _prop_mapping("x:personName", action="reuse-property",
                                       target="nc:PersonName"),
                     ]),
        ])
        findings = audit_generation(inv, matrix)
        assert len(findings) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
