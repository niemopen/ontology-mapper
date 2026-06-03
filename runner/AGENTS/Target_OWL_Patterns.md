# Target Ontology OWL Patterns

How the pipeline emits OWL/TTL for each action, per target ontology specification.
These patterns are implemented in `generate_edge_ontology.py` (Stage 6a).

---

## NIEM 6.x

Source: NDR v6.0 Sections 3.6-3.7, 14.1-14.2; NIEM 6.0 Architectural Changes v1.0.

### Reuse (`rdfs:subClassOf`)

When a source concept maps to an existing NIEM type, the edge type subclasses it:

```turtle
edge:PermitApplicationType a owl:Class ;
    rdfs:subClassOf nc:ActivityType ;
    rdfs:label "Permit Application" .
```

NIEM does **not** use `owl:equivalentClass` — the NDR has zero references to it.
The semantic model is strictly hierarchical via `rdfs:subClassOf`.

### Extend (`rdfs:subClassOf` in ext: namespace)

When no suitable NIEM type exists, a new extension type is created:

```turtle
ext:SpecialCaseType a owl:Class ;
    rdfs:subClassOf nc:ActivityType ;
    rdfs:label "Special Case" .
```

- Extension namespace must be owned by the author (NDR Section 3.6).
- Types follow ISO 11179-5 naming: types end in `Type`.
- Default base when unset: `nc:ObjectType` (NIEM 6 universal base for
  augmentation-capable types), not `owl:Thing`.
- Conformance target: `EXT` (NDR Section 6.1.2, 9.9).

### Augment (transparent in OWL/RDF)

NIEM augmentation types are an **XSD-only artifact**. They do not exist in
OWL/RDF or JSON representations (NDR Section 14.2.11):

> "Augmentation elements have no meaning of their own, and do not appear in
> JSON or RDF messages."

New properties are declared with `rdfs:domain` pointing directly to the
augmented type:

```turtle
# No augmentation type class — properties go directly on the augmented type
ext:newDomainProperty a owl:DatatypeProperty ;
    rdfs:domain nc:PersonType ;
    rdfs:range xsd:string ;
    rdfs:label "new domain property" .
```

In XSD, the same augmentation requires three components (augmentation point
element, augmentation type extending `structures:AugmentationType`, and
augmentation element substituting for the point). In CMF, it is represented
as `AugmentationRecord` entries on the augmenting namespace. But in OWL/RDF,
all of this is transparent.

**SHACL**: Augmentation properties appear as `sh:property` entries directly on
the augmented type's shape, not on a separate augmentation type shape.

### NIEM Preference: Augmentation over Subclassing

NDR Section 3.7: "In general, augmentations are preferred over subclassing."
Reason: NIEM does not support multiple inheritance. If multiple domains
(Justice, Immigration, Health) all subclass `nc:PersonType`, a message
designer cannot compose properties from all three. Augmentation allows
parallel, composable extensions.

For our pipeline (single source ontology mapping to NIEM), subclassing via
reuse/extend is appropriate — we create one edge type per source concept.

---

## SALI / FOLIO

SALI Alliance publishes the LMSS (Legal Matter Specification Standard).
FOLIO (Foundation of Legal Industry Ontology) is the broader ontological
framework. As of 2025, **SALI does not publish formal OWL alignment or
extension patterns**.

### What Exists

- LMSS is primarily a **taxonomy / controlled vocabulary**, not a deeply
  axiomatized OWL ontology. Published as OWL but functions like SKOS
  concept schemes.
- The OWL serialization uses `rdfs:subClassOf` for internal hierarchy.
- No published guidance on how third parties should align or extend.
- No extension namespace conventions or conformance rules (unlike NIEM NDR).
- SALI's contribution model is "propose additions to the canonical taxonomy"
  rather than "extend locally in your own namespace."

### Practical Patterns

Since SALI has no formal spec, the pipeline uses general OWL best practices:

| Action | Pattern | Notes |
|--------|---------|-------|
| Reuse | `rdfs:subClassOf sali:ExistingType` | Same as NIEM. SKOS mapping properties (`skos:exactMatch`, `skos:closeMatch`) could be added as annotations for provenance. |
| Extend | New `owl:Class` in `ext:` namespace with `rdfs:subClassOf` closest SALI type | No SALI conformance rules to follow. Default base: `owl:Thing`. |
| Augment | Not applicable | Augmentation is a NIEM-specific pattern. SALI has no equivalent mechanism. |

### Future Consideration

If SALI publishes formal alignment guidance, update the reuse pattern
accordingly. The most likely direction (given SALI's taxonomic nature) would
be SKOS mapping properties rather than OWL class axioms.
