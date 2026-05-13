#!/usr/bin/env python3
"""Stage 5: Human review — load, present, apply, and save review decisions.

Decisions are stored in `human-review-decisions.json`. The pipeline runner
presents mapping entries grouped by action (reuse, extend, augment) and
the human approves, modifies, or rejects each one.

For the interactive review loop, ``run_pipeline.py`` imports and calls these
functions directly. The CLI subcommands (present, approve, approve-all, etc.)
are available for manual use outside the automated runner.
"""

import json
from pathlib import Path
from datetime import datetime, timezone

from ontology_mapper.run_dir_utils import resolve_run_dir

DECISIONS_FILENAME = "human-review-decisions.json"

# Class-level action groups, presented in this order during review
ACTION_GROUPS = [
    ("reuse", "Reuse — source concept maps to an existing target type"),
    ("augment", "Augment — add new properties directly to an existing target type"),
    ("extend", "Extend — new type required (no suitable target match)"),
]

PROPERTY_ACTION_LABELS = {
    "reuse-property": "Reuse target property",
    "create-property": "Create new property",
    "human-must-decide": "UNDECIDED — human must resolve",
}


# ---------------------------------------------------------------------------
# Input Resolution
# ---------------------------------------------------------------------------
def load_inputs(run_dir_arg):
    """Load matrix and decision log from a run directory.

    Args:
        run_dir_arg: path to the run directory (required).
    """
    run_dir = Path(run_dir_arg)

    matrix = json.loads((run_dir / "mapping-matrix.json").read_text(encoding="utf-8"))
    dec_log = json.loads((run_dir / "decision-log.json").read_text(encoding="utf-8"))
    return run_dir, matrix, dec_log


# ---------------------------------------------------------------------------
# Pending Review Extraction
# ---------------------------------------------------------------------------
def get_pending_items(matrix):
    """Return mapping entries that need human review, sorted by concept name.

    Excludes entries with action 'exclude' — those are not presented for review.
    """
    return sorted(
        [m for m in matrix["mappings"]
         if m["reviewStatus"] == "pending-review" and m["action"] != "exclude"],
        key=lambda m: m["sourceConcept"],
    )


# ---------------------------------------------------------------------------
# Review Item Presentation
# ---------------------------------------------------------------------------
def format_review_item(entry):
    """Format a single mapping entry for human review presentation.

    Returns a multi-line string summarizing the current recommendation.
    """
    concept = entry["sourceConcept"]
    action = entry["action"]
    target = entry.get("targetType") or "(none)"
    rationale = entry.get("rationale", "")

    lines = [
        f"  Concept:    {concept}",
        f"  Action:     {action}",
        f"  Target:     {target}",
    ]
    if rationale:
        lines.append(f"  Rationale:  {rationale[:150]}{'...' if len(rationale) > 150 else ''}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Property-Level Review
# ---------------------------------------------------------------------------
def get_pending_property_items(entry):
    """Return property mappings that need human review for a given class mapping.

    Returns a tuple of (reuse_props, create_props, must_decide_props) lists:
    - reuse_props: reuse-property (evaluator found a target match)
    - create_props: create-property (needs new extension property)
    - must_decide_props: human-must-decide (evaluator could not choose)
    """
    props = entry.get("propertyMappings") or []
    pending = [p for p in props if p.get("reviewStatus") == "pending-review"]

    reuse = [p for p in pending if p["action"] == "reuse-property"]
    create = [p for p in pending if p["action"] == "create-property"]
    must_decide = [p for p in pending if p["action"] == "human-must-decide"]

    return reuse, create, must_decide


def format_property_review(entry):
    """Format property mappings within a class mapping for human review.

    Args:
        entry: The class-level mapping entry (must have propertyMappings).

    Returns a multi-line string summarizing property decisions, grouped by
    action. Returns empty string if no propertyMappings exist.
    """
    props = entry.get("propertyMappings") or []
    if not props:
        return ""

    concept = entry["sourceConcept"]

    reuse_props, create_props, must_decide_props = get_pending_property_items(entry)
    decided = [p for p in props if p.get("reviewStatus") != "pending-review"]

    lines = [f"\n  Property mappings for {concept} ({len(props)} total):"]

    # UNDECIDED properties — presented first, prominently
    if must_decide_props:
        lines.append(f"\n    *** UNDECIDED — human must resolve ({len(must_decide_props)} properties) ***")
        for p in sorted(must_decide_props, key=lambda x: x["sourceProperty"]):
            src = p["sourceProperty"]
            src_def = p.get("sourceDefinition", "")
            rationale = p.get("rationale", "")
            lines.append(f"      {src}:")
            if src_def:
                lines.append(f"        Source def: {src_def[:120]}")
            if rationale:
                lines.append(f"        LLM note:   {rationale[:120]}")

    # Reuse properties (evaluator matched to target)
    if reuse_props:
        lines.append(f"\n    Reuse target property ({len(reuse_props)} properties):")
        for p in sorted(reuse_props, key=lambda x: x["sourceProperty"]):
            tgt = p.get("targetProperty", "?")
            src = p["sourceProperty"]
            rationale = p.get("rationale", "")
            lines.append(f"      {src} -> {tgt}")
            if rationale:
                lines.append(f"        {rationale[:120]}")

    # Create properties (need new extension property)
    if create_props:
        lines.append(f"\n    Create new property ({len(create_props)} properties):")
        for p in sorted(create_props, key=lambda x: x["sourceProperty"]):
            src = p["sourceProperty"]
            src_def = p.get("sourceDefinition", "")

            lines.append(f"      {src}:")
            if src_def:
                lines.append(f"        Source def: {src_def[:120]}")

    # Already decided (for reference)
    if decided:
        lines.append(f"\n    Already decided ({len(decided)} properties):")
        for p in sorted(decided, key=lambda x: x["sourceProperty"]):
            tgt = p.get("targetProperty") or "(new)"
            lines.append(f"      {p['sourceProperty']} -> {tgt}  [{p['action']}]")

    return "\n".join(lines)


def apply_property_decision(entry, source_property, decision):
    """Apply a human review decision to a single property mapping.

    Args:
        entry: The class-level mapping entry (must have propertyMappings).
        source_property: The sourceProperty name to update.
        decision: Dict with keys: action (reuse-property or create-property),
                  targetProperty (optional), notes (optional),
                  confidence (optional, defaults to "confident").

    Returns True if the property was found and updated, False otherwise.
    """
    for p in (entry.get("propertyMappings") or []):
        if p["sourceProperty"] == source_property:
            p["action"] = decision["action"]
            p["reviewStatus"] = "accepted"
            p["confidence"] = decision.get("confidence", "confident")
            p["confidenceExplicit"] = True
            if "targetProperty" in decision:
                p["targetProperty"] = decision["targetProperty"]
            if "targetDefinition" in decision:
                p["targetDefinition"] = decision["targetDefinition"]
            if "targetType" in decision:
                p["targetType"] = decision["targetType"]
            if "notes" in decision:
                p["notes"] = decision["notes"]
            return True
    return False


def apply_all_property_accepts(entry, confidence="confident"):
    """Accept all pending property mappings for a class entry.

    Skips human-must-decide properties — those cannot be bulk-accepted
    and must be resolved individually. Also cascades confidence to
    already-accepted properties that weren't explicitly set by the user.

    Returns (accepted_count, skipped_must_decide_count).
    """
    accepted = 0
    skipped = 0
    for p in (entry.get("propertyMappings") or []):
        if p.get("reviewStatus") == "pending-review":
            if p.get("action") == "human-must-decide":
                skipped += 1
            else:
                p["reviewStatus"] = "accepted"
                p["confidence"] = confidence
                accepted += 1
        elif p.get("reviewStatus") == "accepted" and not p.get("confidenceExplicit"):
            # Cascade type-level confidence to properties the user didn't explicitly set
            p["confidence"] = confidence
    return accepted, skipped


# ---------------------------------------------------------------------------
# Decision Application
# ---------------------------------------------------------------------------
def apply_decision(entry, decision):
    """Apply a single human review decision to a mapping entry.

    Args:
        entry: The mapping entry dict (mutated in place).
        decision: Dict with keys: action, targetType (optional),
                  notes (optional), confidence (optional, defaults
                  to "confident").
    """
    entry["action"] = decision["action"]
    entry["reviewStatus"] = "accepted"
    entry["ruleId"] = "human-review"
    entry["confidence"] = decision.get("confidence", "confident")
    if "targetType" in decision:
        entry["targetType"] = decision["targetType"]
    if "notes" in decision:
        entry["notes"] = decision["notes"]


def load_cascade_context(run_dir):
    """Load target_ontology and catalog for type-change cascades.

    Called lazily — only when a target type change is detected.

    Returns:
        (target_ontology, catalog) tuple.
    """
    from ontology_mapper.run_dir_utils import load_state
    from ontology_mapper.build_strategy_reports import resolve_catalog_path

    state = load_state(Path(run_dir))
    inputs = state.get("inputs", {})
    target_ontology = inputs.get("target_ontology", "")
    target_version = inputs.get("target_version", "")

    catalog_path = resolve_catalog_path(target_ontology, target_version)
    if catalog_path is None:
        raise FileNotFoundError(
            f"No reference catalog for {target_ontology} {target_version}"
        )
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    return target_ontology, catalog


def apply_decision_with_cascade(entry, decision, target_ontology, catalog):
    """Apply a human review decision, reclassifying if targetType changed.

    If the decision includes a targetType that differs from the entry's
    current targetType, the entry is fully reclassified: action recomputed,
    scaffolding rebuilt, review status reset. Otherwise falls back to
    simple apply_decision().

    Args:
        entry: The mapping entry dict (mutated in place).
        decision: Dict with keys: action, targetType (optional), notes.
        target_ontology: e.g. "niem", "sali-folio".
        catalog: Reference catalog dict.
    """
    old_target = entry.get("targetType")
    new_target = decision.get("targetType")

    if "targetType" in decision and new_target != old_target:
        from ontology_mapper.ontology_specific import (
            reclassify_for_target_type_change,
        )
        cascaded = reclassify_for_target_type_change(
            entry, new_target, target_ontology, catalog,
        )
        entry.clear()
        entry.update(cascaded)
        if "notes" in decision:
            entry["notes"] = decision["notes"]
    else:
        apply_decision(entry, decision)


def apply_accept(entry):
    """Accept the current recommendation as-is.

    Sets confidence to "confident" — accepting as-is implies confidence.
    """
    entry["reviewStatus"] = "accepted"
    entry["confidence"] = "confident"


# ---------------------------------------------------------------------------
# Decision Validation
# ---------------------------------------------------------------------------
def validate_class_decision(entry):
    """Check that a mapping entry is internally consistent after a decision.

    Returns a list of issue strings. Empty list means the entry is valid.
    Call this after apply_decision() to verify the change is complete.
    """
    issues = []
    action = entry.get("action")

    if action == "reuse":
        if not entry.get("targetType"):
            issues.append("reuse requires targetType")
        for key in ("extensionType", "baseType", "augmentationType", "augmentsType"):
            if entry.get(key):
                issues.append(f"reuse should not have {key}")

    elif action == "extend":
        if not entry.get("extensionType"):
            issues.append("extend requires extensionType")
        if not entry.get("baseType"):
            issues.append("extend requires baseType")
        for key in ("augmentationType", "augmentsType"):
            if entry.get(key):
                issues.append(f"extend should not have {key}")

    elif action == "augment":
        if not entry.get("targetType"):
            issues.append("augment requires targetType (the type being augmented)")
        if not entry.get("augmentationType"):
            issues.append("augment requires augmentationType")
        if not entry.get("augmentsType"):
            issues.append("augment requires augmentsType")
        for key in ("extensionType", "baseType"):
            if entry.get(key):
                issues.append(f"augment should not have {key}")

    return issues


def validate_property_decision(prop):
    """Check that a property mapping is internally consistent after a decision.

    Returns a list of issue strings. Empty list means the property is valid.
    Call this after apply_property_decision() to verify the change is complete.
    """
    issues = []
    action = prop.get("action")

    if action == "reuse-property":
        if not prop.get("targetProperty"):
            issues.append("reuse-property requires targetProperty")

    elif action == "create-property":
        pass  # no target needed

    elif action == "human-must-decide":
        issues.append(
            "human-must-decide: must be resolved to reuse-property or "
            "create-property before Stage 5 can complete"
        )

    else:
        issues.append(f"unknown property action: {action}")

    return issues


# ---------------------------------------------------------------------------
# Decision Saving
# ---------------------------------------------------------------------------
def save_decisions(run_dir, decisions):
    """Append human review decisions to the decisions file.

    This is an append-only log. Each call adds new entries with a
    ``reviewedAt`` timestamp. Multiple changes to the same concept
    produce multiple entries — replay in order for current state,
    read the log for full history.

    Args:
        run_dir: Path to the run directory.
        decisions: List of decision dicts, each with at minimum:
                   sourceConcept, action. Optional: targetType, notes.
    """
    path = run_dir / DECISIONS_FILENAME
    now = datetime.now(timezone.utc).isoformat()

    # Add reviewedAt to each new decision
    for d in decisions:
        if "reviewedAt" not in d:
            d["reviewedAt"] = now

    # Load existing decisions if file exists
    existing = []
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            existing = data.get("decisions", [])
        except (json.JSONDecodeError, OSError):
            existing = []

    combined = existing + decisions
    data = {
        "savedAt": now,
        "description": (
            "Human review decisions from Stage 5 (append-only log). "
            "Replay in order — later entries override earlier ones for "
            "the same concept."
        ),
        "decisions": combined,
    }
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Matrix Finalization
# ---------------------------------------------------------------------------
def recompute_summary(matrix):
    """Recompute the mapping matrix summary counts after applying decisions."""
    mappings = matrix["mappings"]
    action_counts = {}
    for m in mappings:
        action_counts[m["action"]] = action_counts.get(m["action"], 0) + 1

    accepted_mappings = [m for m in mappings if m["reviewStatus"] == "accepted"]
    summary = {
        "totalConcepts": len(mappings),
        "actionCounts": action_counts,
        "pendingReview": sum(1 for m in mappings if m["reviewStatus"] == "pending-review"),
        "accepted": len(accepted_mappings),
        "bestGuess": sum(1 for m in accepted_mappings if m.get("confidence") == "best-guess"),
    }

    # Recompute property-level stats if any mappings have propertyMappings
    all_props = [
        pm for m in mappings
        for pm in (m.get("propertyMappings") or [])
    ]
    if all_props:
        accepted_props = [p for p in all_props if p.get("reviewStatus") == "accepted"]
        summary["propertyStats"] = {
            "total": len(all_props),
            "reuseProperty": sum(1 for p in all_props if p["action"] == "reuse-property"),
            "createProperty": sum(1 for p in all_props if p["action"] == "create-property"),
            "humanMustDecide": sum(1 for p in all_props if p["action"] == "human-must-decide"),
            "pendingPropertyReview": sum(
                1 for p in all_props if p.get("reviewStatus") == "pending-review"
            ),
            "acceptedProperty": len(accepted_props),
            "bestGuessProperty": sum(
                1 for p in accepted_props if p.get("confidence") == "best-guess"
            ),
        }

    matrix["summary"] = summary
    return matrix["summary"]


def _snapshot_property_decisions(matrix, source_concept):
    """Extract decided property mappings from a matrix entry for persistence.

    Returns a list of property decision dicts (only those with reviewStatus
    "accepted"), or None if no property mappings exist.
    """
    for m in matrix["mappings"]:
        if m["sourceConcept"] == source_concept:
            props = m.get("propertyMappings") or []
            decided = [
                {
                    "sourceProperty": p["sourceProperty"],
                    "action": p["action"],
                    "targetProperty": p.get("targetProperty"),
                    "notes": p.get("notes"),
                    "confidence": p.get("confidence", "confident"),
                }
                for p in props if p.get("reviewStatus") == "accepted"
            ]
            return decided if decided else None
    return None


def save_matrix(run_dir, matrix, dec_log, applied_decisions):
    """Save the updated matrix, decision log, and decisions file.

    Args:
        run_dir: Path to the run directory.
        matrix: The mapping matrix dict (already mutated).
        dec_log: The decision log dict.
        applied_decisions: List of decision dicts that were applied.
    """
    matrix_path = run_dir / "mapping-matrix.json"
    log_path = run_dir / "decision-log.json"

    # Add human review decisions to decision log
    next_id = max((d["id"] for d in dec_log["decisions"]), default=0) + 1
    for decision in applied_decisions:
        entry = {
            "id": next_id,
            "sourceConcept": decision["sourceConcept"],
            "ruleId": "human-review",
            "action": decision["action"],
            "confidence": decision.get("confidence", "confident"),
            "rationale": decision.get("notes", "Human review decision"),
            "targetType": decision.get("targetType"),
            "notes": "Stage 5 human review decision",
        }
        # Embed property decisions from the matrix entry
        prop_decs = _snapshot_property_decisions(matrix, decision["sourceConcept"])
        if prop_decs:
            entry["propertyDecisions"] = prop_decs
        dec_log["decisions"].append(entry)
        next_id += 1

    # Enrich applied_decisions with property decisions for replay file
    for decision in applied_decisions:
        if "propertyDecisions" not in decision:
            prop_decs = _snapshot_property_decisions(matrix, decision["sourceConcept"])
            if prop_decs:
                decision["propertyDecisions"] = prop_decs

    # Recompute summary and finalize
    recompute_summary(matrix)
    matrix["humanReviewApplied"] = datetime.now(timezone.utc).isoformat()
    matrix["mappings"] = sorted(matrix["mappings"], key=lambda m: m["sourceConcept"])

    # Write files
    matrix_path.write_text(json.dumps(matrix, indent=2) + "\n", encoding="utf-8")
    dec_log["totalDecisions"] = len(dec_log["decisions"])
    log_path.write_text(json.dumps(dec_log, indent=2) + "\n", encoding="utf-8")

    # Save decisions for future runs
    save_decisions(run_dir, applied_decisions)

    return matrix["summary"]


# ---------------------------------------------------------------------------
# Grouping by Action
# ---------------------------------------------------------------------------
def group_by_action(pending_items):
    """Group pending review items by class-level action.

    Args:
        pending_items: List of mapping entries from get_pending_items().

    Returns:
        List of (action_key, label, items) tuples, ordered by ACTION_GROUPS.
        Items within each group are sorted by sourceConcept.
    """
    groups = {}
    for entry in pending_items:
        groups.setdefault(entry["action"], []).append(entry)

    result = []
    for key, label in ACTION_GROUPS:
        if key in groups:
            result.append((key, label, sorted(groups.pop(key), key=lambda m: m["sourceConcept"])))
    # Any remaining actions not in ACTION_GROUPS
    for key, items in sorted(groups.items()):
        result.append((key, f"Action: {key}", sorted(items, key=lambda m: m["sourceConcept"])))

    return result


# ---------------------------------------------------------------------------
# Stage 5 Completion (shared between CLI and web)
# ---------------------------------------------------------------------------
def check_stage_5_exit(matrix):
    """Check whether Stage 5 exit criteria are met.

    Returns (can_exit, blockers) where blockers is a list of strings
    describing what still needs resolution.
    """
    blockers = []
    pending = get_pending_items(matrix)
    if pending:
        blockers.append(f"{len(pending)} concepts still pending review")

    must_decide = []
    for entry in matrix.get("mappings", []):
        for prop in entry.get("propertyMappings", []):
            if prop.get("action") == "human-must-decide" and prop.get("reviewStatus") == "pending-review":
                must_decide.append({
                    "concept": entry["sourceConcept"],
                    "property": prop["sourceProperty"],
                })
    if must_decide:
        blockers.append(f"{len(must_decide)} properties require human decision")

    return len(blockers) == 0, blockers


def complete_stage_5(run_dir):
    """Run post-review completion steps for Stage 5.

    Assumes exit criteria have already been checked via check_stage_5_exit().
    Runs residual entropy calculation and marks the stage complete.

    Returns (success, error_message).
    """
    import subprocess

    run_dir = Path(run_dir)
    env = {**__import__("os").environ}

    # Residual entropy
    result = subprocess.run(
        ["om-residual-entropy", "--run-dir", str(run_dir)],
        capture_output=True, text=True, env=env,
    )
    if result.returncode != 0:
        return False, f"om-residual-entropy failed: {result.stderr or result.stdout}"

    # Mark stage complete
    result = subprocess.run(
        ["om-pipeline", "mark-complete", "--stage", "5", "--run-dir", str(run_dir)],
        capture_output=True, text=True, env=env,
    )
    if result.returncode != 0:
        return False, f"mark-complete failed: {result.stderr or result.stdout}"

    return True, None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _prop_counts(entry):
    """Return (total, reuse, create, must_decide) property counts."""
    props = entry.get("propertyMappings") or []
    reuse = sum(1 for p in props if p.get("action") == "reuse-property")
    create = sum(1 for p in props if p.get("action") == "create-property")
    must_decide = sum(1 for p in props if p.get("action") == "human-must-decide")
    return len(props), reuse, create, must_decide


def _cmd_present(args):
    """Print compact review summary — one line per concept, grouped by action."""
    run_dir, matrix, dec_log = load_inputs(args.run_dir)
    pending = get_pending_items(matrix)

    if not pending:
        print("No items pending review.")
        return

    groups = group_by_action(pending)
    total = len(pending)

    print(f"{'=' * 64}")
    print(f"  Stage 5: Human Review — {total} concepts pending")
    print(f"{'=' * 64}")

    for action_key, label, items in groups:
        # Check if any items in this group have properties
        has_props = any((e.get("propertyMappings") or []) for e in items)

        print(f"\n  {label} ({len(items)} concepts)")
        if has_props:
            print(f"  {'concept':<30s} {'target':<30s} props")
        else:
            print(f"  {'concept':<30s} {'target':<30s}")

        for entry in items:
            concept = entry["sourceConcept"].split(":")[-1]
            target = entry.get("targetType") or "(new)"
            base = entry.get("baseType")
            if target == "(new)" and base:
                target = f"(new, base: {base})"

            tp, rp, cp, md = _prop_counts(entry)
            if tp:
                parts = f"{rp}r/{cp}c"
                if md:
                    parts += f"/{md}!"
                print(f"    {concept:<28s} {target:<30s} {tp} ({parts})")
            else:
                print(f"    {concept:<28s} {target:<30s}")

    # --- Summary block ---
    all_props = [
        pm for entry in pending
        for pm in (entry.get("propertyMappings") or [])
    ]
    reuse_props = sum(1 for p in all_props if p.get("action") == "reuse-property")
    create_props = sum(1 for p in all_props if p.get("action") == "create-property")
    must_decide_props = sum(1 for p in all_props if p.get("action") == "human-must-decide")
    total_props = len(all_props)

    summary = matrix.get("summary", {})
    action_counts = summary.get("actionCounts", {})
    parts = [f"{v} {k}" for k, v in sorted(action_counts.items())]

    print(f"\n{'=' * 64}")
    print(f"  {total} concepts — {', '.join(parts)}")
    if total_props:
        prop_parts = f"{reuse_props} reuse, {create_props} create"
        if must_decide_props:
            prop_parts += f", {must_decide_props} UNDECIDED"
        print(f"  {total_props} properties — {prop_parts}")
    if must_decide_props:
        print(f"\n  *** {must_decide_props} properties require individual human decisions ***")
        print(f"  *** Resolve these before using approve-all ***")
    print()
    if must_decide_props:
        print(f"  Flag concepts for changes, or use 'detail <concept>' to resolve UNDECIDED properties.")
    else:
        print(f"  Approve all, or flag concepts for changes.")
    print(f"  Use 'detail <concept>' to see rationale and properties.")
    print(f"{'=' * 64}")


def _cmd_detail(args):
    """Print full detail for a single concept — rationale and property mappings."""
    run_dir, matrix, dec_log = load_inputs(args.run_dir)
    pending = get_pending_items(matrix)

    # Also check non-pending items so detail works after accept
    all_entries = {m["sourceConcept"]: m for m in matrix["mappings"]}

    # Try exact match, then suffix match
    entry = all_entries.get(args.concept)
    if not entry:
        suffix = f":{args.concept}"
        matches = [e for qname, e in all_entries.items() if qname.endswith(suffix)]
        if len(matches) == 1:
            entry = matches[0]
        elif len(matches) > 1:
            print(f"Ambiguous: {args.concept} matches {[m['sourceConcept'] for m in matches]}")
            return
        else:
            print(f"Not found: {args.concept}")
            return

    print(f"\n  {entry['sourceConcept']}")
    print(format_review_item(entry))
    prop_text = format_property_review(entry)
    if prop_text:
        print(prop_text)


def _cmd_accept_all(args):
    """Accept all pending items as-is and save.

    Refuses to run if any human-must-decide properties exist — those must
    be resolved individually first.
    """
    run_dir, matrix, dec_log = load_inputs(args.run_dir)
    pending = get_pending_items(matrix)

    if not pending:
        print("No items pending review.")
        return

    # Block accept-all if any human-must-decide properties remain
    must_decide_count = sum(
        1 for entry in pending
        for p in (entry.get("propertyMappings") or [])
        if p.get("action") == "human-must-decide"
        and p.get("reviewStatus") == "pending-review"
    )
    if must_decide_count:
        print(f"Cannot approve-all: {must_decide_count} human-must-decide "
              f"properties must be resolved individually first.")
        return

    applied = []
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

    summary = save_matrix(run_dir, matrix, dec_log, applied)

    print(f"Approved {len(applied)} concepts.")
    action_counts = summary.get("actionCounts", {})
    parts = [f"{v} {k}" for k, v in sorted(action_counts.items())]
    print(f"  Actions: {', '.join(parts)}")
    print(f"  Decision log: {dec_log['totalDecisions']} decisions")
    print(f"  Saved to: {run_dir / DECISIONS_FILENAME}")


def _cmd_search(args):
    """Search the target catalog for types and/or properties."""
    from ontology_mapper.catalog_search import (
        search_catalog,
        format_type_results,
        format_property_results,
    )

    run_dir = Path(args.run_dir)
    _, catalog = load_cascade_context(run_dir)

    results = search_catalog(
        catalog, args.query,
        kind=args.kind,
        namespace=args.namespace,
        max_results=args.max_results,
    )

    if args.json_output:
        print(json.dumps(results, indent=2))
    else:
        if results["types"]:
            print(format_type_results(results["types"]))
        if results["properties"]:
            if results["types"]:
                print()
            print(format_property_results(results["properties"]))
        if not results["types"] and not results["properties"]:
            print(f"  No results for '{args.query}'.")


def _cmd_accept(args):
    """Accept a single concept's current recommendation and save."""
    run_dir, matrix, dec_log = load_inputs(args.run_dir)

    target_entry = None
    for m in matrix["mappings"]:
        if m["sourceConcept"] == args.concept:
            target_entry = m
            break

    if target_entry is None:
        print(f"Error: concept '{args.concept}' not found in mapping matrix.")
        raise SystemExit(1)

    if target_entry.get("reviewStatus") != "pending-review":
        print(f"Concept '{args.concept}' is not pending review (status: {target_entry.get('reviewStatus')}).")
        return

    apply_accept(target_entry)
    accepted, skipped = apply_all_property_accepts(target_entry)

    applied = [{
        "sourceConcept": args.concept,
        "action": target_entry["action"],
        "targetType": target_entry.get("targetType"),
        "confidence": "confident",
        "notes": "Approved",
    }]

    save_matrix(run_dir, matrix, dec_log, applied)
    print(f"Approved: {args.concept} ({target_entry['action']})")
    if skipped:
        print(f"  *** {skipped} human-must-decide properties were NOT approved ***")
        print(f"  *** These must be resolved individually ***")


def main():
    import argparse
    import io
    import sys
    if sys.stdout.encoding != "utf-8":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Human review tool")
    parser.add_argument("--run-dir", default=None, help="Run directory path")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("present", help="Print compact review summary")
    sub.add_parser("approve-all", help="Approve all pending items as-is")

    detail_cmd = sub.add_parser("detail", help="Show full detail for one concept")
    detail_cmd.add_argument("concept", help="sourceConcept qname or local name")

    approve_cmd = sub.add_parser("approve", help="Approve a single concept")
    approve_cmd.add_argument("concept", help="sourceConcept qname to approve")

    search_cmd = sub.add_parser("search", help="Search target catalog for types/properties")
    search_cmd.add_argument("query", help="Search string (case-insensitive)")
    search_cmd.add_argument("--kind", choices=["type", "property"],
                            help="Search only types or only properties (default: both)")
    search_cmd.add_argument("--namespace", help="Filter by namespace prefix (e.g., 'nc')")
    search_cmd.add_argument("--max-results", type=int, default=20,
                            help="Maximum results per category (default: 20)")
    search_cmd.add_argument("--json", action="store_true", dest="json_output",
                            help="Output results as JSON")

    args = parser.parse_args()

    if args.command == "present":
        _cmd_present(args)
    elif args.command == "detail":
        _cmd_detail(args)
    elif args.command == "approve-all":
        _cmd_accept_all(args)
    elif args.command == "approve":
        _cmd_accept(args)
    elif args.command == "search":
        _cmd_search(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
