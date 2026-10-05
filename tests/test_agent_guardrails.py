import pytest

from lisa.agent.guardrails import gate
from lisa.agent.memory.store import SessionMemory
from lisa.tools.verifier import EXTERNAL, UNVERIFIED, VERIFIED


def rep(*tiers, problems=()):
    return {"passed": not problems, "problems": list(problems),
            "citations": [{"case": f"c{i}", "tier": t, "title": f"Case {i}", "citation": f"{i} I&N Dec. 1",
                           "matched_page": 2 if t == VERIFIED else None} for i, t in enumerate(tiers, 1)]}


def test_parse_final_fenced_bare_and_missing():
    fenced = 'Thinking...\n```json\n{"answer": "A [1].", "citations": [{"case": "eoir_1", "quote": "q", "page": 2}]}\n```'
    assert gate.parse_final(fenced) == {"answer": "A [1].", "citations": [{"case": "eoir_1", "quote": "q", "page": 2}],
                                        "parsed": True}
    bare = 'Here: {"answer": "B [1].", "citations": [{"case": "x"}, "junk", {"quote": "no case"}]}'
    assert gate.parse_final(bare)["citations"] == [{"case": "x"}]
    raw = gate.parse_final("The Board held X.")
    assert raw == {"answer": "The Board held X.", "citations": [], "parsed": False}


def test_salvage_keeps_only_fully_supported_sentences_and_renumbers():
    draft = {"answer": "The Board held A [1]. The Court held B [2]. Both cases agree [1, 3]. Uncited claim held C.",
             "citations": [{"case": "a"}, {"case": "b"}, {"case": "c"}]}
    out = gate.salvage(draft, rep(UNVERIFIED, VERIFIED, EXTERNAL,
                                  problems=[{"kind": "uncited_claim", "sentence": "Uncited claim held C."}]))
    assert out == {"answer": "The Court held B [1].", "citations": [{"case": "b"}]}


def test_salvage_returns_none_when_nothing_survives():
    draft = {"answer": "The Board held A [1].", "citations": [{"case": "a"}]}
    assert gate.salvage(draft, rep(UNVERIFIED, problems=[{"kind": "unverified_citation"}])) is None


def test_render_labels_tiers_status_and_disclaimer_only_for_advice():
    r = rep(VERIFIED, EXTERNAL)
    plain = gate.render("Which BIA cases cite Pereira?", "Answer [1][2].", r, "verified")
    assert "[1] Case 1 1 I&N Dec. 1, p. 2 - verified in-corpus" in plain
    assert "[2] Case 2 2 I&N Dec. 1 - resolved externally (CourtListener)" in plain
    assert gate.STATUS_NOTE in plain and gate.DISCLAIMER not in plain
    advice = gate.render("Should I appeal my removal order?", "Answer [1].", rep(VERIFIED), "verified")
    assert advice.endswith(gate.DISCLAIMER)


@pytest.mark.parametrize("q,expected", [
    ("Am I eligible for cancellation of removal?", True),
    ("What should my client argue at the hearing?", True),
    ("What are the ten most-cited precedents?", False),
    ("Summarize the holding of Pereira v. Sessions.", False),
])
def test_is_advice(q, expected):
    assert gate.is_advice(q) is expected


def test_revision_prompt_lists_problems():
    p = gate.revision_prompt({"problems": [{"kind": "uncited_claim", "sentence": "X held Y."}]})
    assert "FAILED" in p and "uncited_claim" in p


def test_session_memory_survives_restart(tmp_path):
    m = SessionMemory(tmp_path, "case-123")
    assert m.digest() == "" and m.sdk_session_id is None
    m.record("Which BIA decisions cite Pereira?", "Answer text [1].",
             [{"case": "eoir_4028", "case_id": "eoir_4028", "title": "ARAMBULA-BRAVO"}], "verified", "sdk-1")
    again = SessionMemory(tmp_path, "case-123")                 # new process, same file
    assert again.sdk_session_id == "sdk-1" and len(again.turns) == 1
    d = again.digest()
    assert "Which BIA decisions cite Pereira?" in d and "ARAMBULA-BRAVO (eoir_4028)" in d


@pytest.mark.parametrize("bad", ["../etc", "a/b", "", "x" * 65, "sp ace"])
def test_session_name_rejects_path_tricks(tmp_path, bad):
    with pytest.raises(ValueError):
        SessionMemory(tmp_path, bad)
