# City of Red Vale Department of Building Permits and Inspections Ontology Package

## Agency

**City of Red Vale Department of Building Permits and Inspections (DBPI)**

This package is a complete, self-contained ontology artifact set for the City of Red Vale Department of Building Permits and Inspections.
It is designed as an internal reference ontology for the agency itself.

## Scope

The ontology covers:

- agency structure
- jurisdiction and property records
- permit applications and issued permits
- plan review
- inspections
- code enforcement
- appeals and hearings
- controlled vocabularies
- workflow lifecycles
- validation shapes
- seed records
- legal and service-governance artifacts
- JSON-LD context
- overview diagram source

## Package contents

- `ontology/dbpi-core.ttl` — foundational entities and shared properties
- `ontology/dbpi-organization.ttl` — departments, divisions, units, roles, employees
- `ontology/dbpi-permitting.ttl` — permit application and permit lifecycle
- `ontology/dbpi-inspections.ttl` — inspection requests and inspection outcomes
- `ontology/dbpi-enforcement.ttl` — violations, notices, corrective actions, appeals, hearings
- `ontology/dbpi-all.ttl` — module import ontology
- `ontology/dbpi-all.rdf` — combined RDF/XML export
- `ontology/dbpi-combined-expanded.ttl` — combined expanded Turtle export
- `vocab/dbpi-codelists.ttl` — SKOS concept schemes and controlled values
- `shapes/dbpi-shapes.ttl` — SHACL constraints
- `seed-data/dbpi-seed-data.ttl` — seed records that conform to the model
- `contexts/dbpi-context.jsonld` — JSON-LD context
- `docs/agency-mission-and-operations.md` — mission, operating model, and day-to-day workings
- `docs/competency-questions.md` — competency questions grouped by business area
- `docs/policy-narratives.md` — policy narratives for agency operations
- `diagrams/dbpi-overview.mmd` — Mermaid source for a high-level model diagram
- `ontology/dbpi-workflows.ttl` — machine-readable lifecycle models and workflow transitions
- `docs/founding-charter-and-ordinance.md` — ordinance-style founding charter for the Department
- `docs/legal-authority-register.md` — authority inventory and legal provenance register
- `docs/service-catalog.md` — formal departmental service catalog
- `docs/workflow-lifecycle-models.md` — textual lifecycle definitions and allowed transitions
- `seed-data/corpus/dbpi-seed-corpus.ttl` — expanded realistic operational seed corpus
- `seed-data/corpus/dbpi-seed-corpus-summary.md` — corpus description and scenario summary
- `catalog-v001.xml` — Protégé XML catalog for local file resolution

## Namespace

Primary namespace:

- `https://data.redvale.gov/ontology/dbpi/`

Module ontology IRIs:

- `https://data.redvale.gov/ontology/dbpi/core`
- `https://data.redvale.gov/ontology/dbpi/organization`
- `https://data.redvale.gov/ontology/dbpi/permitting`
- `https://data.redvale.gov/ontology/dbpi/inspections`
- `https://data.redvale.gov/ontology/dbpi/enforcement`
- `https://data.redvale.gov/ontology/dbpi/all`
- `https://data.redvale.gov/ontology/dbpi/workflows`
- `https://data.redvale.gov/ontology/dbpi/codelists`
- `https://data.redvale.gov/ontology/dbpi/shapes`

## Modeling style

- OWL 2 / RDF in Turtle
- SHACL for validation
- SKOS for code lists and statuses
- seed records in RDF/Turtle
- JSON-LD context for application-facing serialization

## Suggested loading order

1. `vocab/dbpi-codelists.ttl`
2. the files in `ontology/`
3. `shapes/dbpi-shapes.ttl`
4. `seed-data/dbpi-seed-data.ttl`
