"""Per-file evaluation via the provider-agnostic LLM service.

Each call is an independent subprocess with clean context — no shared
state, safe to run concurrently. The active provider (codex / claude) is
selected by call_structured_async() per OM_LLM_PROVIDER; this module
doesn't care which one runs.
"""

from datetime import datetime, timezone
from typing import NamedTuple, Optional

from orchestrator_service.prompts import build_type_prompt, build_property_prompt
from orchestrator_service.schemas import (
    TYPE_EVALUATION_SCHEMA,
    PROPERTY_EVALUATION_SCHEMA,
    validate_response,
)
from ontology_mapper.llm_service import (
    LLMError,
    ModelUnavailableError,
    call_structured_async,
)

# Dispatch table: kind -> (prompt_builder, schema)
_KIND_DISPATCH = {
    "type": (build_type_prompt, TYPE_EVALUATION_SCHEMA),
    "property": (build_property_prompt, PROPERTY_EVALUATION_SCHEMA),
}


class EvaluationError(Exception):
    """Raised when the LLM call returns an unusable response."""


class EvaluationContext(NamedTuple):
    """Shared context needed for all evaluations in a run."""
    actions: dict
    type_patterns: dict


async def evaluate_file(
    file_doc: dict,
    context: EvaluationContext,
    model: Optional[str] = None,
    provider: Optional[str] = None,
    timeout: int = 120,
) -> dict:
    """Evaluate a single search result file via the active LLM provider.

    Args:
        file_doc: The pre-fetched candidates document for one source concept.
        context: Shared run-wide context (actions, type patterns).
        model: Provider-specific model id. None -> provider default
            (sonnet for claude, gpt-5.5 for codex).
        provider: "codex" | "claude" | None. None -> OM_LLM_PROVIDER /
            default codex.
        timeout: Per-call timeout in seconds.

    Returns:
        The validated evaluation dict with provenance fields added.

    Raises:
        EvaluationError: validation failed or response shape unusable.
        ModelUnavailableError: active model is over capacity/quota; defer.
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

    source_id = file_doc.get("source", {}).get("qname", "unknown")

    try:
        evaluation = await call_structured_async(
            prompt, schema, provider=provider, model=model, timeout=timeout
        )
    except ModelUnavailableError:
        # Re-raise so the runner can treat this as a deferral, not a
        # per-file failure.
        raise
    except LLMError as e:
        raise EvaluationError(f"LLM call failed for {source_id}: {e}")

    # Validate against the source file
    errors = validate_response(evaluation, file_doc)
    if errors:
        raise EvaluationError(
            f"Validation failed: {'; '.join(errors)}"
        )

    # Resolve which model+provider actually ran so provenance reflects truth.
    from ontology_mapper.llm_service import (
        _resolve_provider as _rp,
        _resolve_model as _rm,
    )
    eff_provider = _rp(provider)
    eff_model = _rm(eff_provider, model)

    # Add provenance metadata (not part of LLM output — added post-validation)
    evaluation["evaluatedAt"] = datetime.now(timezone.utc).isoformat()
    evaluation["evaluatedBy"] = f"{eff_provider}:{eff_model}"
    evaluation["candidateCount"] = len(file_doc.get("candidates", []))

    return evaluation
