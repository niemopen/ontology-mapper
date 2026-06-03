#!/usr/bin/env python3
"""Automated pipeline runner — executes mechanical stages without LLM orchestration.

Stages 1-4 and 6-8 are purely mechanical command sequences. Stage 5 is an
interactive review loop: it presents pending items, reads user input, uses
``claude -p`` to interpret the input into structured actions, and executes
them until no pending items remain.

Usage:
    python runner_tools/run_pipeline.py \
        --organization redvale --source dbpi \
        --input-package-path sources/redvale_dbpi_agency_package \
        --target-ontology niem --target-version 6.0
"""

import argparse
import io
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from runner_tools.verify_stage_outputs import verify
from runner_tools._present_and_apply_human_review import (
    load_inputs as review_load_inputs,
    get_pending_items,
    group_by_action,
    format_review_item,
    format_property_review,
    apply_accept,
    apply_all_property_accepts,
    apply_decision_with_cascade,
    apply_property_decision,
    load_cascade_context,
    save_matrix,
    validate_class_decision,
    validate_property_decision,
    _cmd_present,
)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class StageError(Exception):
    """A pipeline stage failed."""

    def __init__(self, stage: str, message: str):
        self.stage = stage
        super().__init__(f"Stage {stage}: {message}")


class VerificationError(StageError):
    """Post-stage verification found errors."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@dataclass
class StageTimer:
    """Tracks wall-clock time for a pipeline stage."""
    stage: str
    start: float = 0.0
    elapsed: float = 0.0

    def __enter__(self):
        self.start = time.monotonic()
        return self

    def __exit__(self, *exc):
        self.elapsed = time.monotonic() - self.start

    @property
    def formatted(self) -> str:
        if self.elapsed < 60:
            return f"{self.elapsed:.1f}s"
        minutes = int(self.elapsed // 60)
        seconds = self.elapsed % 60
        return f"{minutes}m {seconds:.0f}s"


def run_cmd(stage: str, cmd: list[str], cwd: str | None = None) -> str:
    """Run a subprocess command and return its stdout.

    Raises StageError on non-zero exit.
    """
    print(f"    $ {' '.join(cmd)}")
    result = subprocess.run(
        cmd, capture_output=True, text=True, cwd=cwd,
        encoding="utf-8", errors="replace",
    )
    if result.stdout:
        for line in result.stdout.rstrip().split("\n"):
            print(f"      {line}")
    if result.returncode != 0:
        stderr = result.stderr.strip() if result.stderr else "(no stderr)"
        raise StageError(stage, f"Command failed (rc={result.returncode}): {' '.join(cmd)}\n{stderr}")
    return result.stdout


def verify_stage(run_dir: Path, stage: str) -> dict:
    """Run verification checks and raise on error-severity failures."""
    result = verify(run_dir, stage)
    if "error" in result:
        raise VerificationError(stage, result["error"])

    summary = result["summary"]
    print(f"    Verify {stage}: {summary['pass']} pass, {summary['fail']} fail, {summary['warn']} warn")

    if summary["fail"] > 0:
        failed = [c for c in result["checks"] if c["status"] == "fail" and c["severity"] == "error"]
        details = "\n".join(f"  - [{c['checkId']}] {c['message']}" for c in failed)
        raise VerificationError(stage, f"{summary['fail']} error(s):\n{details}")

    return result


def load_state(run_dir: Path) -> dict:
    """Load .mapper-state.json from a run directory."""
    state_path = run_dir / ".mapper-state.json"
    if not state_path.exists():
        raise FileNotFoundError(f"State file not found: {state_path}")
    return json.loads(state_path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Stage 5: Interactive Review Loop
# ---------------------------------------------------------------------------

# JSON schema for claude -p structured output — constrains the LLM's
# interpretation of user natural language to valid review actions.
REVIEW_ACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": [
                "approve", "approve_all", "detail",
                "change_target", "resolve_property", "search",
            ],
        },
        "concept": {
            "type": "string",
            "description": "sourceConcept qname or local name (required for approve, detail, change_target, resolve_property)",
        },
        "new_target_type": {
            "type": "string",
            "description": "New target type qname (required for change_target)",
        },
        "source_property": {
            "type": "string",
            "description": "Source property name (required for resolve_property)",
        },
        "property_action": {
            "type": "string",
            "enum": ["reuse-property", "create-property"],
            "description": "Action for the property (required for resolve_property)",
        },
        "target_property": {
            "type": "string",
            "description": "Target property qname (optional, for resolve_property with reuse-property)",
        },
        "query": {
            "type": "string",
            "description": "Search string (required for search)",
        },
        "search_kind": {
            "type": "string",
            "enum": ["type", "property", "both"],
            "description": "What to search for (optional for search, default: both)",
        },
    },
    "required": ["action"],
    "additionalProperties": False,
}


def _build_review_prompt(pending_summary: str, user_input: str) -> str:
    """Build the prompt for claude -p to interpret user review input.

    The LLM's job is pure NLU: map the user's natural language to a
    structured action. It does NOT do semantic reasoning — that was
    already done at Stage 3.
    """
    return f"""You are interpreting a human reviewer's natural language input during
Stage 5 of the OntologyMapper pipeline. The reviewer is looking at a mapping
matrix and making decisions about how source concepts should map to target types.

Current pending review items:
{pending_summary}

Available actions:
- approve: Accept a single concept's current recommendation. Requires: concept.
- approve_all: Accept ALL pending concepts as-is. No parameters. Only valid when
  no human-must-decide properties remain.
- detail: Show full detail for a concept (rationale + properties). Requires: concept.
- change_target: Change which target type a concept maps to. This triggers
  reclassification (reuse/augment/extend re-evaluated). Requires: concept, new_target_type.
- resolve_property: Resolve a single property mapping (especially human-must-decide).
  Requires: concept, source_property, property_action. Optional: target_property
  (required when property_action is reuse-property).
- search: Search the target catalog for types or properties. Requires: query.
  Optional: search_kind (type, property, or both).

The reviewer said:
"{user_input}"

Interpret their intent as a single structured action. If the concept name they
mention is ambiguous, use the best match from the pending items. If they reference
a concept by local name (without namespace prefix), match it against the pending
items list."""


def _call_claude_interpret(prompt: str) -> dict:
    """Call claude -p to interpret user input into a structured review action.

    Uses --json-schema to constrain output to REVIEW_ACTION_SCHEMA.
    Returns the parsed action dict.
    """
    schema_str = json.dumps(REVIEW_ACTION_SCHEMA)
    result = subprocess.run(
        [
            "claude", "-p",
            "--tools", "",
            "--output-format", "json",
            "--json-schema", schema_str,
            "--model", "sonnet",
            "--no-session-persistence",
        ],
        input=prompt,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        stderr = result.stderr.strip() if result.stderr else "(no stderr)"
        raise StageError("5", f"claude -p failed (rc={result.returncode}): {stderr}")

    response = json.loads(result.stdout)
    action = response.get("structured_output")
    if action is None:
        raise StageError("5", f"claude -p returned no structured_output: {result.stdout[:200]}")
    return action


def _resolve_concept(pending: list, concept_ref: str) -> dict | None:
    """Find a pending entry by exact qname or local name suffix match."""
    # Exact match
    for entry in pending:
        if entry["sourceConcept"] == concept_ref:
            return entry
    # Suffix match (user typed local name without prefix)
    suffix = f":{concept_ref}"
    matches = [e for e in pending if e["sourceConcept"].endswith(suffix)]
    if len(matches) == 1:
        return matches[0]
    # Also try case-insensitive suffix match
    suffix_lower = suffix.lower()
    matches = [e for e in pending if e["sourceConcept"].lower().endswith(suffix_lower)]
    if len(matches) == 1:
        return matches[0]
    return None


def _build_pending_summary(pending: list) -> str:
    """Build a compact summary of pending items for the LLM prompt."""
    lines = []
    groups = group_by_action(pending)
    for action_key, label, items in groups:
        lines.append(f"\n{label} ({len(items)}):")
        for entry in items:
            concept = entry["sourceConcept"]
            target = entry.get("targetType") or "(none)"
            props = entry.get("propertyMappings") or []
            must_decide = sum(1 for p in props if p.get("action") == "human-must-decide"
                              and p.get("reviewStatus") == "pending-review")
            prop_note = ""
            if must_decide:
                prop_note = f"  [{must_decide} UNDECIDED properties]"
            elif props:
                prop_note = f"  [{len(props)} properties]"
            lines.append(f"  {concept} -> {target}{prop_note}")
    return "\n".join(lines)


def _dispatch_review_action(
    action: dict,
    run_dir: Path,
    matrix: dict,
    dec_log: dict,
    pending: list,
    cascade_context: tuple | None,
) -> tuple[str, list, tuple | None]:
    """Execute a parsed review action against the matrix.

    Returns (message, applied_decisions, cascade_context).
    cascade_context is lazily loaded on first change_target call.
    """
    action_type = action["action"]
    applied = []

    if action_type == "approve":
        concept_ref = action.get("concept", "")
        entry = _resolve_concept(pending, concept_ref)
        if not entry:
            return f"Concept not found: {concept_ref}", applied, cascade_context
        apply_accept(entry)
        accepted, skipped = apply_all_property_accepts(entry)
        applied.append({
            "sourceConcept": entry["sourceConcept"],
            "action": entry["action"],
            "targetType": entry.get("targetType"),
            "confidence": "confident",
            "notes": "Approved",
        })
        msg = f"Approved: {entry['sourceConcept']} ({entry['action']})"
        if skipped:
            msg += f"\n  *** {skipped} human-must-decide properties NOT approved — resolve individually ***"
        return msg, applied, cascade_context

    elif action_type == "approve_all":
        # Check for human-must-decide blockers
        must_decide = sum(
            1 for e in pending
            for p in (e.get("propertyMappings") or [])
            if p.get("action") == "human-must-decide"
            and p.get("reviewStatus") == "pending-review"
        )
        if must_decide:
            return (f"Cannot approve-all: {must_decide} human-must-decide properties "
                    f"must be resolved individually first."), applied, cascade_context
        for entry in pending:
            apply_accept(entry)
            apply_all_property_accepts(entry)
            applied.append({
                "sourceConcept": entry["sourceConcept"],
                "action": entry["action"],
                "targetType": entry.get("targetType"),
                "confidence": "confident",
                "notes": "Approved",
            })
        return f"Approved all {len(applied)} pending concepts.", applied, cascade_context

    elif action_type == "detail":
        concept_ref = action.get("concept", "")
        entry = _resolve_concept(pending, concept_ref)
        if not entry:
            # Also check all mappings (not just pending)
            for m in matrix["mappings"]:
                if m["sourceConcept"] == concept_ref or m["sourceConcept"].endswith(f":{concept_ref}"):
                    entry = m
                    break
        if not entry:
            return f"Concept not found: {concept_ref}", applied, cascade_context
        detail = format_review_item(entry)
        prop_detail = format_property_review(entry)
        msg = f"\n{entry['sourceConcept']}\n{detail}"
        if prop_detail:
            msg += f"\n{prop_detail}"
        return msg, applied, cascade_context

    elif action_type == "change_target":
        concept_ref = action.get("concept", "")
        new_target = action.get("new_target_type", "")
        entry = _resolve_concept(pending, concept_ref)
        if not entry:
            return f"Concept not found: {concept_ref}", applied, cascade_context
        if not new_target:
            return "change_target requires new_target_type", applied, cascade_context

        # Lazy-load cascade context
        if cascade_context is None:
            cascade_context = load_cascade_context(run_dir)
        target_ontology, catalog = cascade_context

        old_action = entry["action"]
        old_target = entry.get("targetType")
        decision = {"targetType": new_target}
        apply_decision_with_cascade(entry, decision, target_ontology, catalog)

        # Validate after cascade
        issues = validate_class_decision(entry)

        applied.append({
            "sourceConcept": entry["sourceConcept"],
            "action": entry["action"],
            "targetType": entry.get("targetType"),
            "confidence": entry.get("confidence", "confident"),
            "notes": f"Target changed from {old_target} to {new_target}",
        })

        msg = (f"Changed target: {entry['sourceConcept']}\n"
               f"  {old_action} {old_target} -> {entry['action']} {entry.get('targetType')}")
        if issues:
            msg += "\n  Validation issues:\n" + "\n".join(f"    - {i}" for i in issues)
        return msg, applied, cascade_context

    elif action_type == "resolve_property":
        concept_ref = action.get("concept", "")
        src_prop = action.get("source_property", "")
        prop_action = action.get("property_action", "")
        target_prop = action.get("target_property")

        entry = _resolve_concept(pending, concept_ref)
        if not entry:
            return f"Concept not found: {concept_ref}", applied, cascade_context
        if not src_prop:
            return "resolve_property requires source_property", applied, cascade_context
        if not prop_action:
            return "resolve_property requires property_action", applied, cascade_context

        decision = {"action": prop_action}
        if target_prop:
            decision["targetProperty"] = target_prop

        found = apply_property_decision(entry, src_prop, decision)
        if not found:
            return f"Property not found: {src_prop} on {entry['sourceConcept']}", applied, cascade_context

        # Validate
        prop = next((p for p in (entry.get("propertyMappings") or [])
                      if p["sourceProperty"] == src_prop), None)
        issues = validate_property_decision(prop) if prop else []

        applied.append({
            "sourceConcept": entry["sourceConcept"],
            "action": entry["action"],
            "targetType": entry.get("targetType"),
            "confidence": "confident",
            "notes": f"Property {src_prop} resolved as {prop_action}",
        })

        msg = f"Resolved: {entry['sourceConcept']}.{src_prop} -> {prop_action}"
        if target_prop:
            msg += f" ({target_prop})"
        if issues:
            msg += "\n  Validation issues:\n" + "\n".join(f"    - {i}" for i in issues)
        return msg, applied, cascade_context

    elif action_type == "search":
        query = action.get("query", "")
        if not query:
            return "search requires a query", applied, cascade_context
        kind = action.get("search_kind")
        if kind == "both":
            kind = None

        from ontology_mapper.catalog_search import (
            search_catalog,
            format_type_results,
            format_property_results,
        )
        if cascade_context is None:
            cascade_context = load_cascade_context(run_dir)
        _, catalog = cascade_context

        results = search_catalog(catalog, query, kind=kind)
        parts = []
        if results["types"]:
            parts.append(format_type_results(results["types"]))
        if results["properties"]:
            parts.append(format_property_results(results["properties"]))
        if not parts:
            return f"No results for '{query}'.", applied, cascade_context
        return "\n".join(parts), applied, cascade_context

    return f"Unknown action: {action_type}", applied, cascade_context


def run_stage_5_loop(run_dir: Path) -> list:
    """Interactive Stage 5 review loop.

    Presents pending items, reads user input, interprets via claude -p,
    executes the action, and repeats until no pending items remain.

    Returns the list of all applied decisions.
    """
    # Use argparse.Namespace to satisfy _cmd_present's interface
    import types
    present_args = types.SimpleNamespace(run_dir=str(run_dir))

    _, matrix, dec_log = review_load_inputs(run_dir)
    all_applied = []
    cascade_context = None

    # Initial presentation
    pending = get_pending_items(matrix)
    if not pending:
        print("  No items pending review — Stage 5 already complete.")
        return all_applied

    _cmd_present(present_args)

    while True:
        pending = get_pending_items(matrix)
        if not pending:
            print("\n  All items reviewed — Stage 5 complete.")
            break

        # Read user input
        try:
            user_input = input("\n  Review> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  Review interrupted.")
            # Save progress before exiting
            if all_applied:
                save_matrix(run_dir, matrix, dec_log, all_applied)
                print(f"  Saved {len(all_applied)} decisions before exit.")
            raise StageError("5", "Review interrupted by user")

        if not user_input:
            continue

        # Build prompt and call claude -p for interpretation
        pending_summary = _build_pending_summary(pending)
        prompt = _build_review_prompt(pending_summary, user_input)
        print("  (interpreting...)")
        action = _call_claude_interpret(prompt)

        # Dispatch the action
        message, applied, cascade_context = _dispatch_review_action(
            action, run_dir, matrix, dec_log, pending, cascade_context,
        )
        print(f"\n  {message}")

        # Accumulate decisions and save after each change
        if applied:
            all_applied.extend(applied)
            save_matrix(run_dir, matrix, dec_log, applied)
            # Refresh pending count
            remaining = get_pending_items(matrix)
            print(f"  ({len(remaining)} concepts still pending)")

    return all_applied


# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------

def preflight(input_package_path: str, target_ontology: str, target_version: str):
    """Validate prerequisites before starting the pipeline.

    Checks:
    1. Reference catalog exists for target ontology/version
    2. Vector index exists (needed for om-batch-search)
    3. Input package path exists and is a directory
    4. Key Python dependencies are importable
    """
    errors = []

    # 1. Reference catalog
    try:
        from ontology_mapper.build_strategy_reports import resolve_catalog_path
        catalog_path = resolve_catalog_path(target_ontology, target_version)
        if catalog_path is None:
            errors.append(f"Reference catalog not found for {target_ontology} {target_version}.")
    except ImportError:
        errors.append("ontology-mapper package not installed.")

    # 2. Vector index
    try:
        from ontology_mapper.vector_index import index_exists
        index_name = f"{target_ontology}-{target_version}"
        if not index_exists(index_name, "types"):
            errors.append(f"Vector index not found for {index_name}. "
                          "Run om-build-vector-index first.")
    except (ImportError, Exception) as e:
        errors.append(f"Cannot check vector index: {e}")

    # 3. Input package
    pkg = Path(input_package_path)
    if not pkg.exists():
        errors.append(f"Input package path not found: {input_package_path}")
    elif not pkg.is_dir():
        errors.append(f"Input package path is not a directory: {input_package_path}")

    # 4. Key dependencies
    for mod_name in ("rdflib", "faiss"):
        try:
            __import__(mod_name)
        except ImportError:
            errors.append(f"Python module '{mod_name}' not installed.")

    if errors:
        raise StageError("preflight", "Pre-flight checks failed:\n" + "\n".join(f"  - {e}" for e in errors))

    print("  Pre-flight checks passed.")


# ---------------------------------------------------------------------------
# Stage functions
# ---------------------------------------------------------------------------

def run_stage_1(run_dir: Path, timers: list[StageTimer]):
    """Stage 1: Ingest — auto-marks complete via pipeline handler."""
    with StageTimer("1") as t:
        run_cmd("1", ["om-pipeline", "rerun", "--stage", "1", "--run-dir", str(run_dir)])
        verify_stage(run_dir, "1")
    timers.append(t)


def run_stage_2(run_dir: Path, input_package_path: str, timers: list[StageTimer]):
    """Stage 2: Extract — branches on input_type (owl vs csv)."""
    with StageTimer("2") as t:
        state = load_state(run_dir)
        input_type = state.get("inputs", {}).get("input_type", "owl")

        if input_type == "owl":
            run_cmd("2", ["om-extract", "--run-dir", str(run_dir),
                          "--package", input_package_path])
        else:
            # CSV path: requires namespace info from state
            inputs = state.get("inputs", {})
            csv_path = inputs.get("csv_path", input_package_path)
            ns = inputs.get("namespace", "src")
            ns_uri = inputs.get("namespace_uri", "http://example.org/source#")
            run_cmd("2", ["om-ingest-csv", csv_path,
                          "--run-dir", str(run_dir),
                          "--namespace", ns, "--namespace-uri", ns_uri])

        verify_stage(run_dir, "2")
        run_cmd("2", ["om-pipeline", "mark-complete", "--stage", "2", "--run-dir", str(run_dir)])
    timers.append(t)


def run_stage_3(run_dir: Path, timers: list[StageTimer]):
    """Stage 3: Align — 5 commands in sequence."""
    with StageTimer("3") as t:
        run_cmd("3", ["om-build-strategy", "--run-dir", str(run_dir)])
        run_cmd("3", ["om-batch-search", "--run-dir", str(run_dir)])
        run_cmd("3", ["om-entropy", "--run-dir", str(run_dir)])
        run_cmd("3", ["om-orchestrate-eval", "--run-dir", str(run_dir)])
        run_cmd("3", ["om-collect-alignments", "--run-dir", str(run_dir)])
        verify_stage(run_dir, "3")
        run_cmd("3", ["om-pipeline", "mark-complete", "--stage", "3", "--run-dir", str(run_dir)])
    timers.append(t)


def run_stage_4(run_dir: Path, timers: list[StageTimer]):
    """Stage 4: Decide — build matrix + generation audit."""
    with StageTimer("4") as t:
        run_cmd("4", ["om-build-matrix", "--run-dir", str(run_dir)])
        run_cmd("4", ["om-generation-audit", "--run-dir", str(run_dir)])
        verify_stage(run_dir, "4")
        run_cmd("4", ["om-pipeline", "mark-complete", "--stage", "4", "--run-dir", str(run_dir)])
    timers.append(t)


def run_stage_5(run_dir: Path, timers: list[StageTimer]):
    """Stage 5: Interactive human review loop + post-review completion."""
    from runner_tools._present_and_apply_human_review import complete_stage_5

    with StageTimer("5") as t:
        run_stage_5_loop(run_dir)
        verify_stage(run_dir, "5")
        success, error = complete_stage_5(run_dir)
        if not success:
            raise StageError("5", error)
    timers.append(t)


def run_stage_6(run_dir: Path, timers: list[StageTimer]):
    """Stage 6: Generate — bootstrap dirs, then 3 sub-stages."""
    with StageTimer("6") as t:
        # Bootstrap edge-package directory structure
        run_cmd("6", ["om-pipeline", "rerun", "--stage", "6", "--run-dir", str(run_dir)])
        # Generate ontology artifacts
        run_cmd("6", ["om-generate-ontology", "--run-dir", str(run_dir)])
        verify_stage(run_dir, "6a")
        # Package artifacts
        run_cmd("6", ["om-package-artifacts", "--run-dir", str(run_dir)])
        verify_stage(run_dir, "6b")
        # Generate knowledge graph
        run_cmd("6", ["om-generate-kg", "--run-dir", str(run_dir)])
        verify_stage(run_dir, "6c")
        run_cmd("6", ["om-pipeline", "mark-complete", "--stage", "6", "--run-dir", str(run_dir)])
    timers.append(t)


def run_stage_7(run_dir: Path, timers: list[StageTimer]):
    """Stage 7: Validate — run validation + feedback report."""
    with StageTimer("7") as t:
        run_cmd("7", ["om-validate", "--run-dir", str(run_dir)])
        run_cmd("7", ["python", "runner_tools/feedback_report.py",
                       "--run-dir", str(run_dir)])
        verify_stage(run_dir, "7")
        run_cmd("7", ["om-pipeline", "mark-complete", "--stage", "7", "--run-dir", str(run_dir)])
    timers.append(t)


def run_stage_8(run_dir: Path, timers: list[StageTimer]):
    """Stage 8: Finalize — package and mark complete."""
    with StageTimer("8") as t:
        run_cmd("8", ["om-finalize", "--run-dir", str(run_dir)])
        verify_stage(run_dir, "8")
        run_cmd("8", ["om-pipeline", "mark-complete", "--stage", "8", "--run-dir", str(run_dir)])
    timers.append(t)


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def _read_json(path: Path) -> dict | None:
    """Read a JSON file, returning None if it doesn't exist."""
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _stage_metric(run_dir: Path, stage: str) -> str:
    """Extract a one-line metric string for a completed stage."""
    if stage == "1":
        inv = _read_json(run_dir / "source-inventory.json")
        if inv:
            files = inv.get("total_files", 0)
            input_type = inv.get("input_type", "?")
            return f"{files} files, type: {input_type}"
    elif stage == "2":
        inv = _read_json(run_dir / "concept-inventory.json")
        if inv:
            s = inv.get("summary", {})
            classes = s.get("classCount", "?")
            obj = s.get("objectPropertyCount", 0)
            dt = s.get("datatypePropertyCount", 0)
            return f"{classes} classes, {obj + dt} properties"
    elif stage == "3":
        rpt = _read_json(run_dir / "alignment-report.json")
        if rpt:
            entries = rpt.get("entries", [])
            total_props = sum(len(e.get("properties", [])) for e in entries)
            by_action = {}
            for e in entries:
                a = e.get("action", "?")
                by_action[a] = by_action.get(a, 0) + 1
            action_parts = ", ".join(f"{v} {k}" for k, v in sorted(by_action.items()))
            return f"{len(entries)} types ({action_parts}), {total_props} properties"
    elif stage == "4":
        mx = _read_json(run_dir / "mapping-matrix.json")
        if mx:
            counts = mx.get("summary", {}).get("actionCounts", {})
            parts = [f"{v} {k}" for k, v in sorted(counts.items())]
            return ", ".join(parts) if parts else "matrix built"
    elif stage == "5":
        mx = _read_json(run_dir / "mapping-matrix.json")
        if mx:
            pending = [m for m in mx.get("mappings", [])
                       if m.get("reviewStatus") == "pending-review" and m.get("action") != "exclude"]
            accepted = sum(1 for m in mx.get("mappings", []) if m.get("reviewStatus") == "accepted")
            if not pending:
                return f"{accepted} concepts reviewed"
            return f"{len(pending)} pending, {accepted} accepted"
        return "Human review"
    elif stage == "6":
        ep = run_dir / "edge-package"
        if ep.is_dir():
            count = sum(1 for _ in ep.rglob("*") if _.is_file())
            return f"{count} files generated"
    elif stage == "7":
        vr = _read_json(run_dir / "validation-report.json")
        if vr:
            passed = vr.get("passCount", "?")
            failed = vr.get("failCount", "?")
            return f"{passed} pass, {failed} fail"
    elif stage == "8":
        mf = _read_json(run_dir / "edge-package" / "package-manifest.json")
        if mf:
            status = mf.get("status", "ready")
            return f"status: {status}"
    return ""


def print_summary(run_dir: Path, timers: list[StageTimer], final_stage: str):
    """Print the pipeline run summary table."""
    all_stages = ["1", "2", "3", "4", "5", "6", "7", "8"]
    timer_map = {}
    for t in timers:
        # Merge sub-stage timers (5-present, 5-complete) under parent
        parent = t.stage.split("-")[0]
        if parent in timer_map:
            timer_map[parent] = StageTimer(parent, elapsed=timer_map[parent].elapsed + t.elapsed)
        else:
            timer_map[parent] = t

    state = load_state(run_dir)
    stages_status = state.get("stages", {})

    total_elapsed = sum(t.elapsed for t in timer_map.values())

    print("\n" + "=" * 64)
    print(f"  Pipeline Run: {run_dir.name}")
    print("=" * 64)
    print(f"  {'Stage':<7} {'Status':<14} {'Time':<9} Metric")
    print(f"  {'-----':<7} {'---------':<14} {'------':<9} {'---' * 11}")

    for s in all_stages:
        stage_data = stages_status.get(s, {})
        status = stage_data.get("status", "-")
        if s == final_stage and status != "completed":
            status = "STOPPED"

        timer = timer_map.get(s)
        time_str = timer.formatted if timer else "-"
        metric = _stage_metric(run_dir, s)

        print(f"  {s:<7} {status:<14} {time_str:<9} {metric}")

    print(f"  {'-----':<7} {'---------':<14} {'------':<9} {'---' * 11}")
    total_fmt = StageTimer("total", elapsed=total_elapsed).formatted
    stage_range = f"Stages 1-{final_stage.split('-')[0]}"
    print(f"  {'Total':<7} {'':<14} {total_fmt:<9} {stage_range}")
    print(f"\n  Run dir: {run_dir}")

    # Coherence data for completed runs
    if final_stage == "8":
        cm = _read_json(run_dir / "edge-package" / "governance" / "coherence-manifest.json")
        if cm:
            entropy = cm.get("entropy", {})
            print(f"\n  Entropy: {entropy.get('preTotal', '?')} pre -> "
                  f"{entropy.get('residualTotal', '?')} residual")
        vr = _read_json(run_dir / "validation-report.json")
        if vr:
            print(f"  Validation: {vr.get('passCount', '?')}/{vr.get('checkCount', '?')} checks pass")

    print("=" * 64)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_pipeline(
    organization: str | None = None,
    source: str | None = None,
    input_package_path: str | None = None,
    target_ontology: str = "niem",
    target_version: str = "6.0",
    run_dir: str | None = None,
    from_stage: int = 1,
):
    """Run the pipeline from from_stage through completion.

    Stage 5 is interactive: the pipeline presents review items, reads user
    input, interprets it via claude -p, and loops until all items are reviewed.

    If run_dir is provided, resumes an existing run from from_stage.
    Otherwise creates a new run (requires organization, source, input_package_path).
    """
    timers: list[StageTimer] = []

    if run_dir:
        # Resume mode
        rd = Path(run_dir)
        if not rd.exists():
            raise StageError("init", f"Run directory not found: {run_dir}")
        state = load_state(rd)
        input_package_path = state.get("inputs", {}).get("input_package_path", "")
        print(f"\n  Resuming pipeline: {rd.name}")
        print(f"  From stage: {from_stage}")
    else:
        # New run mode
        if not all([organization, source, input_package_path]):
            raise StageError("init", "New run requires --organization, --source, and --input-package-path")

        print(f"\n  Starting new pipeline run")
        print(f"  Organization: {organization}")
        print(f"  Source: {source}")
        print(f"  Target: {target_ontology} {target_version}")

        preflight(input_package_path, target_ontology, target_version)

        # Initialize pipeline
        run_cmd("init", [
            "om-pipeline",
            "--organization", organization,
            "--source", source,
            "--input-package-path", input_package_path,
            "--target-ontology", target_ontology,
            "--target-version", target_version,
        ])

        # Find the newly created run directory
        runs_root = Path(".mapper-runs")
        candidates = sorted(runs_root.glob(f"{organization}_*"), key=lambda p: p.name, reverse=True)
        if not candidates:
            raise StageError("init", "Pipeline init succeeded but no run directory found")
        rd = candidates[0]
        print(f"  Run dir: {rd}")

    # Run stages in order — final_stage tracks progress for summary on failure
    final_stage = str(from_stage)
    try:
        if from_stage <= 1:
            print("\n  --- Stage 1: Ingest ---")
            run_stage_1(rd, timers)
            final_stage = "1"

        if from_stage <= 2:
            print("\n  --- Stage 2: Extract ---")
            run_stage_2(rd, input_package_path, timers)
            final_stage = "2"

        if from_stage <= 3:
            print("\n  --- Stage 3: Align ---")
            run_stage_3(rd, timers)
            final_stage = "3"

        if from_stage <= 4:
            print("\n  --- Stage 4: Decide ---")
            run_stage_4(rd, timers)
            final_stage = "4"

        if from_stage <= 5:
            print("\n  --- Stage 5: Human Review ---")
            run_stage_5(rd, timers)
            final_stage = "5"

        if from_stage <= 6:
            print("\n  --- Stage 6: Generate ---")
            run_stage_6(rd, timers)
            final_stage = "6"

        if from_stage <= 7:
            print("\n  --- Stage 7: Validate ---")
            run_stage_7(rd, timers)
            final_stage = "7"

        if from_stage <= 8:
            print("\n  --- Stage 8: Finalize ---")
            run_stage_8(rd, timers)
            final_stage = "8"

        print_summary(rd, timers, final_stage)
        print("\n  Pipeline complete.")

    except StageError as e:
        final_stage = e.stage
        print(f"\n  FAILED at Stage {e.stage}: {e}")
        print_summary(rd, timers, final_stage)
        raise


def main():
    # Ensure UTF-8 output on Windows
    if sys.stdout.encoding != "utf-8":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    if sys.stderr.encoding != "utf-8":
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description="Automated pipeline runner — runs mechanical stages without LLM orchestration"
    )

    # New run arguments
    parser.add_argument("--organization", help="Organization name (new run)")
    parser.add_argument("--source", help="Source name (new run)")
    parser.add_argument("--input-package-path", help="Path to input package (new run)")
    parser.add_argument("--target-ontology", default="niem", help="Target ontology (default: niem)")
    parser.add_argument("--target-version", default="6.0", help="Target version (default: 6.0)")

    # Resume arguments
    parser.add_argument("--run-dir", help="Existing run directory (resume after failure)")
    parser.add_argument("--from-stage", type=int, default=1, help="Stage to resume from after failure (default: 1)")

    args = parser.parse_args()

    # Validate: either --run-dir (resume) or --organization+--source+--input-package-path (new)
    if args.run_dir:
        if args.from_stage < 1 or args.from_stage > 8:
            parser.error("--from-stage must be between 1 and 8")
    elif not args.organization or not args.source or not args.input_package_path:
        parser.error("New run requires --organization, --source, and --input-package-path")

    try:
        run_pipeline(
            organization=args.organization,
            source=args.source,
            input_package_path=args.input_package_path,
            target_ontology=args.target_ontology,
            target_version=args.target_version,
            run_dir=args.run_dir,
            from_stage=args.from_stage,
        )
    except StageError as e:
        print(f"\n  ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
