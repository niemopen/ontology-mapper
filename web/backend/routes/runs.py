"""Pipeline run management routes — all scoped by organization."""

import io
import json
import shutil
import subprocess
import threading
import zipfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse, StreamingResponse

from auth import require_auth, get_org_slug
from config import settings
from models import CreateRunRequest, RunSummary

router = APIRouter(tags=["runs"])

# In-memory tracking for background pipeline processes
_pipeline_status: dict[str, dict] = {}


def _org_runs_dir(org: str) -> Path:
    """Runs directory scoped to an organization."""
    return settings.runs_dir / org


def _org_sources_dir(org: str) -> Path:
    """Sources directory scoped to an organization."""
    return settings.runner_dir / "sources" / org


def _find_run_dir(org: str, run_id: str) -> Path:
    """Resolve a run directory within an org, raising 404 if missing."""
    d = _org_runs_dir(org) / run_id
    if not d.exists():
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    return d


def _read_state(run_dir: Path) -> dict | None:
    state_file = run_dir / ".mapper-state.json"
    if state_file.exists():
        return json.loads(state_file.read_text(encoding="utf-8"))
    return None


def _run_to_summary(run_dir: Path) -> RunSummary | None:
    state = _read_state(run_dir)
    if not state:
        return None
    inputs = state.get("inputs", {})
    stages = state.get("stages", {})
    current_stage = None
    for s in ["8", "7", "6", "5", "4", "3", "2", "1"]:
        if stages.get(s, {}).get("status") == "completed":
            current_stage = s
            break
    return RunSummary(
        run_id=run_dir.name,
        organization=inputs.get("organization", ""),
        source=inputs.get("source", ""),
        target_ontology=inputs.get("targetOntology", inputs.get("target_ontology", "")),
        target_version=inputs.get("targetVersion", inputs.get("target_version", "")),
        current_stage=current_stage or "0",
        created_at=state.get("createdAt", run_dir.name),
    )


# --- Runs ---

@router.get("/runs")
async def list_runs(
    user: dict = Depends(require_auth),
    org: str = Depends(get_org_slug),
) -> list[dict]:
    """List pipeline runs for the active organization."""
    runs_dir = _org_runs_dir(org)
    if not runs_dir.exists():
        return []
    results = []
    for d in sorted(runs_dir.iterdir(), reverse=True):
        if d.is_dir() and (d / ".mapper-state.json").exists():
            summary = _run_to_summary(d)
            if summary:
                results.append(summary.model_dump())
    return results


@router.get("/runs/{run_id}")
async def get_run(
    run_id: str,
    user: dict = Depends(require_auth),
    org: str = Depends(get_org_slug),
) -> dict:
    """Get details for a specific run."""
    run_dir = _find_run_dir(org, run_id)
    state = _read_state(run_dir)
    if not state:
        raise HTTPException(status_code=404, detail=f"No state file in: {run_id}")
    summary = _run_to_summary(run_dir)
    bg_status = _pipeline_status.get(run_id)
    return {
        "summary": summary.model_dump() if summary else None,
        "state": state,
        "pipeline_status": bg_status,
    }


@router.delete("/runs/{run_id}")
async def delete_run(
    run_id: str,
    user: dict = Depends(require_auth),
    org: str = Depends(get_org_slug),
) -> dict:
    """Permanently delete a run directory and all its artifacts."""
    run_dir = _find_run_dir(org, run_id)
    shutil.rmtree(run_dir)
    _pipeline_status.pop(run_id, None)

    from routes.review import _cascade_cache
    _cascade_cache.pop(run_id, None)

    return {"status": "deleted", "run_id": run_id}


@router.get("/runs/{run_id}/status")
async def get_run_status(
    run_id: str,
    user: dict = Depends(require_auth),
    org: str = Depends(get_org_slug),
) -> dict:
    """Poll pipeline execution status."""
    run_dir = _find_run_dir(org, run_id)
    state = _read_state(run_dir)
    bg = _pipeline_status.get(run_id, {"status": "idle"})
    stages = state.get("stages", {}) if state else {}
    return {
        "run_id": run_id,
        "pipeline": bg,
        "stages": {
            k: {"status": v.get("status", "unknown")}
            for k, v in stages.items()
        },
    }


@router.post("/runs")
async def create_run(
    req: CreateRunRequest,
    user: dict = Depends(require_auth),
    org: str = Depends(get_org_slug),
) -> dict:
    """Create a new pipeline run within the active organization."""
    runner_dir = settings.runner_dir
    # Source path is org-scoped
    package_path = f"sources/{org}/{req.source}_agency_package"
    full_package = runner_dir / package_path

    if not full_package.exists():
        raise HTTPException(
            status_code=400,
            detail=f"Source package not found: {package_path}. Upload source files first.",
        )

    org_runs = _org_runs_dir(org)
    org_runs.mkdir(parents=True, exist_ok=True)

    try:
        result = subprocess.run(
            [
                "om-pipeline",
                "--organization", req.organization,
                "--source", req.source,
                "--input-package-path", package_path,
                "--target-ontology", req.target_ontology,
                "--target-version", req.target_version,
            ],
            capture_output=True,
            text=True,
            cwd=str(runner_dir),
            env={
                **__import__("os").environ,
                "OM_RUNS_DIR": str(org_runs),
            },
        )
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip()
            raise HTTPException(status_code=500, detail=detail or "om-pipeline failed")
        # Find the most recent run directory within this org
        run_dirs = sorted(org_runs.iterdir(), key=lambda d: d.name, reverse=True)
        if not run_dirs:
            raise HTTPException(status_code=500, detail="Run directory not created")
        run_dir = run_dirs[0]
        return {"run_id": run_dir.name, "run_dir": str(run_dir)}
    except FileNotFoundError:
        raise HTTPException(
            status_code=500,
            detail="om-pipeline command not found. Is ontology-mapper installed?",
        )


# --- Sources ---

@router.post("/sources/upload")
async def upload_source(
    source: str = Form(...),
    files: list[UploadFile] = File(...),
    user: dict = Depends(require_auth),
    org: str = Depends(get_org_slug),
) -> dict:
    """Upload source files for the active organization.

    Files go to sources/{org}/{source}_agency_package.
    """
    source_dir = _org_sources_dir(org) / f"{source}_agency_package"
    source_dir.mkdir(parents=True, exist_ok=True)
    uploaded = []
    for f in files:
        dest = source_dir / f.filename
        dest.parent.mkdir(parents=True, exist_ok=True)
        content = await f.read()
        dest.write_bytes(content)
        uploaded.append(f.filename)
    return {"uploaded": uploaded, "source_dir": str(source_dir)}


@router.get("/sources")
async def list_sources(
    user: dict = Depends(require_auth),
    org: str = Depends(get_org_slug),
) -> list[dict]:
    """List source packages for the active organization."""
    sources_dir = _org_sources_dir(org)
    if not sources_dir.exists():
        return []
    results = []
    for d in sorted(sources_dir.iterdir()):
        if d.is_dir() and d.name.endswith("_agency_package"):
            source_name = d.name.removesuffix("_agency_package")
            file_count = sum(1 for f in d.rglob("*") if f.is_file())
            results.append({
                "package_name": d.name,
                "source_name": source_name,
                "file_count": file_count,
            })
    return results


# --- Pipeline execution ---

def _run_cmd(run_id: str, stage: str, cmd: list[str], cwd: str, env: dict) -> bool:
    """Run a subprocess command, updating pipeline status on failure. Returns True on success."""
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, env=env)
    if result.returncode != 0:
        _pipeline_status[run_id] = {
            "status": "failed", "stage": stage,
            "error": result.stderr.strip() or result.stdout.strip() or f"{cmd[0]} failed",
        }
        return False
    return True


def _record_stage_start(run_dir: Path, stage: str):
    """Write started_at into the state file so mark-complete preserves it."""
    from datetime import datetime, timezone
    state = _read_state(run_dir)
    if not state:
        return
    stages = state.setdefault("stages", {})
    entry = stages.get(stage)
    if entry:
        entry["started_at"] = datetime.now(timezone.utc).isoformat()
    else:
        stages[stage] = {
            "stage": stage,
            "status": "running",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "completed_at": None,
            "error": None,
            "artifacts": [],
            "notes": None,
        }
    state_file = run_dir / ".mapper-state.json"
    state_file.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def _mark_complete(run_id: str, stage: str, run_dir: Path, cwd: str, env: dict) -> bool:
    """Mark a pipeline stage complete. Returns True on success."""
    return _run_cmd(run_id, stage,
                    ["om-pipeline", "mark-complete", "--stage", stage, "--run-dir", str(run_dir)],
                    cwd, env)


def _run_pipeline_stages_1_4(run_id: str, run_dir: Path, cwd: str, env: dict) -> bool:
    """Execute pipeline stages 1-4. Returns True if all succeed."""
    rd = str(run_dir)

    # Stage 1
    _pipeline_status[run_id]["stage"] = "1"
    if not _run_cmd(run_id, "1", ["om-pipeline", "rerun", "--stage", "1", "--run-dir", rd], cwd, env):
        return False

    # Stage 2
    _pipeline_status[run_id]["stage"] = "2"
    _record_stage_start(run_dir, "2")
    state = _read_state(run_dir)
    package_path = (state.get("inputs", {}) if state else {}).get("inputPackagePath", "")
    if not _run_cmd(run_id, "2", ["om-extract", "--run-dir", rd, "--package", package_path], cwd, env):
        return False
    if not _mark_complete(run_id, "2", run_dir, cwd, env):
        return False

    # Stage 3
    _pipeline_status[run_id]["stage"] = "3"
    _record_stage_start(run_dir, "3")
    for cmd in [
        ["om-build-strategy", "--run-dir", rd],
        ["om-batch-search", "--run-dir", rd],
        ["om-entropy", "--run-dir", rd],
        # Concurrency lowered from default 24 to 16: middle ground between
        # default-24 (occasional rate-limit failures observed during OASIS
        # smoke runs) and 8 (markedly slower with no failures). 16 keeps
        # most of the parallel speedup while reducing rate-limit risk.
        ["om-orchestrate-eval", "--run-dir", rd, "--concurrency", "16"],
        ["om-collect-alignments", "--run-dir", rd],
    ]:
        if not _run_cmd(run_id, "3", cmd, cwd, env):
            return False
    if not _mark_complete(run_id, "3", run_dir, cwd, env):
        return False

    # Stage 4
    _pipeline_status[run_id]["stage"] = "4"
    _record_stage_start(run_dir, "4")
    for cmd in [
        ["om-build-matrix", "--run-dir", rd],
        ["om-generation-audit", "--run-dir", rd],
    ]:
        if not _run_cmd(run_id, "4", cmd, cwd, env):
            return False
    if not _mark_complete(run_id, "4", run_dir, cwd, env):
        return False

    return True


def _run_pipeline_stages_6_8(run_id: str, run_dir: Path, cwd: str, env: dict) -> bool:
    """Execute pipeline stages 6-8. Returns True if all succeed."""
    rd = str(run_dir)

    # Stage 6: Generate
    _pipeline_status[run_id]["stage"] = "6"
    if not _run_cmd(run_id, "6", ["om-pipeline", "rerun", "--stage", "6", "--run-dir", rd], cwd, env):
        return False
    if not _run_cmd(run_id, "6", ["om-generate-ontology", "--run-dir", rd], cwd, env):
        return False
    if not _run_cmd(run_id, "6", ["om-package-artifacts", "--run-dir", rd], cwd, env):
        return False
    if not _run_cmd(run_id, "6", ["om-generate-kg", "--run-dir", rd], cwd, env):
        return False
    if not _mark_complete(run_id, "6", run_dir, cwd, env):
        return False

    # Stage 7: Validate
    _pipeline_status[run_id]["stage"] = "7"
    _record_stage_start(run_dir, "7")
    if not _run_cmd(run_id, "7", ["om-validate", "--run-dir", rd], cwd, env):
        return False
    if not _run_cmd(run_id, "7", ["python", "runner_tools/feedback_report.py", "--run-dir", rd], cwd, env):
        return False
    if not _mark_complete(run_id, "7", run_dir, cwd, env):
        return False

    # Stage 8: Finalize
    _pipeline_status[run_id]["stage"] = "8"
    _record_stage_start(run_dir, "8")
    if not _run_cmd(run_id, "8", ["om-finalize", "--run-dir", rd], cwd, env):
        return False
    if not _mark_complete(run_id, "8", run_dir, cwd, env):
        return False

    return True


def _run_pipeline_background(run_id: str, run_dir: Path, org_runs_dir: Path, start_stage: int = 1):
    """Execute pipeline stages in a background thread."""
    env = {
        **__import__("os").environ,
        "OM_RUNS_DIR": str(org_runs_dir),
    }
    cwd = str(settings.runner_dir)

    _pipeline_status[run_id] = {"status": "running", "stage": str(start_stage), "error": None}

    try:
        if start_stage <= 4:
            if not _run_pipeline_stages_1_4(run_id, run_dir, cwd, env):
                return
            # Stages 1-4 done — Stage 5 (review) happens in the UI
            _pipeline_status[run_id] = {"status": "awaiting-review", "stage": "5", "error": None}
            return

        if start_stage == 6:
            if not _run_pipeline_stages_6_8(run_id, run_dir, cwd, env):
                return
            _pipeline_status[run_id] = {"status": "completed", "stage": "8", "error": None}

    except Exception as e:
        _pipeline_status[run_id] = {
            "status": "failed",
            "stage": _pipeline_status[run_id].get("stage", "?"),
            "error": str(e),
        }


@router.post("/runs/{run_id}/execute")
async def execute_pipeline(
    run_id: str,
    user: dict = Depends(require_auth),
    org: str = Depends(get_org_slug),
) -> dict:
    """Start pipeline stages 1-4 in the background."""
    run_dir = _find_run_dir(org, run_id)
    if run_id in _pipeline_status and _pipeline_status[run_id].get("status") == "running":
        raise HTTPException(status_code=409, detail="Pipeline already running")
    thread = threading.Thread(
        target=_run_pipeline_background,
        args=(run_id, run_dir, _org_runs_dir(org)),
        daemon=True,
    )
    thread.start()
    return {"status": "started", "run_id": run_id}


@router.post("/runs/{run_id}/continue")
async def continue_pipeline(
    run_id: str,
    user: dict = Depends(require_auth),
    org: str = Depends(get_org_slug),
) -> dict:
    """Continue pipeline with stages 6-8 after review is complete."""
    run_dir = _find_run_dir(org, run_id)
    if run_id in _pipeline_status and _pipeline_status[run_id].get("status") == "running":
        raise HTTPException(status_code=409, detail="Pipeline already running")

    # Verify Stage 5 is complete
    state = _read_state(run_dir)
    if not state:
        raise HTTPException(status_code=404, detail="No state file found")
    stage_5 = state.get("stages", {}).get("5", {})
    if stage_5.get("status") != "completed":
        raise HTTPException(status_code=409, detail="Stage 5 (review) must be completed first")

    thread = threading.Thread(
        target=_run_pipeline_background,
        args=(run_id, run_dir, _org_runs_dir(org), 6),
        daemon=True,
    )
    thread.start()
    return {"status": "started", "run_id": run_id, "from_stage": 6}


# --- Results ---

# File descriptions keyed by directory or filename pattern
_FILE_DESCRIPTIONS: dict[str, str] = {
    "ontology": "OWL ontology files (Turtle format)",
    "shapes": "SHACL validation shapes",
    "vocab": "SKOS code lists and vocabulary mappings",
    "mappings": "Mapping decisions and alignment reports",
    "extensions": "Extension type catalog and definitions",
    "governance": "Audit trail, validation, lineage, and versioning",
    "kg/neo4j": "Neo4j schema, seed data, and Cypher queries",
    "kg/rdf": "RDF named graphs and SPARQL queries",
    "kg/import": "Data import configuration and transform rules",
    "cmf": "Canonical Model Format exchange files",
    "package-manifest.json": "Package metadata and statistics",
    "README.md": "Human-readable package overview",
}


def _describe_file(rel_path: str) -> str:
    """Return a short description for a file based on its path."""
    # Check exact filename first
    for pattern, desc in _FILE_DESCRIPTIONS.items():
        if rel_path == pattern:
            return desc
    # Check directory prefix
    for pattern, desc in _FILE_DESCRIPTIONS.items():
        if rel_path.startswith(pattern + "/"):
            return desc
    return ""


def _build_review_stats(mapping_matrix: dict) -> dict:
    """Extract review statistics from the mapping matrix."""
    entries = mapping_matrix.get("mappings", [])
    action_counts: dict[str, int] = {}
    confidence_counts: dict[str, int] = {}
    for e in entries:
        action = e.get("action", "unknown")
        action_counts[action] = action_counts.get(action, 0) + 1
        conf = e.get("confidence", "unset")
        confidence_counts[conf] = confidence_counts.get(conf, 0) + 1
    return {
        "totalConcepts": len(entries),
        "actionCounts": action_counts,
        "confidenceCounts": confidence_counts,
    }


@router.get("/runs/{run_id}/results")
async def get_run_results(
    run_id: str,
    user: dict = Depends(require_auth),
    org: str = Depends(get_org_slug),
) -> dict:
    """Return pipeline results: metadata, review stats, validation, file inventory."""
    run_dir = _find_run_dir(org, run_id)
    edge_dir = run_dir / "edge-package"
    if not edge_dir.exists():
        raise HTTPException(status_code=404, detail="No edge-package found — pipeline may not have completed")

    state = _read_state(run_dir)
    inputs = state.get("inputs", {}) if state else {}

    # Run metadata
    manifest_path = edge_dir / "package-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}

    metadata = {
        "runId": run_id,
        "organization": inputs.get("organization", ""),
        "source": inputs.get("source", ""),
        "targetOntology": inputs.get("targetOntology", inputs.get("target_ontology", "")),
        "targetVersion": inputs.get("targetVersion", inputs.get("target_version", "")),
        "createdAt": state.get("createdAt", "") if state else "",
        "finalizedAt": manifest.get("finalizedAt", ""),
        "packageName": manifest.get("name", ""),
        "packageVersion": manifest.get("version", ""),
    }

    # Review stats from mapping matrix
    matrix_path = edge_dir / "mappings" / "mapping-matrix.json"
    review_stats = {}
    if matrix_path.exists():
        matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
        review_stats = _build_review_stats(matrix)

    # Validation summary
    validation_path = edge_dir / "governance" / "validation-report.json"
    validation = {}
    if validation_path.exists():
        vdata = json.loads(validation_path.read_text(encoding="utf-8"))
        validation = {
            "allPassed": vdata.get("allPassed", False),
            "checkCount": vdata.get("checkCount", 0),
            "passCount": vdata.get("passCount", 0),
            "failCount": vdata.get("failCount", 0),
            "checks": vdata.get("checks", []),
        }

    # File inventory
    files = []
    for f in sorted(edge_dir.rglob("*")):
        if not f.is_file():
            continue
        rel = f.relative_to(edge_dir).as_posix()
        files.append({
            "path": rel,
            "size": f.stat().st_size,
            "description": _describe_file(rel),
        })

    # Stage timings from pipeline state
    stages_raw = state.get("stages", {}) if state else {}
    stage_timings = {}
    for num, sdata in stages_raw.items():
        entry = {"status": sdata.get("status", "unknown")}
        if sdata.get("started_at") and sdata.get("completed_at"):
            entry["startedAt"] = sdata["started_at"]
            entry["completedAt"] = sdata["completed_at"]
        stage_timings[num] = entry

    return {
        "metadata": metadata,
        "reviewStats": review_stats,
        "validation": validation,
        "stageTimings": stage_timings,
        "files": files,
    }


@router.get("/runs/{run_id}/download")
async def download_run(
    run_id: str,
    user: dict = Depends(require_auth),
    org: str = Depends(get_org_slug),
):
    """Download the edge-package as a zip file."""
    run_dir = _find_run_dir(org, run_id)
    edge_dir = run_dir / "edge-package"
    if not edge_dir.exists():
        raise HTTPException(status_code=404, detail="No edge-package found")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(edge_dir.rglob("*")):
            if f.is_file():
                arcname = f.relative_to(edge_dir).as_posix()
                zf.write(f, arcname)
    buf.seek(0)

    # Read manifest for package name
    manifest_path = edge_dir / "package-manifest.json"
    pkg_name = run_id
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        pkg_name = manifest.get("name", run_id)

    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{pkg_name}.zip"'},
    )


@router.get("/runs/{run_id}/file/{file_path:path}")
async def get_run_file(
    run_id: str,
    file_path: str,
    user: dict = Depends(require_auth),
    org: str = Depends(get_org_slug),
):
    """Serve a single file from the edge-package."""
    run_dir = _find_run_dir(org, run_id)
    target = (run_dir / "edge-package" / file_path).resolve()

    # Prevent path traversal
    if not str(target).startswith(str((run_dir / "edge-package").resolve())):
        raise HTTPException(status_code=400, detail="Invalid path")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    media = "application/json" if target.suffix == ".json" else None
    return FileResponse(target, media_type=media, filename=target.name)


@router.get("/ontologies")
async def list_ontologies(user: dict = Depends(require_auth)) -> list[dict]:
    """List supported target ontologies, derived from installed reference catalogs."""
    import re
    from ontology_mapper.build_strategy_reports import SPECS_DIR

    # Scan for {key}_reference_catalog_{version}.json
    pattern = re.compile(r"^(.+)_reference_catalog_(.+)\.json$")
    ontologies: dict[str, list[str]] = {}
    for f in sorted(SPECS_DIR.iterdir()):
        m = pattern.match(f.name)
        if m:
            key, version = m.group(1), m.group(2)
            ontologies.setdefault(key, []).append(version)

    return [
        {"key": key, "name": key, "versions": versions}
        for key, versions in ontologies.items()
    ]
