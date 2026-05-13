# OntologyMapper — Orientation

This file orients a contributor (human or agent) entering the repository.
The substantive rules — pipeline protocol, stage-by-stage commands, tool
architecture, web layer conventions — live in the per-subdir `AGENTS.md`
hierarchies. This file points there.

## Three-layer architecture

```
    +---------+              +---------+              +-------+
    | compiler|              | runner  |              |  web  |
    |  (lib)  |  <-imports-  |(driver) |  <-imports-  |(UI/API)|
    +---------+              +---------+              +-------+
        ^                        ^                         ^
        |                        |                         |
   stage tools             pipeline orchestration     browser-based
   (om-* CLI,              (run_pipeline.py,           review UI
   generators,             Stage 3 + 5 LLM             (Stage 5),
   validators)             evaluation)                 project setup
```

| Subdir      | Owns                                                   | Where the rules live          |
| ----------- | ------------------------------------------------------ | ----------------------------- |
| `compiler/` | Pipeline stage tools: `om-*` CLI, generators, validators | `compiler/AGENTS.md` + `compiler/AGENTS/` |
| `runner/`   | End-to-end orchestrator, bounded LLM evaluation, interactive Stage 5 review | `runner/AGENTS.md` + `runner/AGENTS/` |
| `web/`      | FastAPI backend importing `ontology_mapper` + `runner_tools`; Svelte frontend | `web/AGENTS.md` + `web/CLAUDE.md` |

## Code boundary

> **"Does this produce or transform a pipeline artifact?"** → `compiler/`
>
> **"Does this support running, reviewing, or verifying the pipeline?"** → `runner/`
>
> **"Is this a UI / HTTP / auth concern?"** → `web/`

`runner/AGENTS.md` ("Code Boundary — What Lives Where") owns the
authoritative table; check there before introducing a new module.

## Entry points

- **Pipeline (programmatic)** — `runner/runner_tools/run_pipeline.py`,
  invoked from the `runner/` directory after the `om-*` CLI tools are
  installed via `pip install -e compiler/`.
- **Pipeline (CLI)** — the `om-*` entry points declared in
  `compiler/pyproject.toml` (`om-pipeline`, `om-extract`, …).
- **Web app** — `uvicorn main:app` from `web/backend/`; frontend `npm run dev`
  from `web/frontend/`. See top-level `README.md` for the full setup
  walkthrough.

## Documentation contract

- One concept lives in exactly one file. Cross-reference rather than
  duplicate.
- Each AGENTS doc states what it *owns* and what its *companion documents*
  cover (see e.g. `compiler/AGENTS/OM__PLAN__LONG_TERM.md`).
- Stale references that the rename sweep over-corrected get fixed at sight,
  not deferred — sibling-repo paths (e.g. `../OntologyMapper/`) are the most
  common case after the consolidation; replace with `../compiler/`,
  `../runner/`, or `../web/` as appropriate.

## Provenance

The repo is a consolidation of three previously separate repositories
(`CardamomCosmos/SemanticCompiler*`). Some doc text and historical-context
URLs intentionally preserve the old names; see `NOTICE` for the full record.
