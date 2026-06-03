> **Status**: Original design specification. Operational rules are in [AGENTS/OntologyMapper__PROJECT_SPECIFIC.md](AGENTS/OntologyMapper__PROJECT_SPECIFIC.md).

Below is a clean definition of **OntologyMapper** in terms of **inputs, outputs, decision rules, and artifact types**.

## 1. Tool definition

The tool is a **NIEM-aware ontology alignment pipeline** powered by Claude Code as the real-time semantic reasoning engine.

Its job is to take a target business domain specification and produce a **NIEM-aligned edge ontology** plus the downstream artifacts needed to build and operate that domain’s **knowledge graph layer**.
The domain materials should include the ontologies or database schema to be transformed to NIEM-based ontologies.

Conceptually:

**Domain materials → semantic analysis → NIEM alignment → extension modeling → graph artifacts → agentic system integration**

It is not just a search tool. It is a **semantic transformation and generation toolchain**.

---

## 2. Inputs

The inputs fall into four groups: **domain evidence**, **platform constraints**, **modeling policy**, and **generation targets**.

### A. Domain evidence inputs

These are the materials OntologyMapper analyzes to understand the domain.

**Primary domain sources**

* business requirements
* workflow descriptions
* SOPs and policy documents
* domain glossaries
* sample forms and documents
* message payloads
* JSON/XML schemas
* database schemas
* API contracts
* code models / DTOs / C# classes
* event definitions
* state-machine definitions
* existing graph or ontology assets
* regulatory or standards references

**Example**
For a justice domain, the source set might include:

* intake workflow
* incident report JSON
* person/case/offense tables
* evidence document templates
* role definitions
* external exchange contracts

### B. Domain scope inputs

These tell OntologyMapper what slice of the domain to model.

* target domain name
* domain boundary statement
* in-scope entities
* out-of-scope entities
* in-scope workflows
* in-scope document types
* intended consumers of the graph
* intended agent behaviors

**Example**

* In scope: claimant, claim, policy, incident, adjuster, payment, document
* Out of scope: HR, payroll, marketing, facilities

### C. Platform and deployment inputs

These tell OntologyMapper what the output must support operationally.

* target graph platform
  
  * Neo4j
  * RDF triple store
  * property graph abstraction

* target exchange formats
  
  * JSON
  * XML
  * JSON-LD
  * RDF/OWL

* environment constraints
  
  * cloud
  * local
  * confidential/TEE

* runtime expectations
  
  * retrieval
  * planning
  * event-driven reasoning
  * workflow coordination

* identity model requirements

### D. NIEM and semantic policy inputs

These tell OntologyMapper how aggressively to reuse NIEM and when to extend.

* preferred NIEM version / model set
* domain namespaces to prioritize
* reuse-before-extend policy
* minimum confidence threshold for auto-mapping
* extension namespace naming convention
* naming and design rules
* canonical identifier policy
* relation modeling policy
* event modeling policy
* document modeling policy
* provenance / lineage requirements
* human-review thresholds

### E. Generation target inputs

These tell OntologyMapper what to emit.

* ontology artifacts needed
* knowledge graph artifacts needed
* validation artifacts needed
* documentation artifacts needed
* sample/test data needed

---

## 3. Outputs

The outputs should be thought of in layers.

## A. Analytical outputs

These explain what OntologyMapper found.

### 1. Domain concept inventory

A structured inventory of:

* entities
* roles
* events
* documents
* states
* relationships
* attributes
* constraints

### 2. Semantic candidate report

For each domain concept:

* candidate NIEM matches
* confidence score
* rationale
* unresolved ambiguities
* recommended mapping action

### 3. Gap analysis

A report showing:

* what NIEM covers directly
* what NIEM covers partially
* what requires extension
* what is domain-local and should remain outside canonical semantics

## B. Semantic model outputs

These define the domain’s semantic layer.

### 4. NIEM mapping matrix

For each source-domain concept:

* source term

* source definition

* mapped NIEM type/property if any

* match type
  
  * exact
  * close
  * broader
  * narrower
  * none

* extension required yes/no

* notes and rationale

### 5. Edge ontology

The domain-specific ontology layer that:

* reuses NIEM terms where appropriate
* introduces domain extensions where needed
* preserves lineage to source concepts
* defines local constraints and semantics

### 6. Canonical semantic model

A normalized representation of the domain model, ideally centered on:

* classes / node types
* properties
* relations
* identity rules
* event structures
* document semantics
* state transitions
* provenance structures

## C. Graph outputs

These are the implementation-ready graph artifacts.

### 7. Knowledge graph schema

A formal graph definition including:

* node types
* edge types
* property definitions
* cardinality guidance
* indexing hints
* identity and merge rules

### 8. Graph instantiation artifacts

Depending on target platform:

* Cypher DDL / seed scripts
* RDF/OWL exports
* SHACL shapes
* JSON-LD context
* graph import mappings
* seed datasets

## D. Validation outputs

These ensure quality and conformance.

### 9. Validation rules

Rules for:

* ontology consistency
* NIEM conformance
* graph schema conformance
* required property checks
* relation integrity checks
* cardinality checks
* event/document structure checks

### 10. Test fixtures

* sample entities
* sample relationships
* sample events
* sample documents
* positive and negative test cases

## E. Integration outputs

These connect the semantic model to the agentic system.

### 11. Agent-facing semantic contracts

Artifacts that help agents operate correctly:

* entity and relation catalogs
* allowed query patterns
* graph usage guidance
* retrieval hints
* ontology-aware tool contracts

## F. Governance outputs

These support long-term maintenance.

### 13. Lineage and provenance manifest

For every semantic artifact:

* source materials used
* NIEM concepts referenced
* extension rationale
* generation date
* version lineage

### 14. Semantic decision log

A machine-readable and human-readable record of:

* why a mapping was chosen
* why a term was extended
* what was rejected
* what needs review later

---

## 4. Decision rules

These are the core rules that make OntologyMapper more than a lookup utility.

## A. Scope admission rules

A concept is admitted into the semantic model only if it is at least one of:

* operationally important to the agentic workflow
* necessary for graph reasoning
* necessary for retrieval or tool execution
* necessary for interoperability
* necessary for validation or compliance

A concept should usually be excluded if it is:

* purely UI-only
* transient and non-semantic
* implementation-local with no business meaning
* duplicated under another canonical concept

## B. Reuse vs extension rules

### Rule 1: Reuse before extend

If NIEM already provides a concept with the needed meaning, reuse it.

### Rule 2: Extend only for semantic gaps

Create an extension only if:

* NIEM has no appropriate concept
* available NIEM concept is materially too broad or too narrow
* domain requires meaning NIEM does not preserve
* local policy/regulatory semantics require explicit representation

### Rule 3: Do not extend for cosmetic reasons

Do not create a new concept merely because:

* local naming differs
* a team prefers a different label
* a field layout differs but meaning is the same

## C. Mapping confidence rules (semantic triangulation)

Confidence is determined by running three independent mapping strategies and comparing their results. See [AGENTS/OntologyMapper__PROJECT_SPECIFIC.md](AGENTS/OntologyMapper__PROJECT_SPECIFIC.md) Section C for full details.

The three strategies are:

* **Strategy 1: Lexical + Definitional** — match by concept name and definition
* **Strategy 2: Structural + Relational** — match by property profile and relationship patterns
* **Strategy 3: Contextual + Functional** — match by usage in seed data, workflows, and documents

Confidence levels based on strategy agreement:

* **high**: all three strategies agree → auto-accept
* **medium**: two of three agree → include with review flag
* **low**: full disagreement → requires human review

Each strategy scores candidates individually using:

* lexical similarity
* definitional similarity
* structural similarity
* relation compatibility
* domain context compatibility
* usage evidence from source materials

## D. Concept normalization rules

Before mapping, concepts should be normalized:

* singular/plural collapsed
* aliases grouped
* abbreviations expanded
* synonyms clustered
* document fields separated from semantic concepts
* role names separated from person/entity types
* events separated from states

## E. Relationship modeling rules

Relationships should be generated only when they reflect stable semantic meaning, such as:

* participates in
* owns
* authored
* filed
* assigned to
* located at
* references
* resulted in
* derived from

Avoid generating edges from:

* incidental co-occurrence
* UI layout adjacency
* one-off textual proximity
* unsupported inference

## F. Identity rules

OntologyMapper must decide how entities are identified and merged.

For each entity type:

* define canonical identifier
* define alternate identifiers
* define merge/no-merge rules
* define provenance retention rules

Multi-tenancy is deferred — OntologyMapper currently processes one domain for one organization at a time.

Without explicit identity rules, graph quality degrades quickly.

## G. Event rules

Events should be modeled distinctly from entities when they:

* happen at a time
* involve participants
* change state
* create evidence
* trigger workflow actions
* are relevant to reasoning or chronology

Example:
A “claim” is an entity.
A “claim filed” is an event.

## H. Document rules

Documents should be modeled explicitly when they:

* have legal or operational significance
* contain structured evidence
* trigger decisions
* must be versioned
* are used by agents as evidence sources

A document should not automatically be collapsed into a flat property bag.

## I. Graph usefulness rules

A concept should be included in the graph only if it supports one or more of:

* retrieval
* disambiguation
* planning
* reasoning
* constraint validation
* lineage
* cross-document linkage
* human explanation

If a concept adds no graph utility, it may belong in an exchange model but not in the graph.

## J. Human review rules

**Mandatory review gate**: After Stage 4 (Decide), OntologyMapper must present the complete concept inventory and mapping matrix to the user for review before proceeding to Stage 5 (Generate). No artifact generation occurs without user approval. See [AGENTS/OntologyMapper__PROJECT_SPECIFIC.md](AGENTS/OntologyMapper__PROJECT_SPECIFIC.md) Section I for the full review protocol.

**Additional review triggers** — stop and flag immediately when:

* legal/regulatory semantics are involved
* identity rules are ambiguous
* relation semantics are inferred rather than explicit
* source materials appear contradictory or incomplete for a critical concept

---

## 5. Artifact types

OntologyMapper should emit artifacts in several formal categories.

## A. Discovery artifacts

Used to understand the domain.

* source manifest
* extracted concept list
* synonym/alias tables
* workflow concept maps
* domain term glossary

## B. Alignment artifacts

Used to align the domain with NIEM.

* NIEM search result summaries
* NIEM candidate ranking files
* mapping matrix
* unresolved ambiguity report
* extension justification report

## C. Ontology artifacts

Used to define the semantic model.

* class/property definitions
* extension namespace definitions
* ontology modules
* RDF/OWL exports
* JSON-LD contexts
* semantic constraints

## D. Knowledge graph artifacts

Used to deploy the graph.

* graph schema
* node type catalog
* edge type catalog
* cardinality definitions
* Cypher or equivalent DDL
* import/transformation scripts
* seed graph examples

## E. Validation artifacts

Used to assure correctness.

* SHACL shapes
* schema validation rules
* graph integrity tests
* NIEM conformance checks
* semantic regression tests

## F. Agent integration artifacts

Used by the agentic runtime.

* graph query templates
* semantic retrieval profiles
* tool contracts
* entity resolution policies
* planner-facing ontology summaries
* evidence/provenance usage rules

## G. Governance artifacts

Used for maintenance and audit.

* semantic decision log
* lineage manifest
* version manifest
* artifact provenance report
* change impact report

---

## 6. Pipeline stages

### Stage 1: Ingest

Read source materials and normalize them.

### Stage 2: Extract

Identify domain concepts, relationships, events, documents, and constraints.

### Stage 3: Align

Run three independent mapping strategies (lexical+definitional, structural+relational, contextual+functional) against NIEMOpen and rank candidate matches for each.

### Stage 3b: Reconcile

Merge the three strategy reports into a unified semantic candidate report with triangulated confidence scores. Disagreements between strategies are flagged.

### Stage 4: Decide

Apply reuse/extend rules and produce the mapping matrix with extension decisions.

### Stage 4→5: Human Review Gate

Present the complete concept inventory and mapping matrix to the user for approval. OntologyMapper does not proceed until the user has reviewed and approved the results.

### Stage 5: Generate

Emit ontology, graph, validation, and integration artifacts based on the approved mapping matrix.

### Stage 6: Validate

Run semantic, structural, and graph-level checks.

### Stage 7: Package

Produce a versioned semantic bundle for the target agentic system.

---

## 7. Minimal required input/output contract

If you want this tool to be practical, it should support a minimal contract like this.

### Minimum input

* domain description
* source documents/schemas
* target graph platform
* NIEM reuse policy
* required output artifact list

### Minimum output

* concept inventory
* NIEM mapping matrix
* extension recommendations
* edge ontology
* graph schema
* validation set
* generation report

---

## 8. One-sentence definition of success

The tool succeeds if it can take a new domain and produce a **traceable, NIEM-aligned, extension-aware semantic bundle** that is sufficient to build the knowledge graph layer of an agentic system with minimal manual semantic rework.
