from lisa.extract.fewshot import build_fewshot, edge_examples, node_examples
from lisa.extract.prompts import build_system, load_prompt
from lisa.extract.units import Unit, UnitPage

UNIT = Unit(unit_id="g1__u1of1", case_id="g1", domain="immigration", header="CASE_ID: g1\n",
            pages=(UnitPage(1, None, "Page one text."), UnitPage(2, None, "Page two text."),
                   UnitPage(3, None, "Page three text.")),
            raw_pages={1: "Page one text.", 2: "Page two text.", 3: "Page three text."}, segments=(),
            repeated_page=None)
GOLD = {"nodes": [
    {"id": "g1:opinion:majority", "type": "opinion", "label": "Majority", "summary": "s", "part": "majority",
     "author": "Jones", "evidence": [{"page": 1, "quote": "Page one text.", "verified": True}], "attrs": {},
     "case_id": "g1", "dataset": "immigration"},
    {"id": "g1:holding:h", "type": "holding", "label": "Holding", "summary": "s", "part": "majority",
     "author": None, "evidence": [{"page": 2, "quote": "Page two text."}], "attrs": {}},
    {"id": "g1:fact:late", "type": "fact", "label": "Late fact", "summary": "s", "part": "majority",
     "author": None, "evidence": [{"page": 3, "quote": "Page three text."}], "attrs": {"kind": "fact"}}],
    "edges": [
        {"source": "g1:opinion:majority", "target": "g1:holding:h", "relation": "holds", "stance": None,
         "basis": "explicit", "part": "majority", "evidence": [{"page": 2, "quote": "Page two text."}],
         "confidence": 0.9, "attrs": {}, "case_id": "g1"},
        {"source": "g1:opinion:majority", "target": "g1:fact:late", "relation": "states_fact", "stance": None,
         "basis": "explicit", "part": "majority", "evidence": [], "confidence": 0.9, "attrs": {}}]}


def test_prompts_have_versions_and_placeholders():
    for name in ("nodes", "edges"):
        version, body = load_prompt(name)
        assert version.startswith(f"{name}-v") and "{{FEWSHOT}}" in body
    assert "{{SIGNATURES}}" in load_prompt("edges")[1]


def test_build_system_fills_placeholders():
    _, text = build_system("edges", "EXAMPLE")
    assert "EXAMPLE" in text and "{{" not in text and "reasoning -supports-> holding" in text


def test_node_examples_keep_only_pages_shown_and_strip_gold_fields():
    block = node_examples(GOLD, UNIT, max_pages=2)
    assert "Page two text." in block and "Page three text." not in block
    assert '"label": "Majority"' in block and '"label": "Late fact"' not in block
    assert "case_id" not in block and "verified" not in block and "g1:opinion" not in block


def test_edge_examples_use_catalog_ids_and_drop_out_of_window_edges():
    block = edge_examples(GOLD, UNIT, max_pages=2)
    assert '"id": "g1:holding:h"' in block and '"relation": "holds"' in block
    assert "states_fact" not in block


def test_build_fewshot_skips_missing_units():
    nodes, edges = build_fewshot({"g1__u1of1": GOLD}, {"g1__u1of1": UNIT}, ["g1__u1of1", "absent__u1of1"])
    assert nodes.count("### Example input") == 1 and edges.count("### Example input") == 1
    assert build_fewshot({}, {}, []) == ("", "")
