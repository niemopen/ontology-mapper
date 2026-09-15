"""Reference closure must preserve native definitions and expanded identities."""

import gzip

import pytest
from lxml import etree

from ontology_mapper.cmf_reference import complete_cmf_references, load_reference_cmf
from ontology_mapper.validate_edge_package import check_cmf_consistency, validate_cmf_schema

CMF = "https://docs.oasis-open.org/niemopen/ns/specification/cmf/1.0/"
S = "https://docs.oasis-open.org/niemopen/ns/model/structures/6.0/"


def model(body):
    return (f'<Model xmlns="{CMF}" xmlns:structures="{S}" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">' + body + '</Model>')


def namespace(prefix, uri, metadata=""):
    return (f'<Namespace structures:id="{prefix}"><NamespaceURI>{uri}</NamespaceURI>'
            f'<NamespacePrefixText>{prefix}</NamespacePrefixText>'
            f'<NamespaceCategoryCode>EXTERNAL</NamespaceCategoryCode>{metadata}</Namespace>')


def component(kind, prefix, name, body=""):
    return (f'<{kind} structures:id="{prefix}.{name}"><Name>{name}</Name>'
            f'<Namespace structures:ref="{prefix}" xsi:nil="true"/>{body}</{kind}>')


def ref(kind, target):
    return f'<{kind} structures:ref="{target}" xsi:nil="true"/>'


def parse(xml):
    return etree.fromstring(xml.encode())


def ids(xml):
    return {e.get(f"{{{S}}}id"): e for e in parse(xml) if e.get(f"{{{S}}}id")}


def test_closure_keeps_cycles_native_property_kind_datatypes_and_metadata(tmp_path):
    reference = model(
        namespace("t", "urn:target", '<LocalTerm><TermName>term</TermName></LocalTerm>')
        + component("Class", "t", "A", ref("SubClassOf", "t.B"))
        + component("Class", "t", "B", ref("SubClassOf", "t.A"))
        + component("DataProperty", "t", "value", '<DocumentationText>Native</DocumentationText>'
                    + ref("Datatype", "t.Values"))
        + component("Union", "t", "Values", ref("UnionMemberDatatype", "t.List"))
        + component("List", "t", "List", ref("ListItemDatatype", "xs.string"))
        + component("Class", "t", "Unused"))
    generated = model(namespace("edge", "urn:edge") + namespace("t", "urn:target")
        + component("Class", "edge", "Record", ref("SubClassOf", "t.A")
                    + '<ChildPropertyAssociation>' + ref("ObjectProperty", "t.value")
                    + '<MinOccursQuantity>0</MinOccursQuantity><MaxOccursQuantity>1</MaxOccursQuantity>'
                    + '</ChildPropertyAssociation>'))
    result = complete_cmf_references(generated, reference)
    elements = ids(result)
    assert set(elements) == {"edge", "t", "xs", "edge.Record", "t.A", "t.B", "t.value",
                             "t.Values", "t.List", "xs.string"}
    assert elements["t.value"].findtext(f"{{{CMF}}}DocumentationText") == "Native"
    assert elements["t"].find(f"{{{CMF}}}LocalTerm") is not None
    assert elements["edge.Record"].find(f"{{{CMF}}}ChildPropertyAssociation/{{{CMF}}}DataProperty") is not None
    path = tmp_path / "closed.cmf"
    path.write_text(result, encoding="utf-8")
    assert validate_cmf_schema(path) == []
    assert check_cmf_consistency(path, []) == []
    assert complete_cmf_references(generated, reference) == result


def test_source_prefix_collision_and_target_alias_keep_distinct_identities():
    reference = model(namespace("t", "urn:target")
                      + namespace("extra", "urn:native-extra")
                      + component("Class", "t", "A", ref("SubClassOf", "extra.Base"))
                      + component("Class", "extra", "Base"))
    generated = model(namespace("alias", "urn:target") + namespace("extra", "urn:source")
                      + component("Class", "extra", "Base", ref("SubClassOf", "alias.A")))
    result = ids(complete_cmf_references(generated, reference))
    assert "extra.Base" in result and "alias.A" in result
    imported_base_id = result["alias.A"].find(f"{{{CMF}}}SubClassOf").get(f"{{{S}}}ref")
    assert imported_base_id != "extra.Base"
    imported_ns = result[imported_base_id].find(f"{{{CMF}}}Namespace").get(f"{{{S}}}ref")
    assert result[imported_ns].findtext(f"{{{CMF}}}NamespaceURI") == "urn:native-extra"
    assert result["extra"].findtext(f"{{{CMF}}}NamespaceURI") == "urn:source"


def test_conflicting_local_target_declaration_is_not_allowed_to_replace_native_range():
    reference = model(namespace("t", "urn:target") + component("Class", "t", "Text")
                      + component("ObjectProperty", "t", "value", ref("Class", "t.Text")))
    generated = model(namespace("alias", "urn:target") + namespace("edge", "urn:edge")
                      + component("Class", "edge", "Record")
                      + component("ObjectProperty", "alias", "value", ref("Class", "edge.Record")))
    with pytest.raises(ValueError, match="Conflicting.*value"):
        complete_cmf_references(generated, reference)


def test_equivalent_local_definition_with_another_prefix_is_merged():
    reference = model(namespace("t", "urn:target") + component("DataProperty", "t", "value", ref("Datatype", "xs.string")))
    generated = model(namespace("alias", "urn:target") + component("DataProperty", "alias", "value", ref("Datatype", "xs.string")))
    result = ids(complete_cmf_references(generated, reference))
    assert "alias.value" in result and "t.value" not in result
    assert "xs.string" in result


def test_only_known_builtin_datatypes_are_declared_and_missing_targets_remain_errors(tmp_path):
    generated = model(namespace("edge", "urn:edge") + namespace("t", "urn:target")
                      + component("Class", "edge", "Record", ref("SubClassOf", "t.Missing"))
                      + component("DataProperty", "edge", "value", ref("Datatype", "xs.string"))
                      + component("DataProperty", "edge", "bad", ref("Datatype", "xs.NotAType")))
    result = complete_cmf_references(generated)
    assert "xs.string" in ids(result) and "xs.NotAType" not in ids(result)
    path = tmp_path / "missing.cmf"
    path.write_text(result, encoding="utf-8")
    assert validate_cmf_schema(path) == []  # XSD alone missed this failure.
    errors = check_cmf_consistency(path, [])
    assert any("t.Missing" in e and "Unbound" in e for e in errors)
    assert any("xs.NotAType" in e and "Unbound" in e for e in errors)


def test_class_reference_to_datatype_is_not_silently_reinterpreted(tmp_path):
    reference = model(namespace("t", "urn:target") + component("Restriction", "t", "Code", ref("RestrictionBase", "xs.token")))
    generated = model(namespace("edge", "urn:edge") + namespace("t", "urn:target")
                      + component("Class", "edge", "Record", ref("SubClassOf", "t.Code"))
                      + component("DataProperty", "edge", "value", ref("Datatype", "xs.string")))
    path = tmp_path / "wrong-kind.cmf"
    path.write_text(complete_cmf_references(generated, reference), encoding="utf-8")
    assert validate_cmf_schema(path) == []
    assert any("SubClassOf" in e and "Restriction" in e for e in check_cmf_consistency(path, []))


def test_explicit_implicit_root_policy_removes_base_without_fabricating_class():
    generated = model(namespace("edge", "urn:edge") + namespace("infra", "urn:infra")
                      + component("Class", "edge", "Record", ref("SubClassOf", "infra.Root")))
    ordinary = ids(complete_cmf_references(generated))
    assert ordinary["edge.Record"].find(f"{{{CMF}}}SubClassOf") is not None
    native = ids(complete_cmf_references(generated, implicit_roots={("urn:infra", "Root")}))
    assert native["edge.Record"].find(f"{{{CMF}}}SubClassOf") is None
    assert "infra.Root" not in native


def test_reference_loader_uses_configured_target_and_version_offline(tmp_path, monkeypatch):
    monkeypatch.setenv("OM_SPECS_DIR", str(tmp_path))
    content = model(namespace("t", "urn:target"))
    (tmp_path / "sample_reference_model_2.cmf.gz").write_bytes(gzip.compress(content.encode()))
    assert load_reference_cmf("sample", "2") == content
    assert load_reference_cmf("sample", "3") is None
    with pytest.raises(ValueError, match="specs"):
        load_reference_cmf("../sample", "2")


def test_imported_namespace_preserves_native_and_local_augmentation_records(tmp_path):
    def augmentation(prop):
        return ('<AugmentationRecord>' + ref("Class", "t.A") + ref("DataProperty", prop)
                + '<MinOccursQuantity>0</MinOccursQuantity><MaxOccursQuantity>unbounded</MaxOccursQuantity>'
                + '</AugmentationRecord>')
    reference = model(namespace("t", "urn:target", augmentation("t.value")
                                + '<LocalTerm><TermName>term</TermName></LocalTerm>')
                      + component("Class", "t", "A")
                      + component("DataProperty", "t", "value", ref("Datatype", "xs.string")))
    generated = model(namespace("t", "urn:target", augmentation("edge.extra"))
                      + namespace("edge", "urn:edge")
                      + component("DataProperty", "edge", "extra", ref("Datatype", "xs.string")))
    result = complete_cmf_references(generated, reference)
    assert len(ids(result)["t"].findall(f"{{{CMF}}}AugmentationRecord")) == 2
    path = tmp_path / "augmentation.cmf"
    path.write_text(result, encoding="utf-8")
    assert check_cmf_consistency(path, []) == []


def test_reference_loader_rejects_file_symlink_outside_specs(tmp_path, monkeypatch):
    specs = tmp_path / "specs"
    specs.mkdir()
    external = tmp_path / "external.gz"
    external.write_bytes(gzip.compress(b"external"))
    try:
        (specs / "sample_reference_model_2.cmf.gz").symlink_to(external)
    except OSError:
        pytest.skip("File symlinks require permission on this host")
    monkeypatch.setenv("OM_SPECS_DIR", str(specs))
    with pytest.raises(ValueError, match="specs"):
        load_reference_cmf("sample", "2")
