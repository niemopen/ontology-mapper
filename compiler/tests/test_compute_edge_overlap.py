#!/usr/bin/env python3
"""Tests for compute_edge_overlap.py."""
import pytest

from ontology_mapper.compute_edge_overlap import (
    EdgeVocabulary,
    compute_codelist_overlap,
    compute_namespace_overlap,
    compute_pairwise_overlap,
    compute_property_overlap,
    compute_type_overlap,
    extract_vocabulary,
    jaccard,
)



# ─── Jaccard ──────────────────────────────────────────────────────────────

class TestJaccard:
    def test_identical_sets(self):
        assert jaccard({"a", "b"}, {"a", "b"}) == 1.0

    def test_disjoint_sets(self):
        assert jaccard({"a"}, {"b"}) == 0.0

    def test_partial_overlap(self):
        assert jaccard({"a", "b", "c"}, {"b", "c", "d"}) == pytest.approx(0.5)

    def test_empty_sets(self):
        assert jaccard(set(), set()) == 0.0

    def test_one_empty(self):
        assert jaccard({"a"}, set()) == 0.0


# ─── Type Overlap ─────────────────────────────────────────────────────────

class TestTypeOverlap:
    def test_identical(self):
        a = EdgeVocabulary(name="a", source_path="a", target_types={"nc:PersonType", "nc:ActivityType"})
        b = EdgeVocabulary(name="b", source_path="b", target_types={"nc:PersonType", "nc:ActivityType"})
        result = compute_type_overlap(a, b)
        assert result["jaccard"] == 1.0
        assert result["sharedCount"] == 2

    def test_no_overlap(self):
        a = EdgeVocabulary(name="a", source_path="a", target_types={"nc:PersonType"})
        b = EdgeVocabulary(name="b", source_path="b", target_types={"nc:ActivityType"})
        result = compute_type_overlap(a, b)
        assert result["jaccard"] == 0.0
        assert result["sharedCount"] == 0
        assert result["aOnlyCount"] == 1
        assert result["bOnlyCount"] == 1


# ─── Property Overlap ────────────────────────────────────────────────────

class TestPropertyOverlap:
    def test_shared_types_with_different_properties(self):
        a = EdgeVocabulary(name="a", source_path="a",
                          target_properties={"nc:PersonType": {"nc:PersonName", "nc:PersonAge"}})
        b = EdgeVocabulary(name="b", source_path="b",
                          target_properties={"nc:PersonType": {"nc:PersonName", "nc:PersonID"}})
        result = compute_property_overlap(a, b)
        assert result["sharedTypeCount"] == 1
        # Jaccard of {Name, Age} vs {Name, ID} = 1/3
        assert result["perType"]["nc:PersonType"]["jaccard"] == pytest.approx(1/3, rel=0.01)

    def test_no_shared_types(self):
        a = EdgeVocabulary(name="a", source_path="a", target_properties={"nc:PersonType": set()})
        b = EdgeVocabulary(name="b", source_path="b", target_properties={"nc:ActivityType": set()})
        result = compute_property_overlap(a, b)
        assert result["averageJaccard"] == 0.0


# ─── Namespace Overlap ───────────────────────────────────────────────────

class TestNamespaceOverlap:
    def test_shared_namespaces(self):
        a = EdgeVocabulary(name="a", source_path="a", namespaces={"nc", "j", "ext1"})
        b = EdgeVocabulary(name="b", source_path="b", namespaces={"nc", "j", "ext2"})
        result = compute_namespace_overlap(a, b)
        assert result["sharedCount"] == 2
        assert set(result["shared"]) == {"nc", "j"}
        assert result["aOnly"] == ["ext1"]
        assert result["bOnly"] == ["ext2"]


# ─── Codelist Overlap ────────────────────────────────────────────────────

class TestCodelistOverlap:
    def test_shared_schemes_with_value_overlap(self):
        a = EdgeVocabulary(name="a", source_path="a",
                          codelist_schemes={"Status": {"active", "inactive"}, "Color": {"red"}})
        b = EdgeVocabulary(name="b", source_path="b",
                          codelist_schemes={"Status": {"active", "closed"}, "Size": {"large"}})
        result = compute_codelist_overlap(a, b)
        assert result["sharedSchemeCount"] == 1
        assert result["perScheme"]["Status"]["sharedValueCount"] == 1  # "active"


# ─── Composite Score ─────────────────────────────────────────────────────

class TestCompositeScore:
    def test_self_overlap_is_one(self):
        a = EdgeVocabulary(
            name="a", source_path="a",
            target_types={"nc:PersonType"},
            target_properties={"nc:PersonType": {"nc:PersonName"}},
            namespaces={"nc"},
            codelist_schemes={"Status": {"active"}},
        )
        result = compute_pairwise_overlap(a, a)
        assert result["compositeInteroperabilityScore"] == pytest.approx(1.0)

    def test_no_overlap_is_zero(self):
        a = EdgeVocabulary(
            name="a", source_path="a",
            target_types={"nc:PersonType"},
            target_properties={"nc:PersonType": {"nc:PersonName"}},
            namespaces={"nc"},
            codelist_schemes={"Status": {"active"}},
        )
        b = EdgeVocabulary(
            name="b", source_path="b",
            target_types={"j:ChargeType"},
            target_properties={"j:ChargeType": {"j:ChargeText"}},
            namespaces={"j"},
            codelist_schemes={"Severity": {"high"}},
        )
        result = compute_pairwise_overlap(a, b)
        assert result["compositeInteroperabilityScore"] == 0.0


# ─── Vocabulary Extraction ───────────────────────────────────────────────

class TestExtractVocabulary:
    def test_extracts_from_inventory(self):
        inventory = {
            "classes": [
                {"qname": "nc:PersonType"},
                {"qname": "nc:ActivityType"},
            ],
            "shaclShapes": [
                {
                    "targetClass": "nc:PersonType",
                    "properties": [{"path": "nc:PersonName"}, {"path": "nc:PersonAge"}],
                },
            ],
            "namespaceMap": {"http://niem/core": "nc:"},
            "codelistSchemes": [
                {"label": "Status", "concepts": [{"label": "active"}, {"label": "inactive"}]},
            ],
        }
        vocab = extract_vocabulary(inventory, "test.json")
        assert vocab.target_types == {"nc:PersonType", "nc:ActivityType"}
        assert vocab.target_properties["nc:PersonType"] == {"nc:PersonName", "nc:PersonAge"}
        assert vocab.namespaces == {"nc"}
        assert vocab.codelist_schemes["Status"] == {"active", "inactive"}

