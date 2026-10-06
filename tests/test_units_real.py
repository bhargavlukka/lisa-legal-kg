import re

from lisa.common.config import load_dataset
from lisa.extract.units import build_units
from lisa.graph.loader import load_records

# Built by an older reference segment.py: identical page text, different PART markers / header hints.
MARKER_VARIANTS = {"eoir_3371__u1of1", "eoir_3458__u1of1", "eoir_4104__u1of1",
                   "scotus_2018_16-1498__u1of2", "scotus_2018_16-1498__u2of2",
                   "scotus_2025_25-197__u1of2", "scotus_2025_25-197__u2of2"}


def _page_text(t: str) -> str:
    return re.sub(r"\n<<<PART BEGINS:[^\n]*>>>\n", "", t[t.index("\n===== [[PAGE"):])


def test_units_reproduce_pilot_units(real_data_dir):
    recs, _ = load_records(real_data_dir, load_dataset("gold_eval"))
    built = {u.unit_id: u.text for r in recs for u in build_units(r)}
    pilot = {p.stem: p.read_text(encoding="utf-8") for p in (real_data_dir / "pilot_units").glob("*.txt")}
    assert set(built) == set(pilot) and len(pilot) == 25
    for uid, text in pilot.items():
        if uid in MARKER_VARIANTS:
            assert _page_text(built[uid]) == _page_text(text), uid
        else:
            assert built[uid] == text, uid
