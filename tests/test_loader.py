import json

import pytest

from lisa.common.config import load_dataset
from lisa.graph.loader import ChecksumError, load_records, verify_manifest


def test_loads_records_with_utf8(mini_data):
    recs, quarantine = load_records(mini_data, load_dataset("all"))
    assert [r.id for r in recs] == ["eoir_1", "eoir_2", "scotus_2017_17-459"]
    assert quarantine == []
    assert "§ 1182(h)" in recs[0].pages[0]["text"]
    assert "’" in recs[1].pages[0]["text"]
    assert recs[0].domain == "immigration" and recs[2].domain == "litigation"
    assert recs[0].props["court"] == "BIA"
    assert recs[2].props["court"] == "Supreme Court of the United States"
    assert recs[2].props["docket_number"] == "17-459"
    assert recs[0].citations[0] == "22 I&N\nDec. 200"
    assert "Pereira v. Sessions" in recs[0].text


def test_verify_manifest_ok(mini_data):
    verify_manifest(mini_data, ["pack_immigration/records.jsonl", "pack_litigation/records.jsonl"])


def test_verify_manifest_detects_tampering(mini_data):
    p = mini_data / "pack_immigration" / "records.jsonl"
    p.write_text(p.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(ChecksumError, match="pack_immigration/records.jsonl"):
        verify_manifest(mini_data, ["pack_immigration/records.jsonl"])


def test_verify_manifest_rejects_unlisted_file(mini_data):
    with pytest.raises(ChecksumError, match="not listed"):
        verify_manifest(mini_data, ["other/records.jsonl"])


def test_quarantines_bad_lines(mini_data):
    p = mini_data / "pack_immigration" / "records.jsonl"
    with open(p, "a", encoding="utf-8") as f:
        f.write("{not json\n")
        f.write(json.dumps({"id": "eoir_9", "title": "X", "pages": [{"page": 1, "text": "x"}]}) + "\n")
    recs, quarantine = load_records(mini_data, load_dataset("immigration"))
    assert [r.id for r in recs] == ["eoir_1", "eoir_2"]
    assert [q["reason"].split(":")[0] for q in quarantine] == ["bad json", "missing"]
    assert quarantine[1]["id"] == "eoir_9"
