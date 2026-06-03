"""Centralized pipeline configuration.

Thresholds can be overridden per-run via the state file inside the run
directory (`.mapper-runs/{run_id}/.mapper-state.json`):

    {
      "inputs": { ... },
      "thresholds": {
        "property_composition_max_depth": 3
      }
    }

Only the keys you want to change need to appear — all others use defaults.
"""

import json
from pathlib import Path

# ---------------------------------------------------------------------------
# Defaults — each threshold is documented inline
# ---------------------------------------------------------------------------

DEFAULTS = {
    # ── Property Semantic Matching (Catalog + Candidate Builder) ──

    # Max depth for composition navigation when pre-computing reachable
    # properties in the reference catalog. Depth 0 = own + inherited properties,
    # depth 1 = properties of composed types, depth 2 = two levels deep.
    "property_composition_max_depth": 2,

}


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

def load_config(state_file=None, run_dir=None):
    """Load pipeline config, merging per-run overrides from mapper state.

    Args:
        state_file: explicit path to a state file (takes precedence).
        run_dir: path to a run directory; state file is resolved inside it.
            If neither is given, returns defaults (no auto-detection).

    Returns a dict with all threshold keys populated (defaults + overrides).
    """
    config = dict(DEFAULTS)

    # Resolve state file path
    state_path = None
    if state_file:
        state_path = Path(state_file) if isinstance(state_file, str) else state_file
    elif run_dir:
        from ontology_mapper.run_dir_utils import state_path_for
        state_path = state_path_for(run_dir)
    # If neither state_file nor run_dir given, return defaults.
    # No auto-detection — concurrent sessions must be explicit.

    if state_path and state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            overrides = state.get("thresholds", {})
            for key, value in overrides.items():
                if key in config:
                    config[key] = value
        except (json.JSONDecodeError, KeyError) as e:
            print(f"  Warning: Could not load threshold overrides from {state_path}: {e}")

    return config
