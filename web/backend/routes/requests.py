"""Ontology request routes — global (not org-scoped)."""

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException

from auth import require_auth, get_org_slug
from config import settings
from models import OntologyRequestCreate

router = APIRouter(prefix="/ontology-requests", tags=["requests"])


def _requests_file() -> Path:
    return settings.runs_dir / "ontology-requests.json"


def _load_requests() -> list[dict]:
    f = _requests_file()
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    return []


def _save_requests(requests: list[dict]):
    f = _requests_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(requests, indent=2), encoding="utf-8")


def _is_admin(user: dict) -> bool:
    # The single local user is always an admin.
    return True


def _require_admin(user: dict = Depends(require_auth)) -> dict:
    if not _is_admin(user):
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


@router.post("")
async def create_request(
    req: OntologyRequestCreate,
    user: dict = Depends(require_auth),
    org: str = Depends(get_org_slug),
) -> dict:
    """Submit a request for a new target ontology."""
    requests = _load_requests()
    entry = {
        "id": str(uuid4())[:8],
        "name": req.name,
        "version": req.version,
        "reference_url": req.reference_url,
        "notes": req.notes,
        "status": "pending",
        "requested_by": user.get("sub", ""),
        "requested_org": org,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "completed_at": None,
    }
    requests.append(entry)
    _save_requests(requests)
    return entry


@router.get("")
async def list_requests(user: dict = Depends(_require_admin)) -> list[dict]:
    """List all ontology requests (admin only)."""
    return _load_requests()


@router.get("/pending-count")
async def pending_count(user: dict = Depends(require_auth)) -> dict:
    """Get count of pending requests. Returns 0 for non-admin users."""
    if _is_admin(user):
        requests = _load_requests()
        count = sum(1 for r in requests if r["status"] == "pending")
        return {"count": count, "is_admin": True}
    return {"count": 0, "is_admin": False}


@router.post("/{request_id}/complete")
async def complete_request(
    request_id: str,
    user: dict = Depends(_require_admin),
) -> dict:
    """Mark an ontology request as completed (admin only)."""
    requests = _load_requests()
    for r in requests:
        if r["id"] == request_id:
            r["status"] = "completed"
            r["completed_at"] = datetime.now(timezone.utc).isoformat()
            _save_requests(requests)
            return r
    raise HTTPException(status_code=404, detail=f"Request not found: {request_id}")
