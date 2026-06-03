"""Tests for ontology_mapper.collect_alignments module.

Uses canned search-result files and mocked resolve_alignment to
test loading, validation, reassembly, resolution, and report assembly.
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from ontology_mapper.collect_alignments import (
    _build_id_to_qname,
    _hash_definition,
    _add_definition_hashes,
    _resolve_target_qname,
    assemble_alignment_report,
    collect_and_resolve,
    load_search_results,
    reassemble_evaluations,
    validate_evaluations,
)


# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

TYPE_EVAL_A = {
    "sourceConcept": "dbpi:AddressType",
    "sourceDefinition": "A physical mailing address.",
    "sourcePath": "dbpi:AddressType",
    "targetType": "nc:AddressType",
    "targetDefinition": "A postal address.",
    "targetPath": "nc:AddressType",
    "rationale": "Both represent physical/mailing addresses.",
}

TYPE_EVAL_B = {
    "sourceConcept": "dbpi:PersonType",
    "sourceDefinition": "A human being.",
    "sourcePath": "dbpi:PersonType",
    "targetType": "nc:PersonType",
    "targetDefinition": "A human individual.",
    "targetPath": "nc:PersonType",
    "rationale": "Direct equivalence.",
}

PROP_EVAL_STREET = {
    "sourceProperty": "dbpi:streetName",
    "sourceDefinition": "The name of the street",
    "sourcePath": "dbpi:AddressType/dbpi:streetName",
    "targetProperty": "nc:StreetFullText",
    "targetDefinition": "A complete street address.",
    "targetPath": "nc:AddressType/nc:StreetFullText",
    "rationale": "Both represent the street portion.",
}

PROP_EVAL_CITY = {
    "sourceProperty": "dbpi:cityName",
    "sourceDefinition": "The name of the city",
    "sourcePath": "dbpi:AddressType/dbpi:cityName",
    "targetProperty": None,
    "targetDefinition": None,
    "targetPath": None,
    "rationale": "No equivalent found.",
}


def _make_type_file(eval_dict, status="evaluated"):
    return {
        "status": status,
        "kind": "type",
        "source": {"qname": eval_dict["sourceConcept"]},
        "candidates": [],
        "evaluation": eval_dict if status == "evaluated" else None,
    }


def _make_prop_file(eval_dict, parent_type, status="evaluated"):
    return {
        "status": status,
        "kind": "property",
        "source": {
            "qname": eval_dict["sourceProperty"],
            "parentType": parent_type,
        },
        "candidates": [],
        "evaluation": eval_dict if status == "evaluated" else None,
    }


def _write_file(run_dir, subdir, filename, doc):
    d = run_dir / "search-results" / subdir
    d.mkdir(parents=True, exist_ok=True)
    (d / filename).write_text(json.dumps(doc, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# TestLoadSearchResults
# ---------------------------------------------------------------------------

class TestLoadSearchResults:
    def test_loads_both_dirs(self, tmp_path):
        _write_file(tmp_path, "types", "dbpi_AddressType.json",
                     _make_type_file(TYPE_EVAL_A))
        _write_file(tmp_path, "properties", "dbpi_streetName.json",
                     _make_prop_file(PROP_EVAL_STREET, "dbpi:AddressType"))

        types, props = load_search_results(tmp_path)
        assert len(types) == 1
        assert len(props) == 1
        assert types[0][0] == "dbpi_AddressType.json"
        assert props[0][0] == "dbpi_streetName.json"

    def test_sorted_order(self, tmp_path):
        _write_file(tmp_path, "types", "dbpi_PersonType.json",
                     _make_type_file(TYPE_EVAL_B))
        _write_file(tmp_path, "types", "dbpi_AddressType.json",
                     _make_type_file(TYPE_EVAL_A))

        types, _ = load_search_results(tmp_path)
        assert types[0][0] == "dbpi_AddressType.json"
        assert types[1][0] == "dbpi_PersonType.json"

    def test_missing_directory(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="search-results"):
            load_search_results(tmp_path)

    def test_empty_subdirs(self, tmp_path):
        (tmp_path / "search-results" / "types").mkdir(parents=True)
        (tmp_path / "search-results" / "properties").mkdir(parents=True)
        types, props = load_search_results(tmp_path)
        assert types == []
        assert props == []

    def test_missing_properties_subdir(self, tmp_path):
        _write_file(tmp_path, "types", "dbpi_AddressType.json",
                     _make_type_file(TYPE_EVAL_A))
        # No properties/ subdir
        types, props = load_search_results(tmp_path)
        assert len(types) == 1
        assert props == []


# ---------------------------------------------------------------------------
# TestValidateEvaluations
# ---------------------------------------------------------------------------

class TestValidateEvaluations:
    def test_all_evaluated(self):
        results = [
            ("a.json", _make_type_file(TYPE_EVAL_A)),
            ("b.json", _make_type_file(TYPE_EVAL_B)),
        ]
        evaluated, pending = validate_evaluations(results)
        assert len(evaluated) == 2
        assert pending == []

    def test_mixed(self):
        results = [
            ("a.json", _make_type_file(TYPE_EVAL_A)),
            ("b.json", _make_type_file(TYPE_EVAL_B, status="pending")),
        ]
        evaluated, pending = validate_evaluations(results)
        assert len(evaluated) == 1
        assert pending == ["b.json"]

    def test_all_pending(self):
        results = [
            ("a.json", _make_type_file(TYPE_EVAL_A, status="pending")),
        ]
        evaluated, pending = validate_evaluations(results)
        assert evaluated == []
        assert len(pending) == 1


# ---------------------------------------------------------------------------
# TestReassembleEvaluations
# ---------------------------------------------------------------------------

class TestReassembleEvaluations:
    def test_attaches_properties_to_type(self):
        type_eval = [
            ("dbpi_AddressType.json", _make_type_file(TYPE_EVAL_A)),
        ]
        prop_eval = [
            ("dbpi_streetName.json",
             _make_prop_file(PROP_EVAL_STREET, "dbpi:AddressType")),
            ("dbpi_cityName.json",
             _make_prop_file(PROP_EVAL_CITY, "dbpi:AddressType")),
        ]

        combined = reassemble_evaluations(type_eval, prop_eval)
        assert len(combined) == 1
        assert combined[0]["sourceConcept"] == "dbpi:AddressType"
        assert len(combined[0]["properties"]) == 2
        assert combined[0]["properties"][0]["sourceProperty"] == "dbpi:streetName"

    def test_type_with_no_properties(self):
        type_eval = [
            ("dbpi_PersonType.json", _make_type_file(TYPE_EVAL_B)),
        ]
        combined = reassemble_evaluations(type_eval, [])
        assert len(combined) == 1
        assert combined[0]["properties"] == []

    def test_multiple_types(self):
        type_eval = [
            ("dbpi_AddressType.json", _make_type_file(TYPE_EVAL_A)),
            ("dbpi_PersonType.json", _make_type_file(TYPE_EVAL_B)),
        ]
        prop_eval = [
            ("dbpi_streetName.json",
             _make_prop_file(PROP_EVAL_STREET, "dbpi:AddressType")),
        ]

        combined = reassemble_evaluations(type_eval, prop_eval)
        assert len(combined) == 2
        addr = next(c for c in combined if c["sourceConcept"] == "dbpi:AddressType")
        person = next(c for c in combined if c["sourceConcept"] == "dbpi:PersonType")
        assert len(addr["properties"]) == 1
        assert len(person["properties"]) == 0


# ---------------------------------------------------------------------------
# TestCollectAndResolve
# ---------------------------------------------------------------------------

class TestCollectAndResolve:
    @patch("ontology_mapper.collect_alignments.resolve_alignment")
    def test_calls_resolve_for_each(self, mock_resolve):
        def fake_resolve(evaluation, target_ontology, catalog):
            return {**evaluation, "action": "reuse", "actionRationale": "all found"}

        mock_resolve.side_effect = fake_resolve

        evaluations = [
            {**TYPE_EVAL_A, "properties": [PROP_EVAL_STREET]},
            {**TYPE_EVAL_B, "properties": []},
        ]

        entries = collect_and_resolve(evaluations, "niem", {"types": []})

        assert len(entries) == 2
        assert mock_resolve.call_count == 2
        assert entries[0]["action"] == "reuse"
        assert entries[0]["sourceConcept"] == "dbpi:AddressType"


# ---------------------------------------------------------------------------
# TestAssembleAlignmentReport
# ---------------------------------------------------------------------------

class TestAssembleAlignmentReport:
    def test_writes_report(self, tmp_path):
        entries = [
            {**TYPE_EVAL_A, "properties": [], "action": "reuse", "actionRationale": "all found"},
            {**TYPE_EVAL_B, "properties": [], "action": "extend", "actionRationale": "1 missing"},
        ]
        actions = {"reuse": {"description": "Reuse existing type"}}
        type_patterns = {"object": {"description": "Standard object type"}}

        out_path = assemble_alignment_report(
            tmp_path, entries, "niem", "6.0", actions, type_patterns,
        )

        assert out_path == tmp_path / "alignment-report.json"
        assert out_path.exists()

        report = json.loads(out_path.read_text(encoding="utf-8"))
        assert report["matchingMethod"] == "semantic"
        assert report["targetOntology"] == "niem"
        assert report["targetVersion"] == "6.0"
        assert report["actions"] == actions
        assert report["typePatterns"] == type_patterns
        assert report["summary"]["totalConcepts"] == 2
        assert report["summary"]["reuse"] == 1
        assert report["summary"]["extend"] == 1
        assert len(report["entries"]) == 2

    def test_empty_entries(self, tmp_path):
        out_path = assemble_alignment_report(
            tmp_path, [], "niem", "6.0", {}, {},
        )
        report = json.loads(out_path.read_text(encoding="utf-8"))
        assert report["summary"]["totalConcepts"] == 0
        assert report["entries"] == []


# ---------------------------------------------------------------------------
# TestProvenanceFlowThrough
# ---------------------------------------------------------------------------

class TestProvenanceFlowThrough:
    """Provenance fields added by the evaluator survive reassembly and resolution."""

    TYPE_WITH_PROVENANCE = {
        **TYPE_EVAL_A,
        "evaluatedAt": "2026-04-09T12:00:00+00:00",
        "evaluatedBy": "sonnet",
        "candidateCount": 5,
    }

    PROP_WITH_PROVENANCE = {
        **PROP_EVAL_STREET,
        "evaluatedAt": "2026-04-09T12:00:01+00:00",
        "evaluatedBy": "sonnet",
        "candidateCount": 3,
    }

    PROP_NULL_TARGET_WITH_PROVENANCE = {
        **PROP_EVAL_CITY,  # targetProperty is None
        "evaluatedAt": "2026-04-09T12:00:02+00:00",
        "evaluatedBy": "sonnet",
        "candidateCount": 0,
    }

    def test_type_provenance_survives_reassembly(self):
        type_eval = [
            ("dbpi_AddressType.json", _make_type_file(self.TYPE_WITH_PROVENANCE)),
        ]
        combined = reassemble_evaluations(type_eval, [])
        assert combined[0]["evaluatedAt"] == "2026-04-09T12:00:00+00:00"
        assert combined[0]["evaluatedBy"] == "sonnet"
        assert combined[0]["candidateCount"] == 5

    def test_property_provenance_survives_reassembly(self):
        type_eval = [
            ("dbpi_AddressType.json", _make_type_file(self.TYPE_WITH_PROVENANCE)),
        ]
        prop_eval = [
            ("dbpi_streetName.json",
             _make_prop_file(self.PROP_WITH_PROVENANCE, "dbpi:AddressType")),
        ]
        combined = reassemble_evaluations(type_eval, prop_eval)
        prop = combined[0]["properties"][0]
        assert prop["evaluatedAt"] == "2026-04-09T12:00:01+00:00"
        assert prop["evaluatedBy"] == "sonnet"
        assert prop["candidateCount"] == 3

    def test_null_target_property_provenance_survives(self):
        """Provenance is preserved even when targetProperty is null."""
        type_eval = [
            ("dbpi_AddressType.json", _make_type_file(self.TYPE_WITH_PROVENANCE)),
        ]
        prop_eval = [
            ("dbpi_cityName.json",
             _make_prop_file(self.PROP_NULL_TARGET_WITH_PROVENANCE, "dbpi:AddressType")),
        ]
        combined = reassemble_evaluations(type_eval, prop_eval)
        prop = combined[0]["properties"][0]
        assert prop["targetProperty"] is None
        assert prop["evaluatedAt"] == "2026-04-09T12:00:02+00:00"
        assert prop["candidateCount"] == 0

    @patch("ontology_mapper.collect_alignments.resolve_alignment")
    def test_provenance_survives_resolution(self, mock_resolve):
        """resolve_alignment deep-copies — unknown keys pass through."""
        def real_passthrough(evaluation, target_ontology, catalog):
            import copy
            result = copy.deepcopy(evaluation)
            result["action"] = "reuse"
            result["actionRationale"] = "test"
            for p in result.get("properties", []):
                p["propertyAction"] = "reuse-property"
            return result

        mock_resolve.side_effect = real_passthrough

        evaluations = [{
            **self.TYPE_WITH_PROVENANCE,
            "properties": [self.PROP_WITH_PROVENANCE],
        }]
        entries = collect_and_resolve(evaluations, "niem", {"types": []})

        assert entries[0]["evaluatedAt"] == "2026-04-09T12:00:00+00:00"
        assert entries[0]["evaluatedBy"] == "sonnet"
        assert entries[0]["candidateCount"] == 5
        assert entries[0]["properties"][0]["evaluatedAt"] == "2026-04-09T12:00:01+00:00"
        assert entries[0]["properties"][0]["candidateCount"] == 3

    def test_provenance_survives_real_resolve_alignment(self):
        """End-to-end: provenance through actual resolve_alignment (not mocked)."""
        evaluation = {
            **self.TYPE_WITH_PROVENANCE,
            "properties": [
                self.PROP_WITH_PROVENANCE,
                self.PROP_NULL_TARGET_WITH_PROVENANCE,
            ],
        }
        catalog = {"types": []}
        entries = collect_and_resolve([evaluation], "niem", catalog)
        entry = entries[0]

        # Type-level provenance
        assert entry["evaluatedAt"] == "2026-04-09T12:00:00+00:00"
        assert entry["evaluatedBy"] == "sonnet"
        assert entry["candidateCount"] == 5

        # Property-level provenance (reuse-property path)
        reuse_prop = next(p for p in entry["properties"]
                         if p["sourceProperty"] == "dbpi:streetName")
        assert reuse_prop["evaluatedAt"] == "2026-04-09T12:00:01+00:00"
        assert reuse_prop["candidateCount"] == 3

        # Property-level provenance (create-property path, null target)
        create_prop = next(p for p in entry["properties"]
                          if p["sourceProperty"] == "dbpi:cityName")
        assert create_prop["evaluatedAt"] == "2026-04-09T12:00:02+00:00"
        assert create_prop["candidateCount"] == 0

    def test_provenance_in_alignment_report_file(self, tmp_path):
        """Provenance fields appear in the written alignment-report.json."""
        entry = {
            **self.TYPE_WITH_PROVENANCE,
            "properties": [self.PROP_WITH_PROVENANCE],
            "action": "reuse",
            "actionRationale": "all found",
        }
        out_path = assemble_alignment_report(
            tmp_path, [entry], "niem", "6.0", {}, {},
        )
        report = json.loads(out_path.read_text(encoding="utf-8"))
        re_entry = report["entries"][0]
        assert re_entry["evaluatedAt"] == "2026-04-09T12:00:00+00:00"
        assert re_entry["evaluatedBy"] == "sonnet"
        assert re_entry["candidateCount"] == 5
        assert re_entry["properties"][0]["candidateCount"] == 3


# ---------------------------------------------------------------------------
# TestBuildIdToQname
# ---------------------------------------------------------------------------

class TestBuildIdToQname:
    def test_label_based_candidates(self):
        """SALI-style: id is label, qname is real identifier."""
        cands = [
            {"id": "Legal Services", "qname": "abc123"},
            {"id": "Court Filing", "qname": "def456"},
        ]
        lookup = _build_id_to_qname(cands)
        assert lookup == {"Legal Services": "abc123", "Court Filing": "def456"}

    def test_prefixed_candidates(self):
        """NIEM-style: id and qname are the same."""
        cands = [
            {"id": "nc:PersonType", "qname": "nc:PersonType"},
            {"id": "j:CaseType", "qname": "j:CaseType"},
        ]
        lookup = _build_id_to_qname(cands)
        assert lookup["nc:PersonType"] == "nc:PersonType"

    def test_missing_qname_falls_back_to_id(self):
        cands = [{"id": "nc:PersonType"}]
        lookup = _build_id_to_qname(cands)
        assert lookup["nc:PersonType"] == "nc:PersonType"

    def test_empty(self):
        assert _build_id_to_qname([]) == {}


# ---------------------------------------------------------------------------
# TestResolveTargetQname
# ---------------------------------------------------------------------------

class TestResolveTargetQname:
    def test_resolves_label_to_qname(self):
        """When display id differs from qname, field is replaced and label saved."""
        evaluation = {"targetType": "Legal Services"}
        _resolve_target_qname(evaluation, "targetType", {"Legal Services": "abc123"})
        assert evaluation["targetType"] == "abc123"
        assert evaluation["targetTypeLabel"] == "Legal Services"

    def test_noop_when_already_qname(self):
        """When id == qname, no change and no label field added."""
        evaluation = {"targetType": "nc:PersonType"}
        _resolve_target_qname(evaluation, "targetType", {"nc:PersonType": "nc:PersonType"})
        assert evaluation["targetType"] == "nc:PersonType"
        assert "targetTypeLabel" not in evaluation

    def test_undecided_skipped(self):
        evaluation = {"targetType": "[undecided]"}
        _resolve_target_qname(evaluation, "targetType", {})
        assert evaluation["targetType"] == "[undecided]"
        assert "targetTypeLabel" not in evaluation

    def test_none_skipped(self):
        evaluation = {"targetType": None}
        _resolve_target_qname(evaluation, "targetType", {})
        assert evaluation["targetType"] is None
        assert "targetTypeLabel" not in evaluation

    def test_unknown_id_preserved(self):
        """If display id is not in lookup, it stays as-is (no label added)."""
        evaluation = {"targetType": "SomeUnknownLabel"}
        _resolve_target_qname(evaluation, "targetType", {})
        assert evaluation["targetType"] == "SomeUnknownLabel"
        assert "targetTypeLabel" not in evaluation

    def test_property_field(self):
        """Works for targetProperty too."""
        evaluation = {"targetProperty": "Court Date"}
        _resolve_target_qname(evaluation, "targetProperty", {"Court Date": "xyz789"})
        assert evaluation["targetProperty"] == "xyz789"
        assert evaluation["targetPropertyLabel"] == "Court Date"


# ---------------------------------------------------------------------------
# TestTargetDefinitionHashing
# ---------------------------------------------------------------------------

class TestHashDefinition:
    def test_real_definition(self):
        h = _hash_definition("A postal address.")
        assert isinstance(h, str)
        assert len(h) == 16

    def test_null_definition(self):
        assert _hash_definition(None) is None

    def test_empty_string(self):
        h = _hash_definition("")
        assert isinstance(h, str)
        assert len(h) == 16

    def test_stability(self):
        """Same input always produces same hash."""
        h1 = _hash_definition("A court event.")
        h2 = _hash_definition("A court event.")
        assert h1 == h2

    def test_different_definitions_differ(self):
        h1 = _hash_definition("A postal address.")
        h2 = _hash_definition("A physical location.")
        assert h1 != h2


class TestAddDefinitionHashes:
    """Tests use empty catalog lookups — hashes fall back to entry definitions."""

    def test_entry_with_target(self):
        entry = {
            "targetDefinition": "A postal address.",
            "properties": [
                {"targetDefinition": "A street name."},
                {"targetDefinition": "A city name."},
            ],
        }
        _add_definition_hashes(entry, {}, {})
        assert len(entry["targetDefinitionHash"]) == 16
        assert len(entry["properties"][0]["targetDefinitionHash"]) == 16
        assert len(entry["properties"][1]["targetDefinitionHash"]) == 16

    def test_entry_null_target(self):
        """No target type → null hash on entry, properties may vary."""
        entry = {
            "targetDefinition": None,
            "properties": [
                {"targetDefinition": "A street name."},
                {"targetDefinition": None},
            ],
        }
        _add_definition_hashes(entry, {}, {})
        assert entry["targetDefinitionHash"] is None
        assert len(entry["properties"][0]["targetDefinitionHash"]) == 16
        assert entry["properties"][1]["targetDefinitionHash"] is None

    def test_entry_no_properties(self):
        entry = {"targetDefinition": "A person."}
        _add_definition_hashes(entry, {}, {})
        assert len(entry["targetDefinitionHash"]) == 16

    def test_undecided_property(self):
        """[undecided] property has null targetDefinition → null hash."""
        entry = {
            "targetDefinition": "A court event.",
            "properties": [
                {"targetProperty": "[undecided]", "targetDefinition": None},
            ],
        }
        _add_definition_hashes(entry, {}, {})
        assert len(entry["targetDefinitionHash"]) == 16
        assert entry["properties"][0]["targetDefinitionHash"] is None

    def test_prefers_catalog_definition(self):
        """When catalog has the type, hash the catalog definition, not the enriched one."""
        entry = {
            "targetType": "nc:PersonType",
            "targetDefinition": "A person. Enriched with extra details.",
            "properties": [],
        }
        type_defs = {"nc:PersonType": "A person."}
        _add_definition_hashes(entry, type_defs, {})
        assert entry["targetDefinitionHash"] == _hash_definition("A person.")

    def test_prefers_catalog_property_definition(self):
        """When catalog has the property, hash the catalog definition."""
        entry = {
            "targetDefinition": None,
            "properties": [{
                "targetProperty": "nc:PersonName",
                "targetDefinition": "A name. Enriched.",
            }],
        }
        prop_defs = {"nc:PersonName": "A name."}
        _add_definition_hashes(entry, {}, prop_defs)
        assert entry["properties"][0]["targetDefinitionHash"] == _hash_definition("A name.")


class TestDefinitionHashInPipeline:
    def test_hashes_added_by_collect_and_resolve(self):
        """collect_and_resolve adds hashes after resolve_alignment."""
        evaluation = {
            **TYPE_EVAL_A,
            "properties": [PROP_EVAL_STREET, PROP_EVAL_CITY],
        }
        catalog = {"types": []}
        entries = collect_and_resolve([evaluation], "niem", catalog)
        entry = entries[0]

        # Entry-level hash (targetDefinition = "A postal address.")
        assert entry["targetDefinitionHash"] is not None
        assert len(entry["targetDefinitionHash"]) == 16

        # reuse-property (targetDefinition = "A complete street address.")
        reuse_prop = next(p for p in entry["properties"]
                         if p["sourceProperty"] == "dbpi:streetName")
        assert reuse_prop["targetDefinitionHash"] is not None

        # create-property (targetDefinition = None)
        create_prop = next(p for p in entry["properties"]
                          if p["sourceProperty"] == "dbpi:cityName")
        assert create_prop["targetDefinitionHash"] is None

    def test_hashes_in_alignment_report_file(self, tmp_path):
        entry = {
            **TYPE_EVAL_A,
            "properties": [{**PROP_EVAL_STREET, "propertyAction": "reuse-property"}],
            "action": "reuse",
            "actionRationale": "all found",
            "targetDefinitionHash": _hash_definition("A postal address."),
        }
        entry["properties"][0]["targetDefinitionHash"] = _hash_definition(
            "A complete street address."
        )
        out_path = assemble_alignment_report(
            tmp_path, [entry], "niem", "6.0", {}, {},
        )
        report = json.loads(out_path.read_text(encoding="utf-8"))
        re_entry = report["entries"][0]
        assert len(re_entry["targetDefinitionHash"]) == 16
        assert len(re_entry["properties"][0]["targetDefinitionHash"]) == 16

    def test_null_target_type_hashes(self):
        """Entry with no target type → null hash, all props create-property."""
        evaluation = {
            "sourceConcept": "test:Foo",
            "sourceDefinition": "A foo.",
            "sourcePath": "test:Foo",
            "targetType": None,
            "targetDefinition": None,
            "targetPath": None,
            "rationale": "No match.",
            "properties": [{
                "sourceProperty": "test:bar",
                "sourceDefinition": "A bar.",
                "sourcePath": "test:Foo/test:bar",
                "targetProperty": None,
                "targetDefinition": None,
                "targetPath": None,
                "rationale": "No match.",
            }],
        }
        entries = collect_and_resolve([evaluation], "niem", {"types": []})
        entry = entries[0]
        assert entry["targetDefinitionHash"] is None
        assert entry["properties"][0]["targetDefinitionHash"] is None


# ---------------------------------------------------------------------------
# TestEndToEnd
# ---------------------------------------------------------------------------

class TestEndToEnd:
    """Write split files → load → validate → reassemble → resolve → assemble."""

    @patch("ontology_mapper.collect_alignments.resolve_alignment")
    def test_full_pipeline(self, mock_resolve, tmp_path):
        def fake_resolve(evaluation, target_ontology, catalog):
            return {**evaluation, "action": "reuse", "actionRationale": "test"}

        mock_resolve.side_effect = fake_resolve

        # Write type files
        _write_file(tmp_path, "types", "dbpi_AddressType.json",
                     _make_type_file(TYPE_EVAL_A))
        _write_file(tmp_path, "types", "dbpi_PersonType.json",
                     _make_type_file(TYPE_EVAL_B))
        # Write property files
        _write_file(tmp_path, "properties", "dbpi_streetName.json",
                     _make_prop_file(PROP_EVAL_STREET, "dbpi:AddressType"))

        # Load
        types, props = load_search_results(tmp_path)
        assert len(types) == 2
        assert len(props) == 1

        # Validate
        type_eval, type_pending = validate_evaluations(types)
        prop_eval, prop_pending = validate_evaluations(props)
        assert len(type_eval) == 2
        assert type_pending == []
        assert len(prop_eval) == 1

        # Reassemble
        evaluations = reassemble_evaluations(type_eval, prop_eval)
        assert len(evaluations) == 2
        addr = next(e for e in evaluations if e["sourceConcept"] == "dbpi:AddressType")
        assert len(addr["properties"]) == 1

        # Resolve
        catalog = {"types": []}
        entries = collect_and_resolve(evaluations, "niem", catalog)
        assert len(entries) == 2

        # Assemble
        actions = {"reuse": {"description": "Reuse"}}
        out_path = assemble_alignment_report(
            tmp_path, entries, "niem", "6.0", actions, {},
        )

        report = json.loads(out_path.read_text(encoding="utf-8"))
        assert report["matchingMethod"] == "semantic"
        assert report["summary"]["totalConcepts"] == 2
        assert all(e["action"] == "reuse" for e in report["entries"])
