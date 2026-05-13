#!/usr/bin/env python3
"""Tests for catalog_search.py — catalog lookup for Stage 5 review."""

import pytest

from ontology_mapper.catalog_search import (
    search_catalog,
    _rank_match,
    format_type_results,
    format_property_results,
)


# ─── Fixtures ──────────────────────────────────────────────────────────

def _catalog():
    """Build a minimal reference catalog for testing."""
    return {
        "types": [
            {
                "qname": "nc:PersonType",
                "definition": "A data type for a person.",
                "pattern": "object",
                "properties": ["PersonName", "PersonBirthDate", "PersonSex"],
                "propertyDefinitions": {},
            },
            {
                "qname": "nc:ActivityType",
                "definition": "A data type for an activity or action.",
                "pattern": "object",
                "properties": ["ActivityDate", "ActivityDescription"],
                "propertyDefinitions": {},
            },
            {
                "qname": "j:CourtEventType",
                "definition": "A data type for a court event.",
                "pattern": "object",
                "properties": ["CourtEventJudge", "ActivityDate"],
                "propertyDefinitions": {},
            },
            {
                "qname": "nc:PersonNameType",
                "definition": "A data type for a name of a person.",
                "pattern": "complex_value",
                "properties": ["PersonGivenName", "PersonSurName"],
                "propertyDefinitions": {},
            },
            {
                "qname": "j:PersonAugmentationType",
                "definition": "An augmentation type for person.",
                "pattern": "augmentation",
                "properties": ["PersonFBI"],
                "propertyDefinitions": {},
            },
        ],
        "propertyIndex": {
            "nc": {
                "properties": [
                    {
                        "name": "PersonName",
                        "qualifiedProperty": "nc:PersonName",
                        "definition": "A combination of names for a person.",
                        "containingTypes": ["nc:PersonType"],
                    },
                    {
                        "name": "PersonBirthDate",
                        "qualifiedProperty": "nc:PersonBirthDate",
                        "definition": "A date a person was born.",
                        "containingTypes": ["nc:PersonType"],
                    },
                    {
                        "name": "ActivityDate",
                        "qualifiedProperty": "nc:ActivityDate",
                        "definition": "A date of an activity.",
                        "containingTypes": ["nc:ActivityType", "j:CourtEventType"],
                    },
                ],
                "propertyCount": 3,
            },
            "j": {
                "properties": [
                    {
                        "name": "CourtEventJudge",
                        "qualifiedProperty": "j:CourtEventJudge",
                        "definition": "A judge presiding over a court event.",
                        "containingTypes": ["j:CourtEventType"],
                    },
                ],
                "propertyCount": 1,
            },
        },
    }


# ─── Unit tests: _rank_match ──────────────────────────────────────────

class TestRankMatch:

    def test_exact_local_name(self):
        assert _rank_match("persontype", "nc:PersonType", "PersonType", "") == 0

    def test_prefix_match(self):
        assert _rank_match("person", "nc:PersonType", "PersonType", "") == 1

    def test_qname_contains(self):
        assert _rank_match("nc:person", "nc:PersonType", "PersonType", "") == 2

    def test_definition_match(self):
        assert _rank_match("born", "nc:PersonBirthDate", "PersonBirthDate", "A date a person was born.") == 3

    def test_no_match(self):
        assert _rank_match("zzz", "nc:PersonType", "PersonType", "A person.") is None

    def test_case_insensitive(self):
        assert _rank_match("PERSON", "nc:PersonType", "PersonType", "") == 1


# ─── Unit tests: search_catalog — types ───────────────────────────────

class TestSearchTypes:

    def test_search_by_local_name(self):
        results = search_catalog(_catalog(), "Person", kind="type")
        types = results["types"]
        assert len(types) >= 2
        # PersonType should rank higher (prefix match on local name)
        qnames = [t["qname"] for t in types]
        assert "nc:PersonType" in qnames

    def test_exact_match_ranks_first(self):
        results = search_catalog(_catalog(), "PersonType", kind="type")
        assert results["types"][0]["qname"] == "nc:PersonType"

    def test_search_by_namespace_prefix(self):
        results = search_catalog(_catalog(), "court", kind="type")
        types = results["types"]
        qnames = [t["qname"] for t in types]
        assert "j:CourtEventType" in qnames

    def test_search_by_definition(self):
        results = search_catalog(_catalog(), "court event", kind="type")
        types = results["types"]
        assert any(t["qname"] == "j:CourtEventType" for t in types)

    def test_namespace_filter(self):
        results = search_catalog(_catalog(), "Type", kind="type", namespace="j")
        types = results["types"]
        for t in types:
            assert t["qname"].startswith("j:")

    def test_max_results(self):
        results = search_catalog(_catalog(), "Type", kind="type", max_results=2)
        assert len(results["types"]) <= 2

    def test_no_match(self):
        results = search_catalog(_catalog(), "zzzzz", kind="type")
        assert results["types"] == []

    def test_result_structure(self):
        results = search_catalog(_catalog(), "PersonType", kind="type")
        t = results["types"][0]
        assert "qname" in t
        assert "definition" in t
        assert "pattern" in t
        assert "propertyCount" in t
        assert t["propertyCount"] == 3  # PersonName, PersonBirthDate, PersonSex

    def test_kind_type_excludes_properties(self):
        results = search_catalog(_catalog(), "Person", kind="type")
        assert results["properties"] == []


# ─── Unit tests: search_catalog — properties ──────────────────────────

class TestSearchProperties:

    def test_search_by_name(self):
        results = search_catalog(_catalog(), "PersonName", kind="property")
        props = results["properties"]
        assert any(p["qualifiedProperty"] == "nc:PersonName" for p in props)

    def test_search_by_definition(self):
        results = search_catalog(_catalog(), "born", kind="property")
        props = results["properties"]
        assert any(p["qualifiedProperty"] == "nc:PersonBirthDate" for p in props)

    def test_namespace_filter(self):
        results = search_catalog(_catalog(), "event", kind="property", namespace="j")
        props = results["properties"]
        for p in props:
            assert p["qualifiedProperty"].startswith("j:")

    def test_containing_types(self):
        results = search_catalog(_catalog(), "ActivityDate", kind="property")
        props = results["properties"]
        ad = next(p for p in props if p["qualifiedProperty"] == "nc:ActivityDate")
        assert "nc:ActivityType" in ad["containingTypes"]
        assert "j:CourtEventType" in ad["containingTypes"]

    def test_kind_property_excludes_types(self):
        results = search_catalog(_catalog(), "Person", kind="property")
        assert results["types"] == []

    def test_no_match(self):
        results = search_catalog(_catalog(), "zzzzz", kind="property")
        assert results["properties"] == []


# ─── Unit tests: search_catalog — both kinds ──────────────────────────

class TestSearchBothKinds:

    def test_returns_both(self):
        results = search_catalog(_catalog(), "Person")
        assert len(results["types"]) > 0
        assert len(results["properties"]) > 0

    def test_empty_catalog(self):
        results = search_catalog({"types": [], "propertyIndex": {}}, "anything")
        assert results["types"] == []
        assert results["properties"] == []


# ─── Unit tests: format functions ─────────────────────────────────────

class TestFormatFunctions:

    def test_format_type_results_empty(self):
        out = format_type_results([])
        assert "No matching types" in out

    def test_format_type_results(self):
        results = search_catalog(_catalog(), "PersonType", kind="type")
        out = format_type_results(results["types"])
        assert "nc:PersonType" in out
        assert "object" in out

    def test_format_property_results_empty(self):
        out = format_property_results([])
        assert "No matching properties" in out

    def test_format_property_results(self):
        results = search_catalog(_catalog(), "PersonName", kind="property")
        out = format_property_results(results["properties"])
        assert "nc:PersonName" in out
        assert "nc:PersonType" in out  # containing type


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
