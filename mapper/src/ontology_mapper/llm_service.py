"""Provider-agnostic structured-output LLM service.

All LLM calls in this pipeline (Stage 3 fan-out, Stage 5 review
interpretation) route through `call_structured()` / `call_structured_async()`.
The function dispatches to one of two provider paths:

  - **codex** (default): spawns `codex exec` against GPT-5.5 using the
    user's ChatGPT/Codex subscription. No per-token cost, no API key.
    OpenAI structured-output strict mode is enforced via an automatic
    schema rewriter (additionalProperties=false, required listing every
    property, const/enum -> type:string inference, nullable union ->
    first non-null type).

  - **claude**: spawns `claude -p` against the requested Claude model
    (default `sonnet` for fan-out economy; callers can request `opus` or
    a pinned id). Retained for parity with the prior pipeline behavior
    and for cases where Opus quality is preferred.

Provider selection priority:
  1. The `provider=` argument to `call_structured()`
  2. The `OM_LLM_PROVIDER` environment variable
  3. Default: "codex"

Both providers share the same retry-on-transient + defer-on-unavailable
contract. On unavailability (rate-limit, model-not-found, capacity), the
caller receives `ModelUnavailableError` immediately -- no retry, no
sleep -- so the pipeline can defer the affected concept and try again
later.

The async API (`call_structured_async`) is the primary entry point;
Stage 3 fans out hundreds of evaluations concurrently and needs it. The
sync API is a thin asyncio.run wrapper for Stage 5's interactive loop.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Optional

# Bind asyncio.create_subprocess_exec to a local name to keep the rest of the
# code readable. (Despite the name, this is the *safe* Python equivalent of
# execFile -- args are passed as a list, no shell involved, no injection risk.)
_spawn = asyncio.create_subprocess_exec
_PIPE = asyncio.subprocess.PIPE


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class LLMError(Exception):
    """Raised when an LLM call fails after retries."""


class ModelUnavailableError(LLMError):
    """Raised when the active model is unavailable (rate-limit, not found,
    capacity, quota). Callers should treat this as a deferral signal: do
    not persist a partial result, retry the same concept on a later run.
    """


# ---------------------------------------------------------------------------
# Provider configuration
# ---------------------------------------------------------------------------


PROVIDER_ENV_VAR = "OM_LLM_PROVIDER"
DEFAULT_PROVIDER = "codex"

# Default model per provider when the caller doesn't pass --model explicitly.
# Stage 3 fan-out uses these; Stage 5 review interpretation uses these too.
DEFAULT_MODELS = {
    "codex": "gpt-5.5",
    "claude": "sonnet",
}

# Stderr substrings that mean the active model can't serve the request right
# now (vs. a prompt error or transient network blip). Lower-cased before match.
_UNAVAILABLE_SIGNALS = [
    "model_not_found",
    "model not found",
    "rate_limit",
    "rate limit",
    "overloaded",
    "capacity",
    # OpenAI-specific (Codex CLI surfaces these via stderr):
    "insufficient_quota",
    "invalid_api_key",
    "service_unavailable",
]


def _resolve_provider(provider: Optional[str]) -> str:
    if provider is not None:
        return provider
    return os.environ.get(PROVIDER_ENV_VAR, DEFAULT_PROVIDER)


def _resolve_model(provider: str, model: Optional[str]) -> str:
    if model is not None:
        return model
    if provider in DEFAULT_MODELS:
        return DEFAULT_MODELS[provider]
    raise ValueError(
        f"Unknown LLM provider {provider!r}; expected one of "
        f"{sorted(DEFAULT_MODELS.keys())}"
    )


# ---------------------------------------------------------------------------
# Strict-schema enforcement for OpenAI structured-output mode (codex only)
# ---------------------------------------------------------------------------


def enforce_strict_schema(node):
    """Rewrite a JSON-schema tree in place for OpenAI strict response_format.

    OpenAI's strict mode requires:
      - Every object schema has `additionalProperties: false`
      - Every object schema's `required` lists every key in `properties`
      - Every leaf schema has a `type` key (inferred from `const` / `enum`
        if the original schema omits it)

    Nullable union types (`type: ["string", "null"]`) are preserved -- OpenAI
    strict mode supports them and the evaluation schemas rely on them
    (targetType / targetProperty are null when no candidate matches). An
    earlier port of this routine also stripped nulls, which forced codex to
    emit the literal string "null" when it meant absence; that broke
    validate_response().

    Idempotent. Returns the same root node for chaining.
    """
    if isinstance(node, dict):
        if "type" not in node:
            if "const" in node and isinstance(node["const"], str):
                node["type"] = "string"
            elif (
                "enum" in node
                and node["enum"]
                and all(isinstance(x, str) for x in node["enum"])
            ):
                node["type"] = "string"
        if node.get("type") == "object":
            node["additionalProperties"] = False
            if "properties" in node:
                node["required"] = list(node["properties"].keys())
        for v in node.values():
            enforce_strict_schema(v)
    elif isinstance(node, list):
        for item in node:
            enforce_strict_schema(item)
    return node


# ---------------------------------------------------------------------------
# Async public API
# ---------------------------------------------------------------------------


async def call_structured_async(
    prompt: str,
    schema: dict,
    *,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    timeout: int = 120,
) -> dict:
    """Call the active LLM provider to produce JSON matching *schema*.

    Args:
        prompt: Prompt text. Piped via stdin to the provider subprocess.
        schema: A JSON-schema dict describing the expected response shape.
            The `$schema` key is stripped if present.
        provider: "codex" | "claude". If None, reads OM_LLM_PROVIDER from
            the environment, defaulting to "codex".
        model: Provider-specific model id. If None, uses DEFAULT_MODELS.
        timeout: Per-call timeout in seconds.

    Returns:
        The parsed structured-output dict on success.

    Raises:
        ModelUnavailableError: the active model is rate-limited / not
            found / over capacity / quota-exhausted. No retry attempted.
        LLMError: any other non-recoverable failure after one retry.
        ValueError: unknown provider name.
    """
    provider = _resolve_provider(provider)
    model = _resolve_model(provider, model)

    if provider == "codex":
        return await _call_codex_async(prompt, schema, model=model, timeout=timeout)
    if provider == "claude":
        return await _call_claude_async(prompt, schema, model=model, timeout=timeout)
    raise ValueError(
        f"Unknown LLM provider {provider!r}; expected one of "
        f"{sorted(DEFAULT_MODELS.keys())}"
    )


def call_structured(
    prompt: str,
    schema: dict,
    *,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    timeout: int = 120,
) -> dict:
    """Synchronous wrapper around `call_structured_async`. Use from contexts
    without a running event loop (Stage 5 interactive review)."""
    return asyncio.run(
        call_structured_async(
            prompt, schema, provider=provider, model=model, timeout=timeout
        )
    )


# ---------------------------------------------------------------------------
# Codex (GPT-5.5) provider
# ---------------------------------------------------------------------------


async def _call_codex_async(
    prompt: str, schema: dict, *, model: str, timeout: int
) -> dict:
    """Spawn `codex` with the prompt on stdin and a strict-mode schema
    written to a temp file. Read the agent's final structured message from
    the -o output file and parse as JSON."""
    codex_exe = shutil.which("codex") or shutil.which("codex.cmd")
    if not codex_exe:
        raise LLMError(
            "codex executable not on PATH -- install Codex CLI or set "
            f"{PROVIDER_ENV_VAR}=claude to route through Anthropic instead"
        )

    # Deep-copy via JSON round-trip, strip $schema, mutate for OpenAI strict
    # mode. Don't mutate the caller's dict.
    clean = json.loads(json.dumps({k: v for k, v in schema.items() if k != "$schema"}))
    enforce_strict_schema(clean)
    schema_json = json.dumps(clean)

    last_error = None
    for attempt in range(2):
        if attempt > 0:
            await asyncio.sleep(min(2 ** attempt, 4))

        with tempfile.TemporaryDirectory() as td:
            schema_path = Path(td) / "schema.json"
            out_path = Path(td) / "out.txt"
            schema_path.write_text(schema_json, encoding="utf-8")

            proc = await _spawn(
                codex_exe, "exec",
                "-m", model,
                "--ephemeral",
                "-s", "read-only",
                "--skip-git-repo-check",
                "--color", "never",
                "--output-schema", str(schema_path),
                "-o", str(out_path),
                stdin=_PIPE,
                stdout=_PIPE,
                stderr=_PIPE,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(input=prompt.encode("utf-8")),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                last_error = f"codex timed out after {timeout}s"
                continue

            if proc.returncode != 0:
                stderr_text = stderr.decode("utf-8", errors="replace").strip()
                stderr_lower = stderr_text.lower()
                if any(sig in stderr_lower for sig in _UNAVAILABLE_SIGNALS):
                    raise ModelUnavailableError(
                        f"{model} unavailable: {stderr_text[:400]}"
                    )
                last_error = (
                    f"codex failed (rc={proc.returncode}): "
                    f"{stderr_text[:400]}"
                )
                continue

            raw = (
                out_path.read_text(encoding="utf-8", errors="replace")
                if out_path.exists()
                else ""
            )
            if not raw.strip():
                last_error = "codex produced empty output file"
                continue

            try:
                return json.loads(raw.strip())
            except json.JSONDecodeError as exc:
                last_error = (
                    f"codex returned invalid JSON: {exc}; "
                    f"raw[:200]={raw[:200]!r}"
                )
                continue

    raise LLMError(last_error or "unknown codex error after retries")


# ---------------------------------------------------------------------------
# Claude (Opus/Sonnet) provider
# ---------------------------------------------------------------------------


async def _call_claude_async(
    prompt: str, schema: dict, *, model: str, timeout: int
) -> dict:
    """Call `claude -p` to produce JSON matching *schema*. Returns the
    `structured_output` dict from the response envelope on success.

    Claude tolerates loose JSON schemas (no strict-mode rewriting needed).
    """
    clean_schema = {k: v for k, v in schema.items() if k != "$schema"}
    schema_str = json.dumps(clean_schema)

    last_error = None
    for attempt in range(2):
        if attempt > 0:
            await asyncio.sleep(min(2 ** attempt, 4))

        proc = await _spawn(
            "claude", "-p",
            "--tools", "",
            "--output-format", "json",
            "--json-schema", schema_str,
            "--model", model,
            "--no-session-persistence",
            stdin=_PIPE,
            stdout=_PIPE,
            stderr=_PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=prompt.encode("utf-8")),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            last_error = f"claude -p timed out after {timeout}s"
            continue

        if proc.returncode != 0:
            stderr_text = stderr.decode("utf-8", errors="replace").strip()
            stderr_lower = stderr_text.lower()
            if any(sig in stderr_lower for sig in _UNAVAILABLE_SIGNALS):
                raise ModelUnavailableError(
                    f"{model} unavailable: {stderr_text[:400]}"
                )
            last_error = (
                f"claude -p failed (rc={proc.returncode}): {stderr_text[:400]}"
            )
            continue

        try:
            response = json.loads(stdout.decode("utf-8", errors="replace"))
        except json.JSONDecodeError as exc:
            last_error = f"claude -p returned invalid JSON: {exc}"
            continue

        if response.get("is_error"):
            last_error = (
                f"claude -p reported error: {response.get('result', '')[:200]}"
            )
            continue

        structured = response.get("structured_output")
        if structured is None:
            last_error = (
                f"claude -p returned no structured_output: "
                f"{response.get('result', '')[:200]}"
            )
            continue

        return structured

    raise LLMError(last_error or "unknown claude error after retries")
