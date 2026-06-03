#!/usr/bin/env python3
"""Tests for preflight_specs.py — pre-flight inspection of target ontology specs."""

import json
import pytest
from pathlib import Path

from runner_tools.preflight_specs import (
    inspect_type_directory,
    inspect_catalog_summary,
    inspect_reference_catalog,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def type_directory(tmp_path):
    """Create a minimal type directory file."""
    content = "\n".join([
        "# Type directory for test ontology",
        "ns:TypeA | ns:BaseType | object | 3 | A test type | prop1, prop2, prop3",
        "ns:TypeB | ns:BaseType | association | 1 | Another type | prop4",
        "ns:TypeC | other:Base | simple_value | 0 | A value type |",
    ])
    p = tmp_path / "test_type_directory_1.0.txt"
    p.write_text(content, encoding="utf-8")
    return p


@pytest.fixture
def catalog_summary(tmp_path):
    """Create a minimal catalog summary JSON."""
    data = {
        "version": "1.0",
        "stats": {"totalTypes": 2, "totalNamespaces": 1},
        "namespaces": {
            "ns": {
                "label": "Test Namespace",
                "types": [
                    {"qname": "ns:TypeA", "definition": "A test type", "pattern": "object"},
                    {"qname": "ns:TypeB", "definition": "Another type", "pattern": "association"},
                ],
            },
        },
    }
    p = tmp_path / "test_catalog_summary_1.0.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


@pytest.fixture
def reference_catalog(tmp_path):
    """Create a minimal reference catalog JSON."""
    data = {
        "version": "1.0",
        "description": "Test reference catalog",
        "stats": {"totalTypes": 2, "totalProperties": 3},
        "namespaces": {"ns": {"uri": "urn:test:ns", "prefix": "ns"}},
        "types": [
            {
                "qname": "ns:TypeA",
                "definition": "A test type",
                "baseType": "ns:BaseType",
                "pattern": "object",
                "properties": ["ns:prop1", "ns:prop2"],
                "inheritanceChain": [],
            },
        ],
        "propertyIndex": {
            "ns": {
                "properties": [
                    {
                        "qualifiedProperty": "ns:prop1",
                        "name": "prop1",
                        "definition": "First property",
                        "qualifiedType": "xs:string",
                        "containingTypes": ["ns:TypeA"],
                        "isAbstract": False,
                    },
                ],
            },
        },
        "augmentationMap": {
            "ns:TypeA": {
                "augProperties": ["ns:extProp"],
                "augType": "ext:TypeAAugmentationType",
            },
        },
        "actions": {"reuse": "Reuse an existing type directly."},
        "typePatterns": {"object": "Standard object type."},
    }
    p = tmp_path / "test_reference_catalog_1.0.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# inspect_type_directory
# ---------------------------------------------------------------------------

class TestInspectTypeDirectory:
    def test_parses_entries(self, type_directory):
        info = inspect_type_directory(type_directory)
        assert info["totalLines"] == 3

    def test_extracts_namespaces(self, type_directory):
        info = inspect_type_directory(type_directory)
        assert "ns" in info["namespaces"]
        # Namespace is derived from qname prefix, not base type

    def test_counts_patterns(self, type_directory):
        info = inspect_type_directory(type_directory)
        assert info["patternCounts"]["object"] == 1
        assert info["patternCounts"]["association"] == 1
        assert info["patternCounts"]["simple_value"] == 1

    def test_has_format_string(self, type_directory):
        info = inspect_type_directory(type_directory)
        assert "qname" in info["format"]

    def test_has_sample_entry(self, type_directory):
        info = inspect_type_directory(type_directory)
        assert "TypeA" in info["sampleEntry"]


# ---------------------------------------------------------------------------
# inspect_catalog_summary
# ---------------------------------------------------------------------------

class TestInspectCatalogSummary:
    def test_extracts_version(self, catalog_summary):
        info = inspect_catalog_summary(catalog_summary)
        assert info["version"] == "1.0"

    def test_extracts_stats(self, catalog_summary):
        info = inspect_catalog_summary(catalog_summary)
        assert info["stats"]["totalTypes"] == 2

    def test_extracts_namespace_info(self, catalog_summary):
        info = inspect_catalog_summary(catalog_summary)
        assert "ns" in info["namespaces"]
        assert info["namespaces"]["ns"]["label"] == "Test Namespace"
        assert info["namespaces"]["ns"]["typeCount"] == 2

    def test_extracts_type_entry_schema(self, catalog_summary):
        info = inspect_catalog_summary(catalog_summary)
        assert "qname" in info["typeEntrySchema"]


# ---------------------------------------------------------------------------
# inspect_reference_catalog
# ---------------------------------------------------------------------------

class TestInspectReferenceCatalog:
    def test_extracts_version(self, reference_catalog):
        info = inspect_reference_catalog(reference_catalog)
        assert info["version"] == "1.0"

    def test_extracts_description(self, reference_catalog):
        info = inspect_reference_catalog(reference_catalog)
        assert "Test reference catalog" in info["description"]

    def test_extracts_top_level_keys(self, reference_catalog):
        info = inspect_reference_catalog(reference_catalog)
        assert "types" in info["topLevelKeys"]
        assert "propertyIndex" in info["topLevelKeys"]
        assert "augmentationMap" in info["topLevelKeys"]

    def test_extracts_type_schema(self, reference_catalog):
        info = inspect_reference_catalog(reference_catalog)
        assert "qname" in info["typeEntrySchema"]
        assert "baseType" in info["typeEntrySchema"]

    def test_extracts_property_index(self, reference_catalog):
        info = inspect_reference_catalog(reference_catalog)
        assert info["propertyIndex"]["totalProperties"] == 1
        assert "ns" in info["propertyIndex"]["namespaces"]

    def test_extracts_augmentation_map(self, reference_catalog):
        info = inspect_reference_catalog(reference_catalog)
        assert info["augmentationMap"]["totalBaseTypes"] == 1
        assert info["augmentationMap"]["sample"] is not None

    def test_extracts_property_entry_schema(self, reference_catalog):
        info = inspect_reference_catalog(reference_catalog)
        schema = info["propertyIndex"]["propertyEntrySchema"]
        assert "qualifiedProperty" in schema
        assert "definition" in schema
