#!/usr/bin/env python3
"""Ontology-specific action determination for the OntologyMapper pipeline.

Given the evaluator's semantic alignments (type and property evaluations),
applies ontology-specific structural rules to determine the appropriate action
(reuse, extend, or augment) and adds structural scaffolding.

The evaluator performs semantic reasoning — deciding which target types
and properties align with source concepts. This module applies deterministic,
ontology-specific rules that the evaluator should not need to know about.

Currently supported:
  - niem: augment/extend/reuse action logic based on property classification
  - Other ontologies: reuse if all properties match, extend otherwise

This is a library module — no CLI. Called internally by om-collect-alignments
via resolve_alignment().
"""
import json


# Action determination — NIEM
# ---------------------------------------------------------------------------
def _classify_niem_properties(properties, target_type_properties):
    """Classify property alignments into three buckets for NIEM action logic.

    Args:
        properties: list of property alignment dicts from the evaluator.
            Each has targetProperty (str or None) and targetPath (str or None).
        target_type_properties: set of qualified property names that exist
            directly on the selected target type (including inherited).

    Returns:
        (on_target, elsewhere, not_found) — counts of properties in each bucket.
          on_target:  target property exists AND is on the target type
          elsewhere:  target property exists but is NOT on the target type
          not_found:  no target property (targetProperty is None)
    """
    on_target = 0
    elsewhere = 0
    not_found = 0
    for prop in properties:
        tp = prop.get("targetProperty")
        if tp is None or tp == "[undecided]":
            not_found += 1
        elif tp in target_type_properties:
            on_target += 1
        else:
            elsewhere += 1
    return on_target, elsewhere, not_found


def _determine_niem_action(on_target, elsewhere, not_found):
    """Apply NIEM structural rules to choose an action.

    Decision logic:
      - If no properties need augmentation or creation → reuse
      - Of the properties NOT already on the target type:
        if >= 50% exist elsewhere in the ontology → augment
        if < 50% exist elsewhere → extend

    The 50% threshold communicates intent:
      augment = the source concept is mostly covered by existing NIEM properties
      extend  = the source concept brings more new semantics than existing ones

    Args:
        on_target: count of properties already on the target type
        elsewhere: count of properties found elsewhere in the ontology
        not_found: count of properties with no equivalent

    Returns:
        (action, rationale) tuple.
    """
    remaining = elsewhere + not_found

    if remaining == 0:
        return "reuse", (
            f"All {on_target} source properties have equivalents on the "
            f"target type."
        )

    if elsewhere >= not_found:
        parts = []
        if on_target:
            parts.append(f"{on_target} already on the target type")
        parts.append(
            f"{elsewhere} found elsewhere in the ontology"
        )
        if not_found:
            parts.append(f"{not_found} require creation")
        return "augment", (
            f"Of {on_target + remaining} source properties: "
            + ", ".join(parts) + ". "
            f"Majority of unmatched properties exist in the ontology "
            f"({elsewhere} of {remaining}) — augment."
        )

    parts = []
    if on_target:
        parts.append(f"{on_target} already on the target type")
    if elsewhere:
        parts.append(f"{elsewhere} found elsewhere in the ontology")
    parts.append(f"{not_found} require creation")
    return "extend", (
        f"Of {on_target + remaining} source properties: "
        + ", ".join(parts) + ". "
        f"Majority of unmatched properties have no equivalent "
        f"({not_found} of {remaining}) — extend."
    )


# ---------------------------------------------------------------------------
# Structural resolution helpers
# ---------------------------------------------------------------------------
def _local_name(qname):
    """Extract local name from a qualified name (e.g., 'nc:CaseType' → 'CaseType')."""
    return qname.split(":")[-1] if ":" in qname else qname


def _build_target_type_properties(target_type, catalog):
    """Build set of qualified property names on a target type (direct + inherited)."""
    target_type_properties = set()
    type_lookup = {t["qname"]: t for t in catalog.get("types", [])}
    target_entry = type_lookup.get(target_type)
    if not target_entry:
        return target_type_properties

    for entry in [target_entry] + [
        type_lookup[a] for a in target_entry.get("inheritanceChain", [])
        if a in type_lookup
    ]:
        for pname in entry.get("properties", []):
            pdefs = entry.get("propertyDefinitions", {})
            pd = pdefs.get(pname, {})
            qp = pd.get("qualifiedProperty", "")
            target_type_properties.add(qp if qp else pname)

    return target_type_properties


def _resolve_property_actions(properties, target_type_properties):
    """Add propertyAction and newPropertyName to each property alignment.

    Returns a new list (does not mutate input).

    Property actions:
      reuse-property:  targetProperty is a real match (exists in target ontology)
      human-must-decide:       targetProperty is "[undecided]" (LLM could not choose)
      create-property: targetProperty is None (must be created)

    For create-property, newPropertyName is derived from the source property's
    local name.
    """
    resolved = []
    for prop in properties:
        rp = dict(prop)
        tp = rp.get("targetProperty")
        if tp == "[undecided]":
            rp["propertyAction"] = "human-must-decide"
        elif tp is not None:
            rp["propertyAction"] = "reuse-property"
        else:
            rp["propertyAction"] = "create-property"
            rp["newPropertyName"] = _local_name(rp.get("sourceProperty", ""))
        resolved.append(rp)
    return resolved


def _niem_augmentation_type_name(target_type):
    """Derive NIEM augmentation type local name from a target type.

    Convention: nc:PersonType → PersonAugmentationType
    """
    local = _local_name(target_type)
    if local.endswith("Type"):
        return local[:-4] + "AugmentationType"
    return local + "AugmentationType"


# ---------------------------------------------------------------------------
# resolve_alignment — full structural resolution
# ---------------------------------------------------------------------------
def resolve_alignment(evaluation, target_ontology, catalog):
    """Resolve a source concept alignment into a complete, actionable packet.

    The evaluator provides its semantic alignment — which target type
    and properties align with the source concept, with rationale. This
    function applies ontology-specific structural rules to produce a fully
    resolved alignment ready for edge ontology generation.

    Input (from evaluator — NO action field):
        {
            "sourceConcept": "court:HearingType",
            "sourceDefinition": "...",
            "sourcePath": "...",
            "targetType": "j:CourtEventType",
            "targetDefinition": "...",
            "targetPath": "...",
            "rationale": "...",
            "properties": [
                {
                    "sourceProperty": "court:hearingDate",
                    "sourceDefinition": "...",
                    "sourcePath": "...",
                    "targetProperty": "nc:ActivityDate" or null,
                    "targetDefinition": "..." or null,
                    "targetPath": "..." or null,
                    "rationale": "..."
                }
            ]
        }

    Output (fully resolved — action + structural scaffolding added):
        Same fields, plus:
        - action: one of the target ontology's valid actions
        - actionRationale: why this action was chosen (with counts)
        - properties[].propertyAction: "reuse-property" or "create-property"
        - properties[].newPropertyName: local name (for create-property only)
        - For extend: extensionType (local name), baseType (target qname)
        - For augment (NIEM): augmentationType (local name), augmentsType

    Args:
        evaluation: dict — evaluator's semantic alignment (see above)
        target_ontology: str, e.g. "niem", "sali-folio"
        catalog: dict — reference catalog (types, actions, etc.)

    Returns:
        dict — fully resolved alignment. Does not mutate the input.
    """
    import copy
    result = copy.deepcopy(evaluation)
    properties = result.get("properties", [])
    target_type = result.get("targetType")

    # --- No target type: extend from root (create everything from scratch) ---
    if target_type is None:
        base = catalog.get("defaultBaseType")
        result["action"] = "extend"
        result["actionRationale"] = (
            "No target type equivalent found — all properties require creation."
        )
        result["extensionType"] = _local_name(result.get("sourceConcept", ""))
        if base:
            result["baseType"] = base
        result["properties"] = _resolve_property_actions(properties, set())
        return result

    # --- Step 1: Determine action ---
    if target_ontology == "niem":
        target_type_properties = _build_target_type_properties(
            target_type, catalog
        )
        on_target, elsewhere, not_found = _classify_niem_properties(
            properties, target_type_properties
        )
        action, action_rationale = _determine_niem_action(
            on_target, elsewhere, not_found
        )
    else:
        # Non-NIEM: reuse if all found, extend if any missing.
        # No augmentation concept.
        target_type_properties = set()
        found = sum(1 for p in properties
                    if p.get("targetProperty") is not None
                    and p.get("targetProperty") != "[undecided]")
        missing = len(properties) - found
        if missing == 0:
            action = "reuse"
            action_rationale = (
                f"All {found} source properties have equivalents in "
                f"the target ontology."
            )
        else:
            action = "extend"
            action_rationale = (
                f"{found} of {len(properties)} source properties have "
                f"equivalents; {missing} require creation — extend."
            )

    result["action"] = action
    result["actionRationale"] = action_rationale

    # --- Step 2: Resolve property-level actions ---
    result["properties"] = _resolve_property_actions(
        properties, target_type_properties
    )

    # --- Step 3: Add structural scaffolding ---
    if action == "extend":
        result["extensionType"] = _local_name(result.get("sourceConcept", ""))
        result["baseType"] = target_type

    elif action == "augment":
        result["augmentationType"] = _niem_augmentation_type_name(target_type)
        result["augmentsType"] = target_type

    # reuse: no additional scaffolding needed

    return result


# ---------------------------------------------------------------------------
# Target type change cascade — reclassify without LLM re-evaluation
# ---------------------------------------------------------------------------
_SCAFFOLDING_KEYS = ("extensionType", "baseType", "augmentationType", "augmentsType")


def reclassify_for_target_type_change(entry, new_target_type, target_ontology, catalog):
    """Reclassify a mapping matrix entry after the user changes its target type.

    Property-to-property matches are type-independent — the LLM matched
    source properties to the best semantic candidates across the full target
    ontology.  Changing the target type only changes which bucket each
    property falls into (on-target / elsewhere / not-found), which drives
    the class-level action (reuse / augment / extend).

    This function recomputes the action and scaffolding without re-running
    vector search or LLM evaluation.

    Args:
        entry: A mapping matrix entry dict (Stage 4/5 schema with
            propertyMappings, action, scaffolding keys).
        new_target_type: The new target type qname (str), or None to
            indicate no target type match.
        target_ontology: e.g. "niem", "sali-folio".  Determines which
            action-determination rules apply.
        catalog: Reference catalog dict (same format as resolve_alignment).

    Returns:
        A new dict (deep copy of entry) with reclassified action,
        rebuilt scaffolding, and reviewStatus reset to "pending-review".
        The input is never mutated.
    """
    import copy
    result = copy.deepcopy(entry)
    result["targetType"] = new_target_type
    property_mappings = result.get("propertyMappings", [])

    # --- No target type: extend from root ---
    if new_target_type is None:
        base = catalog.get("defaultBaseType")
        action = "extend"
        action_rationale = (
            "No target type equivalent found — all properties require creation."
        )
        for key in _SCAFFOLDING_KEYS:
            result.pop(key, None)
        result["extensionType"] = _local_name(result.get("sourceConcept", ""))
        if base:
            result["baseType"] = base
        result["action"] = action
        result["actionRationale"] = action_rationale
        result["reviewStatus"] = "pending-review"
        result["ruleId"] = "target-type-change-cascade"
        for pm in property_mappings:
            pm["reviewStatus"] = "pending-review"
        return result

    # --- Recompute class-level action ---
    if target_ontology == "niem":
        target_type_properties = _build_target_type_properties(
            new_target_type, catalog
        )
        on_target, elsewhere, not_found = _classify_niem_properties(
            property_mappings, target_type_properties
        )
        action, action_rationale = _determine_niem_action(
            on_target, elsewhere, not_found
        )
    else:
        found = sum(
            1 for p in property_mappings
            if p.get("targetProperty") is not None
            and p.get("targetProperty") != "[undecided]"
        )
        missing = len(property_mappings) - found
        if missing == 0:
            action = "reuse"
            action_rationale = (
                f"All {found} source properties have equivalents in "
                f"the target ontology."
            )
        else:
            action = "extend"
            action_rationale = (
                f"{found} of {len(property_mappings)} source properties have "
                f"equivalents; {missing} require creation — extend."
            )

    result["action"] = action
    result["actionRationale"] = action_rationale

    # --- Clear old scaffolding and rebuild ---
    for key in _SCAFFOLDING_KEYS:
        result.pop(key, None)

    if action == "extend":
        result["extensionType"] = _local_name(result.get("sourceConcept", ""))
        result["baseType"] = new_target_type
    elif action == "augment":
        result["augmentationType"] = _niem_augmentation_type_name(new_target_type)
        result["augmentsType"] = new_target_type

    # --- Reset review status ---
    result["reviewStatus"] = "pending-review"
    result["ruleId"] = "target-type-change-cascade"
    for pm in property_mappings:
        pm["reviewStatus"] = "pending-review"

    return result
