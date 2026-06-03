# Edge Package Specification

> **Version**: 2.1 | **Updated**: 2026-04-02

## Purpose

This specification defines the standard structure for an edge ontology package produced by OntologyMapper, aligned to a target ontology (NIEM, SALI/FOLIO, etc.). Every domain processed by OntologyMapper MUST produce an edge package conforming to this structure. Downstream agentic systems, graph platforms, and integration tooling depend on this layout being consistent across all domains.

**Schemas already defined in [Pipeline__PROJECT_RULES.md](Pipeline__PROJECT_RULES.md)** (not repeated here):
- `mapping-matrix.json` — class and property mapping schemas, valid actions, review statuses
- `alignment-report.json` — alignment entry fields, actions, type patterns

---

## Package naming convention

```
{organization}_{source}_edge_package/
```

## Required directory structure

```
{package_root}/
│
├── README.md                          # Package manifest and usage guide
├── package-manifest.json              # Machine-readable package metadata
│
├── cmf/                               # Canonical Model Format
│   ├── {source}-model.cmf.xml         # CMF model file
│   └── {source}-model.cmf.json        # CMF model in JSON representation
│
├── ontology/                          # Target-aligned OWL/RDF ontology modules
│   ├── {source}-edge-core.ttl         # Core edge classes and properties (target-aligned)
│   ��── {source}-edge-extensions.ttl   # Extension namespace for target ontology gaps
│   ├── {source}-edge-all.ttl          # Import ontology gathering all modules
│   └── {source}-edge-combined.ttl     # Flattened combined export (build artifact)
│
├── mappings/                          # Internal-to-target alignment artifacts
│   ├── mapping-matrix.json            # Final mapping: source concept → target type
│   ├── mapping-matrix.md              # Human-readable mapping matrix
│   ├── alignment-report.json          # Semantic alignment results (LLM evaluation decisions)
│   ├── gap-analysis.md                # What the target ontology covers, partially covers, or misses
│   └── extension-justifications.md    # Rationale for every extension term
│
├── extensions/                        # Extension namespace definitions
│   ├── {source}-ext.ttl               # OWL definitions for extension types/properties
│   ├── extension-catalog.json         # Machine-readable extension inventory
│   └── conformance-notes.md           # How extensions relate to target ontology conformance rules
│
├── schemas/                           # Exchange format schemas
│   ├── json/{message-type}.schema.json
│   ├── xml/{message-type}.xsd
│   └── jsonld/{source}-edge-context.jsonld
│
├── kg/                                # Knowledge graph deployment artifacts
│   ├── neo4j/
│   │   ├── schema.cypher              # Node/edge type DDL, constraints, indexes
│   │   ├── seed.cypher                # Sample data import
│   │   └── queries/{query-name}.cypher
│   ├── rdf/
│   │   ├── {source}-edge.trig         # Named graph export
│   │   └── sparql/{query-name}.rq
│   └── import/
│       ├── internal-to-edge.json      # Transform rules: internal → edge graph
│       └── loader-config.json         # Graph import configuration
│
├── shapes/                            # Validation constraints
│   ├── {source}-edge-shapes.ttl       # SHACL shapes for edge ontology conformance
│   └── conformance-shapes.ttl         # SHACL shapes enforcing target alignment rules
│
├── vocab/                             # Controlled vocabularies (target-aligned)
│   ├── {source}-edge-codelists.ttl    # SKOS concept schemes mapped to target code tables
│   └── codelist-mappings.json         # Internal codelist → target code table mappings
│
├── contracts/                         # Agent-facing integration contracts
│   ├── entity-catalog.json            # Node types available in the edge graph
│   ├── relation-catalog.json          # Edge types available in the edge graph
│   ├── query-patterns.json            # Allowed/recommended graph query patterns
│   ├── retrieval-profiles.json        # Semantic retrieval configurations
│   └── tool-contracts.json            # Ontology-aware tool definitions for agents
│
├── governance/                        # Audit, lineage, and maintenance artifacts
│   ├── decision-log.json              # Every mapping/extension decision with rationale
│   ├── decision-log.md                # Human-readable decision log
│   ├── lineage-manifest.json          # Provenance: source material → artifact traceability
│   ├── version-manifest.json          # Package version, target ontology version, generation metadata
│   └── change-impact.md               # Impact analysis for pending changes
│
├── tests/
│   ├── fixtures/valid/{scenario}.ttl
│   ├── fixtures/invalid/{scenario}.ttl
│   ├── conformance/{check-name}.json
│   └── graph-integrity/{check-name}.cypher
│
└── docs/
    ├── edge-model-overview.md
    ├── alignment-summary.md
    └── integration-guide.md
```

---

## Artifact schemas

### `package-manifest.json`

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | `{org}_{source}_edge_package` |
| `version` | string | Semantic version (e.g., `1.0.0`) |
| `description` | string | One-line package description |
| `sourcePackage` | string | Name of the source internal ontology package |
| `targetOntology` | string | Target ontology name (e.g., `"niem"`) |
| `targetVersion` | string | Target ontology version (e.g., `"6.0"`) |
| `targetDomains` | string[] | Target ontology domains referenced (e.g., `["justice"]`) |
| `targetGraphPlatforms` | string[] | Graph platforms supported (e.g., `["neo4j", "rdf"]`) |
| `generatedBy` | string | `"ontology-mapper"` |
| `generatedAt` | ISO 8601 | Generation timestamp |
| `finalizedAt` | ISO 8601 | Finalization timestamp (set at Stage 8) |
| `extensionNamespace` | URI | Extension namespace IRI |
| `edgeNamespace` | URI | Edge namespace IRI |
| `stats.totalConcepts` | int | Total source concepts processed |
| `stats.actionCounts` | object | `{action: count}` — keys are the target ontology's valid actions |

---

### `governance/decision-log.json`

| Field | Type | Description |
|-------|------|-------------|
| `stage` | string | Pipeline stage that produced the log (e.g., `"4"`) |
| `generatedAt` | ISO 8601 | Generation timestamp |
| `totalDecisions` | int | Total decision count |
| `decisions[]` | array | Decision entries (see below) |

**Decision entry fields:**

| Field | Type | Description |
|-------|------|-------------|
| `id` | int | Sequential decision ID |
| `sourceConcept` | string | Qualified source concept name |
| `ruleId` | string | Decision rule ID (see [Pipeline__PROJECT_RULES.md](Pipeline__PROJECT_RULES.md)) |
| `action` | string | One of the target ontology's valid actions |
| `rationale` | string | Explanation of the decision |
| `targetType` | string? | Target ontology qualified name (if applicable) |
| `notes` | string? | Additional context |
| `propertyDecisions` | array? | Compact property decision snapshots (present when class has accepted properties) |

**Property decision snapshot fields:**

| Field | Type | Description |
|-------|------|-------------|
| `sourceProperty` | string | Source property name |
| `action` | string | `reuse-property` or `create-property` |
| `targetProperty` | string? | Target property name (for reuse-property) |
| `notes` | string? | Additional context |

---

### `extensions/extension-catalog.json`

Includes both extend entries (new types) and augment entries (new properties on existing types).

| Field | Type | Description |
|-------|------|-------------|
| `extensions[].extensionIRI` | URI | Full IRI of the extension or augmentation type |
| `extensions[].name` | string | Local type name |
| `extensions[].baseType` | string | For extend: base type (`baseType` scaffolding). For augment: augmented type (`augmentsType` scaffolding). |
| `extensions[].definition` | string | Type definition |
| `extensions[].properties` | string[] | Extension property IRIs |
| `extensions[].justification` | string | Why this extension is needed |
| `extensions[].sourceConceptIRI` | URI | Source concept IRI |
| `extensions[].mappingEntryRef` | string | Source concept qualified name (links to mapping matrix) |

---

### `contracts/entity-catalog.json`

| Field | Type | Description |
|-------|------|-------------|
| `entities[].label` | string | Human-readable entity label |
| `entities[].edgeIRI` | URI | Edge ontology type IRI |
| `entities[].targetIRI` | string | Target ontology type qualified name |
| `entities[].action` | string | One of the target ontology's valid actions |
| `entities[].graphLabel` | string | Graph node label |
| `entities[].definition` | string | Entity definition |
| `entities[].canonicalId` | string | Canonical identifier property name |
| `entities[].properties` | string[] | Available property names |
| `entities[].inboundRelations` | string[] | Inbound relationship labels |
| `entities[].outboundRelations` | string[] | Outbound relationship labels |

---

### `contracts/relation-catalog.json`

| Field | Type | Description |
|-------|------|-------------|
| `relations[].label` | string | Relationship label (e.g., `SUBMITTED_BY`) |
| `relations[].edgeIRI` | URI | Edge ontology property IRI |
| `relations[].sourceEntityLabel` | string | Source node type label |
| `relations[].targetEntityLabel` | string | Target node type label |
| `relations[].definition` | string | Relationship definition |
| `relations[].cardinality` | string | `one-to-one`, `one-to-many`, `many-to-one`, `many-to-many` |
| `relations[].targetMapping` | string | Target ontology association or property reference |

---

### `contracts/query-patterns.json`

| Field | Type | Description |
|-------|------|-------------|
| `patterns[].id` | string | Pattern ID (e.g., `QP-001`) |
| `patterns[].name` | string | Descriptive name |
| `patterns[].description` | string | What the query retrieves |
| `patterns[].graphPlatform` | string | `neo4j` or `sparql` |
| `patterns[].template` | string | Parameterized query template |
| `patterns[].parameters` | object | `{paramName: type}` |
| `patterns[].returnType` | string | Return type description |

---

### `contracts/retrieval-profiles.json`

| Field | Type | Description |
|-------|------|-------------|
| `profiles[].id` | string | Profile ID (e.g., `RP-001`) |
| `profiles[].name` | string | Descriptive name |
| `profiles[].description` | string | What context is retrieved |
| `profiles[].rootEntity` | string | Root entity label |
| `profiles[].traversalDepth` | int | Max traversal hops |
| `profiles[].includedRelations` | string[] | Relation labels to traverse |
| `profiles[].excludedProperties` | string[] | Properties to omit |
| `profiles[].useCase` | string | When to use this profile |

---

### `contracts/tool-contracts.json`

| Field | Type | Description |
|-------|------|-------------|
| `tools[].id` | string | Tool ID (e.g., `TOOL-001`) |
| `tools[].name` | string | Tool name |
| `tools[].description` | string | What the tool does |
| `tools[].inputSchema` | object | `{paramName: {type, required}}` |
| `tools[].outputSchema` | object | `{fieldName: type}` |
| `tools[].graphQuery` | string | Underlying graph query |
| `tools[].requiresEntities` | string[] | Entity types the tool operates on |

---

### `kg/import/internal-to-edge.json`

Each transform entry maps a source type to an edge graph node:

| Field | Type | Description |
|-------|------|-------------|
| `transforms[].sourceType` | string | Source concept qualified name |
| `transforms[].targetLabel` | string | Graph node label |
| `transforms[].propertyMappings[]` | array | Per-property transforms |
| `transforms[].propertyMappings[].source` | string | Source property qualified name |
| `transforms[].propertyMappings[].target` | string | Target property name |
| `transforms[].propertyMappings[].transform` | string? | Transform function (e.g., `xsd:date-to-iso8601`, `codelist-resolve`) or null |
| `transforms[].relationMappings[]` | array | Per-relation transforms |
| `transforms[].relationMappings[].source` | string | Source relation qualified name |
| `transforms[].relationMappings[].target` | string | Graph relationship label |
| `transforms[].relationMappings[].targetNodeType` | string | Target node type label |

---

### `kg/import/loader-config.json`

| Field | Type | Description |
|-------|------|-------------|
| `targetPlatform` | string | `neo4j` or `rdf` |
| `connectionProfile` | string | Connection profile name |
| `loadOrder` | string[] | Ordered list of scripts to execute |
| `importMode` | string | `create-or-merge` |
| `batchSize` | int | Records per batch |
| `constraints.uniqueProperties` | bool | Enforce unique constraints |
| `constraints.requiredProperties` | bool | Enforce required property constraints |
| `sourceDataPaths` | object | `{logicalName: relativePath}` |

---

### `vocab/codelist-mappings.json`

> **Not yet implemented.** The current version of OntologyMapper does not support code list / controlled vocabulary mapping. Future versions may extract enumerated value sets from both source and target ontologies, define vocabulary alignment relationships (similar to SKOS mapping properties), and produce structured code-value mappings here.

Schema: TBD.

---

### `governance/lineage-manifest.json`

| Field | Type | Description |
|-------|------|-------------|
| `artifacts[].artifactPath` | string | Relative path within package |
| `artifacts[].generatedAt` | ISO 8601 | Generation timestamp |
| `artifacts[].generatedBy` | string | `"ontology-mapper"` |
| `artifacts[].stage` | string | Pipeline stage that produced this artifact |
| `artifacts[].sourceInputs` | string[] | Source files that contributed |
| `artifacts[].targetReferences` | string[] | Target ontology types referenced (qualified names) |
| `artifacts[].mappingEntries` | string[] | Source concepts included |
| `artifacts[].dependsOn` | string[] | Other artifacts this depends on |

---

### `governance/version-manifest.json`

| Field | Type | Description |
|-------|------|-------------|
| `currentVersion` | string | Current semantic version |
| `targetOntology` | string | Target ontology name |
| `targetVersion` | string | Target ontology version |
| `mapperVersion` | string | Mapper version |
| `sourcePackageVersion` | string | `{org}_{source}_agency_package@{version}` |
| `generationHistory[].version` | string | Version for this generation |
| `generationHistory[].generatedAt` | ISO 8601 | Timestamp |
| `generationHistory[].targetOntology` | string | Target ontology name |
| `generationHistory[].targetVersion` | string | Target ontology version |
| `generationHistory[].changeDescription` | string | What changed |
| `generationHistory[].conceptCount` | int | Total concepts |
| `generationHistory[].mappingStats` | object | `{action: count}` — keys are the target ontology's valid actions |

---

## Conformance requirements

An edge package is considered complete when:

1. Every class in the source ontology has an entry in `mapping-matrix.json`
2. Every extend entry has a class definition in `ontology/{source}-edge-extensions.ttl`; every augment entry has property declarations in the same file (no class — NIEM augmentation is transparent in OWL). Both have justifications in `extension-justifications.md`
3. Every entry whose action maps to an existing target type references a valid target ontology IRI
4. `cmf/` contains a valid CMF model (NIEM targets only; otherwise deferred with a note in `package-manifest.json`)
5. At least one graph platform directory under `kg/` contains working schema and seed scripts
6. `shapes/` contains SHACL shapes that validate edge ontology instances
7. `contracts/` contains at least `entity-catalog.json` and `relation-catalog.json`
8. `governance/decision-log.json` contains a decision for every mapping entry
9. `tests/fixtures/valid/` contains at least one valid instance per edge node type
10. `package-manifest.json` is present with accurate stats
11. `mappings/alignment-report.json` is present with entries for every source concept
12. Every mapping and alignment entry includes `action` and `rationale` fields

---

## Relationship to internal ontology package

The edge package does NOT modify the internal ontology. The two packages have a clear boundary:

- **Internal package** (`{org}_{source}_agency_package/`): the domain's own semantic model, optimized for internal agentic operations
- **Edge package** (`.mapper-runs/{run_id}/edge-package/`): the target-aligned boundary layer, optimized for interoperability with external systems

The `mappings/` directory is the bridge between them. `kg/import/internal-to-edge.json` defines how internal graph data transforms into edge-compliant form for external exchange.
