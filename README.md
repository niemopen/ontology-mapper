# OntologyMapper

A pipeline that aligns a source ontology against a target ontology
(NIEM 6.0, SALI/FOLIO, NIEM-derived NODS, or any OWL/CMF target a user
imports) and emits an "edge package" — the reusable subclasses, augmentations,
property mappings, and conformance artifacts that bridge the two.

The work is staged so a domain expert reviews the LLM-proposed alignments
mid-flight (Stage 5) before any artifact is generated. The output package is
self-validating: SHACL shapes, CMF, OWL, JSON-LD context, and a Cypher / SPARQL
test suite all ship together.

## Repo layout

| Subdir      | Role                                                        | Python package         |
| ----------- | ----------------------------------------------------------- | ---------------------- |
| `mapper/` | Pipeline stage tools — extract, align, generate, validate   | `ontology_mapper`      |
| `runner/`   | End-to-end orchestrator; bounded LLM evaluation; review UI  | `runner_tools`, `orchestrator_service` |
| `web/`      | FastAPI backend + Svelte frontend — browser-based review    | (no installable pkg)   |

All three install into one Python environment; `web/backend` imports
`ontology_mapper.*` and `runner_tools.*` directly.

## Prerequisites

- Python ≥ 3.10
- Node.js ≥ 20.19 or ≥ 22.12 (only needed for the web frontend; required by Vite 8)
- Anthropic `claude` CLI on `PATH` if you intend to run pipeline stages that
  need LLM evaluation (Stages 3 and 5). Not required to start the web app.

## Quick start

```bash
# 1. Clone
git clone <repo-url> OntologyMapper
cd OntologyMapper

# 2. Python environment + installs
python -m venv .venv
.venv\Scripts\activate              # Windows
# source .venv/bin/activate         # macOS / Linux
pip install --upgrade pip setuptools wheel
pip install -e "mapper[validation,vector,dev]"
pip install -e runner
pip install -r web/backend/requirements.txt

# 3. Build vector indexes (first-time setup)
#    Downloads the BGE-large-en embedding model from HuggingFace
#    (~1.3 GB, into the user HF cache) on first run, then builds one
#    FAISS index per target ontology. Takes a few minutes.
python scripts/build_indexes.py

# 4. Verify
python scripts/smoke.py
```

`scripts/build_indexes.py` is a one-time post-clone step. The vector
model and indexes are gitignored because they're large and rebuildable;
the reference catalogs they're built from DO ship with the repo.

`scripts/smoke.py` runs a one-shot installation check: Python version,
required imports, CLI entry points, reference catalogs, vector indexes,
demo source package, and the full mapper test suite (skipping the
Docker integration tests). It exits 0 if the install is healthy, 1
otherwise.

If you'd rather run the components manually:

```bash
om-pipeline --help
pytest mapper --ignore=mapper/tests/test_kg_integration_neo4j.py \
                --ignore=mapper/tests/test_kg_integration_cypher.py \
                --ignore=mapper/tests/test_kg_integration_sparql.py
pytest runner
```

The three `--ignore`d test suites exercise Neo4j, SPARQL, and Cypher
endpoints; they're optional integration tests that need Docker.

## Running the web app

**There is no authentication.** Every request resolves to a single
`demo-user` with admin rights — there is no external auth provider and no
access control. This is the mode OASIS reviewers and other external
consumers will use. The backend logs a `WARNING: NO AUTHENTICATION` line
at startup as a guardrail against exposing this configuration publicly.

No environment configuration is required to run it.

In two terminals:

```bash
# Terminal 1 — backend
cd web/backend
uvicorn main:app --reload --port 8000

# Terminal 2 — frontend
cd web/frontend
npm install
npm run dev
```

Open <http://localhost:5173>.

## Running the pipeline from the CLI

Without the web UI, the pipeline is driven by `runner_tools/run_pipeline.py`:

```bash
cd runner
python runner_tools/run_pipeline.py \
    --organization redvale \
    --source dbpi \
    --input-package-path ../mapper/tests/fixtures/redvale_dbpi_agency_package \
    --target-ontology niem \
    --target-version 6.0
```

The fixture under `mapper/tests/fixtures/redvale_dbpi_agency_package/` is
a complete demonstration domain (a fictional municipal Department of Building
Permits and Inspections) suitable for an end-to-end smoke run.

## Where to learn more

| Topic | File |
| ----- | ---- |
| Pipeline rules and stage-by-stage protocol | [`runner/AGENTS.md`](runner/AGENTS.md), [`runner/AGENTS/`](runner/AGENTS/) |
| Pipeline tool architecture and generators | [`mapper/AGENTS.md`](mapper/AGENTS.md), [`mapper/AGENTS/`](mapper/AGENTS/) |
| Web layer architecture | [`web/AGENTS.md`](web/AGENTS.md) |
| Demonstration domain | [`mapper/tests/fixtures/redvale_dbpi_agency_package/README.md`](mapper/tests/fixtures/redvale_dbpi_agency_package/README.md) |

## License

Apache License 2.0. See [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE).

## Provenance

This repo consolidates three earlier repositories on GitHub:

- [`CardamomCosmos/SemanticCompiler`](https://github.com/CardamomCosmos/SemanticCompiler)
- [`CardamomCosmos/SemanticCompilerRunner`](https://github.com/CardamomCosmos/SemanticCompilerRunner)
- [`CardamomCosmos/SemanticCompilerWeb`](https://github.com/CardamomCosmos/SemanticCompilerWeb)

The originals remain on GitHub for history; this repo is the unified version
intended for distribution.
