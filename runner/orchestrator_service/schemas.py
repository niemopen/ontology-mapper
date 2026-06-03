"""JSON schemas and validation for LLM evaluation responses.

The schemas serve two purposes:
1. Passed to ``claude -p --json-schema`` to constrain structured output
2. Used by ``validate_response()`` to check the response before writing

The evaluation dict schemas match what ``om-collect-alignments`` expects
when reading back evaluated search result files.
"""


# ---------------------------------------------------------------------------
# JSON Schemas for --json-schema flag
# ---------------------------------------------------------------------------

def _make_schema(source_field: str, target_field: str) -> dict:
    """Build an evaluation schema for a given source/target field pair."""
    return {
        "type": "object",
        "properties": {
            source_field: {"type": "string"},
            "sourceDefinition": {"type": "string"},
            "sourcePath": {"type": "string"},
            target_field: {"type": ["string", "null"]},
            "targetDefinition": {"type": ["string", "null"]},
            "targetPath": {"type": ["string", "null"]},
            "rationale": {"type": "string"},
        },
        "required": [
            source_field, "sourceDefinition", "sourcePath",
            target_field, "targetDefinition", "targetPath",
            "rationale",
        ],
        "additionalProperties": False,
    }


TYPE_EVALUATION_SCHEMA = _make_schema("sourceConcept", "targetType")
PROPERTY_EVALUATION_SCHEMA = _make_schema("sourceProperty", "targetProperty")

# Field name lookup by kind
_FIELD_NAMES = {
    "type": ("sourceConcept", "targetType"),
    "property": ("sourceProperty", "targetProperty"),
}


# ---------------------------------------------------------------------------
# Response validation
# ---------------------------------------------------------------------------

def _matches_qname(actual: str, expected: str) -> bool:
    """Check if actual matches expected, allowing for missing namespace prefix."""
    if actual == expected:
        return True
    # Accept local name without prefix (e.g. "Address" matches "dbpi:Address")
    if ":" in expected and actual == expected.split(":", 1)[1]:
        return True
    return False


def _fix_source_field(evaluation: dict, field: str, expected: str) -> bool:
    """Auto-correct a source field that's missing its namespace prefix.

    Returns True if a correction was made.
    """
    actual = evaluation.get(field, "")
    if actual != expected and _matches_qname(actual, expected):
        evaluation[field] = expected
        return True
    return False


def validate_response(evaluation: dict, file_doc: dict) -> list[str]:
    """Validate an evaluation dict against the source file.

    Returns a list of error strings.  Empty list means valid.
    Auto-corrects source fields that are missing namespace prefixes.
    Sets ``evaluation["_prefix_corrected"]`` to True if a correction was made.
    """
    errors = []
    kind = file_doc.get("kind", "")
    source = file_doc.get("source", {})
    candidates = file_doc.get("candidates", [])
    candidate_ids = {c["id"] for c in candidates}

    # Field-presence check (defense-in-depth beyond --json-schema)
    schema = TYPE_EVALUATION_SCHEMA if kind == "type" else PROPERTY_EVALUATION_SCHEMA
    for field in schema.get("required", []):
        if field not in evaluation:
            errors.append(f"Missing required field: {field}")
    if errors:
        return errors  # no point checking semantics if fields are missing

    if kind not in _FIELD_NAMES:
        return errors

    source_field, target_field = _FIELD_NAMES[kind]

    # Source name must match the file's qname
    expected = source.get("qname", "")
    if _fix_source_field(evaluation, source_field, expected):
        evaluation["_prefix_corrected"] = True
    actual = evaluation.get(source_field, "")
    if actual != expected:
        errors.append(
            f"{source_field} mismatch: got '{actual}', expected '{expected}'"
        )

    # Target must be a candidate, null, or the [undecided] sentinel
    target = evaluation.get(target_field)
    if target is not None and target != "[undecided]" and target not in candidate_ids:
        errors.append(
            f"{target_field} '{target}' is not among the candidates"
        )

    # Rationale must be substantive
    rationale = evaluation.get("rationale", "")
    if len(rationale) < 20:
        errors.append(
            f"rationale too short ({len(rationale)} chars, minimum 20)"
        )

    return errors
