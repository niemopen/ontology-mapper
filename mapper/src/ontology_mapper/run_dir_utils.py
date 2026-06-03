"""Shared utilities for resolving pipeline run directories and state.

All pipeline tools use this module instead of reading a global
.mapper-state.json from the working directory.  State lives inside
each run directory: .mapper-runs/{run_id}/.mapper-state.json

``resolve_run_dir()`` requires an explicit path — no auto-detection.
Concurrent pipeline sessions must each target a specific run.
"""

import json
import os
import re
from pathlib import Path

STATE_FILENAME = ".mapper-state.json"
RUNS_ROOT = Path(os.environ.get("OM_RUNS_DIR", ".mapper-runs"))


def resolve_specs_dir():
    """Return the specs directory path.

    Checks OM_SPECS_DIR env var first, falls back to
    the specs/ directory inside this package.
    """
    env = os.environ.get("OM_SPECS_DIR")
    if env:
        return Path(env)
    return Path(__file__).parent / "specs"


def _list_run_dirs():
    """Return all run directories sorted most-recent-first."""
    if not RUNS_ROOT.is_dir():
        return []
    return sorted(
        [d for d in RUNS_ROOT.iterdir() if d.is_dir()],
        key=lambda d: d.name,
        reverse=True,
    )


def _org_from_dirname(dirname):
    """Extract org prefix from a run directory name like 'redvale_20260329-045647'.

    Returns the org prefix, or '' for directories without one (bare timestamps).
    """
    parts = dirname.rsplit("_", 1)
    if len(parts) == 2 and len(parts[1]) >= 8 and parts[1][:8].isdigit():
        return parts[0]
    return ""


def list_orgs():
    """Return a sorted list of unique org prefixes from existing run directories."""
    orgs = set()
    for d in _list_run_dirs():
        org = _org_from_dirname(d.name)
        if org:
            orgs.add(org)
    return sorted(orgs)


def _normalize_path(path_str):
    """Normalize a path string to work on Windows.

    Converts Git Bash / MSYS2 paths like /c/dev/foo to C:/dev/foo
    so Python's Path() can resolve them on Windows.
    """
    if isinstance(path_str, Path):
        return path_str
    s = str(path_str)
    # Convert /c/... or /d/... (MSYS2/Git Bash) to C:/... or D:/...
    m = re.match(r'^/([a-zA-Z])(/.*)', s)
    if m:
        s = f"{m.group(1).upper()}:{m.group(2)}"
    return Path(s)


def resolve_run_dir(cli_arg=None, org=None):
    """Return a Path to the run directory.

    Args:
        cli_arg: explicit run-dir path (str or Path). Required.
        org: ignored (kept for signature compatibility during transition).

    Returns:
        Path to the run directory.

    Raises:
        FileNotFoundError: if cli_arg is None or the directory doesn't exist.
    """
    if not cli_arg:
        raise FileNotFoundError(
            "--run-dir is required. Pass the explicit path to the run directory "
            "(e.g., .mapper-runs/redvale_20260406-045218)."
        )
    p = _normalize_path(cli_arg)
    if p.is_dir():
        return p
    raise FileNotFoundError(f"Run directory not found: {cli_arg}")


def load_state(run_dir):
    """Load pipeline state from a run directory.

    Args:
        run_dir: Path to the run directory.

    Returns:
        dict with the full pipeline state (run_id, inputs, stages, etc.).

    Raises:
        FileNotFoundError: if no state file exists in the run directory.
    """
    state_path = Path(run_dir) / STATE_FILENAME
    if not state_path.exists():
        raise FileNotFoundError(
            f"No state file found in {run_dir}. "
            f"Expected: {state_path}"
        )
    return json.loads(state_path.read_text(encoding="utf-8"))


def state_path_for(run_dir):
    """Return the path to the state file inside a run directory."""
    return Path(run_dir) / STATE_FILENAME
