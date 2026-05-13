# NIEM Augmentation Rules

> **Version**: 1.1 | **Updated**: 2026-04-06
>
> **Source**: NDR v6.0-ps01 (local copy: `specs/ndr-v6.0-ps01.html`)

Rules for when the pipeline should choose **augment** vs **extend** vs **reuse**
when mapping a source concept to NIEM. Implemented in `ontology_specific.py`
via `_determine_niem_action()`.

---

## NDR Definitions (Section 3.7)

The NDR defines two model extension mechanisms. These are direct quotes:

**Subclass (extend)**: "a namespace designer creates a new class in his own
namespace to represent a special kind of thing." The new class inherits all
parent properties and adds specialized ones. Example: `nc:Vehicle` is a
subclass of `nc:Conveyance` — only Vehicles have
`nc:VehicleSeatingQuantity`.

**Augmentation**: "a namespace designer creates additional properties for a
class that is defined in a different namespace. Here the designer is not
creating a new class for a new kind of thing. Instead, he is providing
properties which could have been defined by the original class designer, but
in fact were not." Example: Justice augmented `nc:PersonType` with
`j:PersonSightedIndicator` because vision status matters to Justice but not
universally.

**NDR preference**: "In general, augmentations are preferred over
subclassing. At present the NIEM metamodel does not support multiple
inheritance. If several domains were to create a subclass of
`nc:PersonType`, there would be no way for a message designer to combine in
his message model the properties of a person from NIEM Justice, NIEM
Immigration, etc. Such a combination is easily done with augmentations."

---

## Augmentation Mechanics

### In XSD (Section 4.16, Rules 9-58 through 9-79)

Augmentation requires three coordinated XSD components:

1. **Augmentation point element** — abstract, no type, last in the content
   model of the augmented type (e.g., `nc:PersonAugmentationPoint`). Already
   present on every NIEM object and association type.
2. **Augmentation type** — extends `structures:AugmentationType`, contains the
   augmentation properties (e.g., `j:PersonAugmentationType`). Name must end
   in `AugmentationType` (Rule 9-58).
3. **Augmentation element** — substitutes for the augmentation point, typed
   by the augmentation type (e.g., `j:PersonAugmentation`). Name must end in
   `Augmentation` (Rule 9-59).

### In OWL/RDF (see `Target_OWL_Patterns.md`)

Augmentation types are an XSD-only artifact. In OWL/RDF, new properties
simply declare `rdfs:domain` pointing to the augmented type. No augmentation
class or container element exists.

### In CMF

Represented as `AugmentationRecord` objects on the augmenting namespace,
listing the augmented class, the augmentation property, and cardinality.

---

## The Decision: Augment vs Extend

The NDR distinguishes the two patterns by **intent**, not by property origin:

| | Subclass (extend) | Augmentation |
|-|---|---|
| **Intent** | "a special kind of thing" | "properties the original designer could have included but didn't" |
| **Creates new class?** | Yes | No |
| **Relationship to base** | IS-A (specialization) | HAS-MORE (supplementation) |
| **NDR preference** | Use when the concept is genuinely a specialization | Preferred in general; required for composability |

### What the NDR does NOT say

The NDR does not provide a quantitative decision rule (e.g., based on how
many properties come from where). The `elsewhere >= not_found` heuristic
previously in `_determine_niem_action()` has no basis in the specification.

### Open design question for this pipeline

The NDR preference for augmentation assumes a multi-domain ecosystem where
composability matters. Our pipeline maps a **single source ontology** to
NIEM, producing an edge package. Two valid interpretations:

1. **Follow NDR preference** — default to augment whenever the source adds
   properties to an existing NIEM type, because the edge package should be a
   good NIEM citizen that composes well with other domains' extensions.

2. **Follow source intent** — if the source explicitly defines a new named
   type (like Jim's `nods:ChargeType extends j:ChargeType`), honor that as
   extend. Only use augment when the source does not define a named type but
   contributes properties to a NIEM type.

Interpretation 2 respects what the source author built. Interpretation 1
produces more NIEM-idiomatic output. **This choice is not yet resolved.**

---

## What IS Settled

### Reuse

All source properties already exist on the target type → **reuse**. No new
type, no augmentation. The target type covers the source concept completely.

### No target type match

Always **extend** from `structures:ObjectType`. No augmentation is possible
because there is no type to augment.

### Property origin does not determine the class-level action

Whether a source property reuses an existing NIEM property or requires a new
one determines the **property-level** action (`reuse-property` vs
`create-property`). It does not determine the **class-level** action
(augment vs extend). A concept can extend a type while reusing many of its
properties.

---

## NODS Case Study

Jim's NODS XSD defines 33 complexTypes. **All** extend a NIEM base type via
`xs:extension`. **None** extend `structures:AugmentationType`. Jim chose
subclassing for every type, including types like `nods:BondType extends
j:BailBondType` that add only a few properties. The pipeline classified 7 of
these as augment due to the property-origin heuristic; all 7 should have
been extend per Jim's source schema.

---

## Relationship to Other Documents

- **`Target_OWL_Patterns.md`** (orchestrator repo): OWL/TTL emission patterns
  for each action. *When* lives here; *how* lives there.
- **`OM__ONTOLOGY_ADAPTERS.md`**: `resolve_alignment()` interface and
  scaffolding. Update its NIEM action logic section when
  `_determine_niem_action()` changes.
- **Reference catalog** (`niem_reference_catalog_6.0.json`): Contains the
  `augmentationMap` showing how NIEM's own domains use augmentation (68 base
  types augmented by various domains).
- **NDR v6.0** (`specs/ndr-v6.0-ps01.html`): Authoritative source. Section
  3.7 (model extensions), Section 4.16 (augmentation class), Section 9.6
  (rules 9-58 through 9-79).
