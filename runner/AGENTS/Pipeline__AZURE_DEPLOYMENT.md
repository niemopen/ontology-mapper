# Pipeline Azure Deployment Architecture

> **Parent**: [AGENTS.md](../AGENTS.md)
> **Owns**: Cloud deployment shape for the OntologyMapper pipeline — compute mapping per stage, orchestration model, parallelization strategy, cost model, and the prerequisites that gate any cloud target.
> **Generated**: 2026-05-02 from a live Q&A session. Treat capacity claims, pricing shapes, and SKU choices as snapshots; re-verify before commit-grade decisions.

---

## 1. Current shape (verified)

The pipeline already runs as a web-app-orchestrated process. `C:\dev\OntologyMapper\web\backend\routes\runs.py` holds the orchestration:

- `POST /runs/{run_id}/execute` (`runs.py:414`) spawns a daemon thread, calls `_run_pipeline_stages_1_4` (`runs.py:296`). On success, sets status `awaiting-review`.
- Stage 5 (review) is the web app's responsibility — handled by `routes/review.py`, surfaced in the Svelte UI.
- `POST /runs/{run_id}/continue` (`runs.py:433`) verifies Stage 5 is marked complete, calls `_run_pipeline_stages_6_8` (`runs.py:345`).
- Run audit log (post-run): observations are appended to `{run_dir}/run-feedback.json` via `runner_tools/run_feedback.py` on demand. Schema in [Pipeline__POST_RUN.md](Pipeline__POST_RUN.md). This is metadata captured *about* runs, not work performed *during* runs — it is not a pipeline stage.

Each stage call is a `subprocess.run` of the appropriate `om-*` CLI command. Run state lives in `.compiler-runs/{run_id}/.compiler-state.json` on local disk; runtime status lives in the in-memory `_pipeline_status` dict (`runs.py:21`).

The cloud deploy target is a port of this shape, not a redesign.

---

## 2. Prerequisites that gate any cloud deploy

These refactors are required regardless of the chosen compute shape.

1. **Production model decision: `gpt-5.4-mini` via Azure OpenAI Service.** Settled 2026-05-02 after a smoke test of 61 redvale → NIEM 6.0 concepts: gpt-5.4-mini agreed with the Sonnet 4.6 baseline on 84% of picks, 0 schema failures, 0 refusals. The 16% disagreements were either substantive judgment calls (4 of 10) or gpt-5.4-mini abstaining where Sonnet had picked a stretched anchor with caveats (6 of 10) — abstain-on-ambiguity is the preferred Stage 5 behavior (see `feedback_abstain_over_stretched_anchor`). Cost win: gpt-5.4-mini on Azure OpenAI is ~10× cheaper per-token than Sonnet via Anthropic API direct, runs inside the Azure tenant (managed identity, no egress, single billing), and reaches throughput tiers comparable to or better than Anthropic API for our fan-out shape. **Sonnet 4.6 (Anthropic API direct) remains the documented fallback** if gpt-5.4-mini's quality regresses on observed runs — the smoke test harness (`runner_tools/smoke_test_openai.py`) stays in the repo for re-validation when models or prompts change.

   **Local dev keeps using `claude -p`** via the existing `orchestrator_service/evaluator.py`. Anthropic tokens are effectively free under Brian's Claude Code subscription, so dev pays no API cost for development iteration. The two evaluator paths (`evaluator.py` for claude -p, `evaluator_openai.py` for Azure OpenAI) coexist by design.

2. **Move cloud Stage 3 + Stage 5 LLM calls onto the Azure OpenAI SDK.** Stage 3 (`om-orchestrate-eval`) and Stage 5 (`_present_and_apply_human_review.py` NL interpretation) currently shell out to the Claude Code CLI in dev. Cloud images won't ship that CLI. The cloud variant of these call sites uses the `openai` Python SDK with `AzureOpenAI` client + `DefaultAzureCredential` (managed identity), targeting `gpt-5.4-mini` on a GlobalStandard deployment. Stage 5's `--json-schema` becomes structured output via the Responses API's `text.format` (`type: json_schema`, `strict: true`) — see `orchestrator_service/evaluator_openai.py` for the canonical shape. The dev `claude -p` path stays untouched.

   Structure the prompt prefix (system + ontology context + semantic search guidance) as a cacheable block at the front of every call. Azure OpenAI's automatic prompt caching gives ~50% off cached input ≥1024 tokens; with the typical Stage 3c shape (long stable prefix + short variable suffix per concept), this materially compounds the per-token cost win in #1. No explicit cache-control needed — the discount is automatic when the prefix is identical across calls.

3. **State, data catalogs, and vector indexes on a single Azure Files mount.** All three reach Functions and the web container today via the `--run-dir` filesystem contract; preserve that contract by mounting one Azure Files share at a fixed path (e.g. `/mounts/om-data`) inside every Function and the web container, with three sub-paths:
   - `runs/{run_id}/...` — per-run state (`.compiler-state.json`, `runtime-status.json`) and artifacts (read-write).
   - `catalogs/{niem,nods,sali}/...` — target-ontology JSON catalogs (read-mostly; written by catalog-build jobs, read by Stages 3a–3d).
   - `indexes/{niem,nods,sali}/...` — FAISS indexes (read-mostly; written by `om-build-vector-index`, read by `om-batch-search`).

   Constraints (verified against Microsoft Learn, 2026-05-02):
   - Flex Consumption permits **5 mount points per app**; we use 1.
   - **SMB only** (NFS not supported on Flex Consumption). Authentication is via **storage account access key** in site config (`azureStorageAccounts.dataMount`) — managed identity for SMB mounts on Functions is not currently supported. Key rotation has to update mount config on every Function app and the web container; cadence with other secret rotation.
   - **Throughput**: Standard ~60 MB/s per share, no fixed cost (pay-as-you-go for storage + transactions). Premium SSD (FileStorage account) ~100+ MB/s with provisioned billing — **100 GiB minimum share** ⇒ roughly **$10–16/mo fixed floor at example list rates** for the smallest Premium share, baseline 3,000 IOPS / 100 MiB/s included, no transaction charges. Read concurrency is fine on both; writes serialize. Catalogs and indexes are read-mostly so Standard is the starting point — flip to Premium if (a) per-transaction charges from heavy Stage-3c-fan-out parallel reads add up, or (b) FAISS load time over SMB at scale-out becomes a wall-clock concern (see §7 cost-shape and §8 open questions).
   - Mount path must be `/dir-name`, can't start with `/home`.

   This collapses two earlier prerequisites (state externalization + vector index hosting) into one mount and removes the Blob-download cold-start step the earlier shape carried.

4. **Stage 5 already lives in the web app.** No refactor needed for the deployment-shape split.

**What would flip the §2.1 model decision:** Stage 5 review burden grows materially past the Sonnet baseline due to gpt-5.4-mini's higher abstain rate on ambiguous concepts (the trade we're explicitly accepting), or quality regression observed in production. Fallback path is wired: switch the cloud orchestrator to call Sonnet 4.6 via Anthropic API direct (the smoke-test harness validates the prompt + schema work cleanly with both vendors).

**What would flip the §3 vector-store choice:** If query volume grows past the throughput envelope of one Azure Files share, or if multiple long-running services need to share an index without each paying the per-instance SMB page-in, fall back to Azure AI Search (~$75/mo Basic tier floor, no scale-to-zero). Not the case today.

References for this section: [Mount file shares (Flex Consumption)](https://learn.microsoft.com/azure/azure-functions/flex-consumption-plan#mount-file-shares), [Choose a file access strategy](https://learn.microsoft.com/azure/azure-functions/concept-file-access-options#share-mount-scenarios), [Mount limits](https://learn.microsoft.com/azure/azure-functions/concept-file-access-options#mount-limits), [Mount authentication](https://learn.microsoft.com/azure/azure-functions/concept-file-access-options#mount-authentication).

---

## 3. Target architecture (cost-minimal, web-app-orchestrated)

> **Frontend split:** This section describes the Azure backend shape, which is shared across both the all-Azure deployment (frontend + backend on Azure) and the planned Cloudflare-frontend variant (frontend on Cloudflare Pages, backend on Azure). See [Pipeline__CLOUDFLARE_FRONTEND.md](Pipeline__CLOUDFLARE_FRONTEND.md) for the user-facing layer's Cloudflare-hosted shape.

The web app keeps its orchestrator role; `subprocess.run` calls become HTTP calls to Functions. Stage 3c fans out via Service Bus.

```
                           [Svelte UI]
                                |
                       [FastAPI web app]
                       (Container App, scale-to-zero)
                                |
        +-----------+-----------+-----------+-----------+
        |           |           |           |           |
   POST /fn/    POST /fn/   Service Bus   POST /fn/   POST /fn/
   build-       batch-      (per-concept   collect-    (others)
   strategy     search      eval)          alignments
        |           |           |           |           |
        +---- Azure Functions Flex Consumption ---------+
        |          (scale-to-zero, per-second)          |
        |                       |                       |
        |                       v                       |
        |     [Azure OpenAI SDK: gpt-5.4-mini]          |
        |     (managed identity; Sonnet fallback)       |
        +----------------+--------------+---------------+
                         |              |
                         v              v
        [Azure Files mount: /mounts/om-data]   [Cosmos:
        ├── runs/{run_id}/                      per-run eval
        │     ├── .compiler-state.json          counter — atomic
        │     ├── runtime-status.json           decrement only]
        │     └── artifacts/
        ├── catalogs/{niem,nods,sali}/...
        └── indexes/{niem,nods,sali}/...
                         ^
                         |
              Web app polls counter (or SB topic webhook),
              then calls collect-alignments, proceeds to Stage 4
```

Components:

- **Web app**: Container App, `min-replicas=0` (cold starts tolerated). Holds orchestration logic ported from `_run_pipeline_stages_1_4` / `_run_pipeline_stages_6_8`. Replaces `subprocess.run` calls with `httpx.post` to stage endpoints. Mounts the same Azure Files share as the stage workers, at the same path, so the `--run-dir` filesystem contract holds end-to-end.
- **Stage workers** (each `om-*` command exposed as an HTTP-triggered endpoint): Azure Functions Flex Consumption, scale-to-zero. Each fits inside the 30-min default timeout. Each app mounts the shared Azure Files share at `/mounts/om-data`.
- **Stage 3c eval workers**: Service Bus queue-triggered. Web app drops one message per pending eval; KEDA scales workers. Each worker calls Azure OpenAI for `gpt-5.4-mini` (Responses API with structured-output JSON schema; managed identity auth) with one file's prompt, writes the result to the run's `artifacts/` sub-path on the mount, decrements a counter in Cosmos. The 230-s HTTP timeout doesn't apply (queue-triggered).
- **Storage backbone (single Azure Files share, mounted at `/mounts/om-data`)**:
  - `runs/{run_id}/` — `.compiler-state.json` (existing per-stage progress markers — `status`, `started_at`, `completed_at`) and `runtime-status.json` (introduced by this architecture: three fields the frontend depends on — `status` ∈ {`idle`, `running`, `awaiting-review`, `completed`, `failed`}, `stage`, `error`; verified from `runs.py:21, 103, 137, 257, 391–409` and `NewProject.svelte:153–161`). Currently held in the in-memory `_pipeline_status` dict — lost on web-app restart and incorrect under multi-replica scale-out (each replica sees only its own runs). Externalize to a JSON file in the run directory; every site that mutates `_pipeline_status[run_id]` writes the file, every consumer reads it. HTTP API response shape unchanged; no frontend changes. Per-run lifecycle is unchanged (`runs.py:119` `shutil.rmtree(run_dir)` deletes the whole sub-tree).
  - `catalogs/{niem,nods,sali}/` — JSON catalogs, written by catalog-build jobs, read by Stages 3a–3d. Versioning per catalog directory (e.g., `catalogs/niem/6.0/`).
  - `indexes/{niem,nods,sali}/` — FAISS index files, written by `om-build-vector-index`, read by `om-batch-search`. First read on a fresh worker instance pages over SMB; subsequent reads are warm.
- **Per-run eval counter for Stage 3c fan-out**: Cosmos serverless or Table Storage. Atomic decrement is the only requirement Azure Files cannot meet (concurrent SMB writes serialize but read-modify-write is not atomic without external coordination); both work. Tiny RU/op footprint.
- **Secrets**: Azure OpenAI uses managed identity for auth — no API key handling at runtime. Storage account access key for the SMB mount lives in stage-worker site config — see §2.3 caveats. The Sonnet-fallback path (Anthropic API direct) keeps an API key in Key Vault, retrieved on demand only when the fallback is engaged. Same `DefaultAzureCredential` code path on laptop (via `az login`) and in cloud (via managed identity).

---

## 4. Stage-by-stage compute mapping

| Stage | Compute shape | Parallelism | Notes |
|---|---|---|---|
| 1 — Ingest | HTTP Function | Single invocation | I/O-bound, seconds. |
| 2 — Extract | HTTP Function | Single invocation | rdflib/lxml parsing, seconds-to-minutes. Fits 30-min default easily. |
| 3a — `om-build-strategy` | HTTP Function | Single invocation | Deterministic, seconds. |
| 3b — `om-batch-search` | HTTP-triggered worker (or per-concept fan-out — see §6) | Optional fan-out | FAISS index loaded from the Azure Files mount; first read on a fresh worker pages over SMB, subsequent reads warm. |
| 3c — `om-orchestrate-eval` | **Service Bus fan-out** | **N parallel evals** | Web app drops N messages, KEDA scales workers, each calls Azure OpenAI for `gpt-5.4-mini` (managed identity; Sonnet fallback per §2.1). Counter in Cosmos signals completion. |
| 3d — `om-collect-alignments` | HTTP Function | Single invocation (or per-concept fan-out — see §6) | Reassembly, fast. |
| 4 — Decide (`om-build-matrix`, `om-generation-audit`) | HTTP Function | Optional fan-out | Deterministic transforms, seconds. |
| 5 — Review | Web app + UI | N/A | No change from current shape. Hours-to-days wall clock; web app holds the loop. |
| 6 — Generate (`om-generate-ontology`, `om-package-artifacts`, `om-generate-kg`) | HTTP Function | 6c can fan out per-entity; 6a emits aggregate files (not streamable) | `om-generate-ontology` produces six aggregate TTL files (`{SOURCE}-edge-core.ttl`, `-edge-extensions.ttl`, `-edge-all.ttl`, `-edge-combined.ttl`, `-edge-shapes.ttl`, `-edge-codelists.ttl`) plus CMF-XML and CMF-JSON. Verified in `ontology_mapper/generate_edge_ontology.py:518–620+`. |
| 7 — Validate | HTTP Function | Optional per-rule fan-out | Validation queries. Many rules are independent. |
| 8 — Finalize | HTTP Function | Single invocation | Metadata write. |

### Run audit log (not a stage)

`runner_tools/run_feedback.py` appends developer-logged observations to `{run_dir}/run-feedback.json` and reads them back. It does not transform pipeline artifacts, does not gate any other stage, and is not invoked by `run_pipeline.py` or the web-app stage drivers. It is a thin write/read on the run-state storage — the same Azure Files mount or Blob path the rest of the pipeline already uses. Zero compute requirement; zero cloud cost driver. Treat it as a sibling concern to the work-graph, not a successor stage.

---

## 5. Why not Durable Functions

Durable was the obvious default suggestion but doesn't earn its overhead here. Three reasons:

1. **The web app already is the orchestrator.** `runs.py` holds the entire stage sequence, retry-on-failure logic, and status tracking. Moving that into Durable duplicates it without removing it.
2. **Durable's checkpoint storage adds cost without removing failure modes.** Every state transition writes to its backing store. For Stage 3c fanning out N evals, that's 2N+ storage transactions just for bookkeeping. The pipeline already has `.compiler-state.json` and Cosmos as durable state — Durable's checkpoints overlap, not extend.
3. **Durable's killer feature — surviving orchestrator restarts across hour-scale awaits — isn't needed.** Each Function call is short. The web app is the long-lived process, and it already reads state from disk on restart (`runs.py:42`, `_read_state`). Hosting the web app on a Container App with `min-replicas=0` plus Cosmos-backed state survives restarts cleanly.

Signals that would flip this:

- Pipeline runs longer than the web app's session lifetime AND state-on-restart isn't enough — *not the case; state is already file/Cosmos-backed*.
- Cross-process retry/backoff policies grow elaborate enough to be worth replacing — *not the case; current failure handling is "set status=failed and stop"*.
- Multiple orchestrators racing on the same run — *not the case; runs are single-tenant per `run_id`*.

None of these signals are firing today. **Skip Durable.**

---

## 6. Parallelization beyond Stage 3c

Several stages are independent per-unit work that currently runs as monolithic processes. Each can become a Service Bus fan-out using the same pattern as Stage 3c. Per-stage fan-out alone is expected to close the wall-clock gap; cross-stage streaming was considered and rejected — it doesn't reduce total cost (same work, rearranged in time) and the refactor is wide and high-coupling for a wall-clock-only win that fan-out already delivers.

### Per-stage fan-out

| Stage | Fan-out unit | Win |
|---|---|---|
| 3b — `om-batch-search` | One vector search per source concept | Modest. FAISS reads are sub-second once the mount is paged in; the win is mostly on Stage 3c API parallelism, not vector lookup itself. |
| 3d — `om-collect-alignments` | One `resolve_alignment()` per concept | Modest — calls are fast and deterministic; fan-out overhead may eat the win. |
| 4 — `om-build-matrix` | One matrix-cell construction per concept | Modest. Worth it if N is large. |
| 6c — `om-generate-kg` | One per-entity KG fragment, merged at the end | **Significant** for large entity counts. |
| 7 — `om-validate` | One per validation rule | **Significant** — validation rules are the typical long pole and are independent. |

Each fan-out follows the same shape as Stage 3c: web app enumerates work units, drops messages, KEDA scales workers, counter in Cosmos signals completion, web app calls the reduce step.

### Step-by-step roll-out plan

Three phases. Phase A is per-stage and cloud-independent; Phase B is one-time foundational work; Phase C extends per stage in priority order. Each Phase C stage is its own discrete unit, independent of the others.

**Phase A — Tool refactor (cloud-independent, per stage):**

- **A1**: Add per-unit invocation mode to the tool (e.g., `om-batch-search --concept <qname>`, `om-validate --rule <id>`). Existing batch mode (`--run-dir` → all files) stays untouched so dev mode and `run_pipeline.py` are unaffected.
- **A2**: Add a per-stage reduce step — re-reads per-unit outputs, produces the existing batch-mode artifact shape so downstream stages consume it identically.
- **A3**: Verify existing batch mode still works end-to-end via `run_pipeline.py`.

**Phase B — Cloud orchestration template (one-time, foundational):**

- **B1**: Confirm orchestrator location (Path A: FastAPI Container App, recommended; vs Path B: dissolve to Functions). See [Pipeline__CLOUDFLARE_FRONTEND.md](Pipeline__CLOUDFLARE_FRONTEND.md) §3.
- **B2**: Build the reusable fan-out infrastructure: Service Bus namespace, queue creation per fan-out stage, KEDA scaler config with `maxReplicaCount` per *Multi-tenant rate-limit behavior* below, Cosmos counter document shape, completion-signal mechanism.
- **B3**: Wire the existing Stage 3c into this template (or formalize what's already there). Stage 3c is the proof-of-concept; subsequent stages reuse the template directly.

**Phase C — Per-stage cloud wiring (incremental, descending priority):**

In order of expected wall-clock win:

- **C1**: Stage 7 — `om-validate` per-rule. Validation rules are typically the long pole.
- **C2**: Stage 6c — `om-generate-kg` per-entity. Significant for large entity counts.
- **C3**: Stage 4 — `om-build-matrix` per-concept.
- **C4**: Stage 3d — `om-collect-alignments` per-concept.
- **C5**: Stage 3b — `om-batch-search` per-concept.

Stop wherever the wall-clock gap closes. C1 + C2 alone may be enough; the C3–C5 wins are modest.

**Design questions to settle before any C-step:**

- **Reduce-step location**: same Function as per-unit workers, or a separate Function/CLI? Recommend separate for debuggability.
- **Completion-signal mechanism**: orchestrator polls Cosmos counter vs Service Bus topic webhook fires when counter hits zero. Recommend polling for sporadic-run workloads — Cosmos RU cost is trivial.
- **Failure semantics**: abort the whole stage on per-unit failure, or continue and report? Stage 3c's `max_retries=1` per file is the existing model; extend it.

### Multi-tenant rate-limit behavior

When N users overlap, per-run concurrency multiplies: 4 users × concurrency 24 = 96 in-flight calls. With our typical Stage 3c shape (~7K input + ~300 output tokens, ~4s wall-clock per call), peak load translates to:

| Concurrent users | Peak in-flight | RPM-equivalent | TPM-equivalent |
|---|---|---|---|
| 1 | 24 | ~360 | ~2.6M |
| 2 | 48 | ~720 | ~5.3M |
| 4 | 96 | ~1,440 | ~10.5M |
| 8 | 192 | ~2,880 | ~21M |

**TPM is the binding constraint**, not RPM — the long candidate-context prefix dominates token consumption. Against Azure OpenAI `gpt-5.4-mini` GlobalStandard tier ceilings (verified Microsoft Learn, 2026-05-02):

| Tier | RPM | TPM | Headroom for our shape |
|---|---|---|---|
| 1 (new-subscription default) | 1,000 | 1M | **Blown ×10 on TPM by 1 user at concurrency 24** |
| 4 | 7,000 | 7M | OK for 2 users, blown at 3 |
| 5 | 10,000 | 10M | At the edge for 4 users |
| 6 | 15,000 | 15M | Comfortable for 4 users |

Three mechanisms to prevent 429s, layered:

1. **Cap total worker count at the Function app — the architectural answer.** Stage 3c (and any other Axis-1 Service Bus fan-out) is KEDA-scaled. Set `maxReplicaCount` on each fan-out Function deployment so total in-flight stays under your tier's TPM ceiling with ~30% headroom:

   ```
   maxReplicaCount = floor(tier_TPM × 0.7 / (tokens_per_call × calls_per_minute_per_worker))
   ```

   For Tier 5 with this prompt shape: ~48. With 4 concurrent users, those 48 replicas are shared — each user sees ~12 effective workers instead of 24. Per-user Stage 3c wall-clock roughly doubles under contention; no 429s. The per-run `concurrency=24` in `orchestrator_service/runner.py` becomes a *requested* concurrency — Service Bus queues messages and KEDA respects `maxReplicaCount`. Graceful degradation: fast alone, slower when shared, never refused.

2. **Pre-flight tier increase before first deploy.** New Azure OpenAI subscriptions start at Tier 1 (1K RPM / 1M TPM) — too low even for a single concurrency-24 user. Submit a quota-increase request through the Azure quota portal before any production traffic. Tiers also auto-promote with monthly spend on the model, so a healthy production deployment migrates up the ladder over time, but the first month or two is the danger zone where the KEDA cap is doing real work.

3. **SDK-native retry on incidental 429s.** The `openai` SDK has automatic exponential backoff on 429 responses. For Service Bus queue-triggered Functions, the message goes back on the queue with a configurable visibility timeout if processing fails. Together these handle bursts that briefly punch through the tier ceiling — insurance for transients, not a substitute for #1.

**Provisioned Throughput Units (PTUs) — the "no shared rate limits" alternative.** Reserved hourly capacity, no 429s under the provisioned ceiling. Wrong shape for scale-to-zero deployments: PTUs bill hourly regardless of usage, so they only earn their cost at sustained high utilization (enterprise SaaS with continuous traffic). For this pipeline's sporadic-burst shape, GlobalStandard with KEDA-cap is the right call. Re-evaluate PTUs only if (a) sustained traffic justifies the always-on cost or (b) latency-sensitive workloads need guaranteed throughput regardless of contention. Not the case today.

### Where you stop pushing

1. **Azure OpenAI rate limits.** See *Multi-tenant rate-limit behavior* above — TPM ceiling is the architectural ceiling, KEDA `maxReplicaCount` is the operational cap, tier ramp + quota-increase requests handle the long-term ladder.
2. **Functions Flex instance ceiling.** 1,000 instances per app. Past this, fan-out queues — acceptable, but the wall-clock gain plateaus.
3. **Reduce-step cost.** Every fan-out has a fan-in. If the reduce step grows with N, you eventually pay back what you saved.

---

## 7. Cost shape

With cold starts tolerated and `min-replicas=0` everywhere, the only always-on costs are storage baselines. Per-run cost is dominated by model API spend, not Azure compute. Pricing below is READ-tier from Microsoft Learn examples (East US LRS) and the Azure Files pricing page; **confirm against the live pricing calculator before commit-grade decisions**, since list prices drift.

| Component | Cost shape | Idle cost |
|---|---|---|
| Web app (Container App) | Per-second when handling requests | $0 with min-replicas=0 |
| Stage workers (Flex Consumption) | Per-second of execution + per-million invocations | $0 |
| Stage 3c eval workers | Per-second × N parallel × eval duration | $0 |
| Service Bus | Per-million operations (~$0.05/M Standard) | ~$10/mo Standard tier baseline (or use Basic for ~$0) |
| Cosmos DB (serverless) | Per-RU consumed | ~$0 if not queried |
| Blob Storage (if used for archival) | Per-GB stored + per-operation | Cents/GB-month |
| **Azure Files (single SMB share, primary storage)** | **Standard pay-as-you-go**: per-GB stored + per-transaction. **Premium SSD (FileStorage account)**: provisioned per-GiB-hour, 100 GiB minimum, baseline 3,000 IOPS / 100 MiB/s included; no transaction charges. | **Standard**: ~$0.06/GB-month + transaction charges (scales with parallel reads). **Premium**: ~$10–16/mo floor for the 100 GiB minimum share at example list rates. |
| AI Search (if §2.3 fallback chosen) | Tier baseline | ~$75/mo Basic |
| Key Vault | Per-operation | Cents |
| Azure OpenAI `gpt-5.4-mini` (production) | Per-token (input + output); automatic ~50% off cached input ≥1024 tokens | $0 |
| Anthropic Sonnet 4.6 (fallback only) | Per-token (input + output) with explicit cache_control breakpoints | $0 |

**Azure Files Standard vs Premium for the FAISS + catalogs mount.** Standard is cheaper at low read concurrency but bills per transaction, which compounds when many Stage-3c-style fan-out workers each load the FAISS index in parallel. Premium has no transaction charge and a higher throughput ceiling (~100+ MiB/s vs ~60), but the 100 GiB provisioned minimum is a fixed monthly cost regardless of utilization. For modest workloads Standard wins on absolute cost; Premium becomes the right call once parallel read transactions or load latency push past Standard's envelope. Measure (§8) before committing.

**Vector store choice.** The recommended shape (FAISS on Azure Files mount, §2.3) keeps idle cost at the Azure Files baseline above and avoids the AI Search ~$75/mo floor. Re-evaluate AI Search only if query volume exceeds the throughput envelope of one share or if multiple long-running services need to share an index without each paying the per-instance SMB page-in.

---

## 8. Open questions / not VERIFIED

Items below are claims I'd like to land but haven't run end-to-end against the actual pipeline:

- **Total wall-clock time for a typical run after per-stage fan-out** — measure after each Phase C step in §6 to decide whether to stop or continue with the next-priority stage.
- **Azure OpenAI tier and `gpt-5.4-mini` RPM ceiling at expected production volume** — gates how far Stage 3c fan-out can scale before rate-limit retries become the bottleneck. Tier ramps with monthly Azure spend; new subscriptions start at Tier 1 (1K RPM / 1M TPM on GlobalStandard).
- **Stage 5 review burden under gpt-5.4-mini's abstain bias.** Smoke test (61 redvale concepts, 2026-05-02) showed gpt-5.4-mini abstains where Sonnet picks a stretched anchor — preferred behavior, but observe in production whether the absolute review volume becomes a bottleneck. Trigger to switch to Sonnet-fallback if review burden exceeds tolerable threshold.
- **FAISS load time over the Azure Files SMB mount** on a fresh worker instance, at the FAISS index size produced by `om-build-vector-index` for typical catalogs (NIEM/NODS/SALI). Gates whether Standard Azure Files (~60 MB/s) is sufficient or whether Premium FileStorage (~100+ MB/s, ~$10–16/mo floor) earns the upgrade.
- **Live Azure Files pricing** vs the example rates cited in §7 — confirm against the pricing calculator before commit-grade cost claims; published example rates drift.
- **Target-ontology onboarding workflow in Azure** — no doc captures end-to-end how a new target ontology (catalog + FAISS index + any registration) is added to a deployed cloud system. Several of the underlying questions have implicit answers in `OntologyMapper/` code or current convention (catalog-build CLI tools per `Pipeline__REFERENCE.md`, storage layout per §2.3 of this doc, `om-build-vector-index` for the FAISS step), but the operational story — where catalog-build jobs run in Azure, how the pipeline discovers new targets, how versions coexist or supersede, how source materials reach the build environment, and what the validation gate is — isn't surfaced anywhere. Resolve before bringing a new target online in cloud; capture as `AGENTS/Pipeline__TARGET_ONBOARDING.md` when designed.

Each is a half-day spike, not a research project. Run them before architectural commitment.

---

## 9. References

- Current orchestration: `C:\dev\OntologyMapper\web\backend\routes\runs.py` (lines 296–411 hold the stage sequence)
- Pipeline state: `.compiler-runs/{run_id}/.compiler-state.json` per [Pipeline__REFERENCE.md §State Management](Pipeline__REFERENCE.md)
- Stage SOPs: [Pipeline__STAGE_1.md](Pipeline__STAGE_1.md) through [Pipeline__STAGE_8.md](Pipeline__STAGE_8.md)
- Run audit log (post-run): [Pipeline__POST_RUN.md](Pipeline__POST_RUN.md)
- Azure Functions Flex Consumption hosting: https://learn.microsoft.com/azure/azure-functions/flex-consumption-plan
- Azure Functions timeout matrix: https://learn.microsoft.com/azure/azure-functions/functions-scale#function-app-timeout-duration
- Container Apps cold start guidance: https://learn.microsoft.com/azure/container-apps/cold-start
- Service Bus + KEDA for fan-out: https://learn.microsoft.com/azure/container-apps/scale-app
- Azure Files mount on Functions Flex Consumption: https://learn.microsoft.com/azure/azure-functions/flex-consumption-plan#mount-file-shares
- File access strategy (mount limits, authentication): https://learn.microsoft.com/azure/azure-functions/concept-file-access-options
- Azure Files billing models (Provisioned v1/v2, pay-as-you-go): https://learn.microsoft.com/azure/storage/files/understanding-billing
- Azure Files cost estimation examples: https://learn.microsoft.com/azure/storage/files/file-estimate-cost
- Azure Files live pricing: https://azure.microsoft.com/pricing/details/storage/files/
