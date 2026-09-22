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


def test_existing_index_classes_ranked_below_datatypes_still_fill_top_k(
        native_class_catalog, fake_type_retrieval, tmp_path):
    """The native filter runs over the full ranking, before top-k and the score floor."""
    fake_type_retrieval(["alias:Restricted", "alias:Values",
                         "alias:Record", "alias:InheritedLiteral", "alias:Literal"])
    concepts = [{"qname": "source:Record", "properties": []}]
    results = search_all_types(concepts, "example-1.0", top_k=2)
    assert [c["id"] for c in results["source:Record"]] == ["alias:Record", "alias:InheritedLiteral"]
    write_search_results(tmp_path, concepts, results, {}, min_score_ratio=0.75)
    doc = json.loads((tmp_path / "search-results/types/source_Record.json").read_text(encoding="utf-8"))
    assert [c["id"] for c in doc["candidates"]] == ["alias:Record", "alias:InheritedLiteral"]


def test_property_search_keeps_datatype_valued_candidates(native_class_catalog):
    candidate = {"id": "alias:value", "metadata": {"qualifiedType": "alias:Restricted"}}
    concepts = [{"qname": "source:Record", "properties": [{"name": "value", "qname": "source:value"}]}]
    with patch("ontology_mapper.batch_search.query_index", return_value=[{"matches": [candidate]}]):
        results = search_all_properties(concepts, "example-1.0")
    assert results["source:Record"]["source:value"] == [candidate]


@pytest.mark.parametrize("legacy", [False, True])
def test_shared_cross_namespace_property_keeps_both_parents_and_resumes(tmp_path, legacy):
    from ontology_mapper.collect_alignments import load_search_results, reassemble_evaluations

    concepts = [{"qname": parent, "definition": "", "properties": [
        {"name": "flag", "qname": "other:flag"}]} for parent in ("src:A", "src:B")]
    results = {c["qname"]: {"other:flag": [PROP_CANDIDATE]} for c in concepts}
    if legacy:
        directory = tmp_path / "search-results" / "properties"
        directory.mkdir(parents=True)
        doc = build_property_file("src:A", "", "flag", "other:flag", "", [], [])
        doc.update(status="evaluated", evaluation={"sourceProperty": "other:flag", "targetProperty": "nc:Saved"})
        (directory / "other_flag.json").write_text(json.dumps(doc), encoding="utf-8")

    write_search_results(tmp_path, concepts, {}, results)
    types, props = load_search_results(tmp_path)
    assert {(p["source"]["parentType"], p["source"]["qname"]) for _, p in props} == {
        ("src:A", "other:flag"), ("src:B", "other:flag")}
    for filename, doc in types:
        doc.update(status="evaluated", evaluation={"sourceConcept": doc["source"]["qname"]})
        (tmp_path / "search-results" / "types" / filename).write_text(json.dumps(doc), encoding="utf-8")
    for filename, doc in props:
        if doc["status"] != "evaluated":
            assert doc["candidates"][0]["id"] == "nc:StreetFullText"
            doc.update(status="evaluated", evaluation={"sourceProperty": "other:flag", "targetProperty": "nc:Chosen"})
        (tmp_path / "search-results" / "properties" / filename).write_text(json.dumps(doc), encoding="utf-8")
    before = {p.name: p.read_bytes() for p in (tmp_path / "search-results" / "properties").glob("*.json")}
    counts = write_search_results(tmp_path, list(reversed(concepts)), {}, results)
    assert counts["props_skipped"] == 2
    assert before == {p.name: p.read_bytes() for p in (tmp_path / "search-results" / "properties").glob("*.json")}
    combined = reassemble_evaluations(*load_search_results(tmp_path))
    assert all(len(e["properties"]) == 1 for e in combined)
    if legacy:
        assert next(e for e in combined if e["sourceConcept"] == "src:A")["properties"][0]["targetProperty"] == "nc:Saved"


def _write_evaluated_property_file(tmp_path, filename, parent, qname, target):
    directory = tmp_path / "search-results" / "properties"
    directory.mkdir(parents=True, exist_ok=True)
    doc = build_property_file(parent, "", qname.split(":")[-1], qname, "", [], [])
    doc.update(status="evaluated", evaluation={"sourceProperty": qname, "targetProperty": target})
    (directory / filename).write_text(json.dumps(doc), encoding="utf-8")


def test_legacy_file_qualified_under_parent_prefix_is_reused_not_duplicated(tmp_path):
    """A pre-declaration file recorded `src:flag` for the augmenting-namespace
    property `other:flag`; the declared identity must find that evaluated file
    instead of leaving it as a phantom beside a new pending one."""
    _write_evaluated_property_file(tmp_path, "src_flag.json", "src:A", "src:flag", "nc:Saved")
    concepts = [{"qname": "src:A", "definition": "", "properties": [{"name": "flag", "qname": "other:flag"}]}]

    counts = write_search_results(tmp_path, concepts, {}, {"src:A": {"other:flag": [PROP_CANDIDATE]}})

    props_dir = tmp_path / "search-results" / "properties"
    assert counts["props_skipped"] == 1 and counts["props_written"] == 0
    assert sorted(p.name for p in props_dir.glob("*.json")) == ["src_flag.json"]
    from ontology_mapper.collect_alignments import load_search_results, reassemble_evaluations
    types, props = load_search_results(tmp_path)
    assert [(p["status"], p["evaluation"]["targetProperty"]) for _, p in props] == [("evaluated", "nc:Saved")]
    # The reused file now carries the declared identity, so the decision
    # reaches collection as `other:flag` — the identity the inventory and the
    # emitters key by — with no inventory-wide local-name resolution needed.
    assert [p["source"]["qname"] for _, p in props] == ["other:flag"]
    assert [p["evaluation"]["sourceProperty"] for _, p in props] == ["other:flag"]
    for filename, doc in types:
        doc.update(status="evaluated", evaluation={"sourceConcept": doc["source"]["qname"]})
        (tmp_path / "search-results" / "types" / filename).write_text(json.dumps(doc), encoding="utf-8")
    [combined] = reassemble_evaluations(*load_search_results(tmp_path))
    assert [(p["sourceProperty"], p["targetProperty"]) for p in combined["properties"]] == [("other:flag", "nc:Saved")]


def test_requalified_legacy_file_is_matched_exactly_on_the_next_resume(tmp_path):
    """After the first resume the file is `other:flag`; a later `x:flag` on the
    same parent gets its own file and the evaluated decision is untouched."""
    _write_evaluated_property_file(tmp_path, "src_flag.json", "src:A", "src:flag", "nc:Saved")
    first = [{"qname": "src:A", "definition": "", "properties": [{"name": "flag", "qname": "other:flag"}]}]
    write_search_results(tmp_path, first, {}, {"src:A": {"other:flag": [PROP_CANDIDATE]}})

    later = [{"qname": "src:A", "definition": "", "properties": [
        {"name": "flag", "qname": "other:flag"}, {"name": "flag", "qname": "x:flag"}]}]
    counts = write_search_results(tmp_path, later, {}, {"src:A": {
        "other:flag": [PROP_CANDIDATE], "x:flag": [PROP_CANDIDATE]}})

    props_dir = tmp_path / "search-results" / "properties"
    assert counts["props_skipped"] == 1 and counts["props_written"] == 1
    assert sorted(p.name for p in props_dir.glob("*.json")) == ["src_flag.json", "x_flag.json"]
    kept = json.loads((props_dir / "src_flag.json").read_text(encoding="utf-8"))
    assert kept["source"]["qname"] == "other:flag" and kept["evaluation"]["targetProperty"] == "nc:Saved"


def test_a_file_recorded_under_another_namespace_is_never_claimed(tmp_path):
    """Only the mis-qualification the rule exists for is claimed.

    `aux:flag` is not what `_property_qname` would have manufactured for
    a property on `src:A`; it is a different property that happens to
    share a local name, and claiming its file would transplant its
    reviewer's decision — and its stale definition — onto `other:flag`.
    """
    _write_evaluated_property_file(tmp_path, "aux_flag.json", "src:A", "aux:flag", "nc:Two")
    concepts = [{"qname": "src:A", "definition": "", "properties": [{"name": "flag", "qname": "other:flag"}]}]

    counts = write_search_results(tmp_path, concepts, {}, {"src:A": {"other:flag": [PROP_CANDIDATE]}})

    props_dir = tmp_path / "search-results" / "properties"
    assert counts["props_written"] == 1
    # The unrelated file is left alone and the current property gets its own.
    assert sorted(p.name for p in props_dir.glob("*.json")) == ["aux_flag.json", "other_flag.json"]
    kept = json.loads((props_dir / "aux_flag.json").read_text(encoding="utf-8"))
    assert kept["source"]["qname"] == "aux:flag"
    assert kept["evaluation"]["targetProperty"] == "nc:Two"


def test_two_current_properties_sharing_a_local_name_do_not_share_one_legacy_file(tmp_path):
    """`a:flag` and `b:flag` on one parent, one legacy `src:flag`: neither may
    claim it, or the second occurrence would be silently dropped."""
    _write_evaluated_property_file(tmp_path, "src_flag.json", "src:A", "src:flag", "nc:Saved")
    concepts = [{"qname": "src:A", "definition": "", "properties": [
        {"name": "flag", "qname": "a:flag"}, {"name": "flag", "qname": "b:flag"}]}]

    counts = write_search_results(tmp_path, concepts, {}, {"src:A": {
        "a:flag": [PROP_CANDIDATE], "b:flag": [PROP_CANDIDATE]}})

    props_dir = tmp_path / "search-results" / "properties"
    assert counts["props_written"] == 2
    assert sorted(p.name for p in props_dir.glob("*.json")) == ["a_flag.json", "b_flag.json", "src_flag.json"]


def test_file_matching_a_current_identity_is_not_offered_as_legacy(tmp_path):
    """`other:flag` exists exactly and `x:flag` is new: the exact file belongs
    to `other:flag`; `x:flag` gets its own file."""
    _write_evaluated_property_file(tmp_path, "other_flag.json", "src:A", "other:flag", "nc:Saved")
    concepts = [{"qname": "src:A", "definition": "", "properties": [
        {"name": "flag", "qname": "other:flag"}, {"name": "flag", "qname": "x:flag"}]}]

    counts = write_search_results(tmp_path, concepts, {}, {"src:A": {
        "other:flag": [PROP_CANDIDATE], "x:flag": [PROP_CANDIDATE]}})

    props_dir = tmp_path / "search-results" / "properties"
    assert counts["props_skipped"] == 1 and counts["props_written"] == 1
    assert sorted(p.name for p in props_dir.glob("*.json")) == ["other_flag.json", "x_flag.json"]
    saved = json.loads((props_dir / "other_flag.json").read_text(encoding="utf-8"))
    assert saved["evaluation"]["targetProperty"] == "nc:Saved"


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

    def test_windows_illegal_chars_replaced(self):
        # < > : " / \ | ? * all map to underscore so a qname that leaks a
        # BoUML placeholder still yields a valid Windows filename stem.
        assert sanitize_filename("court:<unidirectional association>") == (
            "court__unidirectional association_")

    def test_all_illegal_chars(self):
        assert sanitize_filename('a<b>c:d"e/f\\g|h?i*j') == "a_b_c_d_e_f_g_h_i_j"


# ---------------------------------------------------------------------------
# TestPropertyQname
# ---------------------------------------------------------------------------

class TestPropertyQname:
    """the source ontology's own qname is the property's identity."""

    def test_carried_qname_wins(self):
        prop = {"name": "fiscalYearCode", "qname": "fin:fiscalYearCode"}
        assert _property_qname("dbpi:Fee", prop) == "fin:fiscalYearCode"

    def test_carried_qname_used_even_when_it_matches_the_concept_prefix(self):
        prop = {"name": "streetName", "qname": "dbpi:streetName"}
        assert _property_qname("dbpi:AddressType", prop) == "dbpi:streetName"

    def test_falls_back_for_files_written_before_the_qname_field(self):
        assert _property_qname("dbpi:AddressType", {"name": "streetName"}) == "dbpi:streetName"

    def test_no_prefix(self):
        assert _property_qname("AddressType", {"name": "streetName"}) == "streetName"


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

        def fake_qi(entries, target, kind, top_k=12, eligible=None):
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

        evaluated = {"status": "evaluated", "evaluation": {"some": "data"},
                     "source": {"qname": "dbpi:streetName", "parentType": "dbpi:AddressType"}}
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


def test_an_unreadable_property_file_does_not_end_the_stage(tmp_path):
    """A locked or unreadable file is one this pass cannot reuse. Ending the
    stage on it loses every other concept's search results."""
    props_dir = tmp_path / "search-results" / "properties"
    props_dir.mkdir(parents=True, exist_ok=True)
    # A directory named like a result file: reading it raises OSError.
    (props_dir / "locked.json").mkdir()
    concepts = [{"qname": "src:A", "definition": "",
                 "properties": [{"name": "flag", "qname": "other:flag"}]}]

    counts = write_search_results(tmp_path, concepts, {}, {"src:A": {"other:flag": [PROP_CANDIDATE]}})

    assert counts["props_written"] == 1
    assert any(p.is_file() for p in props_dir.glob("*.json"))
