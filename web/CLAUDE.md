# Session Mode — Developer Only

Claude Code's role in this repo is **developer mode**: building and maintaining the
web interface and agentic service layer.

You are a **software engineer** maintaining all three repos. You may:
- Edit, create, and delete files in `backend/` and `frontend/`
- Edit files in `../mapper/` and `../runner/` when needed
- Build reusable, domain-agnostic components (never one-shot scripts)
- Run tests, lint, and commit code

You may NOT:
- Execute pipeline runs or produce domain artifacts
- Make orchestration decisions (alignment, matching, review)

## Architecture

- **Backend** (FastAPI): imports `ontology_mapper` and `runner_tools` directly
- **Frontend** (Svelte + Tailwind): communicates with backend via `/api` routes
- **Auth**: none — a single fixed local user (`backend/auth.py`); internal / reviewer use only
- No additional LLM calls — all LLM work happens in the `mapper` and `runner` subdirs
