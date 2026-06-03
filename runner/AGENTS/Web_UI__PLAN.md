# Web UI Plan

> **Goal**: A web application that exposes the OntologyMapper pipeline as a
> self-service tool. Users upload a source domain, choose a target domain, run
> the pipeline, review and approve all decisions, and download the resulting
> edge package.

---

## User Journey

### 1. Register and Login

User creates an account. Work is persisted across sessions — a mapping review
that takes days picks up where it left off.

### 2. Upload Source Domain Artifacts

User uploads the artifacts that represent their domain: OWL files, SHACL
shapes, or other ontology formats the pipeline can inventory. The system runs
Stage 1 (concept inventory) on upload.

### 3. Choose Target Domain

User selects a target domain from the catalog of available targets. User can
also request a new target domain be added to the catalog.

The source is unconstrained — it is whatever the user uploads. The system
makes no assumptions about source format beyond what the inventory step can
parse. More target domains may be added — each is defined by a reference catalog
that specifies valid actions, type patterns, and structural scaffolding
rules. Adding a new target requires a reference catalog and a vector index
of its types and properties.

### 4. Run Pipeline

User clicks to start the pipeline. Stages 2-4 run server-side:

- Stage 2: Build strategy from reference catalog
- Stage 3: Semantic alignment (LLM evaluates each concept against target)
- Stage 4: Build mapping matrix

The user sees progress as each stage completes.

### 5. Review and Approve

This is the primary UI surface. The mapping matrix is presented as an
interactive view:

- Class-level decisions grouped by action (reuse, augment, extend)
- Property-level decisions within each class
- **UNDECIDED properties highlighted** — these are `human-must-decide` items
  where the LLM found multiple equally good candidates
- Vector search candidates displayed for each decision, showing what the LLM
  considered and why
- **Custom search**: typeahead against the target catalog for any property
  decision — user types characters, list filters by domain and name, shows
  results only when under 20 matches
- **Target type change**: user can select a different target type for any
  concept. Property matches are not re-evaluated — they are reclassified
  against the new type's property list (on-target vs elsewhere vs not-found),
  the action recomputes, and the updated entry is presented for review. No
  vector search or LLM calls required.
- **Per-concept entropy**: show pre-rotation entropy (log₂ of candidate count
  from batch search) alongside each concept during review. High entropy
  explains why a decision is hard — the LLM had many plausible candidates.
  (Action Plan Item 3)
- **Reviewer confidence**: each decision has radio buttons — **Confident**
  (default) or **Best Guess**. "Best guess" means the reviewer made a
  reasonable choice but would want verification. Best-guess decisions carry
  residual entropy; confident decisions collapse to zero. The confidence
  signal travels with the edge package as metadata.
- **Residual entropy summary**: after all decisions are finalized, show the
  run-level delta (pre − post entropy) — the measured information value of
  the full rotation. Residual entropy is driven by best-guess decisions and
  quantifies unresolved ambiguity that travels with the edge package.
  (Action Plan Item 5)
- **Approve All** is only available when zero `human-must-decide` properties
  remain — user must resolve each one individually first
- Submission is blocked until all required decisions are made

### 6. Re-run and Iteration

User downloads artifacts, tries them in their system, returns to adjust
decisions. The prior decisions are loaded as defaults — the user refines
rather than starting over. This is already supported by the
`human-review-decisions.json` replay file.

A re-run may also be triggered by a new version of the target domain. The
system detects which decisions are affected by target changes (codebook
version fingerprinting, Action Plan Item 6) and presents only those for
re-review.

### 7. Download Artifacts

Once all decisions are approved, Stages 6-8 run server-side:

- Stage 6: Generate artifacts (OWL, CMF, message catalog)
- Stage 7: Validate generated artifacts
- Stage 8: Finalize edge package

User downloads the edge package as a zip archive.

---

## Backend Readiness

### Well-Covered (backend exists)

| Step | Backend Support |
|---|---|
| Concept inventory from upload | `om-pipeline rerun --stage 1`, Stage 1 |
| Target domain catalog | Reference catalogs per target, `om-build-strategy` |
| Pipeline execution (Stages 2-4) | `om-*` CLI tools, evaluation service for LLM calls |
| Matrix presentation | `get_pending_items()`, `group_by_action()`, `format_property_review()` |
| Decision application | `apply_property_decision()`, `apply_accept()`, `apply_all_property_accepts()` |
| Target type change cascade | `apply_decision_with_cascade()`, `load_cascade_context()`, `reclassify_for_target_type_change()` |
| `human-must-decide` enforcement | Bulk approve blocked, GA-006 audit blocks generation |
| Decision validation | `validate_class_decision()`, `validate_property_decision()` |
| Summary recomputation | `recompute_summary()` |
| Decision persistence | `save_matrix()`, `human-review-decisions.json` replay file |
| Re-run with prior decisions | Replay file loaded as defaults on subsequent runs |
| Artifact generation (Stages 6-8) | `om-generate-ontology`, `om-package-artifacts`, `om-generate-kg`, `om-validate`, `om-finalize` |
| Pre-rotation entropy | `om-entropy` CLI, `entropy-summary.json` artifact — per-concept and per-property candidate counts and entropy |
| Catalog search | `search_catalog()` in `catalog_search.py` — filters types/properties by query, ranked results, JSON output mode |
| Target domain extensibility | Reference catalog pattern — add catalog + vector index |

### Remains to be Implemented

| Capability | Description | Depends On |
|---|---|---|
| **Custom search** | Typeahead against the target catalog — user types characters, list filters by domain and name, shows results only when under 20 matches. Not a vector search — a catalog lookup. Available on any property decision, not just undecided ones. Backend: `search_catalog()` in `catalog_search.py` (implemented, Action Plan Item 7). Web UI integration remains. | Web UI integration |
| **Candidate display** | Show the candidates the LLM considered for each decision, with definitions and rationale. | Rotation provenance (Action Plan Item 4) |
| **Version-aware re-run** | Detect which decisions are affected by target ontology changes, present only those for re-review. | Codebook version fingerprinting (Action Plan Item 6) |
| **Auth and session persistence** | User accounts, session state, persistent storage for in-progress reviews. | New infrastructure |
| **Progress reporting** | Real-time status as pipeline stages complete. | Service architecture |
| **Artifact packaging and download** | Zip and serve the edge package. | Service architecture |
| **Request new target domain** | Workflow for users to request a target not yet in the catalog. | Catalog management |
| **File upload and validation** | Accept and validate source ontology files. | Service architecture |

---

## Technology Stack

All FOSS, commercially permissive licenses.

- **FastAPI** — Python web framework (MIT). REST API, async, maps directly
  to the existing stateless pipeline functions.
- **PostgreSQL** — Database for user accounts, session state, run persistence
  (PostgreSQL License, permissive).
- **SQLAlchemy** + **Alembic** — ORM and migrations (MIT).
- **Celery** + **Redis** — Background task queue for running pipeline stages
  asynchronously (BSD).
- **React** or **HTMX** — Frontend (MIT/BSD). React for a richer interactive
  review UI; HTMX to stay closer to Python.
- **Anthropic API** — LLM calls for semantic alignment (commercial terms
  allow paid products).

The entire stack runs on Windows 11 for local development. Deploy to
Railway, Render, or similar when ready — use Cloudflare as CDN/proxy in
front.
