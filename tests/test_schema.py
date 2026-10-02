import json
from pathlib import Path

from lisa.extract import schema
from lisa.extract.schema import SIGNATURES, derive_signatures, validate_edge, validate_node

EV = [{"page": 1, "quote": "some verbatim words"}]


def test_signatures_loaded():
    assert len(SIGNATURES) == 34
    assert ("reasoning", "supports", "holding") in SIGNATURES
    assert ("reasoning", "relies_on", "authority_ref") in SIGNATURES


def test_validate_node_ok_and_cleaned():
    n, why = validate_node({"type": "rule", "label": " Categorical approach ", "part": "majority",
                            "evidence": EV, "attrs": {"rule_kind": "doctrine", "doctrine": "categorical approach"},
                            "confidence": 0.8, "junk": 1})
    assert why is None
    assert n == {"type": "rule", "label": "Categorical approach", "summary": "", "part": "majority", "author": None,
                 "evidence": EV, "confidence": 0.8,
                 "attrs": {"rule_kind": "doctrine", "doctrine": "categorical approach"}}


def test_validate_node_coerces_unknown_part_and_kind():
    n, _ = validate_node({"type": "authority_ref", "label": "Pereira", "part": "lead",
                          "evidence": EV, "attrs": {"cite_string": "585 U.S. 198", "kind": "precedent"}})
    assert n["part"] is None and n["attrs"]["kind"] == "other"


def test_validate_node_rejects():
    assert validate_node({"type": "dog", "label": "x", "evidence": EV})[1] == "unknown node type: dog"
    assert validate_node({"type": "rule", "label": "", "evidence": EV})[1] == "missing label"
    assert validate_node({"type": "rule", "label": "x", "evidence": []})[1] == "missing evidence"
    assert validate_node({"type": "authority_ref", "label": "x", "evidence": EV, "attrs": {}})[1] == \
        "authority_ref without cite_string"
    assert validate_node("not a dict")[1] == "not an object"


TYPES = {"a:reasoning:r": "reasoning", "a:authority_ref:x": "authority_ref", "a:holding:h": "holding"}


def test_validate_edge_ok_defaults_stance_and_basis():
    e, why = validate_edge({"source": "a:reasoning:r", "target": "a:authority_ref:x", "relation": "relies_on",
                            "stance": "approves", "evidence": EV}, TYPES)
    assert why is None and e["stance"] == "relies_on" and e["basis"] == "explicit"
    e, _ = validate_edge({"source": "a:reasoning:r", "target": "a:holding:h", "relation": "supports",
                          "stance": "follows", "basis": "inferred", "evidence": EV}, TYPES)
    assert e["stance"] is None and e["attrs"]["inference_reason"] == "(not given)"


def test_validate_edge_rejects():
    assert validate_edge({"source": "zz", "target": "a:holding:h", "relation": "supports"}, TYPES)[1] == \
        "unknown node id: zz"
    assert validate_edge({"source": "a:reasoning:r", "target": "a:holding:h", "relation": "cites"}, TYPES)[1] == \
        "unknown relation: cites"
    assert validate_edge({"source": "a:holding:h", "target": "a:reasoning:r", "relation": "supports"}, TYPES)[1] == \
        "disallowed signature: holding -supports-> reasoning"


def test_derive_signatures(tmp_path):
    g = {"nodes": [{"id": "1", "type": "fact"}, {"id": "2", "type": "issue"}],
         "edges": [{"source": "1", "target": "2", "relation": "relevant_to"},
                   {"source": "1", "target": "9", "relation": "relevant_to"}]}
    (tmp_path / "u.json").write_text(json.dumps(g), encoding="utf-8")
    assert derive_signatures(tmp_path) == [["fact", "relevant_to", "issue"]]


def test_committed_signatures_match_gold(real_data_dir):
    committed = json.loads((Path(schema.__file__).parent / "schema_signatures.json").read_text(encoding="utf-8"))
    assert committed == derive_signatures(real_data_dir / "gold_standard")
