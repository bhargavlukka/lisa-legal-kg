import pytest

from lisa.graph.statutes import extract_mentions

IMM_PATTERNS = ["usc", "cfr", "ina_symbol", "ina_section"]
PAGES = [{"page": 3, "text": "relief under section 212(h) of the\nAct, 8 U.S.C. § 1182(h) (Supp. II 1996), "
                              "and 8 C.F.R. § 1003.1(d)(3)."}]


def ids(ms):
    return sorted(m.canon_id for m in ms)


def test_immigration_patterns_and_ina_crosswalk():
    assert ids(extract_mentions(PAGES, IMM_PATTERNS)) == ["cfr:8_1003", "usc:8_1182", "usc:8_1182"]


def test_quote_is_verbatim_and_page_anchored():
    reg = [m for m in extract_mentions(PAGES, IMM_PATTERNS) if m.kind == "regulation"][0]
    assert reg.page == 3
    assert reg.quote in PAGES[0]["text"]
    assert "C.F.R." in reg.quote
    assert reg.display == "8 C.F.R. Part 1003"


def test_litigation_spacing_and_ina_symbol():
    pages = [{"page": 1, "text": "under 28 U. S. C. §1253 and INA §§ 240A(b)(1)"}]
    ms = extract_mentions(pages, ["usc", "cfr", "ina_symbol"])
    assert ids(ms) == ["usc:28_1253", "usc:8_1229b"]
    assert {m.display for m in ms} == {"28 U.S.C. § 1253", "8 U.S.C. § 1229b"}


def test_unmapped_ina_section_kept_as_ina_node():
    pages = [{"page": 2, "text": "adjustment under section 245(i) of the Immigration and Nationality Act"}]
    ms = extract_mentions(pages, IMM_PATTERNS)
    assert [(m.canon_id, m.display) for m in ms] == [("ina:245", "INA § 245")]


def test_section_of_the_act_not_used_for_litigation():
    pages = [{"page": 1, "text": "section 2 of the Act forbids vote dilution"}]
    assert extract_mentions(pages, ["usc", "cfr", "ina_symbol"]) == []


def test_unknown_pattern_raises():
    with pytest.raises(ValueError, match="nope"):
        extract_mentions(PAGES, ["nope"])


def test_page_header_number_is_not_a_usc_title():
    pages = [{"page": 3, "text": "Interim Decision #3390\nU.S.C. § 16 and 18 U.S.C. § 924(c)"}]
    assert ids(extract_mentions(pages, ["usc"])) == ["usc:18_924"]
