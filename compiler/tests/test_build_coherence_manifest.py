#!/usr/bin/env python3
"""Tests for build_coherence_manifest.py — coherence manifest artifact."""

import pytest

from ontology_mapper.build_coherence_manifest import (
    build_coherence_manifest,
    _build_rotation_summary,
    _build_entropy_section,
    _build_codebook_digest,
)


# ─── Fixtures ──────────────────────────────────────────────────────────

def _matrix(mappings, target_ontology="niem", target_version="6.0"):
    return {
        "targetOntology": target_ontology,
        "targetVersion": target_version,
        "mappings": mappings,
    }


def _mapping(concept, action, confidence="confident", props=None,
             target_hash="abc123", prop_hashes=None):
    m = {
        "sourceConcept": concept,
        "action": action,
        "confidence": confidence,
        "targetDefinitionHash": target_hash,
        "propertyMappings": [],
    }
    if props:
        for i, (pa, pc) in enumerate(props):
            p = {
                "sourceProperty": f"{concept}:prop{i}",
                "action": pa,
                "confidence": pc,
                "targetDefinitionHash": prop_hashes[i] if prop_hashes else f"ph{i}",
            }
            m["propertyMappings"].append(p)
    return m


def _entropy_summary(h_total=10.0, h_types=6.0, h_props=4.0):
    return {"hTotal": h_total, "hTypes": h_types, "hProperties": h_props}


def _residual(h_residual=2.0, h_res_types=1.0, h_res_props=1.0, h_resolved=8.0):
    return {
        "hResidualTotal": h_residual,
        "hResidualTypes": h_res_types,
        "hResidualProperties": h_res_props,
        "hResolvedTotal": h_resolved,
    }


# ─── Unit tests: _build_rotation_summary ──────────────────────────────

class TestRotationSummary:

    def test_class_action_counts(self):
        mappings = [
            _mapping("x:A", "reuse"),
            _mapping("x:B", "reuse"),
            _mapping("x:C", "extend"),
        ]
        summary = _build_rotation_summary(mappings)
        assert summary["totalConcepts"] == 3
        assert summary["classActions"] == {"reuse": 2, "extend": 1}

    def test_class_confidence_counts(self):
        mappings = [
            _mapping("x:A", "reuse", "confident"),
            _mapping("x:B", "reuse", "best-guess"),
            _mapping("x:C", "extend", "best-guess"),
        ]
        summary = _build_rotation_summary(mappings)
        assert summary["classConfidence"] == {"confident": 1, "bestGuess": 2}

    def test_property_action_counts(self):
        mappings = [
            _mapping("x:A", "reuse", props=[
                ("reuse-property", "confident"),
                ("create-property", "confident"),
                ("human-must-decide", "confident"),
            ]),
        ]
        summary = _build_rotation_summary(mappings)
        assert summary["totalProperties"] == 3
        assert summary["propertyActions"] == {
            "reuse-property": 1, "create-property": 1, "human-must-decide": 1,
        }

    def test_property_confidence_counts(self):
        mappings = [
            _mapping("x:A", "reuse", props=[
                ("reuse-property", "confident"),
                ("reuse-property", "best-guess"),
            ]),
        ]
        summary = _build_rotation_summary(mappings)
        assert summary["propertyConfidence"] == {"confident": 1, "bestGuess": 1}

    def test_empty_mappings(self):
        summary = _build_rotation_summary([])
        assert summary["totalConcepts"] == 0
        assert summary["classActions"] == {}
        assert summary["totalProperties"] == 0

    def test_no_properties(self):
        mappings = [_mapping("x:A", "extend")]
        summary = _build_rotation_summary(mappings)
        assert summary["totalProperties"] == 0
        assert summary["propertyActions"] == {}

    def test_missing_confidence_defaults_confident(self):
        m = {"action": "reuse", "propertyMappings": []}
        summary = _build_rotation_summary([m])
        assert summary["classConfidence"]["confident"] == 1


# ─── Unit tests: _build_entropy_section ───────────────────────────────

class TestEntropySection:

    def test_both_artifacts(self):
        section = _build_entropy_section(_entropy_summary(), _residual())
        assert section["preTotal"] == 10.0
        assert section["residualTotal"] == 2.0
        assert section["resolvedTotal"] == 8.0
        assert section["preTypes"] == 6.0
        assert section["preProperties"] == 4.0
        assert section["residualTypes"] == 1.0
        assert section["residualProperties"] == 1.0

    def test_entropy_only(self):
        section = _build_entropy_section(_entropy_summary(), None)
        assert section["preTotal"] == 10.0
        assert "residualTotal" not in section

    def test_residual_only(self):
        section = _build_entropy_section(None, _residual())
        assert "preTotal" not in section
        assert section["residualTotal"] == 2.0

    def test_neither_returns_none(self):
        assert _build_entropy_section(None, None) is None


# ─── Unit tests: _build_codebook_digest ───────────────────────────────

class TestCodebookDigest:

    def test_counts_hashes(self):
        mappings = [
            _mapping("x:A", "reuse", target_hash="h1", props=[
                ("reuse-property", "confident"),
            ], prop_hashes=["ph1"]),
            _mapping("x:B", "reuse", target_hash="h2", props=[
                ("reuse-property", "confident"),
            ], prop_hashes=["ph2"]),
        ]
        digest = _build_codebook_digest(mappings)
        assert digest["typeHashCount"] == 2
        assert digest["propertyHashCount"] == 2
        assert digest["distinctTypeHashes"] == 2
        assert digest["distinctPropertyHashes"] == 2

    def test_duplicate_hashes(self):
        mappings = [
            _mapping("x:A", "reuse", target_hash="same"),
            _mapping("x:B", "reuse", target_hash="same"),
        ]
        digest = _build_codebook_digest(mappings)
        assert digest["typeHashCount"] == 2
        assert digest["distinctTypeHashes"] == 1

    def test_null_hashes_excluded(self):
        mappings = [
            _mapping("x:A", "extend", target_hash=None),
        ]
        digest = _build_codebook_digest(mappings)
        assert digest["typeHashCount"] == 0

    def test_empty_mappings(self):
        digest = _build_codebook_digest([])
        assert digest["typeHashCount"] == 0
        assert digest["propertyHashCount"] == 0
        assert digest["distinctTypeHashes"] == 0
        assert digest["distinctPropertyHashes"] == 0


# ─── Integration: build_coherence_manifest ────────────────────────────

class TestBuildCoherenceManifest:

    def test_full_manifest(self):
        matrix = _matrix([
            _mapping("x:A", "reuse", props=[
                ("reuse-property", "confident"),
                ("create-property", "best-guess"),
            ]),
            _mapping("x:B", "extend", "best-guess"),
        ])
        manifest = build_coherence_manifest(
            matrix, _entropy_summary(), _residual(),
        )
        assert manifest["schemaVersion"] == "1.0"
        assert manifest["targetOntology"] == "niem"
        assert manifest["targetVersion"] == "6.0"
        assert manifest["generatedBy"] == "ontology-mapper"
        assert "generatedAt" in manifest

        rs = manifest["rotationSummary"]
        assert rs["totalConcepts"] == 2
        assert rs["classActions"]["reuse"] == 1
        assert rs["totalProperties"] == 2

        assert manifest["entropy"]["preTotal"] == 10.0
        assert manifest["entropy"]["residualTotal"] == 2.0

        assert manifest["codebookDigest"]["typeHashCount"] == 2

    def test_without_entropy(self):
        matrix = _matrix([_mapping("x:A", "reuse")])
        manifest = build_coherence_manifest(matrix)
        assert manifest["entropy"] is None
        assert manifest["rotationSummary"]["totalConcepts"] == 1
        assert manifest["codebookDigest"]["typeHashCount"] == 1

    def test_empty_matrix(self):
        matrix = _matrix([])
        manifest = build_coherence_manifest(matrix)
        assert manifest["rotationSummary"]["totalConcepts"] == 0
        assert manifest["entropy"] is None
        assert manifest["codebookDigest"]["typeHashCount"] == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
