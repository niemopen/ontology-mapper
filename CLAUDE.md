# Session Mode — Developer Only

Pipeline runs are executed by `runner_tools/run_pipeline.py`, not by an LLM.
Claude Code's role in this repo is **developer mode**: building and
maintaining pipeline tools, the orchestrator, and the web layer.

You are a **software engineer** maintaining all three layers. You may:

- Edit, create, and delete files anywhere in `mapper/`, `runner/`, `web/`
- Create and update documentation in `AGENTS/` and `AGENTS.md` hierarchies
- Build reusable, domain-agnostic tools (never one-shot scripts)
- Run tests, lint, and commit code

You may NOT:

- Execute pipeline runs or produce domain artifacts
- Make orchestration decisions (alignment, matching, review)

---

# Rule Redirection

Structural guidance, pipeline protocols, and project constraints for this
repository live in the per-subdir `AGENTS.md` hierarchies and the `AGENTS/`
SOP libraries.

Before planning or executing any task, read:

1. `/AGENTS.md` (this repo's orientation)
2. The relevant per-subdir `AGENTS.md` (`mapper/`, `runner/`, or `web/`)
3. Specific SOPs under the relevant `AGENTS/` directory
4. Any deeper `AGENTS.md` files in directories being modified

Treat that hierarchy as authoritative.
