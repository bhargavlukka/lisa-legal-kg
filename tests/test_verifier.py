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
