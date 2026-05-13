"""Per-file evaluation via OpenAI Responses API for smoke testing.

Mirrors the contract of orchestrator_service.evaluator.evaluate_file but
calls OpenAI's Responses API with structured output instead of shelling
out to claude -p. Used by runner_tools/smoke_test_openai.py to compare
OpenAI model outputs (default: gpt-5.4-mini) against the existing Sonnet
baseline already on disk.

Sync (not async) because the smoke test runs serially over a small sample.
"""

import json
from datetime import datetime, timezone
from typing import Optional

from orchestrator_service.evaluator import EvaluationContext, EvaluationError
from orchestrator_service.prompts import build_property_prompt, build_type_prompt
from orchestrator_service.schemas import (
    PROPERTY_EVALUATION_SCHEMA,
    TYPE_EVALUATION_SCHEMA,
    validate_response,
)

try:
    from openai import OpenAI
except ImportError as e:
    raise ImportError(
        "openai package required. Install with: pip install openai"
    ) from e


_KIND_DISPATCH = {
    "type": (build_type_prompt, TYPE_EVALUATION_SCHEMA, "type_evaluation"),
    "property": (build_property_prompt, PROPERTY_EVALUATION_SCHEMA, "property_evaluation"),
}


def evaluate_file_openai(
    file_doc: dict,
    context: EvaluationContext,
    model: str = "gpt-5.4-mini",
    reasoning_effort: str = "low",
    client: Optional[OpenAI] = None,
) -> dict:
    """Evaluate a single search result file via OpenAI Responses API.

    Returns the validated evaluation dict.
    Raises EvaluationError on failure.
    """
    kind = file_doc.get("kind", "")
    if kind not in _KIND_DISPATCH:
        raise EvaluationError(f"Unknown file kind: {kind}")

    build_prompt, schema, schema_name = _KIND_DISPATCH[kind]
    prompt = build_prompt(
        source=file_doc["source"],
        candidates=file_doc["candidates"],
        actions=context.actions,
        type_patterns=context.type_patterns,
    )

    if client is None:
        client = OpenAI()

    source_id = file_doc.get("source", {}).get("qname", "unknown")

    try:
        resp = client.responses.create(
            model=model,
            input=prompt,
            reasoning={"effort": reasoning_effort},
            text={
                "format": {
                    "type": "json_schema",
                    "name": schema_name,
                    "schema": schema,
                    "strict": True,
                }
            },
        )
    except Exception as e:
        raise EvaluationError(f"OpenAI API call failed for {source_id}: {e}") from e

    output_text = getattr(resp, "output_text", None)
    if not output_text:
        status = getattr(resp, "status", "unknown")
        raise EvaluationError(
            f"No output_text in response for {source_id} (status={status})"
        )

    try:
        evaluation = json.loads(output_text)
    except json.JSONDecodeError as e:
        raise EvaluationError(f"Malformed JSON for {source_id}: {e}")

    errors = validate_response(evaluation, file_doc)
    if errors:
        raise EvaluationError(
            f"Validation failed for {source_id}: {'; '.join(errors)}"
        )

    evaluation.pop("_prefix_corrected", None)
    evaluation["evaluatedAt"] = datetime.now(timezone.utc).isoformat()
    evaluation["evaluatedBy"] = model
    evaluation["candidateCount"] = len(file_doc.get("candidates", []))
    return evaluation
