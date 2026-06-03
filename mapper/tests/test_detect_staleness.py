#!/usr/bin/env python3
"""Tests for codebook version fingerprinting — detect_staleness.py."""

import json
import pytest

from ontology_mapper.detect_staleness import (
    compare_properties,
    compare_reports,
    build_staleness_report,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
def _entry(concept, target_type, type_hash, properties=None):
    """Build a minimal alignment entry for testing."""
    e = {
        "sourceConcept": concept,
        "targetType": target_type,
        "targetDefinition": f"Definition for {target_type}",
        "targetDefinitionHash": type_hash,
    }
    if properties is not None:
        e["properties"] = properties
    return e


def _prop(name, target_prop, prop_hash, target_def=None):
    """Build a minimal property for testing."""
    return {
        "sourceProperty": name,
        "targetProperty": target_prop,
        "targetDefinition": target_def or f"Definition for {target_prop}",
        "targetDefinitionHash": prop_hash,
    }


# ---------------------------------------------------------------------------
# TestCompareProperties
# ---------------------------------------------------------------------------
class TestCompareProperties:
    def test_identical_hashes_no_staleness(self):
        old = _entry("x:Foo", "nc:FooType", "aaaa", [
            _prop("Prop1", "nc:Bar", "bbbb"),
        ])
        new = _entry("x:Foo", "nc:FooType", "aaaa", [
            _prop("Prop1", "nc:Bar", "bbbb"),
        ])
        assert compare_properties(old, new) == []

    def test_changed_hash_detected(self):
        old = _entry("x:Foo", "nc:FooType", "aaaa", [
            _prop("Prop1", "nc:Bar", "bbbb"),
        ])
        new = _entry("x:Foo", "nc:FooType", "aaaa", [
            _prop("Prop1", "nc:Bar", "cccc"),
        ])
        result = compare_properties(old, new)
        assert len(result) == 1
        assert result[0]["sourceProperty"] == "Prop1"
        assert result[0]["oldHash"] == "bbbb"
        assert result[0]["newHash"] == "cccc"

    def test_new_property_not_stale(self):
        old = _entry("x:Foo", "nc:FooType", "aaaa", [])
        new = _entry("x:Foo", "nc:FooType", "aaaa", [
            _prop("NewProp", "nc:New", "eeee"),
        ])
        assert compare_properties(old, new) == []

    def test_null_hashes_ignored(self):
        old = _entry("x:Foo", "nc:FooType", "aaaa", [
            _prop("Prop1", "nc:Bar", None),
        ])
        new = _entry("x:Foo", "nc:FooType", "aaaa", [
            _prop("Prop1", "nc:Bar", "cccc"),
        ])
        assert compare_properties(old, new) == []

    def test_both_null_hashes_not_stale(self):
        old = _entry("x:Foo", "nc:FooType", "aaaa", [
            _prop("Prop1", None, None),
        ])
        new = _entry("x:Foo", "nc:FooType", "aaaa", [
            _prop("Prop1", None, None),
        ])
        assert compare_properties(old, new) == []

    def test_multiple_properties_mixed(self):
        old = _entry("x:Foo", "nc:FooType", "aaaa", [
            _prop("Stable", "nc:A", "1111"),
            _prop("Changed", "nc:B", "2222"),
            _prop("AlsoChanged", "nc:C", "3333"),
        ])
        new = _entry("x:Foo", "nc:FooType", "aaaa", [
            _prop("Stable", "nc:A", "1111"),
            _prop("Changed", "nc:B", "9999"),
            _prop("AlsoChanged", "nc:C", "8888"),
        ])
        result = compare_properties(old, new)
        assert len(result) == 2
        names = {r["sourceProperty"] for r in result}
        assert names == {"Changed", "AlsoChanged"}

    def test_includes_definitions_in_result(self):
        old = _entry("x:Foo", "nc:FooType", "aaaa", [
            _prop("Prop1", "nc:Bar", "bbbb", "Old definition."),
        ])
        new = _entry("x:Foo", "nc:FooType", "aaaa", [
            _prop("Prop1", "nc:Bar", "cccc", "New definition."),
        ])
        result = compare_properties(old, new)
        assert result[0]["oldDefinition"] == "Old definition."
        assert result[0]["newDefinition"] == "New definition."

    def test_works_with_property_mappings_key(self):
        """Mapping matrix uses 'propertyMappings' instead of 'properties'."""
        old = {"sourceConcept": "x:Foo", "propertyMappings": [
            _prop("Prop1", "nc:Bar", "bbbb"),
        ]}
        new = {"sourceConcept": "x:Foo", "propertyMappings": [
            _prop("Prop1", "nc:Bar", "cccc"),
        ]}
        result = compare_properties(old, new)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# TestCompareReports
# ---------------------------------------------------------------------------
class TestCompareReports:
    def test_all_unchanged(self):
        entries = [_entry("x:A", "nc:AType", "aaaa")]
        result = compare_reports(entries, entries)
        assert result["unchanged"] == ["x:A"]
        assert result["staleTypes"] == []
        assert result["staleProperties"] == []
        assert result["newConcepts"] == []
        assert result["droppedConcepts"] == []

    def test_stale_type(self):
        old = [_entry("x:A", "nc:AType", "aaaa")]
        new = [_entry("x:A", "nc:AType", "bbbb")]
        result = compare_reports(old, new)
        assert len(result["staleTypes"]) == 1
        assert result["staleTypes"][0]["sourceConcept"] == "x:A"
        assert result["staleTypes"][0]["oldHash"] == "aaaa"
        assert result["staleTypes"][0]["newHash"] == "bbbb"
        assert result["unchanged"] == []

    def test_stale_property_only(self):
        old = [_entry("x:A", "nc:AType", "aaaa", [
            _prop("P1", "nc:B", "1111"),
        ])]
        new = [_entry("x:A", "nc:AType", "aaaa", [
            _prop("P1", "nc:B", "2222"),
        ])]
        result = compare_reports(old, new)
        assert result["staleTypes"] == []
        assert len(result["staleProperties"]) == 1
        assert result["staleProperties"][0]["sourceConcept"] == "x:A"
        assert len(result["staleProperties"][0]["staleProperties"]) == 1

    def test_new_concept(self):
        old = [_entry("x:A", "nc:AType", "aaaa")]
        new = [
            _entry("x:A", "nc:AType", "aaaa"),
            _entry("x:B", "nc:BType", "bbbb"),
        ]
        result = compare_reports(old, new)
        assert result["newConcepts"] == ["x:B"]
        assert result["unchanged"] == ["x:A"]

    def test_dropped_concept(self):
        old = [
            _entry("x:A", "nc:AType", "aaaa"),
            _entry("x:B", "nc:BType", "bbbb"),
        ]
        new = [_entry("x:A", "nc:AType", "aaaa")]
        result = compare_reports(old, new)
        assert result["droppedConcepts"] == ["x:B"]

    def test_empty_reports(self):
        result = compare_reports([], [])
        assert result["unchanged"] == []
        assert result["staleTypes"] == []
        assert result["newConcepts"] == []

    def test_null_type_hashes_not_stale(self):
        old = [_entry("x:A", None, None)]
        new = [_entry("x:A", None, None)]
        result = compare_reports(old, new)
        assert result["unchanged"] == ["x:A"]

    def test_null_to_non_null_hash_not_stale(self):
        """If old had no target (null hash), new having one isn't staleness."""
        old = [_entry("x:A", None, None)]
        new = [_entry("x:A", "nc:AType", "aaaa")]
        result = compare_reports(old, new)
        assert result["unchanged"] == ["x:A"]

    def test_stale_type_also_reports_stale_properties(self):
        old = [_entry("x:A", "nc:AType", "aaaa", [
            _prop("P1", "nc:B", "1111"),
        ])]
        new = [_entry("x:A", "nc:AType", "bbbb", [
            _prop("P1", "nc:B", "2222"),
        ])]
        result = compare_reports(old, new)
        assert len(result["staleTypes"]) == 1
        assert len(result["staleTypes"][0]["staleProperties"]) == 1
        assert result["staleProperties"] == []

    def test_sorted_output(self):
        old = [
            _entry("x:C", "nc:CType", "cccc"),
            _entry("x:A", "nc:AType", "aaaa"),
            _entry("x:B", "nc:BType", "bbbb"),
        ]
        new = [
            _entry("x:B", "nc:BType", "bbbb"),
            _entry("x:A", "nc:AType", "aaaa"),
            _entry("x:C", "nc:CType", "cccc"),
        ]
        result = compare_reports(old, new)
        assert result["unchanged"] == ["x:A", "x:B", "x:C"]


# ---------------------------------------------------------------------------
# TestBuildStalenessReport
# ---------------------------------------------------------------------------
class TestBuildStalenessReport:
    def test_report_structure(self):
        old = {
            "targetOntology": "niem", "targetVersion": "6.0",
            "generatedAt": "2026-01-01T00:00:00+00:00",
            "entries": [_entry("x:A", "nc:AType", "aaaa")],
        }
        new = {
            "targetOntology": "niem", "targetVersion": "6.1",
            "generatedAt": "2026-04-01T00:00:00+00:00",
            "entries": [_entry("x:A", "nc:AType", "bbbb")],
        }
        report = build_staleness_report(old, new)
        assert report["comparisonMetadata"]["oldReport"]["targetVersion"] == "6.0"
        assert report["comparisonMetadata"]["newReport"]["targetVersion"] == "6.1"
        assert report["summary"]["staleTypes"] == 1
        assert report["summary"]["unchanged"] == 0
        assert len(report["staleAlignments"]) == 1

    def test_summary_counts(self):
        old = {
            "entries": [
                _entry("x:A", "nc:AType", "aaaa", [
                    _prop("P1", "nc:B", "1111"),
                    _prop("P2", "nc:C", "2222"),
                ]),
                _entry("x:B", "nc:BType", "bbbb"),
                _entry("x:C", "nc:CType", "cccc"),
            ],
        }
        new = {
            "entries": [
                _entry("x:A", "nc:AType", "aaaa", [
                    _prop("P1", "nc:B", "1111"),
                    _prop("P2", "nc:C", "9999"),  # changed
                ]),
                _entry("x:B", "nc:BType", "xxxx"),  # type changed
                _entry("x:C", "nc:CType", "cccc"),
                _entry("x:D", "nc:DType", "dddd"),  # new
            ],
        }
        report = build_staleness_report(old, new)
        s = report["summary"]
        assert s["totalConcepts"] == 3  # A, B, C (shared)
        assert s["unchanged"] == 1  # C
        assert s["staleTypes"] == 1  # B
        assert s["stalePropertyOnly"] == 1  # A (property P2 changed)
        assert s["totalStaleProperties"] == 1  # P2
        assert s["newConcepts"] == 1  # D
        assert s["droppedConcepts"] == 0

    def test_empty_reports(self):
        report = build_staleness_report({"entries": []}, {"entries": []})
        assert report["summary"]["totalConcepts"] == 0
        assert report["staleAlignments"] == []

    def test_write_and_read_roundtrip(self, tmp_path):
        old = {
            "targetOntology": "niem", "targetVersion": "6.0",
            "entries": [_entry("x:A", "nc:AType", "aaaa")],
        }
        new = {
            "targetOntology": "niem", "targetVersion": "6.1",
            "entries": [_entry("x:A", "nc:AType", "bbbb")],
        }
        report = build_staleness_report(old, new)
        path = tmp_path / "staleness-report.json"
        path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        loaded = json.loads(path.read_text(encoding="utf-8"))
        assert loaded["summary"]["staleTypes"] == 1
