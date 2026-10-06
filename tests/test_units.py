from lisa.extract.units import active_part, build_units, render_pages, segment_record
from lisa.graph.loader import Record


def rec(domain, pages, **props):
    return Record(id="c1", domain=domain, title="Alpha v. Beta", citation=props.pop("citation", None),
                  props=props, pages=[{"page": i + 1, "text": t} for i, t in enumerate(pages)],
                  text="\n".join(pages), citations=[], pdf_pages={i + 1: 10 + i for i in range(len(pages))})


SCOTUS = ["Syllabus\nSummary of the case.",
          "JUSTICE KAGAN delivered the opinion of the Court.\nWe hold for petitioner.",
          "JUSTICE THOMAS, dissenting.\nI disagree."]


def test_segments_litigation_parts_in_order():
    segs = segment_record(rec("litigation", SCOTUS))
    assert [s.part for s in segs] == ["syllabus", "majority", "dissent"]
    assert [s.seg_id for s in segs] == ["c1#s0", "c1#s1", "c1#s2"]
    assert (segs[1].start_page, segs[1].start_char, segs[1].end_page) == (2, 0, 3)
    assert segs[2].label == "Thomas dissenting"
    assert (segs[2].end_page, segs[2].end_char) == (3, len(SCOTUS[2]))


def test_immigration_without_markers_is_body_unsegmented():
    segs = segment_record(rec("immigration", ["Plain text.", "More text."]))
    assert [s.part for s in segs] == ["body_unsegmented"]


def test_single_unit_text_layout():
    [u] = build_units(rec("litigation", SCOTUS, citation="585 U.S. 1", docket_number="17-1",
                          court="Supreme Court of the United States", decision_date="2018-06-22"))
    assert u.unit_id == "c1__u1of1" and u.repeated_page is None
    assert u.text.startswith("CASE_ID: c1\nDATASET: litigation\nTITLE: Alpha v. Beta\nCITATION: 585 U.S. 1\n"
                             "DECISION_DATE: 2018-06-22\nDOCKET: 17-1\nCOURT/BODY: Supreme Court of the United States\n"
                             "UNIT: 1 of 1 (pages 1-3)\nPARTS IN THIS DOCUMENT (deterministic hints): syllabus[")
    assert "\n===== [[PAGE 2 | source_pdf_page 11]] =====\n" in u.text
    assert ("\n<<<PART BEGINS: majority | JUSTICE KAGAN delivered the opinion of the Court. | seg_id=c1#s1>>>\n"
            in u.text)
    assert u.raw_pages[2] == SCOTUS[1]
    assert render_pages(u.pages) in u.text


def test_unknown_metadata_prints_unknown():
    [u] = build_units(rec("immigration", ["Text."]))
    assert "CITATION: unknown\nDECISION_DATE: unknown\nDOCKET: unknown\nCOURT/BODY: unknown\n" in u.text


def test_multi_unit_overlap_and_continuation():
    units = build_units(rec("litigation", SCOTUS), unit_chars=1)
    assert [u.unit_id for u in units] == ["c1__u1of3", "c1__u2of3", "c1__u3of3"]
    assert [[p.page for p in u.pages] for u in units] == [[1], [1, 2], [2, 3]]
    assert [u.repeated_page for u in units] == [None, 1, 2]
    assert "first page repeated from previous unit for context - do not re-extract it" in units[2].header
    # same rule as the reference: the part whose start is <= (page, char 0) — the dissent starts at page 3, char 0
    assert "CONTINUING PART AT TOP OF PAGE 3 (began in an earlier unit): dissent | Thomas dissenting" in units[2].header
    assert "CONTINUING PART AT TOP OF PAGE 2 (began in an earlier unit): majority" in units[1].header


def test_active_part():
    segs = segment_record(rec("litigation", SCOTUS))
    assert active_part(segs, 2).part == "majority"
    assert active_part(segs, 3).part == "dissent"
