#!/usr/bin/env python3
"""Build vector indexes for the bundled reference catalogs.

The catalogs (NIEM 6.0, NODS 1.0, SALI/FOLIO 2.0) ship with the repo
under mapper/src/ontology_mapper/specs/. The FAISS indexes derived
from those catalogs do NOT ship (too large; rebuildable). This script
runs once after a fresh clone to produce them.

On first invocation, sentence-transformers downloads the BGE-large-en
embedding model from HuggingFace (~1.3 GB) into the user's HF cache.
Subsequent runs reuse the cached model.

Usage (from repo root, with .venv activated):

    python scripts/build_indexes.py

Exits 0 on success, 1 if any index fails to build.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

ONTOLOGIES = [
    ("niem",       "6.0"),
    ("nods",       "1.0"),
    ("sali-folio", "2.0"),
]


def find_tool(name: str) -> str | None:
    """Resolve a CLI tool, preferring the dir alongside the running Python."""
    here = Path(sys.executable).parent
    for ext in ("", ".exe", ".cmd"):
        candidate = here / f"{name}{ext}"
        if candidate.exists():
            return str(candidate)
    import shutil
    return shutil.which(name)


def main() -> int:
    tool = find_tool("om-build-vector-index")
    if tool is None:
        print(
            "ERROR: om-build-vector-index not found. Make sure the venv is "
            "activated and `pip install -e \"mapper[vector]\"` has run.",
            file=sys.stderr,
        )
        return 1

    print(f"Building vector indexes for {len(ONTOLOGIES)} ontologies.")
    print(
        "First-time runs download the BGE-large-en embedding model from "
        "HuggingFace (~1.3 GB) into the user HF cache.\n",
        flush=True,
    )

    failures: list[tuple[str, str]] = []
    for name, version in ONTOLOGIES:
        label = f"{name}-{version}"
        print(f"[ {label} ] building...", flush=True)
        t0 = time.time()
        result = subprocess.run(
            [tool, "--ontology", name, "--adapter", "catalog", "--version", version],
            cwd=str(REPO_ROOT),
        )
        elapsed = time.time() - t0
        if result.returncode == 0:
            print(f"[ {label} ] done in {elapsed:.1f}s", flush=True)
        else:
            failures.append((label, f"exit code {result.returncode}"))
            print(f"[ {label} ] FAILED (exit {result.returncode})", flush=True)

    print()
    if failures:
        print(f"{len(failures)} ontology/ies failed to build:", flush=True)
        for label, reason in failures:
            print(f"  {label}: {reason}", flush=True)
        return 1
    print(f"All {len(ONTOLOGIES)} vector indexes built.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
