"""Tests for ontology_mapper.vector_search module."""

import pytest

from ontology_mapper.vector_search import _find_mutual_matches, print_summary


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fwd_entry(source_id: str, matches: list[dict]) -> dict:
    """Build a forward search result entry."""
    return {"query": {"id": source_id}, "matches": matches}


def _rev_entry(target_id: str, matches: list[dict]) -> dict:
    """Build a reverse search result entry."""
    return {"query": {"id": target_id}, "matches": matches}


def _match(target_id: str, score: float) -> dict:
    return {"id": target_id, "score": score}


# ---------------------------------------------------------------------------
# _find_mutual_matches
# ---------------------------------------------------------------------------

class TestFindMutualMatches:

    def test_two_mutual_pairs(self):
        forward = [
            _fwd_entry("A", [_match("X", 0.95)]),
            _fwd_entry("B", [_match("Y", 0.80)]),
        ]
        reverse = [
            _rev_entry("X", [_match("A", 0.90)]),
            _rev_entry("Y", [_match("B", 0.85)]),
        ]
        result = _find_mutual_matches(forward, reverse)

        assert len(result) == 2
        ids = {(m["sourceId"], m["targetId"]) for m in result}
        assert ("A", "X") in ids
        assert ("B", "Y") in ids

    def test_one_directional_no_mutual(self):
        """A->X but X's top match is C, not A."""
        forward = [
            _fwd_entry("A", [_match("X", 0.95)]),
        ]
        reverse = [
            _rev_entry("X", [_match("C", 0.99)]),
        ]
        result = _find_mutual_matches(forward, reverse)
        assert result == []

    def test_empty_inputs(self):
        assert _find_mutual_matches([], []) == []

    def test_entries_with_empty_matches(self):
        forward = [_fwd_entry("A", [])]
        reverse = [_rev_entry("X", [])]
        assert _find_mutual_matches(forward, reverse) == []

    def test_single_mutual_match(self):
        forward = [
            _fwd_entry("A", [_match("X", 0.90)]),
        ]
        reverse = [
            _rev_entry("X", [_match("A", 0.80)]),
        ]
        result = _find_mutual_matches(forward, reverse)

        assert len(result) == 1
        assert result[0]["sourceId"] == "A"
        assert result[0]["targetId"] == "X"

    def test_score_calculation(self):
        forward = [_fwd_entry("A", [_match("X", 0.90)])]
        reverse = [_rev_entry("X", [_match("A", 0.80)])]

        result = _find_mutual_matches(forward, reverse)

        assert result[0]["forwardScore"] == 0.90
        assert result[0]["reverseScore"] == 0.80
        assert result[0]["combinedScore"] == pytest.approx(0.85)

    def test_sorting_by_combined_score_descending(self):
        forward = [
            _fwd_entry("A", [_match("X", 0.70)]),
            _fwd_entry("B", [_match("Y", 0.95)]),
        ]
        reverse = [
            _rev_entry("X", [_match("A", 0.60)]),
            _rev_entry("Y", [_match("B", 0.90)]),
        ]
        result = _find_mutual_matches(forward, reverse)

        assert len(result) == 2
        # B<->Y combined = 0.925, A<->X combined = 0.65
        assert result[0]["sourceId"] == "B"
        assert result[1]["sourceId"] == "A"
        assert result[0]["combinedScore"] > result[1]["combinedScore"]


# ---------------------------------------------------------------------------
# print_summary
# ---------------------------------------------------------------------------

class TestPrintSummary:

    def _minimal_results(self, *, with_mutual: bool = False) -> dict:
        results = {
            "source": "src",
            "target": "tgt",
            "kind": "types",
            "topK": 20,
            "forward": [
                {
                    "query": {"id": "SomeType", "definition": "A type"},
                    "matches": [
                        {
                            "id": "TargetType",
                            "score": 0.92,
                            "rank": 1,
                            "definition": "Target def",
                            "namespace": "ns",
                        },
                    ],
                },
            ],
        }
        if with_mutual:
            results["mutualMatches"] = [
                {
                    "sourceId": "SomeType",
                    "targetId": "TargetType",
                    "forwardScore": 0.92,
                    "reverseScore": 0.88,
                    "combinedScore": 0.90,
                },
            ]
        return results

    def test_does_not_crash_minimal(self):
        print_summary(self._minimal_results())

    def test_includes_mutual_matches_section(self, capsys):
        print_summary(self._minimal_results(with_mutual=True))
        captured = capsys.readouterr().out
        assert "Mutual nearest neighbors" in captured
        assert "SomeType" in captured
        assert "TargetType" in captured
