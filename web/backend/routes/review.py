"""Stage 5 review routes — the core of the web interface."""

import json
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from auth import require_auth, get_org_slug
from config import settings
from models import ApproveRequest, ChangeTargetRequest, ResolvePropertyRequest

router = APIRouter(prefix="/runs/{run_id}/review", tags=["review"])

# Lazy-loaded cascade contexts (target_ontology, catalog) per run
_cascade_cache: dict[str, tuple] = {}


def _run_dir(org: str, run_id: str) -> Path:
    d = settings.runs_dir / org / run_id
    if not d.exists():
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    return d


STAGE4_SNAPSHOT = "mapping-matrix.stage4.json"


def _load_matrix(run_dir: Path) -> dict:
    f = run_dir / "mapping-matrix.json"
    if not f.exists():
        raise HTTPException(
            status_code=404,
            detail="mapping-matrix.json not found. Run stages 1-4 first.",
        )
    return json.loads(f.read_text(encoding="utf-8"))


def snapshot_stage_4(run_dir: Path) -> None:
    """Record Stage 4's matrix as the state `reset` restores.

    Taken when Stage 4 runs, not on first review read: a run reviewed
    outside the web arrives with decisions already in the matrix, and
    snapshotting that made `reset` restore a reviewed matrix while
    answering "reset" — leaving the execute gate refusing with no way
    out that the web offers.
    """
    matrix = run_dir / "mapping-matrix.json"
    if matrix.exists():
        shutil.copy2(matrix, run_dir / STAGE4_SNAPSHOT)


def _load_decision_log(run_dir: Path) -> dict:
    f = run_dir / "decision-log.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    return {"totalDecisions": 0, "decisions": []}


def _save(run_dir: Path, matrix: dict, dec_log: dict, applied: list):
    """Save matrix, decision log, and human review decisions."""
    from runner_tools._present_and_apply_human_review import (
        save_matrix,
        recompute_summary,
    )
    recompute_summary(matrix)
    save_matrix(run_dir, matrix, dec_log, applied)


def _find_entry(matrix: dict, concept: str) -> dict | None:
    """The mapping entry a request names, by the CLI review's rule
    (`find_mapping_entry`). A name several entries share is refused, not
    resolved to the first of them."""
    from runner_tools._present_and_apply_human_review import find_mapping_entry

    entry, candidates = find_mapping_entry(matrix.get("mappings", []), concept)
    if entry is None and len(candidates) > 1:
        raise HTTPException(
            status_code=409,
            detail=f"Concept name is ambiguous: {concept} could be {', '.join(candidates)}",
        )
    return entry


def _mark_undecided(entries: list) -> list:
    """Each property carries ``undecided`` (`property_undecided`), so the
    page shows the gate's answer instead of deciding by action itself: it
    showed an accepted reuse with no target as done, and offered to accept
    a pending one as it stood."""
    from runner_tools._present_and_apply_human_review import property_undecided

    for entry in entries:
        for p in entry.get("propertyMappings") or []:
            p["undecided"] = property_undecided(p)
    return entries


def _get_cascade(run_id: str, run_dir: Path) -> tuple | None:
    """Lazy-load cascade context (target_ontology, catalog) for a run."""
    if run_id not in _cascade_cache:
        try:
            from runner_tools._present_and_apply_human_review import load_cascade_context
            _cascade_cache[run_id] = load_cascade_context(run_dir)
        except Exception:
            return None
    return _cascade_cache.get(run_id)


def stage_5_gate(run_id: str, run_dir: Path, matrix: dict) -> tuple:
    """May review close for this run? One home for the three routes that ask.

    The class-target policy needs the run's catalog. When it cannot be loaded
    the saved targets cannot be proven valid, which is a blocker, not a pass:
    an unvalidated matrix reaching Stage 6 is the hole this check exists for.
    """
    from runner_tools._present_and_apply_human_review import check_stage_5_exit

    cascade = _get_cascade(run_id, run_dir)
    if not cascade:
        return False, ["class targets could not be validated: "
                       "no reference catalog resolved for this run"]
    return check_stage_5_exit(matrix, cascade)


@router.get("")
async def get_review_state(run_id: str, user: dict = Depends(require_auth), org: str = Depends(get_org_slug)) -> dict:
    """Get the full review state: mappings, summary, and validation status."""
    run_dir = _run_dir(org, run_id)
    matrix = _load_matrix(run_dir)

    from runner_tools._present_and_apply_human_review import (
        get_pending_items,
        get_pending_property_items,
    )

    pending = get_pending_items(matrix)
    total = len(matrix.get("mappings", []))
    accepted = total - len(pending)

    # Count human-must-decide properties and best-guess items
    from runner_tools._present_and_apply_human_review import undecided_properties

    must_decide_count = len(undecided_properties(matrix.get("mappings", [])))
    from runner_tools._present_and_apply_human_review import approve_all_blockers

    approve_all_blocked = len(approve_all_blockers(matrix))
    best_guess_count = sum(
        1 for entry in matrix.get("mappings", [])
        if entry.get("confidence") == "best-guess" and entry.get("reviewStatus") == "accepted")

    # Whether Submit is offered is the question submit itself asks, answered
    # by the same gate: counting pending items here offered Submit on a
    # policy-blocked run and the click came back 409 with no blocker shown.
    can_submit, blockers = stage_5_gate(run_id, run_dir, matrix)

    return {
        "targetOntology": matrix.get("targetOntology", ""),
        "targetVersion": matrix.get("targetVersion", ""),
        "summary": matrix.get("summary", {}),
        "mappings": _mark_undecided(matrix.get("mappings", [])),
        "actions": matrix.get("actions", {}),
        "validation": {
            "totalConcepts": total,
            "accepted": accepted,
            "pending": len(pending),
            "humanMustDecide": must_decide_count,
            "approveAllBlocked": approve_all_blocked,
            "bestGuess": best_guess_count,
            "canSubmit": can_submit,
            "blockers": blockers,
        },
    }


@router.post("/approve")
async def approve_concept(
    run_id: str, req: ApproveRequest, user: dict = Depends(require_auth), org: str = Depends(get_org_slug),
) -> dict:
    """Approve a single concept's current recommendation."""
    run_dir = _run_dir(org, run_id)
    matrix = _load_matrix(run_dir)
    dec_log = _load_decision_log(run_dir)
    entry = _find_entry(matrix, req.concept)
    if not entry:
        raise HTTPException(status_code=404, detail=f"Concept not found: {req.concept}")

    from runner_tools._present_and_apply_human_review import (
        apply_accept,
        apply_all_property_accepts,
    )

    apply_accept(entry)
    entry["confidence"] = req.confidence
    _accepted, skipped = apply_all_property_accepts(entry, confidence=req.confidence)

    _save(run_dir, matrix, dec_log, [entry])

    return {
        "approved": entry["sourceConcept"],
        "skippedMustDecide": skipped,
        "reviewStatus": entry["reviewStatus"],
        "confidence": entry["confidence"],
    }


@router.post("/approve-all")
async def approve_all(run_id: str, user: dict = Depends(require_auth), org: str = Depends(get_org_slug)) -> dict:
    """Approve all pending concepts. Blocked while they have undecided
    properties (`approve_all_blockers`)."""
    run_dir = _run_dir(org, run_id)
    matrix = _load_matrix(run_dir)
    dec_log = _load_decision_log(run_dir)

    from runner_tools._present_and_apply_human_review import (
        get_pending_items,
        apply_accept,
        apply_all_property_accepts,
    )

    pending = get_pending_items(matrix)

    from runner_tools._present_and_apply_human_review import approve_all_blockers

    must_decide = approve_all_blockers(matrix)
    if must_decide:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Cannot approve-all: undecided properties exist",
                "mustDecide": must_decide,
            },
        )

    applied = []
    for entry in pending:
        apply_accept(entry)
        apply_all_property_accepts(entry)
        applied.append(entry)

    _save(run_dir, matrix, dec_log, applied)

    return {"approved": len(applied)}


@router.post("/change-target")
async def change_target(
    run_id: str, req: ChangeTargetRequest, user: dict = Depends(require_auth), org: str = Depends(get_org_slug),
) -> dict:
    """Change the target type for a concept (triggers action reclassification)."""
    run_dir = _run_dir(org, run_id)
    matrix = _load_matrix(run_dir)
    dec_log = _load_decision_log(run_dir)
    entry = _find_entry(matrix, req.concept)
    if not entry:
        raise HTTPException(status_code=404, detail=f"Concept not found: {req.concept}")

    from runner_tools._present_and_apply_human_review import apply_decision_with_cascade

    cascade = _get_cascade(run_id, run_dir)
    if not cascade:
        raise HTTPException(
            status_code=500,
            detail="Could not load catalog for reclassification",
        )

    target_ontology, catalog = cascade
    decision = {
        "action": entry.get("action", "reuse"),
        "targetType": req.new_target_type,
    }
    from ontology_mapper.ontology_specific import ClassTargetError
    try:
        apply_decision_with_cascade(entry, decision, target_ontology, catalog)
    except ClassTargetError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    _save(run_dir, matrix, dec_log, [entry])

    return {
        "concept": entry["sourceConcept"],
        "newAction": entry["action"],
        "newTargetType": entry.get("targetType"),
    }


@router.post("/resolve-property")
async def resolve_property(
    run_id: str, req: ResolvePropertyRequest, user: dict = Depends(require_auth), org: str = Depends(get_org_slug),
) -> dict:
    """Resolve a single property mapping (especially human-must-decide)."""
    run_dir = _run_dir(org, run_id)
    matrix = _load_matrix(run_dir)
    dec_log = _load_decision_log(run_dir)
    entry = _find_entry(matrix, req.concept)
    if not entry:
        raise HTTPException(status_code=404, detail=f"Concept not found: {req.concept}")

    from runner_tools._present_and_apply_human_review import apply_property_decision

    cascade = _get_cascade(run_id, run_dir)
    if not cascade and req.property_action == "reuse-property":
        # Only a reuse names a catalog target to fingerprint; the run's
        # state, not the request, is at fault.
        raise HTTPException(
            status_code=503,
            detail="The run's reference catalog could not be loaded, so a reused "
                   "target cannot be recorded; create-property decisions still can",
        )
    decision = {
        "action": req.property_action,
        "targetProperty": req.target_property,
        "confidence": req.confidence,
    }
    from ontology_mapper.generation_utils import PropertyTargetError
    try:
        apply_property_decision(entry, req.source_property, decision, cascade[1] if cascade else {})
    except PropertyTargetError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    _save(run_dir, matrix, dec_log, [entry])

    # Find the updated property
    updated_prop = None
    for prop in entry.get("propertyMappings", []):
        if prop.get("sourceProperty") == req.source_property:
            updated_prop = prop
            break

    return {
        "concept": entry["sourceConcept"],
        "property": req.source_property,
        "newAction": req.property_action,
        "updatedProperty": updated_prop,
    }


@router.get("/validation")
async def get_validation(run_id: str, user: dict = Depends(require_auth), org: str = Depends(get_org_slug)) -> dict:
    """Check whether Stage 5 exit criteria are met."""
    run_dir = _run_dir(org, run_id)
    matrix = _load_matrix(run_dir)

    from runner_tools._present_and_apply_human_review import get_pending_items, undecided_properties

    can_exit, blockers = stage_5_gate(run_id, run_dir, matrix)
    pending = get_pending_items(matrix)
    must_decide = undecided_properties(matrix.get("mappings", []))

    return {
        "canSubmit": can_exit,
        "blockers": blockers,
        "pendingConcepts": [e["sourceConcept"] for e in pending],
        "mustDecideProperties": must_decide,
    }


@router.post("/submit")
async def submit_review(run_id: str, user: dict = Depends(require_auth), org: str = Depends(get_org_slug)) -> dict:
    """Complete Stage 5 — runs post-review steps and marks stage complete."""
    run_dir = _run_dir(org, run_id)
    matrix = _load_matrix(run_dir)

    from runner_tools._present_and_apply_human_review import complete_stage_5

    can_exit, blockers = stage_5_gate(run_id, run_dir, matrix)
    if not can_exit:
        raise HTTPException(status_code=409, detail="; ".join(blockers))

    success, error = complete_stage_5(run_dir)
    if not success:
        raise HTTPException(status_code=500, detail=error)

    # Clear cascade cache
    _cascade_cache.pop(run_id, None)

    return {"status": "completed", "stage": "5"}


@router.post("/reset")
async def reset_review(run_id: str, user: dict = Depends(require_auth), org: str = Depends(get_org_slug)) -> dict:
    """Reset all review decisions back to the original Stage 4 output."""
    run_dir = _run_dir(org, run_id)
    snapshot = run_dir / STAGE4_SNAPSHOT
    if not snapshot.exists():
        raise HTTPException(
            status_code=404,
            detail="No Stage 4 snapshot found — nothing to reset to. This run's "
                   "review came from outside the web; rebuild the matrix with "
                   "`om-build-matrix --force` to start the review over.")

    # Restore mapping matrix from snapshot
    matrix_file = run_dir / "mapping-matrix.json"
    shutil.copy2(snapshot, matrix_file)

    # Clear human review decisions
    decisions_file = run_dir / "human-review-decisions.json"
    if decisions_file.exists():
        decisions_file.unlink()

    # Clear cascade cache for this run
    _cascade_cache.pop(run_id, None)

    # Reload to return fresh state
    matrix = json.loads(matrix_file.read_text(encoding="utf-8"))
    total = len(matrix.get("mappings", []))
    # A snapshot taken before this rule, or a run reviewed elsewhere,
    # can itself carry decisions. Say so: "reset" alone would tell the
    # operator the execute gate is now clear when it is not. Counted by the
    # predicate that gate asks, so the note appears exactly when it refuses.
    from ontology_mapper.build_mapping_matrix import review_decisions_present
    classes, properties, reviewed_at = review_decisions_present(matrix)
    restored_decisions = classes + properties + (1 if reviewed_at else 0)

    return {
        "status": "reset",
        "totalConcepts": total,
        "restoredDecisions": restored_decisions,
        "note": ("The Stage 4 snapshot itself carries review decisions, so "
                 "stages 1-4 still refuse to overwrite it; rebuild the matrix "
                 "with `om-build-matrix --force` to start the review over."
                 if restored_decisions else ""),
    }


# Registered last: FastAPI matches routes in order, and a path parameter
# placed before GET /validation answered it as concept detail
# ("Concept not found: validation").
@router.get("/{concept}")
async def get_concept_detail(
    run_id: str, concept: str, user: dict = Depends(require_auth), org: str = Depends(get_org_slug),
) -> dict:
    """Get detailed view of a single concept mapping."""
    run_dir = _run_dir(org, run_id)
    matrix = _load_matrix(run_dir)
    entry = _find_entry(matrix, concept)
    if not entry:
        raise HTTPException(status_code=404, detail=f"Concept not found: {concept}")
    return _mark_undecided([entry])[0]
