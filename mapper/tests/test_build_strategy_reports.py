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
        assert "hasAddress" in props["dbpi:Person"]
        assert "personName" in props["dbpi:Person"]

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
        assert "permitNumber" in props["dbpi:Permit"]
        assert "issuedDate" in props["dbpi:Permit"]


class TestBuildSourcePropertyDefs:
    def test_builds_from_datatype_properties(self):
        inv = {
            "datatypeProperties": [
                {"qname": "src:personName", "comment": "Name of person", "domain": ["src:Person"], "range": ["xs:string"]},
            ],
            "objectProperties": [],
            "shaclShapes": [],
        }
        class_props = {"src:Person": {"personName"}}
        result = build_source_property_defs(inv, class_props)
        assert "src:Person" in result
        assert "personName" in result["src:Person"]
        assert result["src:Person"]["personName"]["definition"] == "Name of person"

    def test_builds_from_object_properties(self):
        inv = {
            "datatypeProperties": [],
            "objectProperties": [
                {"qname": "src:employer", "comment": "Employing org", "domain": ["src:Person"], "range": ["src:Org"]},
            ],
            "shaclShapes": [],
        }
        class_props = {"src:Person": {"employer"}}
        result = build_source_property_defs(inv, class_props)
        assert result["src:Person"]["employer"]["range"] == ["src:Org"]


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
