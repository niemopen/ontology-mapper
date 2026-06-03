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
    # Snapshot Stage 4 output on first access so we can reset later
    snapshot = run_dir / STAGE4_SNAPSHOT
    if not snapshot.exists():
        shutil.copy2(f, snapshot)
    return json.loads(f.read_text(encoding="utf-8"))


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
    """Find a mapping entry by exact qname or local name suffix."""
    for entry in matrix.get("mappings", []):
        sc = entry.get("sourceConcept", "")
        if sc == concept:
            return entry
        local = sc.split(":")[-1] if ":" in sc else sc
        if local.lower() == concept.lower():
            return entry
    return None


def _get_cascade(run_id: str, run_dir: Path) -> tuple | None:
    """Lazy-load cascade context (target_ontology, catalog) for a run."""
    if run_id not in _cascade_cache:
        try:
            from runner_tools._present_and_apply_human_review import load_cascade_context
            _cascade_cache[run_id] = load_cascade_context(run_dir)
        except Exception:
            return None
    return _cascade_cache.get(run_id)


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
    must_decide_count = 0
    best_guess_count = 0
    for entry in matrix.get("mappings", []):
        if entry.get("confidence") == "best-guess" and entry.get("reviewStatus") == "accepted":
            best_guess_count += 1
        for prop in entry.get("propertyMappings", []):
            if prop.get("action") == "human-must-decide" and prop.get("reviewStatus") == "pending-review":
                must_decide_count += 1

    return {
        "targetOntology": matrix.get("targetOntology", ""),
        "targetVersion": matrix.get("targetVersion", ""),
        "summary": matrix.get("summary", {}),
        "mappings": matrix.get("mappings", []),
        "actions": matrix.get("actions", {}),
        "validation": {
            "totalConcepts": total,
            "accepted": accepted,
            "pending": len(pending),
            "humanMustDecide": must_decide_count,
            "bestGuess": best_guess_count,
            "canSubmit": len(pending) == 0 and must_decide_count == 0,
        },
    }


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
    return entry


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
    skipped = apply_all_property_accepts(entry, confidence=req.confidence)

    _save(run_dir, matrix, dec_log, [entry])

    return {
        "approved": entry["sourceConcept"],
        "skippedMustDecide": skipped,
        "reviewStatus": entry["reviewStatus"],
        "confidence": entry["confidence"],
    }


@router.post("/approve-all")
async def approve_all(run_id: str, user: dict = Depends(require_auth), org: str = Depends(get_org_slug)) -> dict:
    """Approve all pending concepts. Blocked if human-must-decide properties exist."""
    run_dir = _run_dir(org, run_id)
    matrix = _load_matrix(run_dir)
    dec_log = _load_decision_log(run_dir)

    from runner_tools._present_and_apply_human_review import (
        get_pending_items,
        apply_accept,
        apply_all_property_accepts,
    )

    pending = get_pending_items(matrix)

    # Check for human-must-decide blockers
    must_decide = []
    for entry in pending:
        for prop in entry.get("propertyMappings", []):
            if prop.get("action") == "human-must-decide" and prop.get("reviewStatus") == "pending-review":
                must_decide.append({
                    "concept": entry["sourceConcept"],
                    "property": prop["sourceProperty"],
                })
    if must_decide:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Cannot approve-all: human-must-decide properties exist",
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
    apply_decision_with_cascade(entry, decision, target_ontology, catalog)

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

    decision = {
        "action": req.property_action,
        "targetProperty": req.target_property,
        "confidence": req.confidence,
    }
    apply_property_decision(entry, req.source_property, decision)

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

    from runner_tools._present_and_apply_human_review import (
        check_stage_5_exit,
        get_pending_items,
    )

    can_exit, blockers = check_stage_5_exit(matrix)
    pending = get_pending_items(matrix)

    must_decide = []
    for entry in matrix.get("mappings", []):
        for prop in entry.get("propertyMappings", []):
            if prop.get("action") == "human-must-decide" and prop.get("reviewStatus") == "pending-review":
                must_decide.append({
                    "concept": entry["sourceConcept"],
                    "property": prop["sourceProperty"],
                })

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

    from runner_tools._present_and_apply_human_review import (
        check_stage_5_exit,
        complete_stage_5,
    )

    can_exit, blockers = check_stage_5_exit(matrix)
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
        raise HTTPException(status_code=404, detail="No Stage 4 snapshot found — nothing to reset to")

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

    return {
        "status": "reset",
        "totalConcepts": total,
    }
