"""CMF dataclasses, XML/JSON serialization, and parsing.

Provides the in-memory CmfModel representation and serializers/parsers for
NIEM Common Model Format (CMF) XML and JSON.

CMF spec: https://docs.oasis-open.org/niemopen/ns/specification/cmf/1.0/
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from lxml import etree

# ---------------------------------------------------------------------------
# CMF namespace constants
# ---------------------------------------------------------------------------
CMF_NS = "https://docs.oasis-open.org/niemopen/ns/specification/cmf/1.0/"
# Module-level STRUCTURES_NS must be set via set_niem_version() before use.
# Pipeline callers and the CLI both set this explicitly.
STRUCTURES_NS = None


def set_niem_version(version: str):
    """Set the NIEM version used for the structures namespace URI.

    Must be called before using any converter, serializer, or parser class.
    There is no default — callers must always set the version explicitly.
    """
    global STRUCTURES_NS
    STRUCTURES_NS = f"https://docs.oasis-open.org/niemopen/ns/model/structures/{version}/"


# ---------------------------------------------------------------------------
# Internal model (shared between both conversion directions)
# ---------------------------------------------------------------------------
@dataclass
class CmfAugmentationRecord:
    """A CMF AugmentationRecord — one namespace augmenting another's class
    with a property. Lives inside the augmenting Namespace element."""
    class_ref: str  # structures:ref to the augmented class (e.g. "dbpi.PropertyType")
    property_ref: str  # structures:ref to the augmenting property (e.g. "gis.latitude")
    is_object: bool  # True → ObjectProperty, False → DataProperty
    min_occurs: int = 0
    max_occurs: str = "unbounded"
    augmentation_index: Optional[int] = None  # ordering hint, or None


@dataclass
class CmfNamespace:
    """A CMF Namespace."""
    ns_id: str  # e.g. "dbpi"
    uri: str
    prefix: str
    documentation: str = ""
    category: str = "EXTENSION"  # CORE, DOMAIN, EXTENSION, OTHERNIEM, XSD, BUILTIN
    version: str = ""
    file_path: str = ""
    conformance_target: str = ""
    imports: list[str] = field(default_factory=list)
    augmentations: list[CmfAugmentationRecord] = field(default_factory=list)


@dataclass
class CmfHasProperty:
    """A property membership on a class (CMF ChildPropertyAssociation)."""
    property_ref: str  # structures:ref id, e.g. "dbpi.identifier"
    is_object: bool  # True → ObjectProperty ref, False → DataProperty ref
    min_occurs: int = 0
    max_occurs: str = "unbounded"  # int string or "unbounded"
    documentation: str = ""


@dataclass
class CmfClass:
    """A CMF Class."""
    class_id: str  # e.g. "dbpi.PermitApplicationType"
    name: str
    namespace_ref: str  # e.g. "dbpi"
    documentation: str = ""
    is_abstract: bool = False
    sub_class_of: str = ""  # structures:ref id of parent class
    properties: list[CmfHasProperty] = field(default_factory=list)


@dataclass
class CmfProperty:
    """A CMF Property (ObjectProperty or DataProperty)."""
    prop_id: str  # e.g. "dbpi.submittedDate"
    name: str
    namespace_ref: str
    documentation: str = ""
    is_abstract: bool = False
    is_object: bool = True  # True → ObjectProperty, False → DataProperty
    # For ObjectProperty: class_ref (the range class id)
    class_ref: str = ""
    # For DataProperty: datatype_ref
    datatype_ref: str = ""
    sub_property_of: str = ""


@dataclass
class CmfFacet:
    """A facet within a CMF Restriction (for enumerations)."""
    category: str  # "enumeration", "pattern", "length", etc.
    value: str
    documentation: str = ""


@dataclass
class CmfRestriction:
    """A CMF Restriction (datatype with facets, used for code lists)."""
    restriction_id: str
    name: str
    namespace_ref: str
    documentation: str = ""
    restriction_base: str = "xs.token"
    facets: list[CmfFacet] = field(default_factory=list)


@dataclass
class CmfModel:
    """Complete CMF model."""
    namespaces: list[CmfNamespace] = field(default_factory=list)
    classes: list[CmfClass] = field(default_factory=list)
    properties: list[CmfProperty] = field(default_factory=list)
    restrictions: list[CmfRestriction] = field(default_factory=list)




# CMF XML serialization
# ---------------------------------------------------------------------------

class CmfXmlSerializer:
    """Serializes a CmfModel to CMF XML."""

    def __init__(self, model: CmfModel):
        self.model = model

    def serialize(self) -> str:
        """Produce CMF XML string."""
        if STRUCTURES_NS is None:
            raise RuntimeError(
                "NIEM version not set. Call set_niem_version() before serialization."
            )
        nsmap = {
            None: CMF_NS,
            "structures": STRUCTURES_NS,
            "xsi": "http://www.w3.org/2001/XMLSchema-instance",
        }

        root = etree.Element("{%s}Model" % CMF_NS, nsmap=nsmap)

        # Namespaces
        for ns in self.model.namespaces:
            self._add_namespace(root, ns)

        # Classes
        for cls in self.model.classes:
            self._add_class(root, cls)

        # Properties
        for prop in self.model.properties:
            self._add_property(root, prop)

        # Restrictions (code lists)
        for restr in self.model.restrictions:
            self._add_restriction(root, restr)

        raw = etree.tostring(root, xml_declaration=True, encoding="UTF-8",
                             pretty_print=True).decode("utf-8")
        return raw

    def _add_namespace(self, parent, ns: CmfNamespace):
        el = etree.SubElement(parent, "{%s}Namespace" % CMF_NS)
        el.set("{%s}id" % STRUCTURES_NS, ns.ns_id)

        self._text_child(el, "NamespaceURI", ns.uri)
        self._text_child(el, "NamespacePrefixText", ns.prefix)
        if ns.documentation:
            self._text_child(el, "DocumentationText", ns.documentation)
        if ns.conformance_target:
            self._text_child(el, "ConformanceTargetURI", ns.conformance_target)
        if ns.file_path:
            self._text_child(el, "DocumentFilePathText", ns.file_path)
        self._text_child(el, "NamespaceCategoryCode", ns.category)
        if ns.version:
            self._text_child(el, "NamespaceVersionText", ns.version)

        # AugmentationRecords (cross-namespace property additions)
        for aug in ns.augmentations:
            self._add_augmentation_record(el, aug)

    def _add_augmentation_record(self, parent, aug: CmfAugmentationRecord):
        el = etree.SubElement(parent, "{%s}AugmentationRecord" % CMF_NS)
        self._ref_child(el, "Class", aug.class_ref)
        prop_tag = "ObjectProperty" if aug.is_object else "DataProperty"
        self._ref_child(el, prop_tag, aug.property_ref)
        self._text_child(el, "MinOccursQuantity", str(aug.min_occurs))
        self._text_child(el, "MaxOccursQuantity", str(aug.max_occurs))
        if aug.augmentation_index is not None:
            self._text_child(el, "AugmentationIndex", str(aug.augmentation_index))

    def _add_class(self, parent, cls: CmfClass):
        el = etree.SubElement(parent, "{%s}Class" % CMF_NS)
        el.set("{%s}id" % STRUCTURES_NS, cls.class_id)

        self._text_child(el, "Name", cls.name)
        self._ref_child(el, "Namespace", cls.namespace_ref)
        if cls.documentation:
            self._text_child(el, "DocumentationText", cls.documentation)
        if cls.is_abstract:
            self._text_child(el, "AbstractIndicator", "true")
        if cls.sub_class_of:
            self._ref_child(el, "SubClassOf", cls.sub_class_of)

        for hp in cls.properties:
            self._add_has_property(el, hp)

    def _add_has_property(self, parent, hp: CmfHasProperty):
        el = etree.SubElement(parent, "{%s}ChildPropertyAssociation" % CMF_NS)

        prop_tag = "ObjectProperty" if hp.is_object else "DataProperty"
        self._ref_child(el, prop_tag, hp.property_ref)
        self._text_child(el, "MinOccursQuantity", str(hp.min_occurs))
        self._text_child(el, "MaxOccursQuantity", str(hp.max_occurs))
        if hp.documentation:
            self._text_child(el, "DocumentationText", hp.documentation)

    def _add_property(self, parent, prop: CmfProperty):
        tag = "ObjectProperty" if prop.is_object else "DataProperty"
        el = etree.SubElement(parent, "{%s}%s" % (CMF_NS, tag))
        el.set("{%s}id" % STRUCTURES_NS, prop.prop_id)

        self._text_child(el, "Name", prop.name)
        self._ref_child(el, "Namespace", prop.namespace_ref)
        if prop.documentation:
            self._text_child(el, "DocumentationText", prop.documentation)
        if prop.is_abstract:
            self._text_child(el, "AbstractIndicator", "true")
        if prop.sub_property_of:
            self._ref_child(el, "SubPropertyOf", prop.sub_property_of)

        if prop.is_object and prop.class_ref:
            self._ref_child(el, "Class", prop.class_ref)
        elif not prop.is_object and prop.datatype_ref:
            self._ref_child(el, "Datatype", prop.datatype_ref)

    def _add_restriction(self, parent, restr: CmfRestriction):
        el = etree.SubElement(parent, "{%s}Restriction" % CMF_NS)
        el.set("{%s}id" % STRUCTURES_NS, restr.restriction_id)

        self._text_child(el, "Name", restr.name)
        self._ref_child(el, "Namespace", restr.namespace_ref)
        if restr.documentation:
            self._text_child(el, "DocumentationText", restr.documentation)
        self._ref_child(el, "RestrictionBase", restr.restriction_base)

        for facet in restr.facets:
            f_el = etree.SubElement(el, "{%s}Facet" % CMF_NS)
            self._text_child(f_el, "FacetCategoryCode", facet.category)
            self._text_child(f_el, "FacetValue", facet.value)
            if facet.documentation:
                self._text_child(f_el, "DocumentationText", facet.documentation)

    def _text_child(self, parent, local_name: str, text: str):
        child = etree.SubElement(parent, "{%s}%s" % (CMF_NS, local_name))
        child.text = text

    def _ref_child(self, parent, local_name: str, ref_id: str):
        child = etree.SubElement(parent, "{%s}%s" % (CMF_NS, local_name))
        child.set("{%s}ref" % STRUCTURES_NS, ref_id)
        child.set("{http://www.w3.org/2001/XMLSchema-instance}nil", "true")


# ---------------------------------------------------------------------------
# CMF XML → CmfModel parser
# ---------------------------------------------------------------------------

class CmfXmlParser:
    """Parses CMF XML into a CmfModel."""

    def __init__(self):
        self.model = CmfModel()
        self._structures_ns = None

    def parse(self, xml_path: Path) -> CmfModel:
        if STRUCTURES_NS is None:
            raise RuntimeError(
                "NIEM version not set. Call set_niem_version() before parsing."
            )
        tree = etree.parse(str(xml_path))
        root = tree.getroot()
        # Auto-detect structures namespace from the file if it differs from
        # the set_niem_version() value (the canonical URI is /model/structures/).
        self._structures_ns = STRUCTURES_NS
        for prefix, uri in root.nsmap.items():
            if prefix == "structures" and uri != STRUCTURES_NS:
                self._structures_ns = uri
                break
        ns = {"cmf": CMF_NS, "structures": self._structures_ns}

        for el in root.findall("cmf:Namespace", ns):
            self.model.namespaces.append(self._parse_namespace(el, ns))

        for el in root.findall("cmf:Class", ns):
            self.model.classes.append(self._parse_class(el, ns))

        for el in root.findall("cmf:ObjectProperty", ns):
            self.model.properties.append(self._parse_property(el, ns, is_object=True))

        for el in root.findall("cmf:DataProperty", ns):
            self.model.properties.append(self._parse_property(el, ns, is_object=False))

        for el in root.findall("cmf:Restriction", ns):
            self.model.restrictions.append(self._parse_restriction(el, ns))

        return self.model

    def _text(self, el, tag: str, ns: dict, default="") -> str:
        child = el.find(f"cmf:{tag}", ns)
        return child.text.strip() if child is not None and child.text else default

    def _ref(self, el, tag: str, ns: dict) -> str:
        child = el.find(f"cmf:{tag}", ns)
        if child is not None:
            return child.get(f"{{{self._structures_ns}}}ref", "")
        return ""

    def _sid(self, el) -> str:
        return el.get(f"{{{self._structures_ns}}}id", "")

    def _parse_namespace(self, el, ns) -> CmfNamespace:
        augmentations = []
        for aug_el in el.findall("cmf:AugmentationRecord", ns):
            augmentations.append(self._parse_augmentation_record(aug_el, ns))

        return CmfNamespace(
            ns_id=self._sid(el),
            uri=self._text(el, "NamespaceURI", ns),
            prefix=self._text(el, "NamespacePrefixText", ns),
            documentation=self._text(el, "DocumentationText", ns),
            category=self._text(el, "NamespaceCategoryCode", ns, "EXTENSION"),
            version=self._text(el, "NamespaceVersionText", ns),
            file_path=self._text(el, "DocumentFilePathText", ns),
            conformance_target=self._text(el, "ConformanceTargetURI", ns),
            augmentations=augmentations,
        )

    def _parse_augmentation_record(self, el, ns) -> CmfAugmentationRecord:
        class_ref = self._ref(el, "Class", ns)
        obj_ref = self._ref(el, "ObjectProperty", ns)
        data_ref = self._ref(el, "DataProperty", ns)
        is_object = bool(obj_ref)
        property_ref = obj_ref or data_ref

        aug_idx_text = self._text(el, "AugmentationIndex", ns, "")
        aug_idx = int(aug_idx_text) if aug_idx_text else None

        return CmfAugmentationRecord(
            class_ref=class_ref,
            property_ref=property_ref,
            is_object=is_object,
            min_occurs=int(self._text(el, "MinOccursQuantity", ns, "0")),
            max_occurs=self._text(el, "MaxOccursQuantity", ns, "unbounded"),
            augmentation_index=aug_idx,
        )

    def _parse_class(self, el, ns) -> CmfClass:
        properties = []
        for cpa in el.findall("cmf:ChildPropertyAssociation", ns):
            properties.append(self._parse_has_property(cpa, ns))

        return CmfClass(
            class_id=self._sid(el),
            name=self._text(el, "Name", ns),
            namespace_ref=self._ref(el, "Namespace", ns),
            documentation=self._text(el, "DocumentationText", ns),
            is_abstract=self._text(el, "AbstractIndicator", ns) == "true",
            sub_class_of=self._ref(el, "SubClassOf", ns),
            properties=properties,
        )

    def _parse_has_property(self, el, ns) -> CmfHasProperty:
        # Could be ObjectProperty or DataProperty ref
        obj_ref = self._ref(el, "ObjectProperty", ns)
        data_ref = self._ref(el, "DataProperty", ns)
        is_object = bool(obj_ref)
        prop_ref = obj_ref or data_ref

        max_occ = self._text(el, "MaxOccursQuantity", ns, "unbounded")

        return CmfHasProperty(
            property_ref=prop_ref,
            is_object=is_object,
            min_occurs=int(self._text(el, "MinOccursQuantity", ns, "0")),
            max_occurs=max_occ,
            documentation=self._text(el, "DocumentationText", ns),
        )

    def _parse_property(self, el, ns, is_object: bool) -> CmfProperty:
        return CmfProperty(
            prop_id=self._sid(el),
            name=self._text(el, "Name", ns),
            namespace_ref=self._ref(el, "Namespace", ns),
            documentation=self._text(el, "DocumentationText", ns),
            is_abstract=self._text(el, "AbstractIndicator", ns) == "true",
            is_object=is_object,
            class_ref=self._ref(el, "Class", ns) if is_object else "",
            datatype_ref=self._ref(el, "Datatype", ns) if not is_object else "",
            sub_property_of=self._ref(el, "SubPropertyOf", ns),
        )

    def _parse_restriction(self, el, ns) -> CmfRestriction:
        facets = []
        for f_el in el.findall("cmf:Facet", ns):
            facets.append(CmfFacet(
                category=self._text(f_el, "FacetCategoryCode", ns),
                value=self._text(f_el, "FacetValue", ns),
                documentation=self._text(f_el, "DocumentationText", ns),
            ))

        return CmfRestriction(
            restriction_id=self._sid(el),
            name=self._text(el, "Name", ns),
            namespace_ref=self._ref(el, "Namespace", ns),
            documentation=self._text(el, "DocumentationText", ns),
            restriction_base=self._ref(el, "RestrictionBase", ns) or "xs.token",
            facets=facets,
        )


# CMF JSON serialization (for completeness — CMF supports JSON)
# ---------------------------------------------------------------------------

class CmfJsonSerializer:
    """Serializes a CmfModel to CMF JSON."""

    def __init__(self, model: CmfModel):
        self.model = model

    def serialize(self) -> str:
        """Produce CMF JSON string."""
        result = {"Model": {}}
        m = result["Model"]

        m["Namespace"] = [self._ns_to_dict(ns) for ns in self.model.namespaces]
        m["Class"] = [self._cls_to_dict(cls) for cls in self.model.classes]

        obj_props = [p for p in self.model.properties if p.is_object]
        data_props = [p for p in self.model.properties if not p.is_object]
        if obj_props:
            m["ObjectProperty"] = [self._prop_to_dict(p) for p in obj_props]
        if data_props:
            m["DataProperty"] = [self._prop_to_dict(p) for p in data_props]
        if self.model.restrictions:
            m["Restriction"] = [self._restr_to_dict(r) for r in self.model.restrictions]

        return json.dumps(result, indent=2, ensure_ascii=False)

    def _ns_to_dict(self, ns: CmfNamespace) -> dict:
        d = {
            "structures:id": ns.ns_id,
            "NamespaceURI": ns.uri,
            "NamespacePrefixText": ns.prefix,
            "NamespaceCategoryCode": ns.category,
        }
        if ns.documentation:
            d["DocumentationText"] = ns.documentation
        if ns.version:
            d["NamespaceVersionText"] = ns.version
        if ns.file_path:
            d["DocumentFilePathText"] = ns.file_path
        if ns.augmentations:
            d["AugmentationRecord"] = [
                self._aug_to_dict(a) for a in ns.augmentations
            ]
        return d

    def _aug_to_dict(self, aug: CmfAugmentationRecord) -> dict:
        key = "ObjectProperty" if aug.is_object else "DataProperty"
        d = {
            "Class": {"structures:ref": aug.class_ref},
            key: {"structures:ref": aug.property_ref},
            "MinOccursQuantity": aug.min_occurs,
            "MaxOccursQuantity": aug.max_occurs,
        }
        if aug.augmentation_index is not None:
            d["AugmentationIndex"] = aug.augmentation_index
        return d

    def _cls_to_dict(self, cls: CmfClass) -> dict:
        d = {
            "structures:id": cls.class_id,
            "Name": cls.name,
            "Namespace": {"structures:ref": cls.namespace_ref},
        }
        if cls.documentation:
            d["DocumentationText"] = cls.documentation
        if cls.is_abstract:
            d["AbstractIndicator"] = True
        if cls.sub_class_of:
            d["SubClassOf"] = {"structures:ref": cls.sub_class_of}
        if cls.properties:
            d["ChildPropertyAssociation"] = [
                self._hp_to_dict(hp) for hp in cls.properties
            ]
        return d

    def _hp_to_dict(self, hp: CmfHasProperty) -> dict:
        key = "ObjectProperty" if hp.is_object else "DataProperty"
        d = {
            key: {"structures:ref": hp.property_ref},
            "MinOccursQuantity": hp.min_occurs,
            "MaxOccursQuantity": hp.max_occurs,
        }
        if hp.documentation:
            d["DocumentationText"] = hp.documentation
        return d

    def _prop_to_dict(self, prop: CmfProperty) -> dict:
        d = {
            "structures:id": prop.prop_id,
            "Name": prop.name,
            "Namespace": {"structures:ref": prop.namespace_ref},
        }
        if prop.documentation:
            d["DocumentationText"] = prop.documentation
        if prop.is_abstract:
            d["AbstractIndicator"] = True
        if prop.sub_property_of:
            d["SubPropertyOf"] = {"structures:ref": prop.sub_property_of}
        if prop.is_object and prop.class_ref:
            d["Class"] = {"structures:ref": prop.class_ref}
        elif not prop.is_object and prop.datatype_ref:
            d["Datatype"] = {"structures:ref": prop.datatype_ref}
        return d

    def _restr_to_dict(self, restr: CmfRestriction) -> dict:
        d = {
            "structures:id": restr.restriction_id,
            "Name": restr.name,
            "Namespace": {"structures:ref": restr.namespace_ref},
            "RestrictionBase": {"structures:ref": restr.restriction_base},
        }
        if restr.documentation:
            d["DocumentationText"] = restr.documentation
        if restr.facets:
            d["Facet"] = [
                {
                    "FacetCategoryCode": f.category,
                    "FacetValue": f.value,
                    **({"DocumentationText": f.documentation} if f.documentation else {}),
                }
                for f in restr.facets
            ]
        return d


# ---------------------------------------------------------------------------
