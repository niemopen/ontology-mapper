# Web Interface Rules

> **Version**: 1.0 | **Last Updated**: 2026-04-10

## Code Boundary — What Lives Where

> **"Does this produce or transform a pipeline artifact?"**
> -> `ontology-mapper` package -> `CardamomCosmos/SemanticCompiler`
>
> **"Does this support running, reviewing, or verifying the pipeline?"**
> -> `runner_tools/` -> `CardamomCosmos/SemanticCompilerRunner`
>
> **"Does this present pipeline data to users or accept user input via browser?"**
> -> `backend/` + `frontend/` -> `CardamomCosmos/SemanticCompilerWeb`

## Design Principles

1. **No LLM calls from this repo.** All semantic reasoning happens in OntologyMapper.
2. **Import, don't duplicate.** Backend imports functions from `runner_tools` and
   `ontology_mapper` directly. Never reimplement pipeline logic.
3. **Enforce Stage 5 exit criteria in the UI.** The submit button must be disabled
   until all mappings are reviewed and all human-must-decide properties are resolved.
4. **Auth on every route.** All `/api` endpoints require a valid Clerk JWT.
