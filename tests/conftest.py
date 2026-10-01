import hashlib
import json
from pathlib import Path

import pytest

from lisa.common.config import load_dataset
from lisa.graph.extract_det import build_graph
from lisa.graph.loader import load_records

IMM = [
    {"id": "eoir_1", "title": "ALPHA", "citation": "22 I&N Dec. 100", "issuing_body": "BIA",
     "decision_date": "1998-01-01",
     "pages": [
         {"page": 1, "text": "In re ALPHA. We follow Matter of Beta, 22 I&N\nDec. 200 (BIA 1998). "
                             "See section 212(h) of the Act and 8 U.S.C. § 1182(h)."},
         {"page": 2, "text": "Under Pereira v. Sessions, 585 U. S. 198 (2018), the notice was defective. "
                             "8 C.F.R. § 1003.1(b)."}],
     "citations_detected": ["22 I&N\nDec. 200", "22 I&N Dec. 200", "19 I&N Dec. 546", "8 C.F.R. 1003.1"]},
    {"id": "eoir_2", "title": "BETA", "citation": "22 I&N Dec. 200", "issuing_body": "BIA",
     "pages": [{"page": 1, "text": "In re BETA. The respondent’s appeal is dismissed."}],
     "citations_detected": []},
]
LIT = [
    {"id": "scotus_2017_17-459", "title": "Pereira v. Sessions", "citation": "585 U.S. 198",
     "court": "Supreme Court of the United States", "docket_number": "17-459", "term": 2017,
     "pages": [{"page": 1, "text": "OCTOBER TERM, 2017 Syllabus PEREIRA v. SESSIONS. "
                                   "Jurisdiction under 28 U. S. C. § 1253; see INA § 239."}],
     "citations_detected": ["28 U. S. C. § 1253", "384 U. S. 73"]},
]
REPORT = {
    "immigration_internal_edges_list": [{"from": "eoir_1", "to": "eoir_2"}],
    "litigation_internal_edges_list": [],
    "cross_domain_edges_list": [
        {"from": "eoir_1", "to": "scotus_2017_17-459", "basis": "name"},
        {"from": "eoir_1", "to": "scotus_2017_17-459", "basis": "reporter"},
    ],
}


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


@pytest.fixture
def mini_data(tmp_path) -> Path:
    d = tmp_path / "data"
    write_jsonl(d / "pack_immigration" / "records.jsonl", IMM)
    write_jsonl(d / "pack_litigation" / "records.jsonl", LIT)
    files = []
    for rel in ("pack_immigration/records.jsonl", "pack_litigation/records.jsonl"):
        b = (d / rel).read_bytes()
        files.append({"path": rel, "bytes": len(b), "sha256": hashlib.sha256(b).hexdigest()})
    (d / "manifest.json").write_text(json.dumps({"files": files}), encoding="utf-8")
    (d / "selection_report.json").write_text(json.dumps(REPORT), encoding="utf-8")
    return d


def build_json(data_dir: Path, name: str) -> dict:
    ds = load_dataset(name)
    recs, _ = load_records(data_dir, ds)
    return build_graph(recs, ds).to_json()


@pytest.fixture
def graph_all(mini_data) -> dict:
    return build_json(mini_data, "all")


@pytest.fixture
def graph_imm(mini_data) -> dict:
    return build_json(mini_data, "immigration")


def edges_of(graph: dict, etype: str) -> dict:
    return {(e["source"], e["target"]): e for e in graph["edges"] if e["type"] == etype}


def nodes_of(graph: dict, label: str) -> dict:
    return {n["id"]: n for n in graph["nodes"] if n["label"] == label}
