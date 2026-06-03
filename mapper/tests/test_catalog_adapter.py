"""Tests for ontology_mapper.adapters.catalog_adapter.

Tests label extraction, opaque ID filtering, context string building,
and the skip-no-label-no-definition behavior. Uses a synthetic catalog
written to a temp directory to avoid depending on real reference data.
"""

import json
import pytest
from unittest.mock import patch

from ontology_mapper.vector_index import OntologyEntry


# ---------------------------------------------------------------------------
# Synthetic catalog fixture
# ---------------------------------------------------------------------------

def _make_catalog(types=None, property_index=None):
    """Build a minimal catalog dict."""
    return {
        "types": types or [],
        "propertyIndex": property_index or {},
    }


def _make_type(qname, label="", definition="A definition.", pattern="object",
               base_type="", properties=None, inheritance_chain=None,
               alt_labels=None):
    return {
        "qname": qname,
        "label": label,
        "altLabels": alt_labels or [],
        "definition": definition,
        "pattern": pattern,
        "baseType": base_type,
        "properties": properties or [],
        "inheritanceChain": inheritance_chain or [],
        "isAugmentation": pattern == "augmentation",
        "isAdapter": False,
        "isMetadata": False,
    }


def _make_property(qprop, name="", label="", definition="A property.",
                   qual_type="", containing_types=None, is_abstract=False):
    return {
        "qualifiedProperty": qprop,
        "name": name or qprop.split(":")[-1] if ":" in qprop else qprop,
        "label": label,
        "definition": definition,
        "qualifiedType": qual_type,
        "containingTypes": containing_types or [],
        "isAbstract": is_abstract,
    }


@pytest.fixture
def catalog_dir(tmp_path):
    """Write a synthetic catalog and patch _find_catalog to return it."""
    def _write(name, version, catalog_dict):
        path = tmp_path / f"{name}_reference_catalog_{version}.json"
        path.write_text(json.dumps(catalog_dict), encoding="utf-8")
        return path

    return _write


def _extract_types_from(catalog_dir, catalog_dict, name="test", version="1.0"):
    """Write catalog and extract types, patching the file lookup."""
    path = catalog_dir(name, version, catalog_dict)
    with patch("ontology_mapper.adapters.catalog_adapter._find_catalog", return_value=path):
        from ontology_mapper.adapters.catalog_adapter import extract_types
        return extract_types(name, version)


def _extract_props_from(catalog_dir, catalog_dict, name="test", version="1.0"):
    """Write catalog and extract properties, patching the file lookup."""
    path = catalog_dir(name, version, catalog_dict)
    with patch("ontology_mapper.adapters.catalog_adapter._find_catalog", return_value=path):
        from ontology_mapper.adapters.catalog_adapter import extract_properties
        return extract_properties(name, version)


# ---------------------------------------------------------------------------
# Tests: label handling in types
# ---------------------------------------------------------------------------

class TestTypeLabelHandling:
    def test_label_passed_to_entry(self, catalog_dir):
        cat = _make_catalog(types=[
            _make_type("sali:ABC123", label="Court Filing"),
        ])
        entries = _extract_types_from(catalog_dir, cat)
        assert len(entries) == 1
        assert entries[0].label == "Court Filing"

    def test_label_used_in_embedding_text(self, catalog_dir):
        cat = _make_catalog(types=[
            _make_type("sali:XYZ789", label="Legal Matter", definition="A case."),
        ])
        entries = _extract_types_from(catalog_dir, cat)
        text = entries[0].embedding_text()
        assert "Legal Matter" in text
        assert "sali:XYZ789" not in text

    def test_no_label_falls_back_to_qname_in_embedding(self, catalog_dir):
        cat = _make_catalog(types=[
            _make_type("nc:PersonType", label="", definition="A human being."),
        ])
        entries = _extract_types_from(catalog_dir, cat)
        text = entries[0].embedding_text()
        assert "nc:PersonType" in text

    def test_label_used_in_inheritance_path(self, catalog_dir):
        cat = _make_catalog(types=[
            _make_type("sali:BASE", label="Base Thing"),
            _make_type("sali:CHILD", label="Specific Thing",
                       base_type="sali:BASE",
                       inheritance_chain=["sali:ROOT", "sali:BASE"]),
        ])
        entries = _extract_types_from(catalog_dir, cat)
        child = [e for e in entries if e.id == "sali:CHILD"][0]
        assert "Base Thing" in child.context
        assert "sali:BASE" not in child.context

    def test_label_used_for_properties_in_context(self, catalog_dir):
        cat = _make_catalog(
            types=[
                _make_type("sali:T1", label="Parent Type",
                           properties=["sali:P1"]),
            ],
            property_index={"sali": {"properties": [
                _make_property("sali:P1", label="Child Name"),
            ]}},
        )
        entries = _extract_types_from(catalog_dir, cat)
        assert "Child Name" in entries[0].context
        assert "sali:P1" not in entries[0].context

    def test_alt_labels_in_metadata(self, catalog_dir):
        cat = _make_catalog(types=[
            _make_type("sali:X", label="Primary", alt_labels=["Alt1", "Alt2"]),
        ])
        entries = _extract_types_from(catalog_dir, cat)
        assert entries[0].metadata["altLabels"] == ["Alt1", "Alt2"]


# ---------------------------------------------------------------------------
# Tests: label handling in properties
# ---------------------------------------------------------------------------

class TestPropertyLabelHandling:
    def test_label_passed_to_entry(self, catalog_dir):
        cat = _make_catalog(property_index={"ns": {"properties": [
            _make_property("ns:prop1", label="Street Address"),
        ]}})
        entries = _extract_props_from(catalog_dir, cat)
        assert len(entries) == 1
        assert entries[0].label == "Street Address"

    def test_label_used_in_embedding_text(self, catalog_dir):
        cat = _make_catalog(property_index={"ns": {"properties": [
            _make_property("ns:OPAQUE123", label="City Name",
                           definition="The city."),
        ]}})
        entries = _extract_props_from(catalog_dir, cat)
        text = entries[0].embedding_text()
        assert "City Name" in text
        assert "ns:OPAQUE123" not in text

    def test_label_used_in_path_context(self, catalog_dir):
        cat = _make_catalog(
            types=[_make_type("ns:Parent", label="Parent Type")],
            property_index={"ns": {"properties": [
                _make_property("ns:prop", label="My Prop",
                               containing_types=["ns:Parent"]),
            ]}},
        )
        entries = _extract_props_from(catalog_dir, cat)
        assert "Parent Type/My Prop" in entries[0].context

    def test_label_used_for_qualified_type(self, catalog_dir):
        cat = _make_catalog(
            types=[_make_type("ns:TypeA", label="Readable Type")],
            property_index={"ns": {"properties": [
                _make_property("ns:prop", label="My Prop",
                               qual_type="ns:TypeA"),
            ]}},
        )
        entries = _extract_props_from(catalog_dir, cat)
        assert "Readable Type" in entries[0].context


# ---------------------------------------------------------------------------
# Tests: skip entries with no label and no definition
# ---------------------------------------------------------------------------

class TestSkipEmptyEntries:
    def test_type_with_no_label_no_definition_skipped(self, catalog_dir):
        cat = _make_catalog(types=[
            _make_type("sali:OPAQUE1", label="", definition=""),
            _make_type("sali:OPAQUE2", label="Good Label", definition=""),
        ])
        entries = _extract_types_from(catalog_dir, cat)
        assert len(entries) == 1
        assert entries[0].label == "Good Label"

    def test_type_with_definition_but_no_label_kept(self, catalog_dir):
        cat = _make_catalog(types=[
            _make_type("ns:Orphan", label="", definition="An orphaned concept."),
        ])
        entries = _extract_types_from(catalog_dir, cat)
        assert len(entries) == 1

    def test_type_with_label_but_no_definition_kept(self, catalog_dir):
        cat = _make_catalog(types=[
            _make_type("sali:X", label="Has Label", definition=""),
        ])
        entries = _extract_types_from(catalog_dir, cat)
        assert len(entries) == 1

    def test_property_with_no_label_no_definition_skipped(self, catalog_dir):
        cat = _make_catalog(property_index={"ns": {"properties": [
            _make_property("ns:OPAQUE", label="", definition=""),
            _make_property("ns:good", label="Good", definition="Defined."),
        ]}})
        entries = _extract_props_from(catalog_dir, cat)
        assert len(entries) == 1
        assert entries[0].label == "Good"

    def test_property_with_definition_but_no_label_kept(self, catalog_dir):
        cat = _make_catalog(property_index={"ns": {"properties": [
            _make_property("ns:prop", label="", definition="Has a definition."),
        ]}})
        entries = _extract_props_from(catalog_dir, cat)
        assert len(entries) == 1


# ---------------------------------------------------------------------------
# Tests: existing skip rules still work
# ---------------------------------------------------------------------------

class TestExistingSkipRules:
    def test_augmentation_types_skipped(self, catalog_dir):
        cat = _make_catalog(types=[
            _make_type("nc:PersonAugmentation", pattern="augmentation",
                       label="Aug", definition="Augments Person."),
            _make_type("nc:PersonType", pattern="object", definition="A person."),
        ])
        entries = _extract_types_from(catalog_dir, cat)
        assert len(entries) == 1
        assert entries[0].id == "nc:PersonType"

    def test_abstract_properties_skipped(self, catalog_dir):
        cat = _make_catalog(property_index={"nc": {"properties": [
            _make_property("nc:PersonAbstract", is_abstract=True,
                           definition="Abstract head."),
            _make_property("nc:PersonName", definition="Concrete name."),
        ]}})
        entries = _extract_props_from(catalog_dir, cat)
        assert len(entries) == 1
        assert entries[0].id == "nc:PersonName"


# ---------------------------------------------------------------------------
# Tests: entry structure
# ---------------------------------------------------------------------------

class TestEntryStructure:
    def test_type_entry_has_expected_fields(self, catalog_dir):
        cat = _make_catalog(types=[
            _make_type("nc:PersonType", definition="A person.",
                       base_type="s:ComplexObjectType", pattern="object"),
        ])
        entries = _extract_types_from(catalog_dir, cat)
        e = entries[0]
        assert e.id == "nc:PersonType"
        assert e.kind == "type"
        assert "A person." in e.definition
        assert e.metadata["baseType"] == "s:ComplexObjectType"
        assert e.metadata["pattern"] == "object"
        assert e.metadata["namespace"] == "nc"

    def test_property_entry_has_expected_fields(self, catalog_dir):
        cat = _make_catalog(property_index={"nc": {"properties": [
            _make_property("nc:PersonName", name="PersonName",
                           definition="A name.", qual_type="nc:TextType",
                           containing_types=["nc:PersonType"]),
        ]}})
        entries = _extract_props_from(catalog_dir, cat)
        e = entries[0]
        assert e.id == "nc:PersonName"
        assert e.kind == "property"
        assert e.metadata["namespace"] == "nc"
        assert e.metadata["qualifiedType"] == "nc:TextType"
        assert "nc:PersonType" in e.metadata["containingTypes"]
