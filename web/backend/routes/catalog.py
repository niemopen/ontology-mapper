"""Target catalog search routes — powers the typeahead UI."""

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query

from auth import require_auth, get_org_slug
from config import settings

router = APIRouter(tags=["catalog"])

# Cache loaded catalogs per run
_catalog_cache: dict[str, dict] = {}


def _load_catalog_for_run(org: str, run_id: str) -> dict:
    """Load the target ontology reference catalog for a run."""
    cache_key = f"{org}/{run_id}"
    if cache_key in _catalog_cache:
        return _catalog_cache[cache_key]

    run_dir = settings.runs_dir / org / run_id
    if not run_dir.exists():
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")

    # Read state to get target ontology info
    state_file = run_dir / ".mapper-state.json"
    if not state_file.exists():
        raise HTTPException(status_code=404, detail="No state file")
    state = json.loads(state_file.read_text(encoding="utf-8"))
    inputs = state.get("inputs", {})
    target_ontology = inputs.get("targetOntology", inputs.get("target_ontology", ""))
    target_version = inputs.get("targetVersion", inputs.get("target_version", ""))

    # Load catalog via ontology_mapper
    try:
        from ontology_mapper.build_strategy_reports import resolve_catalog_path
        catalog_path = resolve_catalog_path(target_ontology, target_version)
        catalog = json.loads(Path(catalog_path).read_text(encoding="utf-8"))
        _catalog_cache[cache_key] = catalog
        return catalog
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to load catalog: {e}",
        )


@router.get("/catalog/search")
async def search_catalog(
    run_id: str = Query(..., description="Run ID to determine target ontology"),
    q: str = Query(..., min_length=1, description="Search query"),
    kind: str = Query("both", description="type, property, or both"),
    max_results: int = Query(20, ge=1, le=50),
    user: dict = Depends(require_auth),
    org: str = Depends(get_org_slug),
) -> dict:
    """Search the target ontology catalog. Powers typeahead in the review UI."""
    catalog = _load_catalog_for_run(org, run_id)

    from ontology_mapper.catalog_search import search_catalog as sc_search

    kind_arg = None if kind == "both" else kind
    results = sc_search(catalog, q, kind=kind_arg, max_results=max_results)
    return results
