# Ontology Adapters

> **Version**: 1.0 | **Updated**: 2026-04-04

---

## Modules

| Module | CLI | Purpose |
|--------|-----|---------|
| `ontology_specific.py` | *(library)* | Action determination via `resolve_alignment()` |
| `owl_cmf_bridge.py` | *(library)* | CMF dataclasses, XML/JSON serialization & parsing |
| `extract_concepts.py` | `om-extract` | OWL/SHACL/SKOS → concept inventory (Stage 2 OWL path) |
| `ingest_csv.py` | `om-ingest-csv` | CSV → concept inventory (Stage 2 CSV path) |
| `adapters/catalog_adapter.py` | *(library)* | Reference catalog → OntologyEntry for vector indexing |
| `adapters/source_adapter.py` | *(library)* | Concept inventory → OntologyEntry for vector indexing |

---

## Architecture

### The ontology-agnostic / ontology-specific boundary

The pipeline is ontology-agnostic by design. All stage tools, generators,
and the search infrastructure work with any target ontology. The
ontology-specific boundary is concentrated in two places:

1. **`ontology_specific.py`** — Action determination and enrichment rules
   that differ by target ontology (currently: NIEM vs. default)
2. **Catalog generators** — Each target ontology format needs its own
   parser (covered in `OM__GENERATORS.md`)

Everything else — pipeline engine, generators, search, validation — treats
the reference catalog as a uniform data structure.

### ontology_specific.py: Action determination

`resolve_alignment()`: Given the orchestrator's
semantic evaluation (type + property alignments), applies deterministic
structural rules to choose an action. The orchestrator does NOT set the
action directly — it provides evaluations, and `resolve_alignment()` applies
rules.

Before resolving a selected target, `canonical_class_target()` applies the
shared `class_target_filter()` policy and returns the spelling the pipeline
carries. When a native CMF reference is installed for the target/version,
eligibility comes from actual Class identities resolved through the catalog's
namespace bindings, plus explicit implicit roots. A full IRI is eligible only
when the catalog binds its namespace, and it is stored as that catalog QName,
so catalog lookups, scaffolding names, the OWL/CMF emitters and the Stage 7
drift check all see one identity; a reference class in an unbound namespace is
rejected at review rather than failing later as an unbound CMF reference.
The review apply path (`runner_tools.apply_decision_with_cascade`) compares
canonical identities, so re-accepting a stored IRI as its QName stores the QName
without a cascade; only a different class triggers reclassification.
`invalid_class_targets()` asks the same policy of a whole saved matrix: a
decision accepted before the policy existed makes no selection to check, so
review exit (`check_stage_5_exit`: all three web routes, the review state's
`canSubmit`, and the runner's Stage 6 entry `run_pipeline.refuse_invalid_class_targets`)
reports it as a blocker, and the generator itself (`generate_edge_ontology.main`,
reached by a Stage 6 resume, the web executor and a by-hand
`om-generate-ontology`) refuses to generate from it. Codebook drift (Stage 7
Check 12) looks a legacy full-IRI target up by its catalog QName
(`generation_utils.target_qname`), so a saved IRI is not reported missing. The
predicate asks about every field the emitters read as a superclass, not only
`targetType`: `baseType` for extend and `augmentsType` for augment, which an
edited matrix can leave naming a different type.
Datatypes and XSD-only names cannot become superclasses. Literal classes,
including classes with only inherited properties, remain eligible. Names,
patterns and property counts do not determine component kind.

An incompatible saved selection raises `ClassTargetError` without replacement
(`validate_class_target()` is the check-only form used for unchanged Stage 5
submissions). Null and undecided retain their existing review semantics.
Without an installed native reference, existing catalog behavior and the
selection's spelling are preserved; this is not a claim of native class
validation.

The installed reference is read once per process: `load_reference_cmf`
validates the specs path on every call and caches the decompressed text by
resolved path and mtime, because the class policy asks about one target at
a time — per matrix entry at review exit, per concept during collection —
and the file is a 2 MB gzip that expands to 24 MB.

The URI + name rule that builds component IRIs lives in
`generation_utils.component_iri`; its inverse, `generation_utils.target_qname`,
is what the policy and the CMF builder both ground with. The CMF builder
applies it again when emitting ids and namespaces, so a matrix saved before
this policy still emits `prefix.Name` references; an IRI outside the catalog
namespaces is emitted unchanged and reported by reference validation.

### NIEM action logic

`resolve_alignment()` delegates to `_determine_niem_action()`:

- Classifies each source property into three buckets:
  - `on_target`: target property exists AND is on the selected target type
  - `elsewhere`: target property exists but NOT on the target type
  - `not_found`: no target property equivalent
- Decision: if no remaining → **reuse**; if elsewhere >= not_found →
  **augment**; otherwise → **extend**

For non-NIEM ontologies, the default logic applies: if all properties
match → reuse, otherwise extend. No augment for non-NIEM targets (no
augmentation mechanism).

### Structural scaffolding

`resolve_alignment()` also adds ontology-specific scaffolding fields:

| Action | NIEM scaffolding |
|--------|-----------------|
| reuse | *(none)* |
| extend | `extensionType`, `baseType` |
| augment | `augmentationType`, `augmentsType` |

These are carried through to the mapping matrix and consumed by generators.

### reclassify_for_target_type_change()

When the user changes a concept's target type at Stage 5, property matches
are type-independent (the LLM searched the full target ontology). Only the
classification changes (on-target / elsewhere / not-found), which drives
the class-level action (reuse / augment / extend). No vector search or LLM
re-evaluation is needed.

```python
from ontology_mapper.ontology_specific import reclassify_for_target_type_change

result = reclassify_for_target_type_change(entry, new_target_type, target_ontology, catalog)
```

- **Input**: A mapping matrix entry (with `propertyMappings`, `action`,
  scaffolding keys), the new target type qname (or `None`), the target
  ontology name, and the reference catalog dict.
- **Output**: New dict (deep copy). Input is never mutated.
- **Behavior**: Recomputes class-level action using the same helpers as
  `resolve_alignment()` (`_classify_niem_properties` / `_determine_niem_action`
  for NIEM; found/missing count for non-NIEM). Clears old scaffolding, rebuilds
  for the new action, resets `reviewStatus` to `"pending-review"` on entry and
  all properties. Sets `ruleId = "target-type-change-cascade"`.
  Replaces `targetDefinition` and `targetDefinitionHash` with the new target's
  catalog definition (`generation_utils.definition_hash`, the same fingerprint
  alignment collection writes and Stage 7 Check 12 compares), so a legitimate
  target change does not report codebook drift.
  `targetTypeLabel` follows the same rule: the new target's catalog label, or
  removed when the catalog has none, so the review card never shows the
  previous target's label.
- **Null target type**: Allowed — produces extend from root
  (`structures:ObjectType` for NIEM, no `baseType` for non-NIEM).
- **Property actions do NOT change**: `reuse-property` / `create-property` /
  `human-must-decide` depend on `targetProperty` value, which doesn't change
  when the target type changes.

### Property-level actions

`resolve_alignment()` classifies each property:

- `reuse-property`: targetProperty is not None (match found)
- `create-property`: targetProperty is None (new property needed)

For `create-property`, a `newPropertyName` is derived from the source
property's local name.

### owl_cmf_bridge.py

CMF dataclasses (`CmfModel`, `CmfClass`, `CmfProperty`, etc.), XML/JSON
serializers, and XML parser. Used by `MatrixToCmfBuilder` (in
`generate_cmf_from_matrix.py`) to produce
spec-compliant CMF output. No CLI — library only.

Dependencies: `lxml`.

### Concept extraction (Stage 2)

Two paths depending on input format:

- **OWL path** (`om-extract`): Parses OWL classes, object/datatype
  properties, SHACL shapes, SKOS vocabularies from the source package.
  Auto-generates a package manifest if absent.
- **CSV path** (`om-ingest-csv`): Ingests tabular class/attribute
  definitions with types, multiplicities, and definitions.

Both produce `concept-inventory.json` in the same schema.

### Vector index adapters

The `adapters/` directory contains adapters that convert specific data
formats into `OntologyEntry` objects for vector indexing:

- **`catalog_adapter.py`** — Generic adapter for any reference catalog
  (NIEM, OWL, CMF). All three catalog generators produce the same JSON
  schema, so one adapter handles them all. Excludes augmentation-pattern
  types and abstract properties from indexing.
- **`source_adapter.py`** — Reads concept-inventory.json from a pipeline
  run to index source ontology concepts.

---

## Contracts

### resolve_alignment() interface

```python
from ontology_mapper.ontology_specific import resolve_alignment

resolved = resolve_alignment(evaluation, target_ontology, catalog)
```

- **Input**: evaluation dict (from orchestrator) with `targetType`,
  `targetDefinition`, `targetPath`, `rationale`, `properties[]`
- **Output**: Same dict with `action`, `actionRationale`, property-level
  `propertyAction`, `newPropertyName`, and structural scaffolding added
- **The orchestrator must NOT set `action`** — that's `resolve_alignment()`'s
  job based on structural analysis

### Reference catalog schema

All catalog generators produce this structure (abbreviated):

```json
{
  "version": "...",
  "description": "...",
  "stats": { "totalTypes": 0, "totalPropertyMemberships": 0 },
  "actions": { "reuse": "...", "extend": "...", "augment": "..." },
  "typePatterns": { "object": "...", "association": "..." },
  "namespaces": { "prefix": "URI" },
  "types": [{ "qname": "", "definition": "", "baseType": "", "pattern": "",
              "properties": [], "inheritanceChain": [],
              "propertyDefinitions": {} }],
  "propertyIndex": { "prefix": { "properties": [{ "name": "", "definition": "",
                      "qualifiedProperty": "", "qualifiedType": "",
                      "containingTypes": [] }] } },
  "augmentationMap": { "prefix:BaseType": [{ "augType": "", "properties": [] }] }
}
```

The `actions` key defines valid class-level actions for the target ontology.
The `typePatterns` key lists structural patterns actually present.

---

## Development Rules

### Adding a new target ontology

1. Write a catalog generator (or use `om-generate-owl-catalog` for standard OWL)
2. Ensure it produces the standard catalog JSON schema with `actions` and
   `typePatterns` keys
3. If the ontology has unique structural mechanisms (like NIEM augmentation),
   add a branch in `ontology_specific.py` for enrichment and action logic
4. The generic `catalog_adapter.py` handles indexing — no new adapter needed
5. Build vector indexes: `om-build-vector-index --adapter catalog --ontology {name} --version {ver}`

### Key principles (in addition to the hard rules in `AGENTS.md`)

- **Orchestrator reasons, ontology_specific resolves.** The orchestrator
  evaluates semantic similarity. `resolve_alignment()` applies structural
  rules. Never mix these responsibilities.
- **Catalog schema is the contract.** All ontology-specific differences are
  absorbed during catalog generation. Downstream tools see a uniform schema.
- **Pass-through for unknown ontologies.** `ontology_specific.py` must
  always have a default path that works for any ontology without specific
  support.

---

## Anti-Patterns

- **Action override in the orchestrator**: The orchestrator must never set
  `action` directly. It provides evaluations; `resolve_alignment()` decides.
- **Ontology-specific logic in generators**: Generators consume the uniform
  catalog and mapping matrix. If you need ontology-specific behavior, put it
  in `ontology_specific.py`.
- **New adapters per ontology**: The `catalog_adapter.py` is generic. Only
  write a new adapter if the data format genuinely differs from the catalog
  schema.
