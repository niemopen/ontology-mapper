#!/usr/bin/env python3
"""Tests for compute_entropy.py — pre-rotation entropy measurement."""

import json
import math
import pytest

from ontology_mapper.compute_entropy import (
    compute_entropy,
    analyze_search_results,
    build_entropy_summary,
    compute_residual_entropy,
)


# ─── Unit tests: compute_entropy ────────────────────────────────────────

class TestComputeEntropy:

    def test_single_candidate(self):
        assert compute_entropy(1) == 0.0

    def test_zero_candidates(self):
        assert compute_entropy(0) == 0.0

    def test_two_candidates(self):
        assert compute_entropy(2) == 1.0

    def test_eight_candidates(self):
        assert compute_entropy(8) == 3.0

    def test_sixteen_candidates(self):
        assert compute_entropy(16) == 4.0

    def test_non_power_of_two(self):
        assert compute_entropy(5) == pytest.approx(math.log2(5), abs=1e-9)


# ─── Helpers ────────────────────────────────────────────────────────────

def _write_search_result(path, source, candidates):
    """Write a mock search result file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "status": "pending",
        "kind": "type" if "types" in str(path) else "property",
        "source": source,
        "candidates": candidates,
        "evaluation": None,
    }
    path.write_text(json.dumps(data), encoding="utf-8")


def _mock_candidates(n):
    """Build n minimal candidate dicts."""
    return [{"id": f"nc:Type{i}", "definition": f"Type {i}"} for i in range(n)]


# ─── Integration tests: analyze_search_results ──────────────────────────

class TestAnalyzeSearchResults:

    def test_reads_type_files(self, tmp_path):
        types_dir = tmp_path / "search-results" / "types"
        _write_search_result(
            types_dir / "court_CaseType.json",
            {"qname": "court:CaseType"},
            _mock_candidates(8),
        )
        _write_search_result(
            types_dir / "court_PersonType.json",
            {"qname": "court:PersonType"},
            _mock_candidates(2),
        )
        type_entries, prop_entries = analyze_search_results(tmp_path)
        assert len(type_entries) == 2
        assert len(prop_entries) == 0
        by_concept = {e["sourceConcept"]: e for e in type_entries}
        assert by_concept["court:CaseType"]["candidateCount"] == 8
        assert by_concept["court:CaseType"]["entropy"] == 3.0
        assert by_concept["court:PersonType"]["candidateCount"] == 2
        assert by_concept["court:PersonType"]["entropy"] == 1.0

    def test_reads_property_files(self, tmp_path):
        props_dir = tmp_path / "search-results" / "properties"
        _write_search_result(
            props_dir / "court_hearingDate.json",
            {"qname": "court:hearingDate", "parentType": "court:HearingType"},
            _mock_candidates(12),
        )
        type_entries, prop_entries = analyze_search_results(tmp_path)
        assert len(type_entries) == 0
        assert len(prop_entries) == 1
        assert prop_entries[0]["sourceProperty"] == "court:hearingDate"
        assert prop_entries[0]["parentConcept"] == "court:HearingType"
        assert prop_entries[0]["candidateCount"] == 12
        assert prop_entries[0]["entropy"] == pytest.approx(math.log2(12), abs=0.001)

    def test_empty_candidates(self, tmp_path):
        types_dir = tmp_path / "search-results" / "types"
        _write_search_result(
            types_dir / "court_UnknownType.json",
            {"qname": "court:UnknownType"},
            [],
        )
        type_entries, _ = analyze_search_results(tmp_path)
        assert type_entries[0]["candidateCount"] == 0
        assert type_entries[0]["entropy"] == 0.0

    def test_no_search_results_dir(self, tmp_path):
        type_entries, prop_entries = analyze_search_results(tmp_path)
        assert type_entries == []
        assert prop_entries == []

    def test_single_candidate_zero_entropy(self, tmp_path):
        types_dir = tmp_path / "search-results" / "types"
        _write_search_result(
            types_dir / "court_ExactMatch.json",
            {"qname": "court:ExactMatch"},
            _mock_candidates(1),
        )
        type_entries, _ = analyze_search_results(tmp_path)
        assert type_entries[0]["entropy"] == 0.0


# ─── Integration tests: build_entropy_summary ────────────────────────────

class TestBuildEntropySummary:

    def test_computes_totals(self):
        types = [
            {"sourceConcept": "a:X", "candidateCount": 8, "entropy": 3.0},
            {"sourceConcept": "a:Y", "candidateCount": 4, "entropy": 2.0},
        ]
        props = [
            {"sourceProperty": "a:p1", "parentConcept": "a:X",
             "candidateCount": 16, "entropy": 4.0},
        ]
        summary = build_entropy_summary(types, props)
        assert summary["hTypes"] == 5.0
        assert summary["hProperties"] == 4.0
        assert summary["hTotal"] == 9.0
        assert summary["typesAnalyzed"] == 2
        assert summary["propertiesAnalyzed"] == 1
        assert summary["perConcept"] is types
        assert summary["perProperty"] is props

    def test_empty_inputs(self):
        summary = build_entropy_summary([], [])
        assert summary["hTotal"] == 0.0
        assert summary["typesAnalyzed"] == 0
        assert summary["propertiesAnalyzed"] == 0

    def test_types_only(self):
        types = [
            {"sourceConcept": "a:X", "candidateCount": 2, "entropy": 1.0},
        ]
        summary = build_entropy_summary(types, [])
        assert summary["hTotal"] == 1.0
        assert summary["hProperties"] == 0.0


# ─── End-to-end: analyze + build ─────────────────────────────────────────

class TestEndToEnd:

    def test_full_pipeline(self, tmp_path):
        types_dir = tmp_path / "search-results" / "types"
        props_dir = tmp_path / "search-results" / "properties"

        _write_search_result(
            types_dir / "court_CaseType.json",
            {"qname": "court:CaseType"},
            _mock_candidates(8),
        )
        _write_search_result(
            types_dir / "court_PersonType.json",
            {"qname": "court:PersonType"},
            _mock_candidates(1),
        )
        _write_search_result(
            props_dir / "court_caseId.json",
            {"qname": "court:caseId", "parentType": "court:CaseType"},
            _mock_candidates(4),
        )

        type_entries, prop_entries = analyze_search_results(tmp_path)
        summary = build_entropy_summary(type_entries, prop_entries)

        assert summary["typesAnalyzed"] == 2
        assert summary["propertiesAnalyzed"] == 1
        # 3.0 (8 candidates) + 0.0 (1 candidate) + 2.0 (4 candidates)
        assert summary["hTotal"] == 5.0
        assert summary["hTypes"] == 3.0
        assert summary["hProperties"] == 2.0


# ─── Unit tests: compute_residual_entropy ──────────────────────────────

class TestComputeResidualEntropy:

    def _entropy_summary(self, concepts, properties=None):
        """Build a minimal entropy summary."""
        return {
            "perConcept": concepts,
            "perProperty": properties or [],
        }

    def _matrix(self, mappings):
        """Build a minimal mapping matrix."""
        return {"mappings": mappings}

    def test_all_confident_zero_residual(self):
        entropy = self._entropy_summary([
            {"sourceConcept": "x:A", "candidateCount": 8, "entropy": 3.0},
            {"sourceConcept": "x:B", "candidateCount": 4, "entropy": 2.0},
        ])
        matrix = self._matrix([
            {"sourceConcept": "x:A", "confidence": "confident", "propertyMappings": []},
            {"sourceConcept": "x:B", "confidence": "confident", "propertyMappings": []},
        ])
        result = compute_residual_entropy(entropy, matrix)
        assert result["hPreTypes"] == 5.0
        assert result["hResidualTypes"] == 0.0
        assert result["hResidualTotal"] == 0.0
        assert result["hResolvedTotal"] == 5.0

    def test_all_best_guess_full_residual(self):
        entropy = self._entropy_summary([
            {"sourceConcept": "x:A", "candidateCount": 8, "entropy": 3.0},
        ])
        matrix = self._matrix([
            {"sourceConcept": "x:A", "confidence": "best-guess", "propertyMappings": []},
        ])
        result = compute_residual_entropy(entropy, matrix)
        assert result["hResidualTypes"] == 3.0
        assert result["hResolvedTotal"] == 0.0

    def test_mixed_confidence(self):
        entropy = self._entropy_summary([
            {"sourceConcept": "x:A", "candidateCount": 8, "entropy": 3.0},
            {"sourceConcept": "x:B", "candidateCount": 4, "entropy": 2.0},
        ])
        matrix = self._matrix([
            {"sourceConcept": "x:A", "confidence": "confident", "propertyMappings": []},
            {"sourceConcept": "x:B", "confidence": "best-guess", "propertyMappings": []},
        ])
        result = compute_residual_entropy(entropy, matrix)
        assert result["hPreTypes"] == 5.0
        assert result["hResidualTypes"] == 2.0  # only x:B retained
        assert result["hResolvedTotal"] == 3.0  # x:A resolved

    def test_property_level_residual(self):
        entropy = self._entropy_summary(
            [{"sourceConcept": "x:A", "candidateCount": 8, "entropy": 3.0}],
            [
                {"sourceProperty": "x:p1", "parentConcept": "x:A",
                 "candidateCount": 16, "entropy": 4.0},
                {"sourceProperty": "x:p2", "parentConcept": "x:A",
                 "candidateCount": 4, "entropy": 2.0},
            ],
        )
        matrix = self._matrix([
            {"sourceConcept": "x:A", "confidence": "confident", "propertyMappings": [
                {"sourceProperty": "x:p1", "action": "reuse-property",
                 "confidence": "confident"},
                {"sourceProperty": "x:p2", "action": "reuse-property",
                 "confidence": "best-guess"},
            ]},
        ])
        result = compute_residual_entropy(entropy, matrix)
        assert result["hResidualTypes"] == 0.0  # concept confident
        assert result["hResidualProperties"] == 2.0  # p2 best-guess
        assert result["hResidualTotal"] == 2.0
        assert result["hResolvedTotal"] == 7.0  # (3+4+2) - (0+0+2)

    def test_missing_confidence_defaults_confident(self):
        entropy = self._entropy_summary([
            {"sourceConcept": "x:A", "candidateCount": 8, "entropy": 3.0},
        ])
        matrix = self._matrix([
            {"sourceConcept": "x:A", "propertyMappings": []},  # no confidence key
        ])
        result = compute_residual_entropy(entropy, matrix)
        assert result["hResidualTotal"] == 0.0

    def test_concept_not_in_entropy_summary(self):
        """Concept in matrix but not in entropy summary → zero pre-entropy."""
        entropy = self._entropy_summary([])
        matrix = self._matrix([
            {"sourceConcept": "x:New", "confidence": "best-guess",
             "propertyMappings": []},
        ])
        result = compute_residual_entropy(entropy, matrix)
        assert result["hResidualTotal"] == 0.0
        assert result["perConcept"][0]["preEntropy"] == 0.0

    def test_empty_inputs(self):
        result = compute_residual_entropy(
            {"perConcept": [], "perProperty": []},
            {"mappings": []},
        )
        assert result["hPreTotal"] == 0.0
        assert result["hResidualTotal"] == 0.0
        assert result["hResolvedTotal"] == 0.0
        assert result["perConcept"] == []
        assert result["perProperty"] == []

    def test_per_concept_output_structure(self):
        entropy = self._entropy_summary([
            {"sourceConcept": "x:A", "candidateCount": 8, "entropy": 3.0},
        ])
        matrix = self._matrix([
            {"sourceConcept": "x:A", "confidence": "best-guess",
             "propertyMappings": []},
        ])
        result = compute_residual_entropy(entropy, matrix)
        entry = result["perConcept"][0]
        assert entry["sourceConcept"] == "x:A"
        assert entry["preEntropy"] == 3.0
        assert entry["confidence"] == "best-guess"
        assert entry["residualEntropy"] == 3.0

    def test_per_property_output_structure(self):
        entropy = self._entropy_summary(
            [{"sourceConcept": "x:A", "candidateCount": 2, "entropy": 1.0}],
            [{"sourceProperty": "x:p1", "parentConcept": "x:A",
              "candidateCount": 8, "entropy": 3.0}],
        )
        matrix = self._matrix([
            {"sourceConcept": "x:A", "confidence": "confident",
             "propertyMappings": [
                 {"sourceProperty": "x:p1", "action": "reuse-property",
                  "confidence": "best-guess"},
             ]},
        ])
        result = compute_residual_entropy(entropy, matrix)
        prop = result["perProperty"][0]
        assert prop["sourceProperty"] == "x:p1"
        assert prop["sourceConcept"] == "x:A"
        assert prop["preEntropy"] == 3.0
        assert prop["confidence"] == "best-guess"
        assert prop["residualEntropy"] == 3.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
