# Boundary Coherence Reference

> **Paper**: Itelman, R. (2026). *Breaking Bellman: Dark Uncertainty and the
> Computable Cost of Desynchronized Decision Networks.* Draft v6.
>
> **Core idea**: When two systems share a boundary, each maintains its own
> codebook (type definitions, property definitions). Dark uncertainty is the
> entropy that exists at the boundary but is invisible to either side alone.
> The OntologyMapper pipeline makes this uncertainty visible, measurable,
> and actionable.

---

## Implemented Capabilities

### Act/Ask/Halt Decision Interface

Three-valued decision per property: Act (`reuse-property`), Ask
(`human-must-decide`), Halt (`create-property`). Ask properties cannot be
bulk-accepted — Stage 5 review loop continues until none remain.

### Target Type Change Cascade

When the user changes `targetType` at Stage 5,
`reclassify_for_target_type_change()` reclassifies properties against the
new type's property list, recomputes the action, and rebuilds scaffolding.
No vector search or LLM re-evaluation needed.

### Pre-Rotation Entropy Measurement

`om-entropy --run-dir {run_dir}` computes H_total from batch search
candidate counts. Writes `entropy-summary.json`. Runs after batch search,
before LLM evaluation.

### Residual Entropy Measurement

`om-residual-entropy --run-dir {run_dir}` joins pre-rotation entropy with
confidence signals. Confident decisions collapse entropy to zero; best-guess
decisions retain pre-rotation entropy. Writes `residual-entropy.json`.

### Rotation Provenance

Per-evaluation fields (`evaluatedAt`, `evaluatedBy`, `candidateCount`) and
`targetDefinitionHash` (SHA-256, 16 hex chars) for staleness detection.
Append-only `human-review-decisions.json` with `reviewedAt` timestamps.

### Codebook Version Fingerprinting

`om-detect-staleness --old REPORT --new REPORT` compares
`targetDefinitionHash` values between alignment reports. Reports stale
types, stale properties, new/dropped concepts.

### Custom Search During Review

`om-catalog-search` — catalog lookup (not vector search) for Stage 5
review. Case-insensitive substring on qname, local name, and definition.
Also available as the `search` subcommand in the human review tool.

### Coherence Manifest

Edge package artifact (`governance/coherence-manifest.json`) summarizing
rotation decisions, entropy measurements, and codebook version digest.
Bridges compile-time rotation and runtime verification.

### Cross-Boundary Validation

Stage 7 Check 12 loads the current reference catalog, hashes each target
type/property definition, and compares against `targetDefinitionHash` values
in the mapping matrix. Reports definitions that have changed or been removed.

---

## Beyond Current Reach

These capabilities are outside the pipeline's state space. They require
either runtime infrastructure (Observatron) or fundamentally different
architectures.

**Operational codebook divergence** — divergence between practice and formal
definitions. Lemma 1: if the state is outside the system's state space, no
computable function can observe it. The divergence must first be made
explicit.

**Continuous codebook spaces** — the pipeline operates in the discrete
regime (Boolean decisions). The probabilistic regime requires Fisher
information for continuous spaces.

**Autonomous drift detection** — detecting meanings that shift without
formal definition updates. Requires runtime statistical analysis across many
exchanges.

**Network-wide coherence** — coherence coverage across all pairwise
codebook relationships. Requires the Liquid Hypergraphs architecture.

**Real-time on-edge verification** — lightweight runtime verification at
boundary crossings. The pipeline produces the artifacts that support this
(entropy, staleness, coherence manifest). The verification itself is an
Observatron capability.
