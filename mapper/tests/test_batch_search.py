"""Tests for ontology_mapper.batch_search module.

All tests mock query_index so they run without FAISS/sentence-transformers.
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from ontology_mapper.batch_search import (
    build_type_file,
    build_property_file,
    disambiguate_ids,
    filter_candidates,
    load_source_concepts,
    sanitize_filename,
    search_all_properties,
    search_all_types,
    strip_scores,
    write_search_results,
    _property_qname,
)
from ontology_mapper.vector_index import OntologyEntry


# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

CONCEPT_A = {
    "qname": "dbpi:AddressType",
    "localName": "AddressType",
    "definition": "A physical mailing address.",
    "properties": [
        {"name": "streetName", "definition": "The name of the street", "range": ["xsd:string"]},
        {"name": "cityName", "definition": "The name of the city", "range": ["xsd:string"]},
    ],
    "propertyCount": 2,
    "superClasses": ["dbpi:LocationType"],
}

CONCEPT_B = {
    "qname": "dbpi:PersonType",
    "localName": "PersonType",
    "definition": "A human being.",
    "properties": [
        {"name": "fullName", "definition": "The full name of a person", "range": ["xsd:string"]},
    ],
    "propertyCount": 1,
    "superClasses": [],
}

TYPE_CANDIDATE = {
    "rank": 1, "score": 0.87,
    "id": "nc:AddressType", "namespace": "nc",
    "definition": "A postal address.", "kind": "type",
    "context": "", "metadata": {},
}

PROP_CANDIDATE = {
    "rank": 1, "score": 0.82,
    "id": "nc:StreetFullText", "namespace": "nc",
    "definition": "A complete street address.", "kind": "property",
    "context": "", "metadata": {},
}


def _make_query_result(entries, candidates):
    """Build the list[dict] that query_index returns."""
    from dataclasses import asdict
    return [
        {"query": asdict(e), "matches": list(candidates)}
        for e in entries
    ]


# ---------------------------------------------------------------------------
# TestSanitizeFilename
# ---------------------------------------------------------------------------

class TestSanitizeFilename:
    def test_colon_replaced(self):
        assert sanitize_filename("dbpi:AddressType") == "dbpi_AddressType"

    def test_multiple_colons(self):
        assert sanitize_filename("a:b:c") == "a_b_c"

    def test_no_colon(self):
        assert sanitize_filename("AddressType") == "AddressType"

    def test_empty(self):
        assert sanitize_filename("") == ""


# ---------------------------------------------------------------------------
# TestPropertyQname
# ---------------------------------------------------------------------------

class TestPropertyQname:
    def test_normal(self):
        assert _property_qname("dbpi:AddressType", "streetName") == "dbpi:streetName"

    def test_no_prefix(self):
        assert _property_qname("AddressType", "streetName") == "streetName"


# ---------------------------------------------------------------------------
# TestFilterCandidates
# ---------------------------------------------------------------------------

class TestFilterCandidates:
    def test_filters_below_ratio(self):
        cands = [
            {"rank": 1, "score": 1.0},
            {"rank": 2, "score": 0.90},
            {"rank": 3, "score": 0.79},
            {"rank": 4, "score": 0.50},
        ]
        result = filter_candidates(cands, 0.80)
        assert len(result) == 2
        assert result[0]["score"] == 1.0
        assert result[1]["score"] == 0.90

    def test_keeps_exact_boundary(self):
        cands = [
            {"rank": 1, "score": 1.0},
            {"rank": 2, "score": 0.80},
        ]
        result = filter_candidates(cands, 0.80)
        assert len(result) == 2

    def test_empty_input(self):
        assert filter_candidates([], 0.80) == []

    def test_all_pass(self):
        cands = [
            {"rank": 1, "score": 0.90},
            {"rank": 2, "score": 0.85},
        ]
        result = filter_candidates(cands, 0.80)
        assert len(result) == 2

    def test_zero_score(self):
        cands = [{"rank": 1, "score": 0.0}, {"rank": 2, "score": 0.0}]
        result = filter_candidates(cands, 0.80)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# TestLoadSourceConcepts
# ---------------------------------------------------------------------------

class TestLoadSourceConcepts:
    def test_valid_load(self, tmp_path):
        doc = {"concepts": [CONCEPT_A, CONCEPT_B]}
        (tmp_path / "source-concepts.json").write_text(
            json.dumps(doc), encoding="utf-8"
        )
        result = load_source_concepts(tmp_path)
        assert len(result) == 2
        assert result[0]["qname"] == "dbpi:AddressType"

    def test_missing_file(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="source-concepts.json"):
            load_source_concepts(tmp_path)


# ---------------------------------------------------------------------------
# TestSearchAllTypes
# ---------------------------------------------------------------------------

class TestSearchAllTypes:
    @patch("ontology_mapper.batch_search.query_index")
    def test_returns_per_concept(self, mock_qi):
        concepts = [CONCEPT_A, CONCEPT_B]

        def fake_qi(entries, target, kind, top_k=12):
            return _make_query_result(entries, [TYPE_CANDIDATE])

        mock_qi.side_effect = fake_qi

        result = search_all_types(concepts, "niem-6.0", top_k=10)

        assert "dbpi:AddressType" in result
        assert "dbpi:PersonType" in result
        assert result["dbpi:AddressType"][0]["id"] == "nc:AddressType"

        call_args = mock_qi.call_args
        entries = call_args[0][0]
        assert len(entries) == 2
        assert all(isinstance(e, OntologyEntry) for e in entries)
        assert entries[0].id == "dbpi:AddressType"
        assert entries[0].kind == "type"
        assert call_args[0][1] == "niem-6.0"
        assert call_args[0][2] == "types"
        assert call_args[1]["top_k"] == 10

    @patch("ontology_mapper.batch_search.query_index")
    def test_context_includes_superclasses(self, mock_qi):
        mock_qi.return_value = _make_query_result(
            [OntologyEntry(id="x", definition="", kind="type", context="")],
            [],
        )
        search_all_types([CONCEPT_A], "t", top_k=5)
        entry = mock_qi.call_args[0][0][0]
        assert "dbpi:LocationType" in entry.context


# ---------------------------------------------------------------------------
# TestSearchAllProperties
# ---------------------------------------------------------------------------

class TestSearchAllProperties:
    @patch("ontology_mapper.batch_search.query_index")
    def test_returns_nested_dict(self, mock_qi):
        concepts = [CONCEPT_A]  # 2 properties

        def fake_qi(entries, target, kind, top_k=12):
            return _make_query_result(entries, [PROP_CANDIDATE])

        mock_qi.side_effect = fake_qi

        result = search_all_properties(concepts, "niem-6.0")

        assert "dbpi:AddressType" in result
        assert "dbpi:streetName" in result["dbpi:AddressType"]
        assert "dbpi:cityName" in result["dbpi:AddressType"]

    @patch("ontology_mapper.batch_search.query_index")
    def test_context_includes_parent_definition(self, mock_qi):
        mock_qi.return_value = _make_query_result(
            [OntologyEntry(id="x", definition="", kind="property")],
            [],
        )
        search_all_properties([CONCEPT_A], "t")
        entry = mock_qi.call_args[0][0][0]
        assert "dbpi:AddressType" in entry.context
        assert "physical mailing address" in entry.context

    @patch("ontology_mapper.batch_search.query_index")
    def test_empty_properties(self, mock_qi):
        concept_no_props = {**CONCEPT_A, "properties": []}
        result = search_all_properties([concept_no_props], "t")
        assert result == {}
        mock_qi.assert_not_called()


# ---------------------------------------------------------------------------
# TestBuildTypeFile
# ---------------------------------------------------------------------------

class TestBuildTypeFile:
    def test_structure(self):
        doc = build_type_file(CONCEPT_A, [TYPE_CANDIDATE])
        assert doc["status"] == "pending"
        assert doc["kind"] == "type"
        assert doc["evaluation"] is None
        assert doc["source"]["qname"] == "dbpi:AddressType"
        assert doc["source"]["localName"] == "AddressType"
        assert doc["source"]["superClasses"] == ["dbpi:LocationType"]
        assert doc["candidates"] == [TYPE_CANDIDATE]

    def test_no_properties_in_source(self):
        doc = build_type_file(CONCEPT_A, [])
        assert "properties" not in doc["source"]


# ---------------------------------------------------------------------------
# TestBuildPropertyFile
# ---------------------------------------------------------------------------

class TestBuildPropertyFile:
    def test_structure(self):
        doc = build_property_file(
            concept_qname="dbpi:AddressType",
            concept_definition="A physical mailing address.",
            prop_name="streetName",
            prop_qname="dbpi:streetName",
            prop_definition="The name of the street",
            prop_range=["xsd:string"],
            candidates=[PROP_CANDIDATE],
        )
        assert doc["status"] == "pending"
        assert doc["kind"] == "property"
        assert doc["evaluation"] is None
        assert doc["source"]["qname"] == "dbpi:streetName"
        assert doc["source"]["name"] == "streetName"
        assert doc["source"]["parentType"] == "dbpi:AddressType"
        assert doc["source"]["parentDefinition"] == "A physical mailing address."
        assert doc["candidates"] == [PROP_CANDIDATE]


# ---------------------------------------------------------------------------
# TestWriteSearchResults
# ---------------------------------------------------------------------------

class TestWriteSearchResults:
    def test_creates_directories_and_files(self, tmp_path):
        concepts = [CONCEPT_A, CONCEPT_B]
        type_results = {
            "dbpi:AddressType": [TYPE_CANDIDATE],
            "dbpi:PersonType": [],
        }
        prop_results = {
            "dbpi:AddressType": {"dbpi:streetName": [PROP_CANDIDATE]},
        }

        counts = write_search_results(
            tmp_path, concepts, type_results, prop_results,
        )

        assert counts["types_written"] == 2
        assert counts["types_skipped"] == 0

        types_dir = tmp_path / "search-results" / "types"
        props_dir = tmp_path / "search-results" / "properties"
        assert types_dir.is_dir()
        assert props_dir.is_dir()
        assert (types_dir / "dbpi_AddressType.json").exists()
        assert (types_dir / "dbpi_PersonType.json").exists()
        assert (props_dir / "dbpi_streetName.json").exists()

        doc = json.loads(
            (types_dir / "dbpi_AddressType.json").read_text(encoding="utf-8")
        )
        assert doc["status"] == "pending"
        assert doc["kind"] == "type"
        assert doc["candidates"][0]["id"] == "nc:AddressType"

    def test_skips_evaluated_type_files(self, tmp_path):
        types_dir = tmp_path / "search-results" / "types"
        types_dir.mkdir(parents=True)

        evaluated = {"status": "evaluated", "evaluation": {"some": "data"}}
        (types_dir / "dbpi_AddressType.json").write_text(
            json.dumps(evaluated), encoding="utf-8"
        )

        concepts = [CONCEPT_A]
        counts = write_search_results(
            tmp_path, concepts, {"dbpi:AddressType": []}, {},
        )

        assert counts["types_written"] == 0
        assert counts["types_skipped"] == 1

        doc = json.loads(
            (types_dir / "dbpi_AddressType.json").read_text(encoding="utf-8")
        )
        assert doc["status"] == "evaluated"

    def test_skips_evaluated_property_files(self, tmp_path):
        props_dir = tmp_path / "search-results" / "properties"
        props_dir.mkdir(parents=True)

        evaluated = {"status": "evaluated", "evaluation": {"some": "data"}}
        (props_dir / "dbpi_streetName.json").write_text(
            json.dumps(evaluated), encoding="utf-8"
        )

        concepts = [CONCEPT_A]
        counts = write_search_results(
            tmp_path, concepts,
            {"dbpi:AddressType": [TYPE_CANDIDATE]},
            {"dbpi:AddressType": {"dbpi:streetName": [PROP_CANDIDATE]}},
        )

        assert counts["props_skipped"] == 1
        # cityName should still be written
        assert counts["props_written"] == 1

    def test_filters_low_score_candidates(self, tmp_path):
        high = {**TYPE_CANDIDATE, "rank": 1, "score": 1.0}
        low = {**TYPE_CANDIDATE, "rank": 2, "score": 0.50, "id": "nc:Noise"}
        concepts = [CONCEPT_B]  # no properties
        counts = write_search_results(
            tmp_path, concepts,
            {"dbpi:PersonType": [high, low]}, {},
            min_score_ratio=0.80,
        )

        doc = json.loads(
            (tmp_path / "search-results" / "types" / "dbpi_PersonType.json")
            .read_text(encoding="utf-8")
        )
        assert len(doc["candidates"]) == 1
        assert doc["candidates"][0]["id"] == "nc:AddressType"

    def test_overwrites_corrupt_files(self, tmp_path):
        types_dir = tmp_path / "search-results" / "types"
        types_dir.mkdir(parents=True)

        (types_dir / "dbpi_AddressType.json").write_text(
            "not valid json", encoding="utf-8"
        )

        concepts = [CONCEPT_A]
        counts = write_search_results(
            tmp_path, concepts, {"dbpi:AddressType": []}, {},
        )
        assert counts["types_written"] == 1


# ---------------------------------------------------------------------------
# TestStripScores
# ---------------------------------------------------------------------------

class TestStripScores:
    def test_removes_rank_and_score(self):
        cands = [{"rank": 1, "score": 0.9, "id": "nc:X", "definition": "D"}]
        result = strip_scores(cands)
        assert result == [{"id": "nc:X", "definition": "D"}]

    def test_preserves_other_fields(self):
        cands = [{"rank": 1, "score": 0.9, "id": "A", "qname": "A", "label": "L"}]
        result = strip_scores(cands)
        assert result[0] == {"id": "A", "qname": "A", "label": "L"}

    def test_empty_input(self):
        assert strip_scores([]) == []


# ---------------------------------------------------------------------------
# TestDisambiguateIds
# ---------------------------------------------------------------------------

class TestDisambiguateIds:
    def test_no_duplicates_returns_same(self):
        cands = [{"id": "A"}, {"id": "B"}, {"id": "C"}]
        result = disambiguate_ids(cands)
        assert result == cands

    def test_duplicate_ids_get_suffixed(self):
        cands = [
            {"id": "Legal Services", "qname": "abc123"},
            {"id": "Legal Services", "qname": "def456"},
            {"id": "Unique Thing", "qname": "ghi789"},
        ]
        result = disambiguate_ids(cands)
        assert result[0]["id"] == "Legal Services [1]"
        assert result[1]["id"] == "Legal Services [2]"
        assert result[2]["id"] == "Unique Thing"

    def test_preserves_other_fields(self):
        cands = [
            {"id": "Same", "qname": "q1", "definition": "d1"},
            {"id": "Same", "qname": "q2", "definition": "d2"},
        ]
        result = disambiguate_ids(cands)
        assert result[0]["qname"] == "q1"
        assert result[0]["definition"] == "d1"
        assert result[1]["qname"] == "q2"

    def test_three_way_duplicate(self):
        cands = [{"id": "X"}, {"id": "X"}, {"id": "X"}]
        result = disambiguate_ids(cands)
        assert [c["id"] for c in result] == ["X [1]", "X [2]", "X [3]"]

    def test_empty_input(self):
        assert disambiguate_ids([]) == []

    def test_does_not_mutate_original(self):
        cands = [{"id": "A"}, {"id": "A"}]
        disambiguate_ids(cands)
        assert cands[0]["id"] == "A"
        assert cands[1]["id"] == "A"
