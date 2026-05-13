"""Per-file evaluation via claude -p with structured output.

Each call is an independent process with clean context — no shared state,
safe to run concurrently.
"""

import asyncio
import json
from datetime import datetime, timezone

from orchestrator_service.prompts import build_type_prompt, build_property_prompt
from orchestrator_service.schemas import (
    TYPE_EVALUATION_SCHEMA,
    PROPERTY_EVALUATION_SCHEMA,
    validate_response,
)

# Dispatch table: kind -> (prompt_builder, schema)
_KIND_DISPATCH = {
    "type": (build_type_prompt, TYPE_EVALUATION_SCHEMA),
    "property": (build_property_prompt, PROPERTY_EVALUATION_SCHEMA),
}


from typing import NamedTuple


class EvaluationError(Exception):
    """Raised when claude -p returns an unusable response."""


class EvaluationContext(NamedTuple):
    """Shared context needed for all evaluations in a run."""
    actions: dict
    type_patterns: dict


async def evaluate_file(
    file_doc: dict,
    context: EvaluationContext,
    model: str = "sonnet",
    timeout: int = 120,
) -> dict:
    """Evaluate a single search result file via claude -p.

    Returns the validated evaluation dict.
    Raises EvaluationError on failure.
    """
    kind = file_doc.get("kind", "")
    if kind not in _KIND_DISPATCH:
        raise EvaluationError(f"Unknown file kind: {kind}")

    build_prompt, schema = _KIND_DISPATCH[kind]
    prompt = build_prompt(
        source=file_doc["source"],
        candidates=file_doc["candidates"],
        actions=context.actions,
        type_patterns=context.type_patterns,
    )

    schema_str = json.dumps(schema)

    # Uses create_subprocess_exec (not shell) to avoid injection risks.
    # The prompt is passed via stdin, not as a shell argument.
    proc = await asyncio.create_subprocess_exec(
        "claude", "-p",
        "--tools", "",
        "--output-format", "json",
        "--json-schema", schema_str,
        "--model", model,
        "--no-session-persistence",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=prompt.encode("utf-8")),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        source_id = file_doc.get("source", {}).get("qname", "unknown")
        raise EvaluationError(f"Timeout after {timeout}s for {source_id}")

    if proc.returncode != 0:
        source_id = file_doc.get("source", {}).get("qname", "unknown")
        err_text = stderr.decode("utf-8", errors="replace").strip()
        raise EvaluationError(
            f"claude -p exited {proc.returncode} for {source_id}: {err_text}"
        )

    # Parse the JSON response envelope
    try:
        response = json.loads(stdout.decode("utf-8"))
    except json.JSONDecodeError as e:
        raise EvaluationError(f"Malformed JSON response: {e}")

    if response.get("is_error"):
        raise EvaluationError(
            f"claude -p reported error: {response.get('result', '')}"
        )

    # Extract structured output
    evaluation = response.get("structured_output")
    if evaluation is None:
        raise EvaluationError(
            "No structured_output in response. "
            f"Result: {response.get('result', '')[:200]}"
        )

    # Validate against the source file
    errors = validate_response(evaluation, file_doc)
    if errors:
        raise EvaluationError(
            f"Validation failed: {'; '.join(errors)}"
        )

    # Add provenance metadata (not part of LLM output — added post-validation)
    evaluation["evaluatedAt"] = datetime.now(timezone.utc).isoformat()
    evaluation["evaluatedBy"] = model
    evaluation["candidateCount"] = len(file_doc.get("candidates", []))

    return evaluation
