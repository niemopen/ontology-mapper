"""Tests for orchestrator_service.schemas."""

import pytest

from orchestrator_service.schemas import (
    TYPE_EVALUATION_SCHEMA,
    PROPERTY_EVALUATION_SCHEMA,
    validate_response,
)


# ---------------------------------------------------------------------------
# Schema structure tests
# ---------------------------------------------------------------------------

class TestSchemaStructure:
    def test_type_schema_has_required_fields(self):
        required = TYPE_EVALUATION_SCHEMA["required"]
        assert "sourceConcept" in required
        assert "targetType" in required
        assert "rationale" in required

    def test_property_schema_has_required_fields(self):
        required = PROPERTY_EVALUATION_SCHEMA["required"]
        assert "sourceProperty" in required
        assert "targetProperty" in required
        assert "rationale" in required

    def test_target_fields_allow_null(self):
        props = TYPE_EVALUATION_SCHEMA["properties"]
        assert props["targetType"]["type"] == ["string", "null"]
        assert props["targetDefinition"]["type"] == ["string", "null"]

    def test_no_additional_properties(self):
        assert TYPE_EVALUATION_SCHEMA["additionalProperties"] is False
        assert PROPERTY_EVALUATION_SCHEMA["additionalProperties"] is False


# ---------------------------------------------------------------------------
# Type validation tests
# ---------------------------------------------------------------------------

def _type_file(qname="dbpi:Address", candidates=None):
    if candidates is None:
        candidates = [
            {"id": "nc:AddressType", "definition": "A postal address."},
            {"id": "nc:LocationType", "definition": "A location."},
        ]
    return {
        "kind": "type",
        "source": {"qname": qname},
        "candidates": candidates,
    }


def _make_type_response(source="dbpi:Address", target="nc:AddressType",
                        rationale="Both represent physical addresses."):
    return {
        "sourceConcept": source,
        "sourceDefinition": "",
        "sourcePath": source,
        "targetType": target,
        "targetDefinition": "A postal address.",
        "targetPath": target,
        "rationale": rationale,
    }


class TestTypeValidation:
    def test_valid_response(self):
        errors = validate_response(_make_type_response(), _type_file())
        assert errors == []

    def test_null_target_is_valid(self):
        resp = _make_type_response(target=None)
        resp["targetDefinition"] = None
        resp["targetPath"] = None
        errors = validate_response(resp, _type_file())
        assert errors == []

    def test_source_mismatch(self):
        resp = _make_type_response(source="dbpi:Wrong")
        errors = validate_response(resp, _type_file())
        assert any("sourceConcept mismatch" in e for e in errors)

    def test_undecided_sentinel_is_valid(self):
        resp = _make_type_response(target="[undecided]")
        errors = validate_response(resp, _type_file())
        assert errors == []

    def test_target_not_in_candidates(self):
        resp = _make_type_response(target="nc:NotACandidate")
        errors = validate_response(resp, _type_file())
        assert any("not among the candidates" in e for e in errors)

    def test_short_rationale(self):
        resp = _make_type_response(rationale="ok")
        errors = validate_response(resp, _type_file())
        assert any("rationale too short" in e for e in errors)

    def test_empty_rationale(self):
        resp = _make_type_response(rationale="")
        errors = validate_response(resp, _type_file())
        assert any("rationale too short" in e for e in errors)

    def test_multiple_errors(self):
        resp = _make_type_response(
            source="wrong", target="nc:NotACandidate", rationale="x",
        )
        errors = validate_response(resp, _type_file())
        assert len(errors) == 3


# ---------------------------------------------------------------------------
# Property validation tests
# ---------------------------------------------------------------------------

def _prop_file(qname="dbpi:streetName", candidates=None):
    if candidates is None:
        candidates = [
            {"id": "nc:StreetFullText", "definition": "A street address."},
        ]
    return {
        "kind": "property",
        "source": {"qname": qname},
        "candidates": candidates,
    }


def _make_prop_response(source="dbpi:streetName", target="nc:StreetFullText",
                        rationale="Both represent the street portion."):
    return {
        "sourceProperty": source,
        "sourceDefinition": "",
        "sourcePath": f"dbpi:Address/{source}",
        "targetProperty": target,
        "targetDefinition": "A street address.",
        "targetPath": f"nc:AddressType/{target}",
        "rationale": rationale,
    }


class TestPropertyValidation:
    def test_valid_response(self):
        errors = validate_response(_make_prop_response(), _prop_file())
        assert errors == []

    def test_null_target_is_valid(self):
        resp = _make_prop_response(target=None)
        resp["targetDefinition"] = None
        resp["targetPath"] = None
        errors = validate_response(resp, _prop_file())
        assert errors == []

    def test_source_mismatch(self):
        resp = _make_prop_response(source="dbpi:wrong")
        errors = validate_response(resp, _prop_file())
        assert any("sourceProperty mismatch" in e for e in errors)

    def test_undecided_sentinel_is_valid(self):
        resp = _make_prop_response(target="[undecided]")
        errors = validate_response(resp, _prop_file())
        assert errors == []

    def test_target_not_in_candidates(self):
        resp = _make_prop_response(target="nc:NotReal")
        errors = validate_response(resp, _prop_file())
        assert any("not among the candidates" in e for e in errors)
