#!/usr/bin/env python3
"""Build a coherence manifest summarizing boundary coherence state.

The coherence manifest is an edge package artifact that bridges compile-time
rotation and runtime verification. It summarizes rotation decisions, entropy
measurements, and codebook version context so a receiving system can evaluate
whether prior rotations are still valid.
"""

from datetime import datetime, timezone


def build_coherence_manifest(matrix, entropy_summary=None, residual_entropy=None):
    """Build a coherence manifest from pipeline artifacts.

    Args:
        matrix: Mapping matrix dict (required).
        entropy_summary: Pre-rotation entropy dict (optional).
        residual_entropy: Residual entropy dict (optional).

    Returns:
        Coherence manifest dict.
    """
    mappings = matrix.get("mappings", [])

    return {
        "schemaVersion": "1.0",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "generatedBy": "ontology-mapper",
        "targetOntology": matrix.get("targetOntology", ""),
        "targetVersion": matrix.get("targetVersion", ""),
        "rotationSummary": _build_rotation_summary(mappings),
        "entropy": _build_entropy_section(entropy_summary, residual_entropy),
        "codebookDigest": _build_codebook_digest(mappings),
    }


def _build_rotation_summary(mappings):
    """Summarize rotation decisions at class and property levels."""
    class_actions = {}
    class_confident = 0
    class_best_guess = 0

    prop_actions = {}
    prop_confident = 0
    prop_best_guess = 0
    total_props = 0

    for m in mappings:
        action = m.get("action", "")
        class_actions[action] = class_actions.get(action, 0) + 1

        confidence = m.get("confidence", "confident")
        if confidence == "best-guess":
            class_best_guess += 1
        else:
            class_confident += 1

        for p in m.get("propertyMappings", []):
            total_props += 1
            pa = p.get("action", "")
            prop_actions[pa] = prop_actions.get(pa, 0) + 1

            pc = p.get("confidence", "confident")
            if pc == "best-guess":
                prop_best_guess += 1
            else:
                prop_confident += 1

    return {
        "totalConcepts": len(mappings),
        "classActions": class_actions,
        "classConfidence": {"confident": class_confident, "bestGuess": class_best_guess},
        "totalProperties": total_props,
        "propertyActions": prop_actions,
        "propertyConfidence": {"confident": prop_confident, "bestGuess": prop_best_guess},
    }


def _build_entropy_section(entropy_summary, residual_entropy):
    """Build entropy section from pre-rotation and residual entropy artifacts.

    Returns None if neither artifact is available.
    """
    if entropy_summary is None and residual_entropy is None:
        return None

    section = {}

    if entropy_summary:
        section["preTotal"] = entropy_summary.get("hTotal", 0.0)
        section["preTypes"] = entropy_summary.get("hTypes", 0.0)
        section["preProperties"] = entropy_summary.get("hProperties", 0.0)

    if residual_entropy:
        section["residualTotal"] = residual_entropy.get("hResidualTotal", 0.0)
        section["residualTypes"] = residual_entropy.get("hResidualTypes", 0.0)
        section["residualProperties"] = residual_entropy.get("hResidualProperties", 0.0)
        section["resolvedTotal"] = residual_entropy.get("hResolvedTotal", 0.0)

    return section


def _build_codebook_digest(mappings):
    """Summarize targetDefinitionHash values from the matrix."""
    type_hashes = []
    prop_hashes = []

    for m in mappings:
        h = m.get("targetDefinitionHash")
        if h is not None:
            type_hashes.append(h)

        for p in m.get("propertyMappings", []):
            ph = p.get("targetDefinitionHash")
            if ph is not None:
                prop_hashes.append(ph)

    return {
        "typeHashCount": len(type_hashes),
        "propertyHashCount": len(prop_hashes),
        "distinctTypeHashes": len(set(type_hashes)),
        "distinctPropertyHashes": len(set(prop_hashes)),
    }
