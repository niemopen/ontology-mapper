#!/usr/bin/env python3
"""OntologyMapper Pipeline Runner.

Manages the end-to-end compilation pipeline from internal ontology
to target-ontology-aligned edge package. Tracks progress, supports resume/replay/jump,
and progressively collects required inputs.

Usage:
    om-pipeline --organization redvale --source dbpi \\
        --input-package-path sources/redvale_dbpi_agency_package  # New run
    om-pipeline rerun --run-dir X  # Resume a specific run
    om-pipeline rerun --organization redvale --stage 3  # Jump to stage 3
    om-pipeline status --run-dir X   # Show progress for a run
    om-pipeline replay --run-dir X   # Re-run last completed stage
    om-pipeline help                 # Show all stages and commands

    rerun/status/replay require --run-dir <path> or --organization <org>
    to target a run. With one org, the most recent run for that org is used.

    State is stored per-run: .mapper-runs/{run_id}/.mapper-state.json
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from ontology_mapper.pipeline_context import PipelineContext
from ontology_mapper.run_dir_utils import STATE_FILENAME, RUNS_ROOT, resolve_run_dir, load_state, state_path_for, resolve_specs_dir
SPECS_DIR = resolve_specs_dir()

# Ensure UTF-8 output on Windows
if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if sys.stderr.encoding != "utf-8":
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Stage definitions
# ---------------------------------------------------------------------------

@dataclass
class StageSpec:
    """Immutable definition of a pipeline stage."""
    number: str          # "1", "2", "3", "4", "5", "6", "7", "8"
    name: str
    description: str
    inputs: list[str]    # Human-readable list of what this stage needs
    outputs: list[str]   # Human-readable list of what this stage produces
    requires_human_review: bool = False

    @property
    def sort_key(self) -> tuple:
        """Sortable representation of the stage number."""
        parts = self.number.replace("b", ".1").split(".")
        return tuple(int(p) for p in parts)


STAGES: list[StageSpec] = [
    StageSpec(
        number="1",
        name="Ingest",
        description="Read raw domain materials and produce a normalized source inventory.",
        inputs=[
            "input_package_path  — path to the input package (ontology or CSV) "
            "(e.g. sources/redvale_dbpi_agency_package)",
        ],
        outputs=["Normalized source inventory (file manifest + type classification)"],
    ),
    StageSpec(
        number="2",
        name="Extract",
        description="Analyze normalized sources and extract a domain concept inventory.",
        inputs=["Normalized source inventory from Stage 1"],
        outputs=["Domain concept inventory (classes, properties, codelists, workflows)"],
    ),
    StageSpec(
        number="3",
        name="Align",
        description=(
            "Prepare alignment workspace; perform semantic alignment "
            "against the target ontology reference catalog."
        ),
        inputs=[
            "Domain concept inventory from Stage 2",
            "target_ontology       — Target ontology name (e.g. niem, sali-folio)",
            "target_version        — Target ontology version (e.g. 6.0, 2.0)",
        ],
        outputs=["Alignment report (semantic alignment)"],
    ),
    StageSpec(
        number="4",
        name="Decide",
        description=(
            "Apply decision rules to the alignment report to produce "
            "the mapping matrix and extension decisions."
        ),
        inputs=["Alignment report from Stage 3"],
        outputs=["Mapping matrix (mapping-matrix.json)", "Extension decisions"],
    ),
    StageSpec(
        number="5",
        name="Review",
        description=(
            "MANDATORY. Present the mapping matrix grouped by action "
            "(reuse/extend/augment) for human review. The pipeline pauses "
            "here until the user approves."
        ),
        inputs=["Mapping matrix from Stage 4"],
        outputs=["User-approved mapping matrix"],
        requires_human_review=True,
    ),
    StageSpec(
        number="6",
        name="Generate",
        description=(
            "Generate edge package artifacts from the approved mapping matrix "
            "and internal ontology: OWL/TTL modules, CMF, graph scripts, shapes."
        ),
        inputs=[
            "Approved mapping matrix from Stage 5",
        ],
        outputs=["Edge package directory with ontology, CMF, mappings, shapes, kg, contracts"],
    ),
    StageSpec(
        number="7",
        name="Validate",
        description=(
            "Run conformance checks: Turtle syntax, SHACL, CMF validity, "
            "round-trip, mapping completeness, target IRI verification."
        ),
        inputs=["Edge package from Stage 6"],
        outputs=["Conformance report"],
    ),
    StageSpec(
        number="8",
        name="Finalize",
        description=(
            "Stamp governance metadata: version and lineage manifests, "
            "change-impact analysis, final stats reconciliation."
        ),
        inputs=["Validated edge package from Stage 7"],
        outputs=["Versioned edge package ready for consumption"],
    ),
]

STAGE_MAP: dict[str, StageSpec] = {s.number: s for s in STAGES}
STAGE_ORDER: list[str] = [s.number for s in sorted(STAGES, key=lambda s: s.sort_key)]


def stage_index(number: str) -> int:
    """Return the ordinal index of a stage number in STAGE_ORDER."""
    return STAGE_ORDER.index(number)


# ---------------------------------------------------------------------------
# Pipeline state
# ---------------------------------------------------------------------------

# STATE_FILENAME is imported from run_dir_utils


@dataclass
class StageResult:
    """Outcome of a single stage execution."""
    stage: str
    status: str  # "completed", "failed", "skipped", "pending_review", "pending"
    started_at: str
    completed_at: Optional[str] = None
    error: Optional[str] = None
    artifacts: list[str] = field(default_factory=list)
    notes: Optional[str] = None


@dataclass
class PipelineState:
    """Persistent state for a pipeline run."""
    run_id: str
    created_at: str
    updated_at: str

    # User-provided inputs (collected progressively)
    inputs: dict[str, str] = field(default_factory=dict)

    # Stage results keyed by stage number
    stages: dict[str, dict[str, Any]] = field(default_factory=dict)

    # The highest stage number completed successfully
    highest_completed: Optional[str] = None

    # The current / last-attempted stage
    current_stage: Optional[str] = None

    # Evaluation config (model, concurrency, search params) — set by om-orchestrate-eval
    orchestration_config: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def new(cls, organization: str = "") -> "PipelineState":
        now = datetime.now(timezone.utc).isoformat()
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        # Include org prefix only when runs are in the default flat directory.
        # When OM_RUNS_DIR is set (e.g., web UI org-scoped dirs),
        # the org is already the parent directory — no prefix needed.
        if organization and not os.environ.get("OM_RUNS_DIR"):
            run_id = f"{organization}_{timestamp}"
        else:
            run_id = timestamp
        return cls(run_id=run_id, created_at=now, updated_at=now)

    @classmethod
    def load(cls, path: Path) -> "PipelineState":
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(**data)

    def save(self, path: Path) -> None:
        self.updated_at = datetime.now(timezone.utc).isoformat()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(asdict(self), indent=2, default=str) + "\n",
            encoding="utf-8",
        )

    def record_stage(self, result: StageResult) -> None:
        self.stages[result.stage] = asdict(result)
        self.current_stage = result.stage
        if result.status == "completed":
            if (
                self.highest_completed is None
                or stage_index(result.stage) > stage_index(self.highest_completed)
            ):
                self.highest_completed = result.stage

    def stage_status(self, number: str) -> Optional[str]:
        entry = self.stages.get(number)
        return entry["status"] if entry else None

    def next_stage(self) -> Optional[str]:
        """Return the next stage to run, or None if pipeline is complete."""
        if self.highest_completed is None:
            return STAGE_ORDER[0]
        idx = stage_index(self.highest_completed)
        if idx + 1 < len(STAGE_ORDER):
            return STAGE_ORDER[idx + 1]
        return None

    def can_jump_to(self, number: str) -> bool:
        """True if the stage has been reached (completed or attempted) before."""
        if number == STAGE_ORDER[0]:
            return True
        # Can jump to any stage up to and including highest_completed + 1
        if self.highest_completed is None:
            return number == STAGE_ORDER[0]
        max_idx = stage_index(self.highest_completed) + 1
        target_idx = stage_index(number)
        return target_idx <= max_idx


# ---------------------------------------------------------------------------
# Input collection
# ---------------------------------------------------------------------------

def discover_catalogs():
    """Find all available reference catalogs in specs/.

    Returns a list of (ontology_name, version) tuples.
    """
    results = []
    for path in sorted(SPECS_DIR.glob("*_reference_catalog_*.json")):
        match = re.search(r'^(.+)_reference_catalog_(.+)\.json$', path.name)
        if match:
            results.append((match.group(1), match.group(2)))
    return results


def catalog_exists(ontology_name, version):
    """Check if a reference catalog exists for the given ontology and version."""
    path = SPECS_DIR / f"{ontology_name}_reference_catalog_{version}.json"
    return path.exists()


# Map of input_key → (prompt_text, required_for_stages, default_value)
# Note: organization and source are collected at init (before Stage 1) because
# the organization prefix is used in the run_id (e.g. redvale_20260322-223523).
INPUT_SPECS: list[tuple[str, str, list[str], Optional[str]]] = [
    (
        "organization",
        "Organization identifier (e.g. redvale)",
        ["1"],
        None,
    ),
    (
        "source",
        "Source identifier (e.g. dbpi)",
        ["1"],
        None,
    ),
    (
        "input_package_path",
        "Path to the input package (ontology or CSV-based)",
        ["1"],
        None,
    ),
    (
        "target_ontology",
        "Target ontology name (e.g. niem, sali-folio)",
        ["3"],
        None,
    ),
    (
        "target_version",
        "Target ontology version (e.g. 6.0, 2.0)",
        ["3"],
        None,
    ),
]


def check_inputs_for_stage(state: PipelineState, stage_number: str) -> bool:
    """Check that all inputs required by the given stage are present in state.

    Returns True if all inputs are satisfied, False if any are missing.
    """
    needed = [
        (key, prompt)
        for key, prompt, stages, default in INPUT_SPECS
        if stage_number in stages and key not in state.inputs
    ]

    if not needed:
        return True

    print(f"  Error: Missing required inputs for Stage {stage_number}:")
    for key, prompt in needed:
        flag = f"--{key.replace('_', '-')}"
        print(f"    {flag}  ({prompt})")
    print(f"\n  Pass these flags to om-pipeline or om-pipeline rerun.")
    return False


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def print_banner() -> None:
    print()
    print("=" * 64)
    print("  OntologyMapper Pipeline")
    print("=" * 64)
    print()


def print_stage_table(state: Optional[PipelineState] = None) -> None:
    """Print all stages with their status."""
    print(f"  {'#':<5} {'Name':<22} {'Status':<16}")
    print(f"  {'─'*5} {'─'*22} {'─'*16}")
    for number in STAGE_ORDER:
        spec = STAGE_MAP[number]
        status = "—"
        marker = " "
        if state:
            s = state.stage_status(number)
            if s:
                status = s
            if state.current_stage == number:
                marker = "→"
            elif state.next_stage() == number:
                marker = "▸"
        review = " [human review]" if spec.requires_human_review else ""
        print(f" {marker}{number:<5} {spec.name:<22} {status:<16}{review}")
    print()


def print_status(state: PipelineState) -> None:
    """Print detailed pipeline status."""
    print_banner()
    print(f"  Run ID:    {state.run_id}")
    print(f"  Created:   {state.created_at}")
    print(f"  Updated:   {state.updated_at}")
    if state.highest_completed:
        print(f"  Completed: up to Stage {state.highest_completed} "
              f"({STAGE_MAP[state.highest_completed].name})")
    else:
        print(f"  Completed: (none)")
    nxt = state.next_stage()
    if nxt:
        print(f"  Next:      Stage {nxt} ({STAGE_MAP[nxt].name})")
    else:
        print(f"  Next:      Pipeline complete!")
    print()

    if state.inputs:
        print("  Inputs:")
        for k, v in state.inputs.items():
            print(f"    {k}: {v}")
        print()

    print_stage_table(state)


def print_help() -> None:
    """Print help for all commands and stages."""
    print_banner()
    print("  Commands:")
    print("    (no command)         Start a new pipeline run")
    print("    rerun                Resume a run (requires --run-dir or --organization)")
    print("    rerun --stage N      Jump to stage N (must have reached it)")
    print("    rerun --run-dir X    Resume a specific run directory")
    print("    replay               Re-run the last completed stage")
    print("    status               Show current pipeline progress")
    print("    help                 Show this help message")
    print()
    print("  Init flags (no subcommand):")
    print("    --organization ORG         Organization identifier (required)")
    print("    --source SOURCE            Source identifier (required)")
    print("    --input-package-path PATH  Path to input package (required)")
    print("    --target-ontology NAME     Target ontology (e.g. niem, sali-folio)")
    print("    --target-version VER      Target version (e.g. 6.0, 2.0)")
    print()
    print("  Run resolution (rerun/status/replay):")
    print("    --run-dir X          Use the specified directory directly")
    print("    --organization ORG   Select org when multiple exist")
    print("    (one org)            Selects the most recent run for that org")
    print()
    print("  Stages:")
    print()
    for number in STAGE_ORDER:
        spec = STAGE_MAP[number]
        review = " ★ HUMAN REVIEW" if spec.requires_human_review else ""
        print(f"  Stage {number}: {spec.name}{review}")
        print(f"    {spec.description}")
        if spec.inputs:
            print(f"    Inputs:")
            for inp in spec.inputs:
                print(f"      • {inp}")
        if spec.outputs:
            print(f"    Outputs:")
            for out in spec.outputs:
                print(f"      • {out}")
        print()


# ---------------------------------------------------------------------------
# Stage execution stubs
# ---------------------------------------------------------------------------

def execute_stage(state: PipelineState, stage_number: str) -> StageResult:
    """Execute a pipeline stage.

    Each stage is implemented as a call to the appropriate om-* CLI tool.
    This runner manages pipeline state and I/O — the actual semantic work
    is performed by the evaluation service.

    Returns a StageResult with the outcome.
    """
    spec = STAGE_MAP[stage_number]
    now = datetime.now(timezone.utc).isoformat()

    print(f"\n{'─' * 64}")
    print(f"  Stage {stage_number}: {spec.name}")
    print(f"  {spec.description}")
    print(f"{'─' * 64}\n")

    # Collect any missing inputs for this stage
    if not check_inputs_for_stage(state, stage_number):
        return StageResult(
            stage=stage_number,
            status="failed",
            started_at=now,
            completed_at=datetime.now(timezone.utc).isoformat(),
            error="Input collection cancelled by user.",
        )

    # Dispatch to stage-specific handler
    handler = STAGE_HANDLERS.get(stage_number)
    if handler is None:
        print(f"  Stage {stage_number} has no built-in handler.")
        print(f"  Run the appropriate tools directly, then mark complete.")
        print()
        return StageResult(
            stage=stage_number,
            status="pending",
            started_at=now,
            completed_at=None,
            notes="Run tools directly, then mark complete.",
        )

    return handler(state, spec, now)


def _handle_ingest(state: PipelineState, spec: StageSpec, started: str) -> StageResult:
    """Stage 1: Ingest — scan the input package and build a source inventory."""
    pkg_path = Path(state.inputs["input_package_path"])

    # Check if this is a CSV-based package (skip OWL validation if so)
    has_input_csv = (pkg_path / "input").is_dir() and any((pkg_path / "input").glob("*.csv"))

    if has_input_csv:
        # CSV-based package: verify CSV files are present
        csv_files = list((pkg_path / "input").glob("*.csv"))
        print(f"  CSV package detected: {len(csv_files)} CSV file(s) in input/")
    else:
        # OWL-based package: run standard RDF/OWL validation
        from ontology_mapper.validate_input_package import validate_input_package, format_findings
        findings = validate_input_package(pkg_path)
        errors = [f for f in findings if f["severity"] == "error"]
        if errors:
            print(format_findings(findings))
            return StageResult(
                stage=spec.number,
                status="failed",
                started_at=started,
                completed_at=datetime.now(timezone.utc).isoformat(),
                error=f"Input validation failed: {errors[0]['code']} — {errors[0]['message']}",
            )
        if findings:
            print(format_findings(findings))

    # Build file inventory
    inventory: dict[str, list[str]] = {
        "ontology": [],
        "shapes": [],
        "vocab": [],
        "seed_data": [],
        "contexts": [],
        "workflows": [],
        "docs": [],
        "input_csv": [],
        "other": [],
    }

    classification_rules = {
        "ontology": lambda p: p.parent.name == "ontology" and p.suffix == ".ttl",
        "shapes": lambda p: p.parent.name == "shapes" and p.suffix == ".ttl",
        "vocab": lambda p: p.parent.name == "vocab" and p.suffix == ".ttl",
        "seed_data": lambda p: "seed" in p.parent.name and p.suffix == ".ttl",
        "contexts": lambda p: p.suffix == ".jsonld",
        "workflows": lambda p: "workflow" in p.name.lower() and p.suffix == ".ttl",
        "docs": lambda p: p.suffix in (".md", ".txt", ".pdf"),
        "input_csv": lambda p: p.parent.name == "input" and p.suffix == ".csv",
    }

    file_count = 0
    for root, _dirs, files in os.walk(pkg_path):
        for fname in sorted(files):
            fpath = Path(root) / fname
            rel = fpath.relative_to(pkg_path)
            classified = False
            for category, rule in classification_rules.items():
                if rule(fpath):
                    inventory[category].append(str(rel))
                    classified = True
                    break
            if not classified:
                inventory["other"].append(str(rel))
            file_count += 1

    # Detect input type: CSV (tabular model) vs OWL (ontology)
    input_type = "owl"  # default
    if inventory["input_csv"]:
        input_type = "csv"

    # Store input type in state for downstream stages
    state.inputs["input_type"] = input_type

    # Write inventory to state directory
    output_dir = _get_run_dir(state)
    output_dir.mkdir(parents=True, exist_ok=True)
    inv_path = output_dir / "source-inventory.json"
    inv_data = {
        "input_package": str(pkg_path),
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "total_files": file_count,
        "input_type": input_type,
        "inventory": inventory,
    }
    inv_path.write_text(json.dumps(inv_data, indent=2) + "\n", encoding="utf-8")

    # Summary
    print(f"  Scanned: {pkg_path}")
    print(f"  Input type: {input_type}")
    print(f"  Total files: {file_count}")
    for cat, files in inventory.items():
        if files:
            print(f"    {cat}: {len(files)} file(s)")
    print(f"\n  Inventory written to: {inv_path}")

    return StageResult(
        stage=spec.number,
        status="completed",
        started_at=started,
        completed_at=datetime.now(timezone.utc).isoformat(),
        artifacts=[str(inv_path)],
        notes=f"Found {file_count} files across {sum(1 for v in inventory.values() if v)} categories.",
    )


def _handle_human_review_gate(
    state: PipelineState, spec: StageSpec, started: str
) -> StageResult:
    """Stage 5: Human Review Gate.

    This stage is managed by run_pipeline.py (interactive review loop) or
    _present_and_apply_human_review.py (manual CLI). The pipeline CLI sets
    status to pending_review; the review tool presents results to the human,
    processes their decisions, then reruns to advance past this gate.
    """
    run_dir = _get_run_dir(state)
    review_artifacts = [
        "mapping-matrix.json",
        "alignment-report.json",
    ]
    print("  Human review gate reached.")
    print("  Artifacts for review:")
    for art in review_artifacts:
        art_path = run_dir / art
        exists = "✓" if art_path.exists() else "—"
        print(f"    [{exists}] {art_path}")

    # Check if review has been completed (all entries accepted)
    matrix_path = run_dir / "mapping-matrix.json"
    if matrix_path.exists():
        import json
        matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
        all_accepted = all(
            e.get("reviewStatus") == "accepted"
            for e in matrix.get("mappings", [])
        )
        if all_accepted and matrix.get("mappings"):
            print("  All mapping entries accepted. Review gate passed.")
            return StageResult(
                stage=spec.number,
                status="completed",
                started_at=started,
                completed_at=datetime.now(timezone.utc).isoformat(),
                notes="All entries accepted — review gate passed.",
            )

    print("\n  Review not yet complete. Use run_pipeline.py or _present_and_apply_human_review.py")
    print("  to process human decisions, then rerun to advance.")
    return StageResult(
        stage=spec.number,
        status="pending_review",
        started_at=started,
        completed_at=datetime.now(timezone.utc).isoformat(),
        notes="Awaiting human review.",
    )


def _handle_bootstrap_output(
    state: PipelineState, spec: StageSpec, started: str
) -> StageResult:
    """Stage 6 pre-step: bootstrap the edge package directory structure."""
    run_dir = _get_run_dir(state)
    ctx = PipelineContext.from_inputs(state.inputs, run_dir=run_dir)
    output_path = ctx.pkg_dir

    dirs_to_create = [
        "cmf",
        "ontology",
        "mappings",
        "extensions",
        "schemas/json",
        "schemas/xml",
        "schemas/jsonld",
        "kg/neo4j/queries",
        "kg/rdf/sparql",
        "kg/import",
        "shapes",
        "vocab",
        "contracts",
        "governance",
        "tests/fixtures/valid",
        "tests/fixtures/invalid",
        "tests/conformance",
        "tests/graph-integrity",
        "docs",
    ]

    created = []
    for d in dirs_to_create:
        p = output_path / d
        if not p.exists():
            p.mkdir(parents=True, exist_ok=True)
            created.append(str(d))

    # Write initial package-manifest.json if not present
    manifest_path = output_path / "package-manifest.json"
    if not manifest_path.exists():
        manifest = {
            "name": ctx.edge_package_name,
            "version": "0.1.0",
            "description": ctx.description,
            "sourcePackage": ctx.agency_package_name,
            "targetOntology": ctx.target_ontology,
            "targetVersion": ctx.target_version,
            "targetDomains": [],
            "targetGraphPlatforms": ["neo4j", "rdf"],
            "generatedBy": "ontology-mapper",
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "extensionNamespace": ctx.extension_namespace,
            "edgeNamespace": ctx.edge_namespace,
            "stats": {
                "totalConcepts": 0,
                "targetMapped": 0,
                "targetExtended": 0,
            },
        }
        manifest_path.write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )
        created.append("package-manifest.json")

    print(f"  Edge package bootstrapped at: {output_path}")
    print(f"  Created {len(created)} directories/files.")

    return StageResult(
        stage=spec.number,
        status="completed",
        started_at=started,
        completed_at=datetime.now(timezone.utc).isoformat(),
        artifacts=created,
        notes=f"Edge package bootstrapped with {len(created)} directories/files.",
    )


# ---------------------------------------------------------------------------
# Stage handler dispatch
# ---------------------------------------------------------------------------

# Stages that have automated handlers get registered here.
# Stages without handlers (2-4, 6-8) are executed by Claude Code interactively.
STAGE_HANDLERS = {
    "1": _handle_ingest,
    "5": _handle_human_review_gate,
}


# ---------------------------------------------------------------------------
# Run directory
# ---------------------------------------------------------------------------

def _get_run_dir(state: PipelineState) -> Path:
    """Return the working directory for intermediate pipeline artifacts."""
    return RUNS_ROOT / state.run_id


def _resolve_org(org_flag: Optional[str] = None) -> Optional[str]:
    """Resolve the organization for run directory lookup.

    If org_flag is provided, use it. Otherwise auto-select if only one org
    exists. Error if multiple orgs and no flag.
    """
    from ontology_mapper.run_dir_utils import list_orgs
    orgs = list_orgs()
    if org_flag:
        if org_flag in orgs:
            return org_flag
        print(f"  Error: Organization '{org_flag}' not found.")
        if orgs:
            print(f"  Available: {', '.join(orgs)}")
        return None
    if len(orgs) <= 1:
        return orgs[0] if orgs else None
    print("  Error: Multiple organizations found. Pass --organization to select one:")
    for org in orgs:
        print(f"    --organization {org}")
    return None


def _find_state_file(run_dir: Optional[str] = None, org_flag: Optional[str] = None) -> Optional[Path]:
    """Find a pipeline state file.

    If *run_dir* is given, look inside that directory.
    Otherwise resolve via org disambiguation and most-recent-first sort.
    """
    # Explicit run dir
    if run_dir:
        candidate = Path(run_dir) / STATE_FILENAME
        if candidate.exists():
            return candidate
        return None

    # Org-aware: find most recent run for the specified org
    org = _resolve_org(org_flag)
    if org is None:
        return None

    from ontology_mapper.run_dir_utils import _list_run_dirs, _org_from_dirname
    for d in _list_run_dirs():
        if _org_from_dirname(d.name) == org:
            candidate = state_path_for(d)
            if candidate.exists():
                return candidate

    return None


# ---------------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------------

def cmd_init(args: argparse.Namespace) -> int:
    """Initialize a new pipeline run.  Always creates a new run directory."""
    print_banner()
    print("  Initializing new pipeline run...")

    # Validate required inputs
    org = getattr(args, "organization", None)
    source = getattr(args, "source", None)
    input_path = getattr(args, "input_package_path", None)
    target_ont = getattr(args, "target_ontology", None) or "niem"
    target_ver = getattr(args, "target_version", None) or "6.0"

    missing = []
    if not org:
        missing.append("--organization")
    if not source:
        missing.append("--source")
    if not input_path:
        missing.append("--input-package-path")
    if missing:
        print(f"  Error: Missing required flags: {', '.join(missing)}")
        print(f"\n  Usage: om-pipeline --organization ORG --source SOURCE "
              f"--input-package-path PATH [--target-ontology NAME] [--target-version VER]")
        return 1

    # Validate reference catalog exists
    if not catalog_exists(target_ont, target_ver):
        print(f"  Error: No reference catalog found for {target_ont} {target_ver}.")
        print(f"  Generate one first (NIEM: om-generate-catalog, OWL: om-generate-owl-catalog)")
        return 1

    collected_inputs = {
        "organization": org,
        "source": source,
        "input_package_path": input_path,
        "target_ontology": target_ont,
        "target_version": target_ver,
    }

    # Create state with organization prefix in run_id
    state = PipelineState.new(organization=org)
    state.inputs = collected_inputs

    # Create run directory and save state inside it
    run_dir = _get_run_dir(state)
    run_dir.mkdir(parents=True, exist_ok=True)
    state_path = state_path_for(run_dir)
    state.save(state_path)

    print(f"\n  Pipeline initialized.")
    print(f"  Run ID:     {state.run_id}")
    print(f"  Run dir:    {run_dir}")
    print(f"  Edge pkg:   {run_dir / 'edge-package'}")
    print(f"\n  Next: run 'om-pipeline rerun' to start Stage 1.")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """Show current pipeline status."""
    state_path = _find_state_file(getattr(args, "run_dir", None), getattr(args, "organization", None))
    if not state_path:
        print("  No existing pipeline runs. Ready to initialize a new run.")
        return 0

    state = PipelineState.load(state_path)
    print_status(state)
    return 0


def cmd_rerun(args: argparse.Namespace) -> int:
    """Resume an existing pipeline run (or jump to a specific stage)."""
    state_path = _find_state_file(getattr(args, "run_dir", None), getattr(args, "organization", None))
    if not state_path:
        print("  No pipeline run found. Run 'om-pipeline' to start a new one.")
        return 1

    state = PipelineState.load(state_path)
    target = args.stage

    if target:
        if target not in STAGE_MAP:
            print(f"  Error: Unknown stage '{target}'.")
            print(f"  Valid stages: {', '.join(STAGE_ORDER)}")
            return 1
        if not state.can_jump_to(target):
            highest = state.highest_completed or "(none)"
            print(f"  Error: Cannot jump to Stage {target}.")
            print(f"  Highest completed stage: {highest}")
            print(f"  You can only jump to stages you've already reached.")
            return 1
        stage_number = target
    else:
        # Check if last stage was pending_review — resume there
        if state.current_stage and state.stage_status(state.current_stage) == "pending_review":
            stage_number = state.current_stage
        else:
            stage_number = state.next_stage()
        if stage_number is None:
            print("  Pipeline is complete! All stages finished.")
            print_stage_table(state)
            return 0

    print_banner()
    print(f"  Resuming pipeline run: {state.run_id}")
    print(f"  Target: Stage {stage_number} ({STAGE_MAP[stage_number].name})")

    # For Generate stage, bootstrap the output directory first
    if stage_number == "6":
        if not check_inputs_for_stage(state, "6"):
            print("  Input collection cancelled.")
            return 1
        _handle_bootstrap_output(state, STAGE_MAP["6"], datetime.now(timezone.utc).isoformat())

    result = execute_stage(state, stage_number)
    state.record_stage(result)
    state.save(state_path)

    print(f"\n  Stage {stage_number} result: {result.status}")
    if result.error:
        print(f"  Error: {result.error}")
    if result.notes:
        print(f"  Notes: {result.notes}")

    nxt = state.next_stage()
    if nxt:
        print(f"\n  Next: Stage {nxt} ({STAGE_MAP[nxt].name})")
        print(f"  Run 'om-pipeline rerun' to continue.")
    else:
        print(f"\n  Pipeline complete!")

    return 0 if result.status in ("completed", "pending_review", "pending") else 1


def cmd_replay(args: argparse.Namespace) -> int:
    """Re-run the last completed stage."""
    state_path = _find_state_file(getattr(args, "run_dir", None), getattr(args, "organization", None))
    if not state_path:
        print("  No pipeline run found. Run 'om-pipeline' to start a new one.")
        return 1

    state = PipelineState.load(state_path)

    replay_target = state.highest_completed or state.current_stage
    if not replay_target:
        print("  Nothing to replay — no stages have been run yet.")
        return 1

    print_banner()
    print(f"  Replaying Stage {replay_target} ({STAGE_MAP[replay_target].name})")

    result = execute_stage(state, replay_target)
    state.record_stage(result)
    state.save(state_path)

    print(f"\n  Replay result: {result.status}")
    if result.error:
        print(f"  Error: {result.error}")

    return 0 if result.status in ("completed", "pending_review", "pending") else 1


def cmd_mark_complete(args: argparse.Namespace) -> int:
    """Mark a pipeline stage as completed with timing."""
    state_path = _find_state_file(getattr(args, "run_dir", None), getattr(args, "organization", None))
    if not state_path:
        print("  No pipeline run found.")
        return 1

    state = PipelineState.load(state_path)
    stage_number = args.stage

    if stage_number not in STAGE_MAP:
        print(f"  Error: Unknown stage '{stage_number}'.")
        return 1

    now = datetime.now(timezone.utc).isoformat()

    # Update existing stage entry or create new one
    existing = state.stages.get(stage_number)
    if existing:
        existing["status"] = "completed"
        existing["completed_at"] = now
        if args.notes:
            existing["notes"] = args.notes
    else:
        result = StageResult(
            stage=stage_number,
            status="completed",
            started_at=now,
            completed_at=now,
            notes=args.notes,
        )
        state.stages[stage_number] = asdict(result)

    state.current_stage = stage_number
    if (
        state.highest_completed is None
        or stage_index(stage_number) > stage_index(state.highest_completed)
    ):
        state.highest_completed = stage_number

    state.save(state_path)
    print(f"  Stage {stage_number} marked complete at {now}")
    return 0


def cmd_help(args: argparse.Namespace) -> int:
    """Show help."""
    print_help()
    return 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        prog="pipeline",
        description="OntologyMapper Pipeline Runner",
    )
    # Init flags (used when no subcommand — creates a new run)
    parser.add_argument("--organization", type=str, default=None,
                        help="Organization identifier (e.g. redvale, ncsc)")
    parser.add_argument("--source", type=str, default=None,
                        help="Source identifier (e.g. dbpi, nods)")
    parser.add_argument("--input-package-path", type=str, default=None,
                        help="Path to the input package (e.g. sources/redvale_dbpi_agency_package)")
    parser.add_argument("--target-ontology", type=str, default=None,
                        help="Target ontology name (e.g. niem, sali-folio, nods)")
    parser.add_argument("--target-version", type=str, default=None,
                        help="Target ontology version (e.g. 6.0, 2.0, 1.0)")

    subparsers = parser.add_subparsers(dest="command")

    # Common arguments for run-dir and org selection
    def add_common_args(p):
        p.add_argument(
            "--run-dir",
            type=str,
            default=None,
            help="Path to a specific run directory (default: most recent)",
        )
        p.add_argument(
            "--organization",
            type=str,
            default=None,
            help="Organization to select when multiple exist",
        )

    # rerun
    rerun_parser = subparsers.add_parser("rerun", help="Resume an existing pipeline run")
    rerun_parser.add_argument(
        "--stage", "-s",
        type=str,
        default=None,
        help="Jump to a specific stage number (e.g. 3, 4, 5)",
    )
    add_common_args(rerun_parser)

    # status
    status_parser = subparsers.add_parser("status", help="Show current pipeline progress")
    add_common_args(status_parser)

    # replay
    replay_parser = subparsers.add_parser("replay", help="Re-run the last completed stage")
    add_common_args(replay_parser)

    # mark-complete
    mc_parser = subparsers.add_parser("mark-complete",
                                       help="Mark a pipeline stage as completed")
    mc_parser.add_argument("--stage", "-s", type=str, required=True,
                           help="Stage number to mark complete")
    mc_parser.add_argument("--notes", type=str, default=None,
                           help="Optional notes about what was done")
    add_common_args(mc_parser)

    # help
    subparsers.add_parser("help", help="Show detailed help")

    args = parser.parse_args()

    commands = {
        "rerun": cmd_rerun,
        "status": cmd_status,
        "replay": cmd_replay,
        "mark-complete": cmd_mark_complete,
        "help": cmd_help,
        None: cmd_init,  # Default: start a new run
    }

    handler = commands.get(args.command)
    if handler is None:
        print_help()
        return 0

    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
