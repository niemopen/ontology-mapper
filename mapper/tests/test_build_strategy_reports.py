#!/usr/bin/env python3
"""Tests for Stage 3: build_strategy_reports.py

Covers utility functions (strip_prefix),
property extraction (build_class_properties, build_source_property_defs),
and the source concept summary builder.
"""

import pytest
from ontology_mapper.build_strategy_reports import (
    strip_prefix,
    build_class_properties,
    build_source_property_defs,
    build_source_concept_summary,
)


# ═══════════════════════════════════════════════════════════════════════════
# Utility Functions
# ═══════════════════════════════════════════════════════════════════════════

class TestStripPrefix:
    def test_qname(self):
        assert strip_prefix("dbpi:Person") == "Person"

    def test_no_prefix(self):
        assert strip_prefix("Person") == "Person"


# ═══════════════════════════════════════════════════════════════════════════
# Property Extraction
# ═══════════════════════════════════════════════════════════════════════════

class TestBuildClassProperties:
    """A property's identity is its qname, not its local name: a class
    in one namespace may own a property in an augmenting namespace."""

    def test_from_domains(self):
        inv = {
            "classes": [{"qname": "dbpi:Person"}],
            "objectProperties": [
                {"qname": "dbpi:hasAddress", "domain": ["dbpi:Person"]},
            ],
            "datatypeProperties": [
                {"qname": "dbpi:personName", "domain": ["dbpi:Person"]},
            ],
            "shaclShapes": [],
        }
        props = build_class_properties(inv)
        assert props["dbpi:Person"] == {"dbpi:hasAddress", "dbpi:personName"}

    def test_from_shacl(self):
        inv = {
            "classes": [{"qname": "dbpi:Permit"}],
            "objectProperties": [],
            "datatypeProperties": [],
            "shaclShapes": [{
                "targetClass": "dbpi:Permit",
                "propertyCount": 2,
                "properties": [
                    {"path": "dbpi:permitNumber"},
                    {"path": "dbpi:issuedDate"},
                ],
            }],
        }
        props = build_class_properties(inv)
        assert props["dbpi:Permit"] == {"dbpi:permitNumber", "dbpi:issuedDate"}

    def test_augmenting_namespace_property_keeps_its_own_prefix(self):
        """The redvale shape: `fin:fiscalYearCode` is a property of
        `dbpi:Fee`. Reducing it to `fiscalYearCode` here is what let the
        downstream stages re-qualify it as `dbpi:fiscalYearCode`."""
        inv = {
            "classes": [{"qname": "dbpi:Fee"}],
            "objectProperties": [],
            "datatypeProperties": [
                {"qname": "fin:fiscalYearCode", "domain": ["dbpi:Fee"]},
                {"qname": "dbpi:amount", "domain": ["dbpi:Fee"]},
            ],
            "shaclShapes": [],
        }
        assert build_class_properties(inv)["dbpi:Fee"] == {
            "fin:fiscalYearCode", "dbpi:amount"}

    def test_same_local_name_in_two_namespaces_stays_distinct(self):
        inv = {
            "classes": [{"qname": "dbpi:Site"}],
            "objectProperties": [],
            "datatypeProperties": [
                {"qname": "gis:code", "domain": ["dbpi:Site"]},
                {"qname": "fin:code", "domain": ["dbpi:Site"]},
            ],
            "shaclShapes": [],
        }
        assert build_class_properties(inv)["dbpi:Site"] == {"gis:code", "fin:code"}


class TestBuildSourcePropertyDefs:
    def test_builds_from_datatype_properties(self):
        inv = {
            "datatypeProperties": [
                {"qname": "src:personName", "comment": "Name of person", "domain": ["src:Person"], "range": ["xs:string"]},
            ],
            "objectProperties": [],
            "shaclShapes": [],
        }
        class_props = {"src:Person": {"src:personName"}}
        result = build_source_property_defs(inv, class_props)
        assert "src:Person" in result
        assert "src:personName" in result["src:Person"]
        assert result["src:Person"]["src:personName"]["definition"] == "Name of person"

    def test_builds_from_object_properties(self):
        inv = {
            "datatypeProperties": [],
            "objectProperties": [
                {"qname": "src:employer", "comment": "Employing org", "domain": ["src:Person"], "range": ["src:Org"]},
            ],
            "shaclShapes": [],
        }
        class_props = {"src:Person": {"src:employer"}}
        result = build_source_property_defs(inv, class_props)
        assert result["src:Person"]["src:employer"]["range"] == ["src:Org"]

    def test_two_namespaces_one_local_name_get_their_own_definitions(self):
        inv = {
            "datatypeProperties": [
                {"qname": "gis:code", "comment": "Zone code", "domain": ["src:Site"], "range": ["xs:string"]},
                {"qname": "fin:code", "comment": "Ledger code", "domain": ["src:Site"], "range": ["xs:string"]},
            ],
            "objectProperties": [],
            "shaclShapes": [],
        }
        result = build_source_property_defs(inv, {"src:Site": {"gis:code", "fin:code"}})
        assert result["src:Site"]["gis:code"]["definition"] == "Zone code"
        assert result["src:Site"]["fin:code"]["definition"] == "Ledger code"


# ═══════════════════════════════════════════════════════════════════════════
# Source Concept Summary
# ═══════════════════════════════════════════════════════════════════════════

class TestBuildSourceConceptSummary:
    def test_extracts_all_classes(self):
        inv = {
            "classes": [
                {"qname": "court:Case", "comment": "A court case.", "subClassOf": []},
                {"qname": "court:Person", "comment": "A person.", "subClassOf": []},
            ],
            "objectProperties": [],
            "datatypeProperties": [],
            "shaclShapes": [],
        }
        result = build_source_concept_summary(inv)
        assert len(result) == 2
        assert result[0]["qname"] == "court:Case"
        assert result[0]["localName"] == "Case"
        assert result[0]["definition"] == "A court case."

    def test_includes_properties_with_definitions(self):
        inv = {
            "classes": [
                {"qname": "court:Case", "comment": "A court case.", "subClassOf": []},
            ],
            "objectProperties": [],
            "datatypeProperties": [
                {"qname": "court:CaseNumber", "comment": "The case number.", "domain": ["court:Case"], "range": ["xs:string"]},
            ],
            "shaclShapes": [],
        }
        result = build_source_concept_summary(inv)
        assert len(result) == 1
        assert result[0]["propertyCount"] == 1
        assert result[0]["properties"][0]["name"] == "CaseNumber"
        assert result[0]["properties"][0]["definition"] == "The case number."

    def test_includes_superclasses(self):
        inv = {
            "classes": [
                {"qname": "court:CriminalCase", "comment": "A criminal case.", "subClassOf": ["court:Case"]},
            ],
            "objectProperties": [],
            "datatypeProperties": [],
            "shaclShapes": [],
        }
        result = build_source_concept_summary(inv)
        assert result[0]["superClasses"] == ["court:Case"]

    def test_empty_inventory(self):
        inv = {
            "classes": [],
            "objectProperties": [],
            "datatypeProperties": [],
            "shaclShapes": [],
        }
        result = build_source_concept_summary(inv)
        assert result == []

    def test_property_count_matches_properties(self):
        inv = {
            "classes": [
                {"qname": "court:Case", "comment": "", "subClassOf": []},
            ],
            "objectProperties": [
                {"qname": "court:hasJudge", "comment": "Judge.", "domain": ["court:Case"], "range": ["court:Person"]},
            ],
            "datatypeProperties": [
                {"qname": "court:CaseNumber", "comment": "Number.", "domain": ["court:Case"], "range": ["xs:string"]},
                {"qname": "court:FilingDate", "comment": "Date.", "domain": ["court:Case"], "range": ["xs:date"]},
            ],
            "shaclShapes": [],
        }
        result = build_source_concept_summary(inv)
        assert result[0]["propertyCount"] == 3
        assert len(result[0]["properties"]) == 3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
