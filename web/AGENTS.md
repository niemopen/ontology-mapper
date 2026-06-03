# Web Interface Rules

> **Version**: 1.0 | **Last Updated**: 2026-04-10

## Code Boundary — What Lives Where

> **"Does this produce or transform a pipeline artifact?"**
> -> `ontology-mapper` package (`mapper/`)
>
> **"Does this support running, reviewing, or verifying the pipeline?"**
> -> `runner_tools/` (`runner/`)
>
> **"Does this present pipeline data to users or accept user input via browser?"**
> -> `backend/` + `frontend/` (`web/`)

## Design Principles

1. **No LLM calls from this repo.** All semantic reasoning happens in OntologyMapper.
2. **Import, don't duplicate.** Backend imports functions from `runner_tools` and
   `ontology_mapper` directly. Never reimplement pipeline logic.
3. **Enforce Stage 5 exit criteria in the UI.** The submit button must be disabled
   until all mappings are reviewed and all human-must-decide properties are resolved.
4. **Single local user — no external auth.** There is no authentication provider.
   Every request resolves to one fixed local user with admin rights via
   `require_auth` (`backend/auth.py`); routes stay org-scoped through
   `get_org_slug`. This is for internal / reviewer / single-tenant use only —
   there is no access control, so do not expose a deployment publicly.
