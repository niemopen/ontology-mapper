#!/usr/bin/env python3
"""Smoke test for an OntologyMapper install.

Runs after the README setup steps to confirm the install is functional
before kicking off a real pipeline run or starting the dashboard.

Usage (from repo root, with .venv activated):

    python scripts/smoke.py

Exits 0 if everything looks good, 1 otherwise. Each check prints a
single PASS/FAIL line so the output is easy to scan and easy to
report back when something breaks.
"""

from __future__ import annotations

import importlib
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

REQUIRED_IMPORTS = [
    # Pipeline package
    "ontology_mapper",
    "ontology_mapper.pipeline",
    "ontology_mapper.vector_index",
    # Runner package
    "runner_tools",
    "orchestrator_service",
    # Web backend deps
    "fastapi",
    "uvicorn",
    # Vector stack (mapper[vector] extras)
    "faiss",
    "sentence_transformers",
    # RDF stack
    "rdflib",
    "lxml",
]

REQUIRED_CLI_TOOLS = [
    "om-pipeline",
    "om-extract",
    "om-build-strategy",
    "om-batch-search",
    "om-orchestrate-eval",
    "om-collect-alignments",
    "om-build-matrix",
    "om-generate-ontology",
    "om-validate",
    "om-finalize",
]


def emit(label: str, ok: bool, detail: str = "") -> None:
    tag = "PASS" if ok else "FAIL"
    line = f"[{tag}] {label}"
    if detail:
        line += f" -- {detail}"
    print(line, flush=True)


def check_python_version() -> bool:
    ok = sys.version_info >= (3, 10)
    emit("python >= 3.10", ok, f"running {sys.version_info.major}.{sys.version_info.minor}")
    return ok


def check_imports() -> bool:
    failures: list[str] = []
    for name in REQUIRED_IMPORTS:
        try:
            importlib.import_module(name)
        except Exception as exc:
            failures.append(f"{name}: {exc}")
    ok = not failures
    emit(
        f"imports ({len(REQUIRED_IMPORTS)} modules)",
        ok,
        "; ".join(failures) if failures else f"all {len(REQUIRED_IMPORTS)} importable",
    )
    return ok


def _find_cli_tool(name: str) -> str | None:
    """Resolve a CLI entry point, checking PATH first, then the dir
    alongside the running Python interpreter (covers venvs that haven't
    been activated in this shell)."""
    p = shutil.which(name)
    if p:
        return p
    here = Path(sys.executable).parent
    for ext in ("", ".exe", ".cmd"):
        candidate = here / f"{name}{ext}"
        if candidate.exists():
            return str(candidate)
    return None


def check_cli_tools() -> bool:
    missing = [t for t in REQUIRED_CLI_TOOLS if _find_cli_tool(t) is None]
    ok = not missing
    emit(
        f"cli entry points ({len(REQUIRED_CLI_TOOLS)} tools)",
        ok,
        f"missing: {', '.join(missing)}" if missing else "all resolvable",
    )
    if not ok:
        print(
            "       hint: re-run `pip install -e \"mapper[validation,vector]\"` "
            "and `pip install -e runner` from the activated venv."
        )
    return ok


def check_specs() -> bool:
    specs = REPO_ROOT / "mapper" / "src" / "ontology_mapper" / "specs"
    catalogs = list(specs.glob("*_reference_catalog_*.json")) if specs.exists() else []
    indexes = (specs / "vector" / "indexes")
    index_dirs = [d for d in indexes.iterdir() if d.is_dir()] if indexes.exists() else []

    catalogs_ok = bool(catalogs)
    indexes_ok = bool(index_dirs)

    if catalogs_ok and indexes_ok:
        emit(
            "reference data (catalogs + vector indexes)",
            True,
            f"{len(catalogs)} catalogs, {len(index_dirs)} vector indexes",
        )
        return True

    if catalogs_ok and not indexes_ok:
        emit(
            "reference data",
            False,
            f"{len(catalogs)} catalogs found; vector indexes missing",
        )
        print(
            "       hint: run `python scripts/build_indexes.py` to build "
            "the FAISS indexes (one-time post-clone setup; downloads the "
            "BGE-large-en embedding model on first run)."
        )
        return False

    emit("reference data", False, f"{len(catalogs)} catalogs, {len(index_dirs)} indexes")
    print(
        "       hint: the reference catalogs should ship with the repo "
        "under mapper/src/ontology_mapper/specs/. If they're missing, "
        "check that you cloned with all files (and re-run install)."
    )
    return False


def check_demo_source() -> bool:
    demo = REPO_ROOT / "runner" / "sources" / "demo" / "dbpi_agency_package"
    ok = demo.exists() and any(demo.iterdir())
    emit("demo source package", ok, f"path: runner/sources/demo/dbpi_agency_package")
    return ok


def check_pytest_runs() -> bool:
    """Run the mapper test suite minus the Docker integration tests."""
    cmd = [
        sys.executable, "-m", "pytest", str(REPO_ROOT / "mapper"),
        "--ignore", str(REPO_ROOT / "mapper" / "tests" / "test_kg_integration_neo4j.py"),
        "--ignore", str(REPO_ROOT / "mapper" / "tests" / "test_kg_integration_cypher.py"),
        "--ignore", str(REPO_ROOT / "mapper" / "tests" / "test_kg_integration_sparql.py"),
        "-q", "--no-header", "--tb=line", "-p", "no:cacheprovider",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO_ROOT))
    ok = result.returncode == 0
    last_line = result.stdout.strip().splitlines()[-1] if result.stdout else "(no output)"
    emit("mapper pytest", ok, last_line)
    if not ok:
        print(result.stdout[-2000:])
        print(result.stderr[-2000:])
    return ok


def main() -> int:
    print("OntologyMapper smoke test", flush=True)
    print(f"  Repo root: {REPO_ROOT}", flush=True)
    print(f"  Python:    {sys.executable}", flush=True)
    print("", flush=True)

    checks = [
        check_python_version,
        check_imports,
        check_cli_tools,
        check_specs,
        check_demo_source,
        check_pytest_runs,
    ]
    results = [c() for c in checks]
    print("", flush=True)
    if all(results):
        print("All checks passed.", flush=True)
        return 0
    failed = sum(1 for r in results if not r)
    print(f"{failed} check(s) failed. See above for details.", flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())
