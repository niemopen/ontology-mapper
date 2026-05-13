# Validation

> **Version**: 1.0 | **Updated**: 2026-04-04

---

## Modules

| Module | CLI | Stage | Purpose |
|--------|-----|-------|---------|
| `validate_input_package.py` | `om-validate-input` | pre-1 | Fail-fast check on source ontology package |
| `validate_edge_package.py` | `om-validate` | 7 | Cross-artifact conformance checks |
| `quality_gates.py` | *(library)* | post-4 | Mapping matrix internal consistency |
| `compute_edge_overlap.py` | `om-edge-overlap` | post-run | Cross-edge vocabulary overlap (Jaccard) |

---

## Architecture

### Validation layers

The pipeline has three validation layers at different points:

**Pre-pipeline** (`om-validate-input`): Validates that the source package
has minimum viable data before Stage 1. Checks:

| Code | Check |
|------|-------|
| IV-010 | Directory exists and is non-empty |
| IV-020 | Contains at least one parseable RDF/OWL file |
| IV-030 | Contains at least one class definition (owl:Class or rdfs:Class) |
| IV-040 | Contains at least one property definition |

Supported RDF formats: `.ttl`, `.owl`, `.rdf`, `.n3`, `.nt`, `.jsonld`.

**Post-matrix** (`quality_gates.py`): Sanity checks on the mapping matrix
after Stage 4. Returns structured warnings, not crashes:

| Code | Check |
|------|-------|
| QG-001 | No concepts in matrix (empty output) |
| QG-002 | Action counts must sum to total |
| QG-003 | Property stats must be internally consistent |

**Post-generation** (`om-validate`, Stage 7): Full conformance checks on
the edge package. Includes:

- Turtle syntax (rdflib parse all `.ttl` files)
- SHACL conformance (edge shapes against edge instances)
- CMF validity (if CMF artifacts present)
- Mapping completeness (every source class has a mapping entry)
- Extension justification (every extend entry has a justification)
- Decision log completeness (every mapping has a decision)
- Graph script validity (Cypher/SPARQL syntax, label cross-references)
- Target IRI verification (targetType resolves in target ontology)
- Package manifest accuracy (stats match actual counts)

### Cross-reference checks in validate_edge_package.py

Testable helper functions for graph script validation:

- `check_schema_labels(schema_content, active_labels)` — verifies Cypher
  schema constraints reference active classes from the mapping matrix
- `check_seed_consistency(seed_content)` — verifies MATCH labels in
  seed.cypher reference CREATEd labels

### Cross-edge overlap

`compute_edge_overlap.py` compares two or more edge packages to measure
interoperability. Uses Jaccard similarity on shared target type coverage.
This is a post-run analysis tool, not part of the standard pipeline.

---

## Contracts

### validate_edge_package.py output

Writes `{run_dir}/validation-report.json`:

```json
{
  "stage": "7",
  "generatedAt": "ISO-8601",
  "allPassed": true,
  "checkCount": 10,
  "passCount": 10,
  "failCount": 0,
  "checks": [
    { "check": "Turtle syntax", "status": "pass", "details": "" },
    { "check": "SHACL conformance", "status": "FAIL", "details": "..." }
  ]
}
```

### quality_gates.py output

Returns a list of warning dicts (not written to file):

```python
[{ "severity": "error", "code": "QG-002",
   "message": "Action counts don't sum to total",
   "detail": "..." }]
```

---

## Development Rules

In addition to the hard rules in `AGENTS.md`:

- **Fail fast, fail clear.** `validate_input_package.py` exists to produce
  clear error messages before Stage 1 rather than cryptic errors three
  stages later. If you add new pre-conditions, add them here.
- **Quality gates are warnings, not gates.** `quality_gates.py` returns
  warnings — the pipeline continues. Only Stage 7 validation is a hard gate.
- **Validation checks are testable functions.** Extract logic into pure
  functions (like `check_schema_labels`) that can be unit tested without
  file I/O.

---

## Anti-Patterns

- **Validating during generation**: Generators should not validate — they
  trust their inputs. Validation is a separate stage.
- **Suppressing warnings silently**: Quality gate warnings must be reported
  to the operator. Never swallow them.
- **Checking naming conventions for IRIs**: Do not rely on naming conventions
  to infer validity. For target IRIs, verify against the actual target
  ontology (API or catalog).
