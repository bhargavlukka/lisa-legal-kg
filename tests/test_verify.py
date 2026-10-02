from lisa.extract.verify import PageIndex, evidence_strength, squash, verify_item

PAGES = {
    1: "The respondent was law-\nfully admitted for permanent residence in 1990.",
    2: "We find that the “admission” was\nnot lawful. The Board",
    3: "agrees with the Immigration Judge. The appeal is dismissed. The Court",
    4: "has jurisdiction because the stop was lawful under Terry v. Ohio.",
}
IDX = PageIndex(PAGES)


def test_squash_drops_space_hyphen_quotes_and_markers():
    assert squash("law-\nfully  “admitted” it’s") == squash('lawfully "admitted" its')
    assert squash("<<<PART BEGINS: majority | X | seg_id=a#s1>>>Text") == "Text"


def test_locate_hyphenation_across_line():
    sp = IDX.locate("lawfully admitted for permanent residence", 1)
    assert sp and sp.page == 1


def test_locate_curly_quotes_and_replacement_char():
    assert IDX.locate('We find that the "admission" was not lawful', 2).page == 2
    assert IDX.locate("We find that the �admission� was not lawful", 2).page == 2


def test_locate_corrects_off_by_one_page():
    assert IDX.locate("The appeal is dismissed.", 4).page == 3
    assert IDX.locate("The appeal is dismissed.", 2).page == 3


def test_locate_cross_page_quote_starts_on_first_page():
    assert IDX.locate("not lawful. The Board agrees with the Immigration Judge", 2).page == 2


def test_locate_too_far_or_absent_page_fails():
    assert IDX.locate("The appeal is dismissed.", 1) is None   # page 3 is 2 away from 1
    assert IDX.locate("The appeal is dismissed.", None) is None
    assert IDX.locate("Something never said in the opinion", 2) is None


def test_short_quote_never_verifies():
    assert IDX.locate("The Court", 3) is None


def test_verify_all_found():
    out = verify_item({"confidence": 0.9, "evidence": [{"page": 3, "quote": "The appeal is dismissed."}]}, IDX)
    assert out["provenance"] == "llm" and out["evidence_verified"] is True
    assert out["confidence"] == 0.9 and out["evidence_strength"] == "moderate"
    assert out["evidence"][0]["verified"] is True and "span" in out["evidence"][0]


def test_verify_partial_drops_bad_quote_and_scales_confidence():
    out = verify_item({"confidence": 0.9, "evidence": [
        {"page": 3, "quote": "The appeal is dismissed."}, {"page": 3, "quote": "a quote that is not there at all"}]}, IDX)
    assert out["provenance"] == "llm" and len(out["evidence"]) == 1
    assert out["confidence"] == 0.72


def test_verify_none_found_is_unverified_and_capped():
    out = verify_item({"confidence": 0.95, "evidence": [{"page": "2", "quote": "invented text not in pages"}]}, IDX)
    assert out["provenance"] == "unverified" and out["evidence_verified"] is False
    assert out["confidence"] == 0.3 and out["evidence"][0] == {"page": 2, "quote": "invented text not in pages",
                                                               "verified": False}


def test_verify_default_confidence_and_bad_evidence_shape():
    out = verify_item({"evidence": "nope"}, IDX)
    assert out["provenance"] == "unverified" and out["confidence"] == 0.3 and out["evidence"] == []


def test_evidence_strength_rules():
    assert evidence_strength([]) == "weak"
    assert evidence_strength(["short quote here"]) == "moderate"
    assert evidence_strength(["one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen"]) == "strong"
    assert evidence_strength(["a b c", "d e f"]) == "strong"
