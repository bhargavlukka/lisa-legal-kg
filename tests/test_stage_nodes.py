import json
import re

from fakes import FakeClient
from lisa.extract.stage_nodes import assign_ids, dedupe, extract_nodes, make_windows, slug, window_message
from lisa.extract.units import Segment, Unit, UnitPage
from lisa.llm.budget import RunStats

TEXTS = {i: f"Page {i} says the respondent number {i} was admitted lawfully in the year {1990 + i}." for i in range(1, 6)}


def unit(n=5, repeated=None):
    pages = tuple(UnitPage(i, None, TEXTS[i]) for i in range(1, n + 1))
    seg = Segment("c#s0", "majority", "Opinion", 1, 0, n, 10)
    return Unit("c__u1of1", "c", "immigration", "CASE_ID: c\n", pages, {i: TEXTS[i] for i in range(1, n + 1)},
                (seg,), repeated)


def node(page, label="Admission", type_="fact", conf=0.8):
    return {"type": type_, "label": label, "summary": "", "part": "majority", "author": None, "confidence": conf,
            "evidence": [{"page": page, "quote": TEXTS[page][:50]}], "attrs": {}}


def test_slug():
    assert slug("Section 212(h) waiver — LPR!") == "section_212_h_waiver_lpr"
    assert slug("!!!") == "x"


def test_make_windows_overlap_one_page():
    assert [[p.page for p in w] for w in make_windows(unit(5), 3)] == [[1, 2, 3], [3, 4, 5]]
    assert [[p.page for p in w] for w in make_windows(unit(2), 3)] == [[1, 2]]
    assert [[p.page for p in w] for w in make_windows(unit(4), 3)] == [[1, 2, 3], [3, 4]]


def test_window_message_has_header_part_and_pages():
    msg = window_message(unit(5), unit(5).pages[2:4])
    assert msg.startswith("CASE_ID: c\nPART ACTIVE AT TOP OF WINDOW (page 3): majority | Opinion\n")
    assert "[[PAGE 3 |" in msg and "[[PAGE 5 |" not in msg


def test_assign_ids_suffixes_collisions():
    out = assign_ids("c", [{"type": "fact", "label": "A b"}, {"type": "fact", "label": "a-b"},
                           {"type": "rule", "label": "a b"}])
    assert [n["id"] for n in out] == ["c:fact:a_b", "c:fact:a_b_2", "c:rule:a_b"]
    assert all(n["case_id"] == "c" for n in out)


def _verified(n):
    from lisa.extract.verify import PageIndex, verify_item
    return verify_item(n, PageIndex(TEXTS))


def test_dedupe_merges_overlapping_same_type():
    a, b = _verified(node(3, "Admission", conf=0.6)), _verified(node(3, "Lawful admission", conf=0.9))
    [m] = dedupe([a, b])
    assert m["confidence"] == 0.9 and m["label"] == "Admission" and len(m["evidence"]) == 1


def test_dedupe_merges_equal_labels_and_unions_evidence():
    a, b = _verified(node(1, "Admission")), _verified(node(2, "admission"))
    [m] = dedupe([a, b])
    assert sorted(e["page"] for e in m["evidence"]) == [1, 2] and m["evidence_strength"] == "strong"


def test_dedupe_keeps_different_types_apart():
    assert len(dedupe([_verified(node(3, "A", "fact")), _verified(node(3, "B", "issue"))])) == 2


def reply_for_pages(messages):
    pages = [int(x) for x in re.findall(r"\[\[PAGE (\d+) \|", messages[-1]["content"])]
    return json.dumps({"nodes": [node(p, f"Fact on page {p}") for p in pages] + [{"type": "dog"}]})


def test_extract_nodes_end_to_end_with_rejects_and_overlap_dedupe():
    stats = RunStats()
    nodes = extract_nodes(unit(5), FakeClient(reply_for_pages), "SYS", "nodes-v1", 3, stats)
    assert [n["label"] for n in nodes] == [f"Fact on page {p}" for p in range(1, 6)]   # page 3 seen twice, merged
    assert all(n["provenance"] == "llm" and n["id"].startswith("c:fact:") for n in nodes)
    assert len(stats.schema_rejects) == 2 and stats.schema_rejects[0]["reason"] == "unknown node type: dog"


def test_extract_nodes_drops_items_only_on_repeated_page():
    nodes = extract_nodes(unit(3, repeated=1), FakeClient(reply_for_pages), "SYS", "v", 3, RunStats())
    assert [n["label"] for n in nodes] == ["Fact on page 2", "Fact on page 3"]


def test_truncated_window_is_split_in_half_once():
    def responder(messages):
        if messages[-1]["content"].count("[[PAGE") == 3:
            return ("{", "length")
        return reply_for_pages(messages)
    stats = RunStats()
    fc = FakeClient(responder)
    nodes = extract_nodes(unit(3), fc, "SYS", "v", 3, stats)
    assert len(fc.calls) == 3 and len(nodes) == 3 and stats.failed == []


def test_unsplittable_truncation_and_bad_json_are_recorded_as_failed():
    stats = RunStats()
    assert extract_nodes(unit(1), FakeClient(lambda m: ("{", "length")), "S", "v", 3, stats) == []
    assert stats.failed == [{"unit": "c__u1of1", "stage": "nodes", "pages": [1], "reason": "truncated"}]
    stats = RunStats()
    extract_nodes(unit(1), FakeClient(lambda m: "nope"), "S", "v", 3, stats)
    assert stats.failed[0]["reason"].startswith("invalid output")
