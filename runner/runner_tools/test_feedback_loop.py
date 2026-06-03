#!/usr/bin/env python3
"""Tests for generation_audit.py and feedback_report.py"""

import pytest
from ontology_mapper.generation_audit import audit_generation, format_findings
from runner_tools.feedback_report import (
    build_feedback,
)


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════

def make_inv(classes, obj_props=None, dt_props=None, shapes=None):
    return {
        "classes": classes,
        "objectProperties": obj_props or [],
        "datatypeProperties": dt_props or [],
        "shaclShapes": shapes or [],
    }


def make_matrix(mappings, target_ontology="niem"):
    return {
        "targetOntology": target_ontology,
        "targetVersion": "6.0",
        "mappings": mappings,
    }


def make_mapping(concept, action, target_type=None, **kwargs):
    m = {
        "sourceConcept": concept,
        "action": action,
        "targetType": target_type,
        "reviewStatus": "pending-review",
    }
    m.update(kwargs)
    return m


# ═══════════════════════════════════════════════════════════════════════════
# Generation Audit
# ═══════════════════════════════════════════════════════════════════════════

class TestAuditGeneration:
    def test_no_issues_clean(self):
        inv = make_inv(
            [{"qname": "dbpi:Person"}, {"qname": "dbpi:Permit"}],
            obj_props=[{
                "qname": "dbpi:issuedTo",
                "domain": ["dbpi:Permit"],
                "range": ["dbpi:Person"],
            }],
            dt_props=[{
                "qname": "dbpi:name",
                "domain": ["dbpi:Person"],
                "range": [],
            }],
        )
        matrix = make_matrix([
            make_mapping("dbpi:Person", "reuse", "nc:PersonType",
                         propertyMappings=[{"sourceProperty": "dbpi:name", "action": "reuse-property", "targetProperty": "nc:PersonName"}]),
            make_mapping("dbpi:Permit", "extend", extensionType="dbpi-edge:PermitType", baseType="nc:ActivityType",
                         propertyMappings=[{"sourceProperty": "dbpi:issuedTo", "action": "reuse-property", "targetProperty": "nc:Person"}]),
        ])
        findings = audit_generation(inv, matrix)
        assert len(findings) == 0

    def test_zero_property_reuse_flagged(self):
        """GA-001: Reuse class with zero source properties."""
        inv = make_inv([{"qname": "dbpi:Agent"}])
        matrix = make_matrix([make_mapping("dbpi:Agent", "reuse", "nc:EntityType")])
        findings = [f for f in audit_generation(inv, matrix) if f["code"] == "GA-001"]
        assert len(findings) == 1
        assert "zero source properties" in findings[0]["message"]

    def test_zero_property_extend_flagged(self):
        """GA-001: Extend class with zero properties is also flagged."""
        inv = make_inv([{"qname": "dbpi:Widget"}])
        matrix = make_matrix([make_mapping("dbpi:Widget", "extend",
                                           extensionType="dbpi-edge:WidgetType",
                                           baseType="nc:ItemType")])
        findings = [f for f in audit_generation(inv, matrix) if f["code"] == "GA-001"]
        assert len(findings) == 1

    def test_augment_on_non_niem_flagged(self):
        """GA-002: Augment action on non-NIEM flow is an error."""
        inv = make_inv([])
        matrix = make_matrix(
            [make_mapping("x:Thing", "augment",
                          augmentationType="x-edge:ThingAugType",
                          augmentsType="folio:ThingType")],
            target_ontology="sali-folio",
        )
        findings = [f for f in audit_generation(inv, matrix) if f["code"] == "GA-002"]
        assert len(findings) == 1
        assert findings[0]["severity"] == "error"

    def test_augment_on_niem_not_flagged(self):
        """GA-002: Augment on NIEM is fine."""
        inv = make_inv([])
        matrix = make_matrix([make_mapping("x:Thing", "augment",
                                           augmentationType="x-edge:ThingAugType",
                                           augmentsType="nc:ThingType")])
        findings = [f for f in audit_generation(inv, matrix) if f["code"] == "GA-002"]
        assert len(findings) == 0

    def test_augment_zero_reuse_properties_flagged(self):
        """GA-003: Augment entry with all create-property is suspicious."""
        inv = make_inv([])
        matrix = make_matrix([make_mapping("x:Person", "augment",
                                           augmentationType="x-edge:PersonAugType",
                                           augmentsType="nc:PersonType",
                                           propertyMappings=[
                                               {"sourceProperty": "x:foo", "action": "create-property", "targetProperty": None},
                                           ])])
        findings = [f for f in audit_generation(inv, matrix) if f["code"] == "GA-003"]
        assert len(findings) == 1
        assert findings[0]["severity"] == "warning"

    def test_concept_with_source_props_but_no_mappings(self):
        """GA-004: Source properties exist but nothing in matrix."""
        inv = make_inv(
            [{"qname": "dbpi:Case"}],
            obj_props=[{"qname": "dbpi:hasJudge", "domain": ["dbpi:Case"], "range": []}],
        )
        matrix = make_matrix([make_mapping("dbpi:Case", "reuse", "j:CaseType")])
        findings = [f for f in audit_generation(inv, matrix) if f["code"] == "GA-004"]
        assert len(findings) == 1
        assert "lost between Stage 3 and Stage 4" in findings[0]["message"]

    def test_extend_missing_scaffolding(self):
        """GA-005: Extend without extensionType/baseType."""
        inv = make_inv([])
        matrix = make_matrix([make_mapping("x:Thing", "extend", "nc:ThingType")])
        findings = [f for f in audit_generation(inv, matrix) if f["code"] == "GA-005"]
        assert len(findings) == 1
        assert findings[0]["severity"] == "error"

    def test_reuse_with_unexpected_scaffolding(self):
        """GA-005: Reuse should not have scaffolding."""
        inv = make_inv([])
        matrix = make_matrix([make_mapping("x:Case", "reuse", "j:CaseType",
                                           extensionType="x-edge:CaseType")])
        findings = [f for f in audit_generation(inv, matrix) if f["code"] == "GA-005"]
        assert len(findings) == 1


class TestFormatFindings:
    def test_empty_no_issues(self):
        result = format_findings([])
        assert "no issues found" in result

    def test_formats_with_code_and_message(self):
        findings = [{
            "severity": "warning",
            "code": "GA-003",
            "concept": "dbpi:foo",
            "message": "Test message",
            "related": {"action": "augment"},
        }]
        result = format_findings(findings)
        assert "GA-003" in result
        assert "Test message" in result


# ═══════════════════════════════════════════════════════════════════════════
# Feedback Report
# ═══════════════════════════════════════════════════════════════════════════

class TestBuildFeedback:
    def test_no_failures_no_feedback(self):
        validation = {"allPassed": True, "checks": []}
        matrix = make_matrix([make_mapping("dbpi:Person", "reuse", "nc:PersonType")])
        feedback = build_feedback(validation, matrix, None)
        assert len(feedback) == 0

    def test_shacl_failure_traced(self):
        """SHACL failure mentioning a type should link to its decision."""
        validation = {
            "allPassed": False,
            "checks": [{
                "check": "shacl-conformance",
                "status": "FAIL",
                "details": "Violations: PersonType constraint minCount 1 not met",
            }],
        }
        matrix = make_matrix([
            make_mapping("dbpi:Person", "reuse", "nc:PersonType"),
        ])
        feedback = build_feedback(validation, matrix, None)
        assert len(feedback) >= 1
        fb = feedback[0]
        assert fb["concept"] == "dbpi:Person"
        assert fb["decision"]["action"] == "reuse"
        assert "SHACL" in fb["downstream_issue"]["detail"]

    def test_audit_findings_included(self):
        """Generation audit warnings should be included in feedback."""
        validation = {"allPassed": True, "checks": []}
        matrix = make_matrix([
            make_mapping("dbpi:Person", "augment",
                         augmentationType="dbpi-edge:PersonAugType",
                         augmentsType="nc:PersonType",
                         propertyMappings=[
                             {"sourceProperty": "dbpi:foo", "action": "create-property", "targetProperty": None},
                         ]),
        ])
        audit = {
            "findings": [{
                "severity": "warning",
                "code": "GA-003",
                "concept": "dbpi:Person",
                "message": "Augment with zero reuse-properties",
                "related": {
                    "action": "augment",
                    "targetType": "nc:PersonType",
                },
            }],
        }
        feedback = build_feedback(validation, matrix, audit)
        assert len(feedback) >= 1
        fb = [f for f in feedback if f.get("concept") == "dbpi:Person"]
        assert len(fb) == 1

    def test_info_findings_not_included(self):
        """Only warnings from audit should become feedback, not info."""
        audit = {
            "findings": [{
                "severity": "info",
                "code": "GA-001",
                "concept": "dbpi:Agent",
                "message": "Zero properties",
                "related": {"action": "reuse"},
            }],
        }
        feedback = build_feedback({"allPassed": True, "checks": []},
                                  make_matrix([]), audit)
        assert len(feedback) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
