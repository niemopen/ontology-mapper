# Orchestration Project Rules

> **Repo**: OntologyMapper | **Version**: 3.0 | **Updated**: 2026-04-04
> **Scope**: Schema definitions, valid actions, and decision rule summaries

---

## Entropy Summary Schema

The entropy summary (`entropy-summary.json`) is produced by `om-entropy` after batch search and before LLM evaluation. It is a separate artifact from the mapping matrix — different lifecycle, different concern. Per-concept entropy values are surfaced during Stage 5 review.

Top-level fields: `hTotal`, `hTypes`, `hProperties`, `typesAnalyzed`, `propertiesAnalyzed`. Arrays: `perConcept` (entries with `sourceConcept`, `candidateCount`, `entropy`) and `perProperty` (entries with `sourceProperty`, `parentConcept`, `candidateCount`, `entropy`).

## Residual Entropy Schema

The residual entropy report (`residual-entropy.json`) is produced by `om-residual-entropy` after Stage 5 review. It joins pre-rotation entropy with confidence signals: confident decisions collapse to zero entropy, best-guess decisions retain their pre-rotation value. Top-level fields: `hPreTotal`, `hResidualTotal`, `hResolvedTotal` (and per-type/property breakdowns). Per-concept and per-property arrays include `preEntropy`, `confidence`, and `residualEntropy`.

## Staleness Report Schema

The staleness report (`staleness-report.json`) is produced by `om-detect-staleness --old REPORT --new REPORT`. It compares `targetDefinitionHash` values between two alignment reports. Top-level: `comparisonMetadata` (old/new ontology+version+timestamp), `summary` (`totalConcepts`, `unchanged`, `staleTypes`, `stalePropertyOnly`, `totalStaleProperties`, `newConcepts`, `droppedConcepts`), `staleAlignments` (array of entries with `sourceConcept`, `oldHash`/`newHash`, `oldDefinition`/`newDefinition`, nested `staleProperties`), `newConcepts`, `droppedConcepts`. Works with both alignment report (`properties` key) and mapping matrix (`propertyMappings` key).

## Coherence Manifest Schema

The coherence manifest (`governance/coherence-manifest.json`) is built at Stage 6b by `build_coherence_manifest()`. Top-level: `schemaVersion`, `generatedAt`, `generatedBy`, `targetOntology`, `targetVersion`, `rotationSummary` (class/property action counts and confidence counts), `entropy` (preTotal/residualTotal/resolvedTotal and type/property breakdowns; `null` when entropy artifacts absent), `codebookDigest` (typeHashCount, propertyHashCount, distinctTypeHashes, distinctPropertyHashes from `targetDefinitionHash` values).

---

## Alignment Report Schema

The alignment report (`alignment-report.json`) is produced at Stage 3 by semantic search and LLM evaluation. Each entry represents one source concept:

```json
{
  "matchingMethod": "semantic",
  "targetOntology": "niem", "targetVersion": "6.0",
  "actions": { "reuse": "...", "extend": "...", "augment": "..." },
  "typePatterns": { "object": "...", "association": "..." },
  "entries": [{
    "sourceConcept": "court:HearingType",
    "sourceDefinition": "A scheduled court proceeding.",
    "sourcePath": "court:HearingType",
    "action": "reuse", "actionRationale": "All properties matched.",
    "targetType": "j:CourtEventType",
    "targetDefinition": "A data type for a court event.",
    "targetPath": "j:CourtEventType",
    "rationale": "Both represent scheduled court proceedings.",
    "evaluatedAt": "2026-04-09T14:30:00+00:00", "evaluatedBy": "sonnet",
    "candidateCount": 8, "targetDefinitionHash": "a1b2c3d4e5f67890",
    "properties": [{
      "sourceProperty": "court:HearingDate",
      "sourceDefinition": "The date of the hearing.",
      "sourcePath": "court:HearingType/court:HearingDate",
      "propertyAction": "reuse-property",
      "targetProperty": "ActivityDate", "targetDefinition": "A date of an activity.",
      "targetPath": "nc:ActivityDate", "rationale": "Both represent activity dates.",
      "evaluatedAt": "2026-04-09T14:30:01+00:00", "evaluatedBy": "sonnet",
      "candidateCount": 12, "targetDefinitionHash": "b2c3d4e5f6789012"
    }]
  }]
}
```

### Alignment Report Top-Level Fields

| Field | Type | Required | Description |
|---|---|---|---|
| `matchingMethod` | string | Yes | `"semantic"` when evaluation is complete; `"pending-evaluation"` in the placeholder |
| `targetOntology` | string | Yes | Target ontology name (e.g., `"niem"`, `"sali-folio"`) |
| `targetVersion` | string | Yes | Target ontology version (e.g., `"6.0"`) |
| `actions` | object | Yes | Valid actions for this target ontology, read from the reference catalog. Keys are action names, values are descriptions. The evaluator chooses from this list. |
| `typePatterns` | object | Yes | Structural patterns from the reference catalog. Keys are pattern names, values are descriptions. Context for semantic search. |
| `entries` | array | Yes | List of alignment entries (one per source concept) |

Both files also include `stage` and `generatedAt` metadata fields (not shown above) for traceability.

### Orchestration Config (`.mapper-state.json`)

Run-level orchestration parameters are stored in the `orchestrationConfig`
object within `.mapper-state.json` (via `PipelineState.orchestration_config`).
Written by the evaluation service (`runner.py`) after evaluation completes.

| Field | Type | Description |
|---|---|---|
| `evaluatorModel` | string | Claude model name used for LLM evaluation (e.g., `"sonnet"`) |
| `evaluatorConcurrency` | integer | Number of concurrent LLM evaluation calls |
| `maxRetries` | integer | Maximum retry count per evaluation call |

This is run-level metadata — it does not vary per entry. Per-entry provenance
(`evaluatedAt`, `evaluatedBy`, `candidateCount`) is in the alignment report.

### Alignment Entry Fields

| Field | Type | Required | Description |
|---|---|---|---|
| `sourceConcept` | string | Yes | Qualified name of the source concept (e.g., `court:HearingType`) |
| `sourceDefinition` | string | Yes | Definition from the source concept inventory |
| `sourcePath` | string | Yes | Composition path for the source concept |
| `action` | string | Yes | One of the actions defined in the top-level `actions` object (set by `resolve_alignment()`) |
| `actionRationale` | string | Yes | Explanation of the action choice (set by `resolve_alignment()`) |
| `targetType` | string | Conditional | Target qualified name (required when the action involves a target type) |
| `targetDefinition` | string | Conditional | Target type definition (present when `targetType` is set) |
| `targetPath` | string | Conditional | Composition path for the target type |
| `rationale` | string | Yes | Explanation of why this decision was made |
| `evaluatedAt` | string | Yes | ISO 8601 timestamp of the LLM evaluation (provenance) |
| `evaluatedBy` | string | Yes | Model name used for evaluation (provenance) |
| `candidateCount` | integer | Yes | Number of post-filter candidates presented to the LLM (provenance) |
| `targetDefinitionHash` | string/null | Yes | SHA-256 prefix (16 hex chars) of `targetDefinition` at evaluation time; `null` when `targetDefinition` is `null`. Enables staleness detection: when a target ontology releases a new version, diff hashes to identify which alignments reference changed definitions without re-running the pipeline. Bridge to codebook version fingerprinting (Item 6). |
| *(scaffolding)* | string | Conditional | Ontology-specific structural fields added by `resolve_alignment()` — see Mapping Entry Fields for details. |
| `properties` | array | Yes | Per-property alignments (see Alignment Property Fields below) |

### Alignment Property Fields

Each entry in the `properties` array represents one source property aligned to the target ontology. The matrix builder reshapes these into `propertyMappings` (renaming `propertyAction` → `action`, adding `reviewStatus`).

| Field | Type | Required | Description |
|---|---|---|---|
| `sourceProperty` | string | Yes | Source property name |
| `sourceDefinition` | string | Yes | Source property definition |
| `sourcePath` | string | Yes | Composition path for the source property |
| `propertyAction` | string | Yes | `reuse-property`, `create-property`, or `human-must-decide` (set by `resolve_alignment()`) |
| `targetProperty` | string | Conditional | Target property local name (for `reuse-property`), `"[undecided]"` (for `human-must-decide`), or `null` (for `create-property`) |
| `targetDefinition` | string | Conditional | Target property definition |
| `targetPath` | string | Conditional | Composition path for the target property |
| `rationale` | string | Yes | Explanation of the property-level decision |
| `evaluatedAt` | string | Yes | ISO 8601 timestamp of the LLM evaluation (provenance) |
| `evaluatedBy` | string | Yes | Model name used for evaluation (provenance) |
| `candidateCount` | integer | Yes | Number of post-filter candidates presented to the LLM (provenance) |
| `targetDefinitionHash` | string/null | Yes | SHA-256 prefix (16 hex chars) of `targetDefinition`; `null` when `targetDefinition` is `null`. Same staleness detection purpose as the entry-level hash. |
| `newPropertyName` | string | Conditional | Local name for new property (for `create-property`, set by `resolve_alignment()`) |

---

## Mapping Matrix Schema

The mapping matrix is a decision artifact — it does not carry provenance
fields (`evaluatedAt`, `evaluatedBy`, `candidateCount`). Those remain in
the alignment report, which is the audit trail. The matrix builder
(`build_mapping_matrix.py`) copies only the fields listed below.

The mapping matrix (`mapping-matrix.json`) is produced at Stage 4 by the matrix builder and refined through Stage 5 human review:

```json
{
  "actions": { "reuse": "...", "extend": "...", "augment": "..." },
  "mappings": [{
    "sourceConcept": "court:HearingType",
    "sourceDefinition": "A scheduled court proceeding.",
    "sourcePath": "court:HearingType",
    "action": "reuse", "actionRationale": "Direct semantic match.",
    "targetType": "j:CourtEventType",
    "targetDefinition": "A data type for a court event.",
    "targetPath": "j:CourtEventType",
    "rationale": "Both represent scheduled court proceedings.",
    "reviewStatus": "pending-review",
    "propertyMappings": [{
      "sourceProperty": "court:HearingDate", "sourceDefinition": "The date of the hearing.",
      "sourcePath": "court:HearingType/court:HearingDate",
      "action": "reuse-property", "targetProperty": "ActivityDate",
      "targetDefinition": "A date of an activity.", "targetPath": "nc:ActivityDate",
      "reviewStatus": "pending-review", "rationale": "Both represent activity dates."
    }]
  }],
  "summary": { "totalConcepts": 25, "actionCounts": {"reuse": 12, "extend": 10, "augment": 3}, "pendingReview": 25, "accepted": 0, "bestGuess": 0, "propertyStats": { "total": 150, "reuseProperty": 80, "createProperty": 67, "humanMustDecide": 3, "pendingPropertyReview": 150, "acceptedProperty": 0, "bestGuessProperty": 0 } }
}
```

### Mapping Matrix Top-Level Fields

| Field | Type | Required | Description |
|---|---|---|---|
| `targetOntology` | string | Yes | Target ontology name |
| `targetVersion` | string | Yes | Target ontology version |
| `actions` | object | Yes | Valid actions (carried from alignment report) |
| `typePatterns` | object | Yes | Structural patterns (carried from alignment report) |
| `mappings` | array | Yes | Array of mapping entries |
| `summary` | object | Yes | Aggregate counts (recomputed by `recompute_summary()`). Includes `bestGuess` and `bestGuessProperty` — count of accepted decisions with `confidence: "best-guess"`. |
| `humanReviewApplied` | string | Conditional | ISO 8601 timestamp, added by `save_matrix()` when human review decisions are applied |

As with the alignment report, `stage` and `generatedAt` metadata fields are present but not shown.

### Mapping Entry Fields

| Field | Type | Required | Description |
|---|---|---|---|
| `sourceConcept` | string | Yes | Qualified name of the source concept |
| `sourceDefinition` | string | Yes | Source concept definition |
| `sourcePath` | string | Yes | Composition path for the source concept |
| `action` | string | Yes | One of the actions defined in the top-level `actions` object |
| `actionRationale` | string | Yes | Explanation of the action choice |
| `targetType` | string | Conditional | Target ontology qualified name (required when the action involves a target type) |
| `targetDefinition` | string | Conditional | Target type definition (present when `targetType` is set) |
| `targetPath` | string | Conditional | Composition path for the target type |
| `rationale` | string | Yes | Explanation of why this decision was made |
| `reviewStatus` | string | Yes | `pending-review` or `accepted` |
| `confidence` | string | Conditional | `"confident"` (default) or `"best-guess"`. Set at Stage 5. Confident decisions collapse residual entropy to zero; best-guess decisions retain pre-rotation entropy — the ambiguity was forced to a choice, not truly resolved. |
| `ruleId` | string | Conditional | Decision rule ID (set by `human-review` at Stage 5) |
| `notes` | string | Conditional | Additional context from human review |
| *(scaffolding)* | string | Conditional | Ontology-specific structural fields added by `resolve_alignment()` (e.g., `extensionType`/`baseType` for extend, `augmentationType`/`augmentsType` for augment). Carried forward verbatim — the set of fields depends on the target ontology's action definitions. |
| `propertyMappings` | array | Conditional | Per-property decisions (present when `targetType` is set) |

### Property Mapping Fields

| Field | Type | Required | Description |
|---|---|---|---|
| `sourceProperty` | string | Yes | Source property name |
| `sourceDefinition` | string | Yes | Source property definition |
| `sourcePath` | string | Yes | Composition path for the source property |
| `action` | string | Yes | Property-level action (see Valid Actions below) |
| `targetProperty` | string | Conditional | Target property local name (for `reuse-property`), `"[undecided]"` (for `human-must-decide`), or `null` (for `create-property`) |
| `targetDefinition` | string | Conditional | Target property definition |
| `targetPath` | string | Conditional | Composition path for the target property |
| `reviewStatus` | string | Yes | `pending-review` or `accepted` |
| `confidence` | string | Conditional | `"confident"` or `"best-guess"`. Set at Stage 5 (same semantics as class-level). |
| `rationale` | string | Yes | Explanation of the property-level decision |
| `newPropertyName` | string | Conditional | Local name for new property (for `create-property`) |

---

## Valid Actions

### Class-Level Actions

Class-level actions are defined by the target ontology's reference catalog. The `actions` object in the alignment report and mapping matrix lists the valid actions for the current run. The evaluator chooses from this list — it is a multiple-choice selection, not a free-form field.

Every source concept in the source ontology must be mapped. There is no "exclude" action — the organization is presenting their full ontology for alignment.

### Property-Level Actions

| Action | Meaning |
|---|---|
| `reuse-property` | The source property maps to an existing target property reachable from the target type. |
| `create-property` | The source property has no viable target match and requires a new extension property. |
| `human-must-decide` | The LLM found multiple equally good candidates and could not confidently choose. The `targetProperty` field is set to `"[undecided]"`. This property **must** be resolved individually at Stage 5 — it cannot be bulk-accepted, skipped, or defaulted. |

---

## Review Status Lifecycle

### Class-Level

```
pending-review  -->  accepted
                       ^
                       |
              (human review at Stage 5)
```

### Property-Level

```
pending-review  -->  accepted
                       ^
                       |
              (human review at Stage 5)
```

Properties with `action: "human-must-decide"` cannot be bulk-accepted. They must be individually resolved to `reuse-property` or `create-property` at Stage 5. The review loop (present → decide → check) continues until no `human-must-decide` properties remain.

All mappings must reach `reviewStatus: "accepted"` before Stage 6 generation begins. The generation audit (GA-006) blocks generation if any `human-must-decide` properties remain unresolved.

### Decision Persistence

Human review decisions are stored in `human-review-decisions.json` as an
append-only log. Each decision entry includes a `reviewedAt` timestamp.
Multiple changes to the same concept produce multiple entries — replay in
order for current state, read the log for full history. The mapping matrix
does not store decision history; the decisions file is the single source of
truth for review provenance.

### Target Type Change Cascade

When the user changes `targetType` for a concept at Stage 5, the system
reclassifies existing property matches against the new type's property list
and recomputes the action. No vector search or LLM re-evaluation is needed —
property-to-property matches are type-independent.

Use `apply_decision_with_cascade()` (not `apply_decision()`) when a decision
may include a target type change. The cascade calls
`reclassify_for_target_type_change()` in `ontology_specific.py`, which:
1. Reclassifies properties (on-target / elsewhere / not-found)
2. Recomputes the action (reuse / augment / extend)
3. Clears old scaffolding and rebuilds for the new action
4. Resets `reviewStatus` to `pending-review` on the entry and all properties

The generation audit (GA-007) blocks generation if scaffolding is inconsistent
with `targetType` — e.g., `augmentsType` does not match `targetType` for an
augment entry, or `baseType` does not match for an extend entry.
