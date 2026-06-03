"""Tests for ontology_mapper.adapters.source_adapter.

Tests type extraction, property extraction (object, datatype, SHACL),
deduplication, ontology name resolution, and error handling. Uses
synthetic concept-inventory data written to tmp_path.
"""

import json
import pytest

from ontology_mapper.adapters.source_adapter import (
    extract_types,
    extract_properties,
    ontology_name,
)
from ontology_mapper.vector_index import OntologyEntry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_inventory(run_dir, *, classes=None, object_properties=None,
                     datatype_properties=None, shacl_shapes=None):
    """Write a concept-inventory.json with the given sections."""
    inv = {
        "classes": classes or [],
        "objectProperties": object_properties or [],
        "datatypeProperties": datatype_properties or [],
        "shaclShapes": shacl_shapes or [],
    }
    path = run_dir / "concept-inventory.json"
    path.write_text(json.dumps(inv), encoding="utf-8")
    return path


def _write_state(run_dir, source_name):
    """Write a .mapper-state.json with a source name."""
    state = {"inputs": {"source": source_name}}
    path = run_dir / ".mapper-state.json"
    path.write_text(json.dumps(state), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# extract_types
# ---------------------------------------------------------------------------

class TestExtractTypes:

    def test_extracts_class_as_type_entry(self, tmp_path):
        _write_inventory(
            tmp_path,
            classes=[{
                "qname": "ex:Person",
                "comment": "A person",
                "subClassOf": "ex:Entity",
            }],
        )
        result = extract_types(tmp_path)

        assert len(result) == 1
        entry = result[0]
        assert isinstance(entry, OntologyEntry)
        assert entry.id == "ex:Person"
        assert entry.definition == "A person"
        assert entry.kind == "type"
        assert entry.metadata["subClassOf"] == "ex:Entity"
        assert entry.metadata["path"] == "ex:Entity/ex:Person"
        assert "Subclass of ex:Entity" in entry.context

    def test_class_with_properties_in_context(self, tmp_path):
        _write_inventory(
            tmp_path,
            classes=[{
                "qname": "ex:Person",
                "comment": "A person",
                "subClassOf": "ex:Entity",
            }],
            object_properties=[{
                "qname": "ex:knows",
                "comment": "Knows someone",
                "domain": ["ex:Person"],
                "range": ["ex:Person"],
            }],
            datatype_properties=[{
                "qname": "ex:name",
                "comment": "Name",
                "domain": ["ex:Person"],
                "range": ["xsd:string"],
            }],
        )
        result = extract_types(tmp_path)

        entry = result[0]
        assert "Properties:" in entry.context
        assert "knows" in entry.context
        assert "name" in entry.context
        assert entry.metadata["propertyCount"] == 2
        assert "knows" in entry.metadata["properties"]
        assert "name" in entry.metadata["properties"]

    def test_class_without_parent(self, tmp_path):
        _write_inventory(
            tmp_path,
            classes=[{
                "qname": "ex:Thing",
                "comment": "A thing",
            }],
        )
        result = extract_types(tmp_path)

        entry = result[0]
        assert entry.metadata["path"] == "ex:Thing"
        assert "Subclass of" not in entry.context

    def test_empty_inventory(self, tmp_path):
        _write_inventory(tmp_path)
        result = extract_types(tmp_path)
        assert result == []

    def test_missing_inventory_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="concept-inventory.json"):
            extract_types(tmp_path)


# ---------------------------------------------------------------------------
# extract_properties
# ---------------------------------------------------------------------------

class TestExtractProperties:

    def test_extracts_object_property(self, tmp_path):
        _write_inventory(
            tmp_path,
            object_properties=[{
                "qname": "ex:knows",
                "comment": "Knows someone",
                "domain": ["ex:Person"],
                "range": ["ex:Person"],
            }],
        )
        result = extract_properties(tmp_path)

        assert len(result) == 1
        entry = result[0]
        assert isinstance(entry, OntologyEntry)
        assert entry.id == "ex:knows"
        assert entry.definition == "Knows someone"
        assert entry.kind == "property"
        assert entry.metadata["propertyType"] == "object"
        assert entry.metadata["domain"] == ["ex:Person"]
        assert entry.metadata["range"] == ["ex:Person"]
        assert entry.metadata["localName"] == "knows"
        assert entry.metadata["paths"] == ["ex:Person/ex:knows"]

    def test_extracts_datatype_property(self, tmp_path):
        _write_inventory(
            tmp_path,
            datatype_properties=[{
                "qname": "ex:name",
                "comment": "Name",
                "domain": ["ex:Person"],
                "range": ["xsd:string"],
            }],
        )
        result = extract_properties(tmp_path)

        assert len(result) == 1
        entry = result[0]
        assert entry.metadata["propertyType"] == "datatype"
        assert entry.metadata["range"] == ["xsd:string"]

    def test_deduplicates_properties(self, tmp_path):
        """Same qname in both objectProperties and datatypeProperties yields one entry."""
        shared = {
            "qname": "ex:value",
            "comment": "A value",
            "domain": ["ex:Thing"],
            "range": ["xsd:string"],
        }
        _write_inventory(
            tmp_path,
            object_properties=[shared],
            datatype_properties=[shared],
        )
        result = extract_properties(tmp_path)

        qnames = [e.id for e in result]
        assert qnames.count("ex:value") == 1

    def test_extracts_shacl_properties(self, tmp_path):
        _write_inventory(
            tmp_path,
            shacl_shapes=[{
                "targetClass": "ex:Person",
                "properties": [{
                    "path": "ex:age",
                    "datatype": "xsd:integer",
                }],
            }],
        )
        result = extract_properties(tmp_path)

        assert len(result) == 1
        entry = result[0]
        assert entry.id == "ex:age"
        assert entry.kind == "property"
        assert entry.metadata["propertyType"] == "shacl"
        assert entry.metadata["domain"] == ["ex:Person"]
        assert entry.metadata["range"] == ["xsd:integer"]
        assert entry.metadata["paths"] == ["ex:Person/ex:age"]

    def test_empty_inventory(self, tmp_path):
        _write_inventory(tmp_path)
        result = extract_properties(tmp_path)
        assert result == []


# ---------------------------------------------------------------------------
# ontology_name
# ---------------------------------------------------------------------------

class TestOntologyName:

    def test_reads_from_state_file(self, tmp_path):
        _write_state(tmp_path, "my-ontology")
        assert ontology_name(tmp_path) == "my-ontology"

    def test_fallback_to_dir_name(self, tmp_path):
        """No state file — falls back to directory name, stripping timestamp suffix."""
        run_dir = tmp_path / "my-ontology_20260405"
        run_dir.mkdir()
        assert ontology_name(run_dir) == "my-ontology"

    def test_fallback_keeps_short_suffix(self, tmp_path):
        """Directory name with short suffix (not timestamp-like) is returned as-is."""
        run_dir = tmp_path / "simple"
        run_dir.mkdir()
        assert ontology_name(run_dir) == "simple"
