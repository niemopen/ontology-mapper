#!/usr/bin/env python3
"""Tests for feedback_report.py — mapping validation failures to source decisions."""

import pytest

from runner_tools.feedback_report import build_feedback


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _matrix(mappings):
    return {"mappings": mappings}


def _mapping(concept, action, target=None):
    m = {"sourceConcept": concept, "action": action}
    if target:
        m["targetType"] = target
    return m


def _validation_report(checks, all_passed=None):
    if all_passed is None:
        all_passed = all(c["status"] == "pass" for c in checks)
    return {"allPassed": all_passed, "checks": checks}


def _check(name, status, details=""):
    return {"check": name, "status": status, "details": details}


# ---------------------------------------------------------------------------
# SHACL conformance failures
# ---------------------------------------------------------------------------
class TestShaclFeedback:
    def test_shacl_failure_maps_to_concept(self):
        matrix = _matrix([_mapping("src:Permit", "extend", "nc:ActivityType")])
        validation = _validation_report([
            _check("shacl-conformance", "FAIL", "PermitType has cardinality violation"),
        ])
        fb = build_feedback(validation, matrix, None)
        assert len(fb) == 1
        assert fb[0]["concept"] == "src:Permit"
        assert fb[0]["decision"]["action"] == "extend"
        assert fb[0]["severity"] == "warning"

    def test_shacl_failure_no_match_produces_no_feedback(self):
        matrix = _matrix([_mapping("src:Permit", "extend", "nc:ActivityType")])
        validation = _validation_report([
            _check("shacl-conformance", "FAIL", "UnrelatedType has issue"),
        ])
        fb = build_feedback(validation, matrix, None)
        assert len(fb) == 0

    def test_shacl_pass_produces_no_feedback(self):
        matrix = _matrix([_mapping("src:Permit", "extend")])
        validation = _validation_report([
            _check("shacl-conformance", "pass", "Valid"),
        ])
        fb = build_feedback(validation, matrix, None)
        assert len(fb) == 0

    def test_shacl_maps_augment_concept(self):
        matrix = _matrix([_mapping("src:Person", "augment", "nc:PersonType")])
        validation = _validation_report([
            _check("shacl-conformance", "FAIL", "PersonType shape violation"),
        ])
        fb = build_feedback(validation, matrix, None)
        assert len(fb) == 1
        assert fb[0]["concept"] == "src:Person"
        assert fb[0]["decision"]["action"] == "augment"


# ---------------------------------------------------------------------------
# Mapping completeness failures
# ---------------------------------------------------------------------------
class TestMappingCompletenessFeedback:
    def test_unmapped_concepts_produce_feedback(self):
        matrix = _matrix([_mapping("src:A", "reuse")])
        validation = _validation_report([
            _check("mapping-completeness", "FAIL", "9/10 classes mapped, unmapped: {'src:Missing'}"),
        ])
        fb = build_feedback(validation, matrix, None)
        assert len(fb) == 1
        assert fb[0]["concept"] is None
        assert "Unmapped" in fb[0]["downstream_issue"]["detail"]

    def test_mapping_complete_no_feedback(self):
        matrix = _matrix([_mapping("src:A", "reuse")])
        validation = _validation_report([
            _check("mapping-completeness", "pass", "10/10 classes mapped"),
        ])
        fb = build_feedback(validation, matrix, None)
        assert len(fb) == 0


# ---------------------------------------------------------------------------
# Other check failures (all non-SHACL, non-completeness checks)
# ---------------------------------------------------------------------------
class TestOtherCheckFeedback:
    @pytest.mark.parametrize("check_name", [
        "extension-catalog-count",
        "decision-log-count",
        "cypher-validity",
        "sparql-syntax",
        "schema-ontology-consistency",
        "seed-data-consistency",
        "transform-matrix-consistency",
        "cmf-consistency",
    ])
    def test_produces_info_feedback(self, check_name):
        matrix = _matrix([_mapping("src:A", "reuse")])
        validation = _validation_report([
            _check(check_name, "FAIL", "some detail"),
        ])
        fb = build_feedback(validation, matrix, None)
        assert len(fb) == 1
        assert fb[0]["severity"] == "info"
        assert fb[0]["downstream_issue"]["check"] == check_name

    def test_unknown_check_name_ignored(self):
        """Check names not handled by feedback_report are silently skipped."""
        matrix = _matrix([_mapping("src:A", "reuse")])
        validation = _validation_report([
            _check("turtle-syntax", "FAIL", "parse error"),
        ])
        fb = build_feedback(validation, matrix, None)
        assert len(fb) == 0


# ---------------------------------------------------------------------------
# Generation audit feedback
# ---------------------------------------------------------------------------
class TestAuditFeedback:
    def test_audit_warning_produces_feedback(self):
        matrix = _matrix([_mapping("src:A", "extend", "nc:ActivityType")])
        audit = {"findings": [{
            "severity": "warning",
            "concept": "src:A",
            "code": "GA-005",
            "message": "Missing baseType scaffolding",
            "related": {"action": "extend", "targetType": "nc:ActivityType"},
        }]}
        fb = build_feedback(None, matrix, audit)
        assert len(fb) == 1
        assert fb[0]["concept"] == "src:A"
        assert fb[0]["downstream_issue"]["stage"] == "4-audit"

    def test_audit_info_not_included(self):
        matrix = _matrix([_mapping("src:A", "reuse")])
        audit = {"findings": [{
            "severity": "info",
            "concept": "src:A",
            "code": "GA-001",
            "message": "OK",
        }]}
        fb = build_feedback(None, matrix, audit)
        assert len(fb) == 0


# ---------------------------------------------------------------------------
# No validation, no audit
# ---------------------------------------------------------------------------
class TestNoInputs:
    def test_none_validation_none_audit(self):
        matrix = _matrix([_mapping("src:A", "reuse")])
        fb = build_feedback(None, matrix, None)
        assert fb == []

    def test_all_passed_validation(self):
        matrix = _matrix([_mapping("src:A", "reuse")])
        validation = _validation_report(
            [_check("turtle-syntax", "pass", "ok")],
            all_passed=True,
        )
        fb = build_feedback(validation, matrix, None)
        assert fb == []


# ---------------------------------------------------------------------------
# Stage labels in feedback output
# ---------------------------------------------------------------------------
class TestStageLabels:
    def test_validation_failure_uses_stage_7(self):
        matrix = _matrix([_mapping("src:Permit", "extend")])
        validation = _validation_report([
            _check("shacl-conformance", "FAIL", "PermitType violation"),
        ])
        fb = build_feedback(validation, matrix, None)
        assert fb[0]["downstream_issue"]["stage"] == "7-validation"

    def test_audit_finding_uses_stage_4(self):
        matrix = _matrix([_mapping("src:A", "extend")])
        audit = {"findings": [{
            "severity": "warning",
            "concept": "src:A",
            "code": "GA-005",
            "message": "test",
            "related": {"action": "extend"},
        }]}
        fb = build_feedback(None, matrix, audit)
        assert fb[0]["downstream_issue"]["stage"] == "4-audit"
