import pytest

from lisa.graph.canon import canon, squash


@pytest.mark.parametrize("raw,cid,kind,display", [
    ("22 I&N Dec. 1415", "in_dec:22_1415", "case", "22 I&N Dec. 1415"),
    ("15 I&N Dec.\n775", "in_dec:15_775", "case", "15 I&N Dec. 775"),
    ("384 U. S. 73", "us:384_73", "case", "384 U.S. 73"),
    ("149 U. S. \n698", "us:149_698", "case", "149 U.S. 698"),
    ("585 U.S. 198", "us:585_198", "case", "585 U.S. 198"),
    ("18\nU.S.C. § 5032", "usc:18_5032", "statute", "18 U.S.C. § 5032"),
    ("28 U. S. C. § 1253", "usc:28_1253", "statute", "28 U.S.C. § 1253"),
    ("8 U.S.C. 1229b(b)(1)", "usc:8_1229b", "statute", "8 U.S.C. § 1229b"),
    ("8 C.F.R. 208.14(b)", "cfr:8_208", "regulation", "8 C.F.R. Part 208"),
    ("8 C.F.R. § 1003.1", "cfr:8_1003", "regulation", "8 C.F.R. Part 1003"),
    ("721 F.3d 1064", "f3d:721_1064", "case", "721 F.3d 1064"),
    ("100 \nF. 3d 418", "f3d:100_418", "case", "100 F. 3d 418"),
    ("138 S. Ct. 2105", "sct:138_2105", "case", "138 S. Ct. 2105"),
    ("Matter of Something", "other:matter_of_something", "other", "Matter of Something"),
])
def test_canon(raw, cid, kind, display):
    c = canon(raw)
    assert (c.id, c.kind, c.display) == (cid, kind, display)


def test_squash_collapses_all_whitespace():
    assert squash("  18\n U.S.C.\t§  5032 ") == "18 U.S.C. § 5032"
