# OntologyMapper

A semantic transformation toolchain that reads an organization's **internal domain model** — whether OWL/RDF ontologies or tabular CSV data models — and produces an **edge ontology** aligned to a target standard (e.g., NIEM, SALI/FOLIO), the boundary layer that enables interoperability with external agentic systems.

## How It Works

OntologyMapper operates as a staged pipeline, orchestrated through [Claude Code](https://docs.anthropic.com/en/docs/claude-code). Claude Code drives the entire lifecycle — from ingesting the source ontology, through semantic alignment against the target ontology standard, to the reasoning that determines whether each proposed mapping actually makes sense.

| Stage | Name             | Description                                                                                                                                        |
| ----- | ---------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1     | **Ingest**       | Scan raw domain materials and build a normalized source inventory                                                                                  |
| 2     | **Extract**      | Analyze sources and extract a domain concept inventory                                                                                             |
| 3     | **Align**        | Prepare alignment workspace; orchestrator performs semantic matching against the target ontology catalog                                            |
| 4     | **Decide**       | Format orchestrator decisions into the mapping matrix (reuse / extend / augment) with per-property mappings                                        |
| 5     | **Human Review** | Mandatory review gate — user approves each class and property mapping before generation                                                            |
| 6a    | **Generate OWL** | Produce OWL/TTL modules, CMF, and SHACL shapes with target property IRIs for reuse-property decisions                                              |
| 6b    | **Package**      | Assemble non-OWL artifacts (mappings, extensions, governance, manifest, README)                                                                    |
| 6c    | **Generate KG**  | Produce knowledge graph deployment scripts (Neo4j Cypher, SPARQL, TriG, import config)                                                             |
| 7     | **Validate**     | Run 11 conformance checks (Turtle syntax, SHACL, CMF, mapping completeness, KG cross-references)                                                   |
| 8     | **Finalize**     | Stamp governance artifacts (version manifest, lineage, change-impact, pipeline timing) and reconcile package manifest                               |

### Semantic Alignment (Stage 3)

All matching is performed semantically by the orchestrator (Claude Code). At Stage 3, the orchestrator uses vector search to find candidate target types and properties, then reasons about each source concept to determine the best alignment. There is no algorithmic scoring or filtering — the orchestrator evaluates candidates based on meaning, definitions, and structural fit.

For each source concept, `resolve_alignment()` applies ontology-specific structural rules to determine the action (reuse, extend, or augment). The alignment report carries forward to Stage 4 with all decisions and per-property mappings.

### Human Review (Stage 5)

The human review gate is mandatory. Every pending mapping is presented to the user, grouped by action (reuse, augment, extend) with rationale. The user may approve, modify, or reject any class or property mapping.

Review decisions are saved to `human-review-decisions.json`. *Planned*: on subsequent pipeline runs against the same domain, prior decisions will be loaded as suggestions — shown alongside each pending item with the original rationale, individually accepted or rejected. Prior decisions will never be auto-applied.

### Pipeline Safeguards

The pipeline includes several mechanisms to catch problems early and trace them to their source:

- **Quality gates** run after decision formatting to verify internal consistency (action counts sum correctly). Warnings are saved to `quality-gate-report.json`.
- **Generation audit** runs after Stage 4, before generation. It detects data that would be silently lost — properties dropped because their range type was excluded, reuse classes with zero properties, orphaned properties. Each finding links to the specific decision that caused it.
- **Validation-to-decision traceability** (*Planned*) — map validation failures back to the decisions that caused them. Within a run, the user could adjust decisions and re-run generation. Across runs, prior feedback would be surfaced during human review.

## Quick Start

### Prerequisites

- Python 3.10+
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) (the pipeline orchestration and semantic reasoning engine)

```bash
# Core + validation (Turtle syntax, SHACL conformance)
pip install -e ".[validation]"

# Vector search (FAISS + sentence-transformers for semantic matching at Stage 3)
pip install -e ".[vector]"

# All extras
pip install -e ".[validation,vector]"
```

### Running the Pipeline

The pipeline is run from within **Claude Code**. Open a Claude Code session in the repository root and instruct it to run the pipeline. Claude Code orchestrates each stage, performs semantic extraction (Stages 1-2), semantic alignment (Stage 3), and pauses at the human review gate (Stage 5) for your approval.

```
# Start Claude Code in the repository
claude

# Then instruct it to run the pipeline, for example:
> Initialize a new pipeline run for sources/redvale_dbpi_agency_package
> Run the next stage
> Show pipeline status
```

The pipeline runner (`om-pipeline`) manages state, stage sequencing, and input collection. Claude Code invokes it as part of its orchestration. Running `om-pipeline` with no subcommand always creates a new run directory under `.mapper-runs/`; use `om-pipeline rerun` to resume an existing one. All state and artifacts are stored per-run. Tools require `--run-dir` or `--organization` to target a run — there is no auto-detection, so concurrent sessions stay independent.

### Input Validation

Before Stage 1 begins, the pipeline validates that the input package has the minimum viable data. This catches problems immediately rather than producing cryptic errors downstream. The validator does **not** enforce directory structure, naming conventions, or serialization formats — only that minimum semantic content exists. OWL validation is skipped for CSV-based packages, detected automatically by the presence of an `input/` directory with `.csv` files. See `AGENTS/OM__VALIDATION.md` for the full check table (IV-010 through IV-040).

The validator can also be run standalone before starting a pipeline run:

```bash
om-validate-input sources/my_agency_package
```

### Standalone Tools

```bash
# Regenerate the NIEM reference catalog with GitHub CSV enrichment (--version is required)
om-generate-catalog --version 6.0

# Regenerate without GitHub CSV data (API-only, smaller catalog)
om-generate-catalog --version 6.0 --no-github-csv

# Regenerate using a specific GitHub tag for CSV data
om-generate-catalog --version 6.0 --github-ref 6.0-ps02

# CSV-based source domain ingestion (tabular model -> concept-inventory.json)
om-ingest-csv "sources/NODS NIEM6 Message Specification/input/INPUT.csv" --namespace court

# Generate OWL-based ontology catalog (SALI/FOLIO, FIBO, etc.)
om-generate-owl-catalog --input LMSS.owl --name sali-folio --version 2.0 --label-as-name

# Cross-edge vocabulary overlap analysis
om-edge-overlap inventory1.json inventory2.json

# Validate an input domain package before running the pipeline
om-validate-input sources/my_agency_package
```

## Repository Structure

```
OntologyMapper/
├── CLAUDE.md                          # Claude Code config (forwards to AGENTS.md)
├── AGENTS.md                          # AI agent rules and conventions
├── AGENTS/                            # Domain-specific SOPs
│   ├── OM__GENERATORS.md              # Run generators and catalog generators
│   ├── OM__ONTOLOGY_ADAPTERS.md       # Ontology-specific logic, CMF bridge, adapters
│   ├── OM__PIPELINE_ENGINE.md         # Pipeline runner, stages, context
│   ├── OM__SEARCH_AND_INDEXING.md     # Vector search, indexing, batch search
│   ├── OM__TESTING_AND_INTERFACES.md  # Test standards, CLI contracts, environment
│   └── OM__VALIDATION.md             # Input validation, quality gates, conformance
├── pyproject.toml                     # Package definition (ontology-mapper)
├── src/
│   └── ontology_mapper/
│       ├── __init__.py
│       ├── pipeline.py                # Pipeline runner (om-pipeline)
│       ├── pipeline_config.py         # Pipeline configuration
│       ├── pipeline_context.py        # PipelineContext: run-scoped names and paths
│       ├── run_dir_utils.py           # Shared run directory resolution
│       ├── validate_input_package.py  # Pre-Stage 1: input validation (om-validate-input)
│       ├── build_package_manifest.py  # Auto-discovery: domain TTL → package-manifest.json (om-build-manifest)
│       ├── extract_concepts.py        # Stage 2: OWL/SHACL/SKOS extraction (om-extract)
│       ├── ingest_csv.py              # Stage 2: CSV ingestion (om-ingest-csv)
│       ├── semantic_search.py         # Stage 3: per-concept vector search
│       ├── build_strategy_reports.py  # Stage 3: alignment workspace (om-build-strategy)
│       ├── ontology_specific.py       # Action determination via resolve_alignment()
│       ├── build_mapping_matrix.py    # Stage 4: mapping matrix (om-build-matrix)
│       ├── quality_gates.py           # Post-Stage 4: mapping matrix consistency
│       ├── generation_audit.py        # Stage 4: detect dropped properties (om-generation-audit)
│       ├── generation_utils.py        # Shared pure utilities for generators
│       ├── generate_edge_ontology.py  # Stage 6a: OWL/TTL generation (om-generate-ontology)
│       ├── generate_cmf_from_matrix.py # Stage 6a: CMF generation (MatrixToCmfBuilder)
│       ├── owl_cmf_bridge.py          # CMF dataclasses, XML/JSON serialization & parsing
│       ├── package_edge_artifacts.py  # Stage 6b: non-OWL artifacts (om-package-artifacts)
│       ├── generate_kg_artifacts.py   # Stage 6c: KG deployment scripts (om-generate-kg)
│       ├── validate_edge_package.py   # Stage 7: conformance validation (om-validate)
│       ├── finalize_package.py        # Stage 8: governance artifacts (om-finalize)
│       ├── generate_niem_catalog.py   # Catalog generator: NIEM (om-generate-catalog)
│       ├── generate_owl_catalog.py    # Catalog generator: OWL (om-generate-owl-catalog)
│       ├── generate_cmf_catalog.py    # Catalog generator: CMF (om-generate-cmf-catalog)
│       ├── build_vector_index.py      # Vector index builder (om-build-vector-index)
│       ├── vector_index.py            # Vector index data structures
│       ├── vector_search.py           # Ad-hoc vector search (om-vector-search)
│       ├── batch_search.py            # Batch vector search (om-batch-search)
│       ├── collect_alignments.py      # Alignment collector (om-collect-alignments)
│       ├── compute_edge_overlap.py    # Cross-edge overlap analysis (om-edge-overlap)
│       ├── adapters/                  # Vector index adapters
│       │   ├── catalog_adapter.py     # Reference catalog → OntologyEntry
│       │   ├── source_adapter.py      # Concept inventory → OntologyEntry
│       └── specs/                     # Reference specs (bundled as package data)
│           ├── {ontology}_reference_catalog_{version}.json
│           ├── {ontology}_catalog_summary_{version}.json
│           └── {ontology}_type_directory_{version}.txt
├── tests/
│   ├── conftest.py                    # Pytest markers (integration, docker)
│   ├── fixtures/                      # Test fixture data
│   │   ├── redvale_dbpi_agency_package/
│   │   └── cmf_reference/             # Community CMF examples for conformance tests
│   ├── test_validate_input_package.py
│   ├── test_build_package_manifest.py
│   ├── test_extract_concepts.py
│   ├── test_ingest_csv.py
│   ├── test_semantic_search.py
│   ├── test_build_strategy_reports.py
│   ├── test_ontology_specific.py
│   ├── test_build_mapping_matrix.py
│   ├── test_quality_gates.py
│   ├── test_generation_audit.py
│   ├── test_generation_utils.py
│   ├── test_generate_edge_ontology.py
│   ├── test_generate_cmf_from_matrix.py  # MatrixToCmfBuilder + community conformance
│   ├── test_package_edge_artifacts.py
│   ├── test_generate_kg_artifacts.py
│   ├── test_validate_edge_package.py
│   ├── test_finalize_package.py
│   ├── test_run_dir_utils.py
│   ├── test_pipeline_state.py
│   ├── test_pipeline_context.py
│   ├── test_compute_edge_overlap.py
│   ├── test_generate_niem_catalog.py
│   ├── test_generate_owl_catalog.py
│   ├── test_generate_cmf_catalog.py
│   ├── test_vector_index.py
│   ├── test_vector_search.py
│   ├── test_batch_search.py
│   ├── test_collect_alignments.py
│   ├── test_catalog_adapter.py
│   ├── test_kg_integration_sparql.py  # Integration: SPARQL against rdflib
│   ├── test_kg_integration_cypher.py  # Integration: Cypher structural validation
│   └── test_kg_integration_neo4j.py   # Integration: Docker Neo4j (requires Docker)
└── OntologyMapper Definition.md    # Original design specification
```

## Example Input Package

The runner (`../runner/`) contains domain packages. The `redvale_dbpi_agency_package` is a complete demonstration domain — a fictional municipal Department of Building Permits and Inspections (DBPI) for the City of Redvale. It includes:

- **OWL ontology modules** — core, organization, permitting, inspections, enforcement, workflows, augmentations
- **SHACL shapes** — validation constraints for all entity types
- **SKOS codelists** — controlled vocabularies for statuses, types, zones
- **Seed data** — realistic instance data covering the full domain
- **Policy documents** — mission statement, founding charter, service catalog
- **JSON-LD context** — complete property mappings for all predicates

## Output: Edge Package

OntologyMapper produces a self-contained edge package. An edge package includes:

- **OWL/TTL modules** — reused target types and domain-specific extensions (core, extensions, combined, all)
- **CMF** — Common Model Format XML + JSON for NIEM tooling interoperability (NIEM targets only)
- **Mapping matrix** — every source concept mapped to reuse, extend, or augment, with per-property decisions
- **SHACL shapes** — validation constraints with shared-target relaxation for multi-mapped types
- **Knowledge graph scripts** — Neo4j Cypher (schema, seed, queries), SPARQL templates, TriG named graphs, import config
- **Governance artifacts** — version manifest (with pipeline timing), lineage manifest, change-impact analysis, decision log, validation report, extension justifications

## Supported Target Ontologies

The target ontology and version are specified at the beginning of each pipeline run and flow through every stage — alignment, decision rules, ontology generation, and validation all operate against the target you specify.

| Ontology | Key (`target_ontology`) | Versions | Catalog Generator | Enrichment |
|----------|------------------------|----------|-------------------|------------|
| [NIEMOpen](https://www.niemopen.org/) (NIEM) | `niem` | 6.0 | `om-generate-catalog` (API + GitHub CSV) | Augmentation action logic in `resolve_alignment()` |
| [SALI/FOLIO](https://www.sali.org/) | `sali-folio` | 2.0 | `om-generate-owl-catalog` (OWL parsing) | Pass-through (no ontology-specific enrichment) |
| NODS (NIEM message spec) | `nods` | 1.0 | `om-generate-cmf-catalog` (CMF XML + optional Genericode) | Inherits NIEM augmentation logic via `--niem-version` |

### NIEM

NIEM is an OASIS open standard for information exchange. The implementation follows the [NDR v6.0](https://docs.oasis-open.org/niemopen/ndr/v6.0/ndr-v6.0.pdf) naming and design rules. NIEM-specific action logic (augment vs. extend vs. reuse) is handled by `resolve_alignment()` in `ontology_specific.py`. CMF (Common Model Format) artifacts are generated during Stage 6 for NIEM targets only.

### SALI/FOLIO

SALI LMSS (Legal Matter Specification Standard) and its FOLIO OWL ontology provide a standard for describing legal matters. The catalog is generated from the FOLIO OWL file using `om-generate-owl-catalog`. SALI uses opaque IRIs with `rdfs:label` as display names and `skos:definition` for definitions.

### NODS

NODS (National Online Dispute System) is a NIEM 6.0 message specification distributed as a CMF (Common Model Format) file. Because it's a NIEM extension, alignments against NODS inherit NIEM's augmentation-vs-extend-vs-reuse logic via the `--niem-version` flag on the catalog generator. NODS can be used as both a source domain (via `om-ingest-csv`) and a target ontology for alignment.

### Reference Catalogs

Each target ontology requires a version-pinned reference catalog in `specs/`. The catalog format is the same regardless of ontology — a JSON file with types, properties, and metadata. Each generator also produces a namespace-grouped summary and a compact type directory for efficient orchestrator scanning.

**NIEM catalogs** are generated from the [NIEM API 2.0](https://api.niemopen.org/v2) (public, no auth). Regenerate when adopting a new NIEM version:

```bash
om-generate-catalog --version 6.0
```

The generator fetches all types (across all 8 NIEM patterns) from NIEM's core + domain namespaces and resolves property memberships via the subproperties endpoint. It also fetches authoritative CSVs from the [NIEM GitHub repository](https://github.com/niemopen/niem-model) to enrich each type with:

- **Property cardinalities** (min/max occurs) — used by the orchestrator for semantic matching context
- **Property definitions and types** — parsed from Property.csv, enabling property-level semantic matching with full NIEM definitions
- **Parent type** relationships and **content style** (CCC/CSC/S)
- **Augmentation, adapter, and metadata** type flags

To skip GitHub CSV enrichment (e.g., when offline), use `--no-github-csv`.

**SALI/FOLIO catalogs** are generated from the FOLIO OWL file using the generic OWL catalog generator:

```bash
om-generate-owl-catalog --input LMSS.owl --name sali-folio --version 2.0 --label-as-name
```

The `--label-as-name` flag uses `rdfs:label` instead of IRI local names, which is necessary for ontologies with opaque IRIs like SALI.

**NODS (and other NIEM-derived CMF catalogs)** are generated from a CMF XML file, optionally enriched with Genericode (`.gc`) codelist files for enumeration values:

```bash
# CMF only
om-generate-cmf-catalog --input nods.cmf --name nods --version 1.0 --niem-version 6.0

# CMF + codelists
om-generate-cmf-catalog --input nods.cmf --codelists codelists/ --name nods --version 1.0 --niem-version 6.0
```

`--niem-version` points at the NIEM structures namespace version (e.g. `6.0`) so the generator can resolve the ultimate `structures:ObjectType` root for extend-from-root scenarios. The generator works with any CMF file, not just NODS.

### CMF Generation

NIEM 6.0 introduced CMF (Common Model Format) as its canonical modeling format. The pipeline generates CMF directly from the mapping matrix via `MatrixToCmfBuilder` — producing spec-compliant CMF per NDR v6.0 for any source/target combination. CMF and OWL are generated independently from the same matrix inputs — neither depends on the other.

## Tested Neo4j Versions

Knowledge graph scripts (schema, seed, queries) are integration-tested against real Neo4j instances via [testcontainers](https://testcontainers-python.readthedocs.io/). These tests execute the generated Cypher scripts, verify constraints/indexes, seed data, query execution, and cross-script consistency.

| Version | Status | Verified |
|---------|--------|----------|
| Neo4j 5.x Community (5.26) | Passing | 2026-04-04 |

To run these tests locally (requires Docker):

```bash
pip install -e ".[integration]"
pytest -m docker -v
```

To add a new Neo4j version: append its Docker image tag to `NEO4J_VERSIONS` in `tests/test_kg_integration_neo4j.py`, run the tests, and update this table when they pass.

## License

MIT
