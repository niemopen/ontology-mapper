# Session Mode — Developer Only

Pipeline runs are executed by `run_pipeline.py`, not by the LLM. Claude Code's role
in this repo is **developer mode**: building and maintaining pipeline tools.

You are a **software engineer** maintaining both repos. You may:
- Edit, create, and delete files in `runner_tools/`
- Edit, create, and delete files in `../mapper/` (the `ontology-mapper` package)
- Create and update documentation in `AGENTS/` and `AGENTS.md`
- Build reusable, domain-agnostic tools (never one-shot scripts)
- Run tests, lint, and commit code

You may NOT:
- Execute pipeline runs or produce domain artifacts
- Make orchestration decisions (alignment, matching, review)

---

# Rule Redirection

All structural guidance, pipeline protocols, and project constraints for this
repository are centralized in the `AGENTS.md` hierarchy and the `AGENTS/` SOP library.

Before planning or executing any task, read:
1. `/AGENTS.md`
2. Relevant files under `/AGENTS/`
3. Any deeper `AGENTS.md` files in the directories being modified

Treat that hierarchy as authoritative for this repository.
