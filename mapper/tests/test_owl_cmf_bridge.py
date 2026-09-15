"""CMF XML/JSON information preservation."""

import json

from ontology_mapper.owl_cmf_bridge import (
    CmfJsonSerializer, CmfModel, CmfNamespace, set_niem_version,
)


def test_json_retains_present_conformance_and_does_not_invent_absent_value():
    set_niem_version("6.0")
    model = CmfModel(namespaces=[
        CmfNamespace("extension", "https://example.org/ext#", "extension",
                     conformance_target="https://example.org/conformance/extension"),
        CmfNamespace("external", "https://example.org/external/", "external"),
    ])
    namespaces = json.loads(CmfJsonSerializer(model).serialize())["Model"]["Namespace"]
    assert namespaces[0]["ConformanceTargetURI"] == "https://example.org/conformance/extension"
    assert "ConformanceTargetURI" not in namespaces[1]


def test_xml_json_preserves_native_union_datatype_and_metadata():
    from ontology_mapper.owl_cmf_bridge import cmf_xml_to_json

    xml = '''<Model xmlns="https://docs.oasis-open.org/niemopen/ns/specification/cmf/1.0/"
       xmlns:structures="https://docs.oasis-open.org/niemopen/ns/model/structures/6.0/"
       xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
      <Namespace structures:id="t"><NamespaceURI>urn:test</NamespaceURI>
        <NamespacePrefixText>t</NamespacePrefixText><NamespaceCategoryCode>EXTERNAL</NamespaceCategoryCode>
        <LocalTerm><TermName>sample</TermName><DocumentationText>Reference metadata</DocumentationText></LocalTerm>
      </Namespace>
      <Datatype structures:id="t.A"><Name>A</Name><Namespace structures:ref="t" xsi:nil="true"/></Datatype>
      <Union structures:id="t.U"><Name>U</Name><Namespace structures:ref="t" xsi:nil="true"/>
        <UnionMemberDatatype structures:ref="t.A" xsi:nil="true"/>
      </Union>
    </Model>'''
    result = json.loads(cmf_xml_to_json(xml))["Model"]
    assert result["Datatype"][0]["Name"] == "A"
    assert result["Union"][0]["UnionMemberDatatype"] == [{"structures:ref": "t.A"}]
    assert result["Namespace"][0]["LocalTerm"][0]["DocumentationText"] == "Reference metadata"


def test_xml_json_keeps_text_with_language_metadata():
    from ontology_mapper.owl_cmf_bridge import cmf_xml_to_json

    xml = '''<Model xmlns="https://docs.oasis-open.org/niemopen/ns/specification/cmf/1.0/">
      <Namespace><DocumentationText xml:lang="en">Reference meaning</DocumentationText></Namespace>
    </Model>'''
    result = json.loads(cmf_xml_to_json(xml))["Model"]["Namespace"][0]["DocumentationText"]
    assert result == {"xml:lang": "en", "#text": "Reference meaning"}
