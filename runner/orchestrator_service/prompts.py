"""Prompt templates for bounded per-file evaluation.

Each template is source/target agnostic — all domain-specific context
(actions, typePatterns, semantic search guidance) comes from the run's
alignment report and is passed through as opaque data.
"""

import json

# ---------------------------------------------------------------------------
# Semantic search guidance (bundled, not read from AGENTS/ at runtime)
# ---------------------------------------------------------------------------

SEMANTIC_SEARCH_GUIDANCE = """\
Before choosing a target type, check whether the target ontology already \
defines a specific element or property for the source concept. If it does, \
the type follows from that element — not from name similarity alone.

Some source "classes" are really simple data values (a country name, a \
language name, a telephone number). Check whether the concept is better \
represented as a property on a parent type rather than as a standalone type. \
If so, map it to the existing property that carries this data rather than \
creating a new type-level alignment.

Each target ontology defines its own type patterns (e.g., object, \
association, complex_value). These describe the structural patterns you \
will encounter — what kinds of types exist and how they relate to matching \
decisions. Read these as context, not as a selection list.

Never rely on candidate ordering or position in the list. Evaluate every \
candidate by comparing definitions and available data.\
"""


# ---------------------------------------------------------------------------
# Kind-specific text fragments
# ---------------------------------------------------------------------------

_KIND_FRAGMENTS = {
    "type": {
        "entity": "concept",
        "source_label": "Source Type",
        "task_compare": (
            "Compare the source type's definition and available data against each "
            "candidate's definition, pattern, properties, and path."
        ),
        "task_null": "set targetType to null",
        "task_undecided": (
            'If multiple candidates are equally good and you cannot confidently '
            'pick one, set targetType to "[undecided]".'
        ),
        "source_field": "sourceConcept",
        "source_example": '"dbpi:Address" not just "Address"',
        "target_field": "targetType",
    },
    "property": {
        "entity": "property",
        "source_label": "Source Property",
        "task_compare": (
            "Compare the source property's definition, range, and parent type context "
            "against each candidate's definition, type, and path."
        ),
        "task_null": "set targetProperty to null",
        "task_undecided": (
            'If multiple candidates are equally good and you cannot confidently '
            'pick one, set targetProperty to "[undecided]".'
        ),
        "source_field": "sourceProperty",
        "source_example": '"dbpi:streetName" not just "streetName"',
        "target_field": "targetProperty",
    },
}


# ---------------------------------------------------------------------------
# Shared prompt builder
# ---------------------------------------------------------------------------

def _build_prompt(
    kind: str,
    source: dict,
    candidates: list[dict],
    actions: dict,
    type_patterns: dict,
) -> str:
    f = _KIND_FRAGMENTS[kind]
    return f"""\
You are evaluating a semantic alignment between a source ontology {f['entity']} \
and candidates from a target ontology. Your task is to select the best \
semantic match or determine that no candidate matches.

## Target Ontology Context

Actions available:
{json.dumps(actions, indent=2)}

Type patterns:
{json.dumps(type_patterns, indent=2)}

## Evaluation Protocol

{SEMANTIC_SEARCH_GUIDANCE}

## {f['source_label']}

{json.dumps(source, indent=2)}

## Candidates

{json.dumps(candidates, indent=2)}

## Task

{f['task_compare']} Select the best \
semantic match. If no candidate is a genuine semantic match, \
{f['task_null']}. {f['task_undecided']}

IMPORTANT: Use the exact qualified names as they appear in the data above. \
For {f['source_field']}, copy the source's qname exactly (including the namespace \
prefix, e.g. {f['source_example']}). The value for {f['target_field']} must be a \
candidate's id exactly as listed (e.g. "nc:AddressType"). \
It must be a candidate id, "[undecided]", or null.

Return your evaluation as structured JSON matching the required schema."""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_type_prompt(
    source: dict,
    candidates: list[dict],
    actions: dict,
    type_patterns: dict,
) -> str:
    """Build a bounded prompt for evaluating one type file."""
    return _build_prompt("type", source, candidates, actions, type_patterns)


def build_property_prompt(
    source: dict,
    candidates: list[dict],
    actions: dict,
    type_patterns: dict,
) -> str:
    """Build a bounded prompt for evaluating one property file."""
    return _build_prompt("property", source, candidates, actions, type_patterns)
