#!/usr/bin/env python3
"""Tests for ingest_csv.py — CSV source domain ingestion."""

import csv
import json
import pytest
import tempfile

from ontology_mapper.ingest_csv import (
    parse_csv,
    parse_multiplicity,
    build_concept_inventory,
    _clean_definition,
    _merge_property_domains,
)


# ─── Fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture
def simple_csv(tmp_path):
    """A minimal CSV with 2 classes, attributes, and an object reference."""
    csv_path = tmp_path / "INPUT.csv"
    rows = [
        ["Model Class", "Model Attribute", "Model Type", "Model Multiplicity", "Model Definition"],
        ["Person", "", "", "", ""],
        ["Person", "FullName", "string", "1", "The full legal name"],
        ["Person", "BirthDate", "date", "0..1", "Date of birth"],
        ["Person", "Active", "bool", "1", "Is person active"],
        ["Person", "(Address)", "", "*", ""],
        ["Address", "", "", "", ""],
        ["Address", "Street", "string", "1", "Street address line"],
        ["Address", "ZipCode", "string", "0..1", "ZIP or postal code"],
    ]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerows(rows)
    return csv_path


@pytest.fixture
def csv_with_definitions(tmp_path):
    """CSV with Element# and User Story boilerplate in definitions."""
    csv_path = tmp_path / "INPUT.csv"
    rows = [
        ["Model Class", "Model Attribute", "Model Type", "Model Multiplicity", "Model Definition"],
        ["Case", "", "", "", ""],
        ["Case", "CaseNumber", "string", "1",
         "Unique identifier for the case\nElement# 1-1\nUser Story: I am a clerk and I need to find cases."],
        ["Case", "FilingDate", "date", "1",
         "Date case was filed\nElement# 1-2\nUser Story: "],
    ]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerows(rows)
    return csv_path


@pytest.fixture
def csv_with_typo_ref(tmp_path):
    """CSV with a parenthesized reference that doesn't exactly match class name."""
    csv_path = tmp_path / "INPUT.csv"
    rows = [
        ["Model Class", "Model Attribute", "Model Type", "Model Multiplicity", "Model Definition"],
        ["Container", "", "", "", ""],
        ["Container", "(Item)", "", "*", ""],
        ["Items", "", "", "", ""],
        ["Items", "Name", "string", "1", "Item name"],
    ]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerows(rows)
    return csv_path


# ─── parse_multiplicity ─────────────────────────────────────────────────

class TestParseMultiplicity:
    def test_single_required(self):
        assert parse_multiplicity("1") == (1, 1)

    def test_optional(self):
        assert parse_multiplicity("0..1") == (0, 1)

    def test_unbounded(self):
        assert parse_multiplicity("*") == (0, None)

    def test_one_or_more(self):
        assert parse_multiplicity("1..*") == (1, None)

    def test_empty(self):
        assert parse_multiplicity("") == (0, None)

    def test_none(self):
        assert parse_multiplicity(None) == (0, None)


# ─── _clean_definition ──────────────────────────────────────────────────

class TestCleanDefinition:
    def test_strips_element_number(self):
        result = _clean_definition("Some text\nElement# 15-9\nUser Story: ")
        assert result == "Some text"

    def test_keeps_user_story_text(self):
        result = _clean_definition("Desc\nElement# 1\nUser Story: I need to find cases.")
        assert result == "Desc I need to find cases."

    def test_empty_input(self):
        assert _clean_definition("") == ""

    def test_plain_text(self):
        assert _clean_definition("Just a description") == "Just a description"


# ─── parse_csv ───────────────────────────────────────────────────────────

class TestParseCsv:
    def test_class_count(self, simple_csv):
        classes = parse_csv(simple_csv)
        assert len(classes) == 2
        assert "Person" in classes
        assert "Address" in classes

    def test_datatype_attributes(self, simple_csv):
        classes = parse_csv(simple_csv)
        attrs = classes["Person"]["attributes"]
        names = [a["name"] for a in attrs]
        assert "FullName" in names
        assert "BirthDate" in names
        assert "Active" in names

    def test_object_references(self, simple_csv):
        classes = parse_csv(simple_csv)
        refs = classes["Person"]["object_refs"]
        assert len(refs) == 1
        assert refs[0]["ref_name"] == "Address"

    def test_definition_cleaning(self, csv_with_definitions):
        classes = parse_csv(csv_with_definitions)
        case_num = next(a for a in classes["Case"]["attributes"] if a["name"] == "CaseNumber")
        assert "Element#" not in case_num["definition"]
        assert "I am a clerk" in case_num["definition"]


# ─── build_concept_inventory ─────────────────────────────────────────────

class TestBuildConceptInventory:
    def test_produces_valid_structure(self, simple_csv):
        classes = parse_csv(simple_csv)
        inv = build_concept_inventory(classes, simple_csv, "test", "urn:test")
        required_keys = {
            "extractedAt", "sourcePackage", "primaryNamespace", "namespaceMap",
            "summary", "classes", "objectProperties", "datatypeProperties",
            "codelistSchemes", "workflowModels", "shaclShapes", "augmentingNamespaces",
        }
        assert required_keys.issubset(inv.keys())

    def test_class_entries(self, simple_csv):
        classes = parse_csv(simple_csv)
        inv = build_concept_inventory(classes, simple_csv, "test", "urn:test")
        qnames = [c["qname"] for c in inv["classes"]]
        assert "test:Person" in qnames
        assert "test:Address" in qnames

    def test_class_fields(self, simple_csv):
        classes = parse_csv(simple_csv)
        inv = build_concept_inventory(classes, simple_csv, "test", "urn:test")
        person = next(c for c in inv["classes"] if c["qname"] == "test:Person")
        assert person["label"] == "Person"
        assert person["iri"] == "urn:test#Person"
        assert person["subClassOf"] == []
        assert "comment" in person

    def test_datatype_properties(self, simple_csv):
        classes = parse_csv(simple_csv)
        inv = build_concept_inventory(classes, simple_csv, "test", "urn:test")
        dp_qnames = [p["qname"] for p in inv["datatypeProperties"]]
        assert "test:FullName" in dp_qnames
        assert "test:BirthDate" in dp_qnames

    def test_datatype_property_domains(self, simple_csv):
        classes = parse_csv(simple_csv)
        inv = build_concept_inventory(classes, simple_csv, "test", "urn:test")
        fullname = next(p for p in inv["datatypeProperties"] if p["qname"] == "test:FullName")
        assert "test:Person" in fullname["domain"]

    def test_datatype_property_ranges(self, simple_csv):
        classes = parse_csv(simple_csv)
        inv = build_concept_inventory(classes, simple_csv, "test", "urn:test")
        bdate = next(p for p in inv["datatypeProperties"] if p["qname"] == "test:BirthDate")
        assert "xs:date" in bdate["range"]

    def test_object_properties(self, simple_csv):
        classes = parse_csv(simple_csv)
        inv = build_concept_inventory(classes, simple_csv, "test", "urn:test")
        op_qnames = [p["qname"] for p in inv["objectProperties"]]
        assert "test:Address" in op_qnames

    def test_object_property_range(self, simple_csv):
        classes = parse_csv(simple_csv)
        inv = build_concept_inventory(classes, simple_csv, "test", "urn:test")
        addr = next(p for p in inv["objectProperties"] if p["qname"] == "test:Address")
        assert "test:Address" in addr["range"]

    def test_shacl_shapes(self, simple_csv):
        classes = parse_csv(simple_csv)
        inv = build_concept_inventory(classes, simple_csv, "test", "urn:test")
        shape_targets = [s["targetClass"] for s in inv["shaclShapes"]]
        assert "test:Person" in shape_targets
        assert "test:Address" in shape_targets

    def test_shape_cardinalities(self, simple_csv):
        classes = parse_csv(simple_csv)
        inv = build_concept_inventory(classes, simple_csv, "test", "urn:test")
        person_shape = next(s for s in inv["shaclShapes"] if s["targetClass"] == "test:Person")
        fullname_prop = next(p for p in person_shape["properties"] if p["path"] == "test:FullName")
        assert fullname_prop["minCount"] == 1
        assert fullname_prop["maxCount"] == 1
        bdate_prop = next(p for p in person_shape["properties"] if p["path"] == "test:BirthDate")
        assert bdate_prop["minCount"] == 0
        assert bdate_prop["maxCount"] == 1

    def test_summary_counts(self, simple_csv):
        classes = parse_csv(simple_csv)
        inv = build_concept_inventory(classes, simple_csv, "test", "urn:test")
        assert inv["summary"]["classCount"] == 2
        assert inv["summary"]["objectPropertyCount"] == 1
        assert inv["summary"]["datatypePropertyCount"] == 5  # 3 Person + 2 Address
        assert inv["summary"]["shaclShapeCount"] == 2

    def test_typo_ref_resolved(self, csv_with_typo_ref):
        classes = parse_csv(csv_with_typo_ref)
        inv = build_concept_inventory(classes, csv_with_typo_ref, "test", "urn:test")
        item_ref = next(p for p in inv["objectProperties"] if p["qname"] == "test:Item")
        # Should resolve "Item" → "Items" via fuzzy match
        assert "test:Items" in item_ref["range"]


# ─── _merge_property_domains ────────────────────────────────────────────

class TestMergePropertyDomains:
    def test_merges_domains(self):
        props = [
            {"qname": "test:Name", "iri": "urn:1", "label": "Name", "comment": "",
             "domain": ["test:A"], "range": ["xs:string"]},
            {"qname": "test:Name", "iri": "urn:2", "label": "Name", "comment": "",
             "domain": ["test:B"], "range": ["xs:string"]},
        ]
        merged = _merge_property_domains(props)
        assert len(merged) == 1
        assert set(merged[0]["domain"]) == {"test:A", "test:B"}

    def test_preserves_unique(self):
        props = [
            {"qname": "test:A", "iri": "urn:1", "label": "A", "comment": "",
             "domain": ["test:X"], "range": ["xs:string"]},
            {"qname": "test:B", "iri": "urn:2", "label": "B", "comment": "",
             "domain": ["test:Y"], "range": ["xs:date"]},
        ]
        merged = _merge_property_domains(props)
        assert len(merged) == 2
