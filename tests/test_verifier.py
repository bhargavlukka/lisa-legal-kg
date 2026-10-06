import pytest

from lisa.store.memory import MemoryStore
from lisa.tools.verifier import EXTERNAL, UNVERIFIED, VERIFIED, Verifier, sentences

QUOTE = "Under Pereira v. Sessions, 585 U. S. 198 (2018), the notice was defective"


class FakeExternal:
    def __init__(self, status="resolved"):
        self.status, self.calls = status, []

    def lookup_citation(self, c):
        self.calls.append(c)
        if self.status == "resolved":
            return {"status": "resolved", "case_name": "Niz-Chavez v. Garland", "citation": c}
        return {"status": "unavailable", "reason": "COURTLISTENER_TOKEN not set"}


@pytest.fixture
def v(graph_all):
    return Verifier(MemoryStore([graph_all]), FakeExternal())


def test_in_corpus_quote_verified_with_whitespace_and_quote_typography(v):
    r = v.verify_citation("Matter of Alpha", "Under Pereira v.  Sessions, 585 U.\nS. 198 (2018), the notice", 2)
    assert r["tier"] == VERIFIED and r["case_id"] == "eoir_1" and r["matched_page"] == 2


def test_wrong_page_still_matches_but_reports_actual_page(v):
    r = v.verify_citation("eoir_1", QUOTE, 1)
    assert r["tier"] == VERIFIED and r["matched_page"] == 2 and "page 2" in r["page_note"]


def test_fabricated_or_missing_quote_is_unverified(v):
    assert v.verify_citation("eoir_1", QUOTE + " and the Board granted asylum", 2)["tier"] == UNVERIFIED
    assert v.verify_citation("eoir_1")["tier"] == UNVERIFIED
    assert v.verify_citation("eoir_1", "the notice", 2)["tier"] == UNVERIFIED     # too short to prove anything


def test_external_tiers(graph_all):
    ok = Verifier(MemoryStore([graph_all]), FakeExternal())
    assert ok.verify_citation("593 U.S. 155")["tier"] == EXTERNAL
    down = Verifier(MemoryStore([graph_all]), FakeExternal("unavailable"))
    r = down.verify_citation("593 U.S. 155")
    assert r["tier"] == UNVERIFIED and "TOKEN" in r["reason"]
    assert ok.verify_citation("Some Unknown Case")["tier"] == UNVERIFIED


def test_verify_answer_passes_clean_answer(v):
    ans = ("The Board held that the notice was defective under Pereira [1].\n\n"
           "Provenance: [1] verified in-corpus. Legal status: not verified; may have subsequent treatment.")
    r = v.verify_answer(ans, [{"case": "eoir_1", "quote": QUOTE, "page": 2}])
    assert r["passed"], r["problems"]
    assert r["tiers"][VERIFIED] == 1


@pytest.mark.parametrize("ans,cits,kind", [
    ("The Board held the notice was defective.", [{"case": "eoir_1", "quote": QUOTE, "page": 2}], "uncited_claim"),
    ("The Board held the notice was defective [2].", [{"case": "eoir_1", "quote": QUOTE, "page": 2}], "dangling_marker"),
    ("The Board held the notice was defective [1].", [{"case": "eoir_1", "quote": "made up quote text here", "page": 2}],
     "unverified_citation"),
    ("Pereira is still good law [1].", [{"case": "eoir_1", "quote": QUOTE, "page": 2}], "unqualified_status_claim"),
    ("The Board held the notice was defective.", [], "no_citations"),
])
def test_verify_answer_blocks(v, ans, cits, kind):
    r = v.verify_answer(ans, cits)
    assert not r["passed"] and kind in {p["kind"] for p in r["problems"]}


def test_qualified_status_statement_allowed(v):
    ans = "Whether Pereira is still good law is not verified; no citator check was run [1]."
    r = v.verify_answer(ans, [{"case": "eoir_1", "quote": QUOTE, "page": 2}])
    assert r["passed"], r["problems"]


def test_sentences_keep_legal_abbreviations():
    s = sentences("See Pereira v. Sessions, 585 U.S. 198 (2018). The Board held X [1].\n- Second bullet [2].")
    assert s == ["See Pereira v. Sessions, 585 U.S. 198 (2018).", "The Board held X [1].", "Second bullet [2]."]


CIT = [{"case": "eoir_1", "quote": QUOTE, "page": 2}]


def test_quotes_in_answer_prose_must_be_on_a_cited_page(v):
    fake = v.verify_answer('The Board stated that "the respondent is plainly eligible for asylum relief" [1].', CIT)
    assert not fake["passed"] and "unverified_quote" in {p["kind"] for p in fake["problems"]}
    real = v.verify_answer("The Board noted \u201cthe notice was defective\u201d under Pereira [1].", CIT)
    assert real["passed"], real["problems"]


def test_legal_cues_are_case_insensitive_and_section_sign_counts(v):
    for s in ["Held: the notice was defective.", "Eligibility turns on the notice.", "See \u00a7 1229(a) for the rule."]:
        r = v.verify_answer(s + " The Board held so [1].", CIT)
        assert "uncited_claim" in {p["kind"] for p in r["problems"]}, s


def test_citation_never_referenced_by_a_marker_is_a_problem(v):
    r = v.verify_answer("The Board held the notice was defective [1].", CIT + CIT)
    assert not r["passed"] and {"kind": "unused_citation", "marker": 2} in r["problems"]


def test_external_citation_cannot_carry_an_unchecked_quote_or_a_wrong_name(graph_all):
    ok = Verifier(MemoryStore([graph_all]), FakeExternal())
    assert ok.verify_citation("Niz-Chavez v. Garland, 593 U.S. 155")["tier"] == EXTERNAL
    wrong = ok.verify_citation("Roe v. Wade, 593 U.S. 155")
    assert wrong["tier"] == UNVERIFIED and "name" in wrong["reason"]
    quoted = ok.verify_citation("593 U.S. 155", "a quotation the external source text was never checked for", 3)
    assert quoted["tier"] == UNVERIFIED and "quote" in quoted["reason"]


def test_quoted_terms_are_not_quotations_and_bracket_alterations_match(v):
    term = v.verify_answer('The Board applied "Chevron deference" and the "categorical approach" here [1].', CIT)
    assert term["passed"], term["problems"]
    altered = v.verify_answer("The Board noted that \u201c(2018), [t]he notice was defective\u201d [1].", CIT)
    assert altered["passed"], altered["problems"]
    fake = v.verify_answer("The Board noted that \u201c(2018), [t]he notice was perfectly valid\u201d [1].", CIT)
    assert "unverified_quote" in {p["kind"] for p in fake["problems"]}


@pytest.mark.parametrize("prose", [
    'The Board said "asylum was plainly granted" [1].',                                   # short fabricated quote
    "The Board said \u201cthe notice [was not] defective\u201d [1].",                    # inserted words via brackets
    "The Board said \u201c(2018), the notice [wasn't] defective\u201d [1].",
])
def test_short_fabrications_and_bracket_insertions_are_caught(v, prose):
    r = v.verify_answer(prose, CIT)
    assert "unverified_quote" in {p["kind"] for p in r["problems"]}, prose


def test_suffix_alteration_matches_contiguously(v):
    ok = v.verify_answer("The Board said \u201cthe notice wa[] defective\u201d [1].", CIT)
    assert ok["passed"], ok["problems"]


def test_alteration_with_ellipsis_headings_and_quoted_citations(v):
    ok = v.verify_answer("The Board said \u201c(2018), [t]he notice . . . defective\u201d [1].", CIT)
    assert ok["passed"], ok["problems"]
    head = v.verify_answer("SUPREME COURT\nThe Board held the notice was defective [1].", CIT)
    assert head["passed"], head["problems"]
    cite = v.verify_answer('The Board relied on "585 U.S. 198" for this [1].', CIT)
    assert "unverified_quote" not in {p["kind"] for p in cite["problems"]}


def test_brackets_present_in_the_source_match_literally(graph_all):
    store = MemoryStore([graph_all])
    store.pages["eoir_1"][2] += "\nthe basic judicial task of \u201csay[ing] what the law is.\u201d"
    r = Verifier(store).verify_answer('It is the task of "say[ing] what the law is" [1].', CIT)
    assert r["passed"], r["problems"]


@pytest.mark.parametrize("prose,kind", [
    ("The Board said \u201c(2018), the notice wa[s not] defective\u201d [1].", "unverified_quote"),   # insertion
    ("The Board said \u201cthe notice was [in]defective here\u201d [1].", "unverified_quote"),       # additive letters
    ("The Board said 'the respondent is plainly eligible for asylum' [1].", "unverified_quote"),   # single quotes
    ("The Board said \u00abthe respondent is plainly eligible for asylum\u00bb [1].", "unverified_quote"),
    ("THE BOARD HELD THAT RELIEF IS GRANTED\nThe Board held so [1].", "uncited_claim"),            # all-caps claim
])
def test_meaning_changing_alterations_other_quote_marks_and_caps_claims_are_caught(v, prose, kind):
    r = v.verify_answer(prose, CIT)
    assert kind in {p["kind"] for p in r["problems"]}, prose


def test_case_change_alteration_and_apostrophes_still_pass(v):
    r = v.verify_answer("The Board\u2019s view: \u201c(2018), [T]he notice was defective\u201d isn't new [1].", CIT)
    assert r["passed"], r["problems"]
