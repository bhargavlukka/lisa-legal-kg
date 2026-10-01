# Phase 1 — Graph Foundation Implementation Plan

> Execute task by task; steps use checkboxes for tracking.

**Goal:** One config-driven Python codebase that turns the LISA case packs into a deterministic knowledge graph (JSON + Neo4j) with provenance, confidence and page-anchored evidence on every node and edge.

**Architecture:** `loader` (checksum-verified JSONL → `Record`s) → `extract_det` + `statutes` + `crossdomain` (pure Python, builds a `Graph`) → `out/graph_<dataset>.json` → `check` (vs `selection_report.json`) and `neo4j_load` (idempotent MERGE). Everything domain-specific lives in `config/domains/*.yaml` and `config/datasets/*.yaml`.

**Tech Stack:** Python 3.13 (`py -3`), PyYAML, python-dotenv, neo4j Python driver 5.x, pytest, Neo4j 5 Community (Docker).

**Spec:** `docs/design/phase1-graph-foundation.md`

## Global Constraints

- Python ≥ 3.10; venv at `.venv`; run tools as `.venv/Scripts/python -m ...` (Windows, Git Bash).
- Every file open/read/write uses `encoding="utf-8"` (Windows default is cp1252; the corpora contain `§`, `’`).
- No raw corpora and no secrets in git. Data is read from `LISA_DATA_DIR`; secrets only from env / `.env` (gitignored).
- Commits are authored by the repo owner only; no co-author or tool attribution trailers.
- Every `Case` has `legal_status = "not verified"`.
- Every node/edge: `provenance` ∈ {`deterministic`, `llm`, `unverified`}, `confidence` float 0–1, `evidence` = list of `{page, quote}` (quote copied verbatim from stored page text, or `null` for metadata), `extractor` string.
- Edge without any located evidence → `provenance="unverified"`, `confidence=0.5`.
- Confidence: detected citation 1.0, reporter match 1.0, name match 0.9, statute 1.0.
- Switching or adding a domain = YAML only; no code changes.

## Review Focus

1. **Windows encoding** — a record containing `§`/`’` must load intact, not mojibake → test in Task 4 (`test_loads_records_with_utf8`).
2. **Same citation printed two ways** (`"22 I&N\nDec. 200"` and `"22 I&N Dec. 200"`) must yield one edge with one evidence item → Task 5 (`test_internal_cite_dedups_whitespace_variants_and_has_verbatim_quote`).
3. **Digit-boundary false matches** (`15 I&N Dec. 775` inside `115 I&N Dec. 7750`) must not count as evidence → Task 5 (`test_find_evidence_respects_digit_boundaries`).
4. **Rebuild twice** must give identical JSON and no duplicate Neo4j nodes → Task 5 (`test_output_is_deterministic`), Task 8 (`test_load_is_idempotent`).
5. **Missing/wrong `LISA_DATA_DIR` or Neo4j down** must give a clear one-line error, not a traceback, and still write the JSON → Task 1 (`test_settings_*`), Task 7 (`test_cli_*`).

---

## File Structure

| File | Responsibility |
|---|---|
| `pyproject.toml` | package `lisa` (src layout), deps |
| `.env.example`, `.gitignore`, `docker-compose.yml` | env template, ignores, Neo4j service |
| `config/settings.yaml` | out_dir, default Neo4j URI |
| `config/domains/{immigration,litigation}.yaml` | field mapping, extra props, statute patterns per domain |
| `config/datasets/{immigration,litigation,all,gold_eval}.yaml` | which files, which domains, cross-domain rules |
| `src/lisa/common/config.py` | `Settings`, `Source`, `DatasetConfig`, `load_settings`, `load_dataset` |
| `src/lisa/graph/canon.py` | `squash`, `Canon`, `canon()` citation normalizer |
| `src/lisa/graph/statutes.py` | `Mention`, `INA_TO_USC`, `extract_mentions()` |
| `src/lisa/graph/loader.py` | `Record`, `ChecksumError`, `verify_manifest`, `load_records` |
| `src/lisa/graph/evidence.py` | `cite_pattern`, `find_evidence` |
| `src/lisa/graph/extract_det.py` | `Graph`, `build_graph`, `EXTRACTOR` |
| `src/lisa/graph/crossdomain.py` | `Match`, `CONFIDENCE`, `find_matches` |
| `src/lisa/graph/check.py` | `CheckResult`, `check` |
| `src/lisa/graph/cli.py` + `scripts/build_graph.py` | the one build command |
| `src/lisa/graph/neo4j_load.py` | `Neo4jUnavailable`, `load` |
| `tests/conftest.py` | mini dataset fixtures |

---

### Task 1: Scaffold, environment, config loader

**Files:**
- Create: `pyproject.toml`, `.env.example`, `config/settings.yaml`, `config/domains/immigration.yaml`, `config/domains/litigation.yaml`, `config/datasets/immigration.yaml`, `config/datasets/litigation.yaml`, `config/datasets/all.yaml`, `config/datasets/gold_eval.yaml`, `src/lisa/__init__.py`, `src/lisa/common/__init__.py`, `src/lisa/common/config.py`, `src/lisa/graph/__init__.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `Source(path: str, domain: str, fields: dict[str,str], extra: list[str], statute_patterns: list[str])`, `DatasetConfig(name: str, sources: list[Source], cross_domain: list[tuple[str,str]])`, `Settings(data_dir: Path, out_dir: Path, neo4j_uri: str, neo4j_user: str, neo4j_password: str|None)`, `load_settings(config_dir=CONFIG_DIR, env_file=REPO_ROOT/".env") -> Settings`, `load_dataset(name, config_dir=CONFIG_DIR) -> DatasetConfig`, constants `REPO_ROOT`, `CONFIG_DIR`.

- [ ] **Step 1: Create packaging and env files**

`pyproject.toml`:
```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "lisa"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = ["pyyaml>=6", "python-dotenv>=1.0", "neo4j>=5.20"]

[project.optional-dependencies]
dev = ["pytest>=8"]

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

`.env.example`:
```
# Absolute path to LISA_Project_Package/data (never committed)
LISA_DATA_DIR=C:/Users/you/Desktop/Adway Con/Final_Project (1)/LISA_Project_Package/data
# Optional: override output dir (default ./out)
# LISA_OUT_DIR=
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
# min 8 chars (Neo4j requirement)
NEO4J_PASSWORD=change-me-please
```

Empty files: `src/lisa/__init__.py`, `src/lisa/common/__init__.py`, `src/lisa/graph/__init__.py`.

- [ ] **Step 2: Create config YAML**

`config/settings.yaml`:
```yaml
out_dir: out
neo4j_uri: bolt://localhost:7687
```

`config/domains/immigration.yaml`:
```yaml
domain: immigration
fields:
  id: id
  title: title
  citation: citation
  decision_date: decision_date
  decision_year: decision_year
  court: issuing_body
  source_url: source_url
  sha256: sha256
  page_count: page_count
extra: [volume, jurisdiction, document_type, precedent_status_at_publication, current_legal_status, index_label]
statute_patterns: [usc, cfr, ina_symbol, ina_section]
```

`config/domains/litigation.yaml`:
```yaml
domain: litigation
fields:
  id: id
  title: title
  citation: citation
  decision_date: decision_date
  decision_year: decision_year
  court: court
  source_url: source_url
  sha256: sha256
  page_count: page_count
extra: [docket_number, term, jurisdiction, document_type, current_legal_status, publisher_description,
        reporter_page_start, reporter_page_end, source_pdf_page_start, source_pdf_page_end]
statute_patterns: [usc, cfr, ina_symbol]
```

`config/datasets/immigration.yaml`:
```yaml
name: immigration
sources:
  - {path: pack_immigration/records.jsonl, domain: immigration}
cross_domain: []
```

`config/datasets/litigation.yaml`:
```yaml
name: litigation
sources:
  - {path: pack_litigation/records.jsonl, domain: litigation}
cross_domain: []
```

`config/datasets/all.yaml`:
```yaml
name: all
sources:
  - {path: pack_immigration/records.jsonl, domain: immigration}
  - {path: pack_litigation/records.jsonl, domain: litigation}
cross_domain:
  - {from_domain: immigration, to_domain: litigation}
```

`config/datasets/gold_eval.yaml`:
```yaml
name: gold_eval
sources:
  - {path: gold_cases/records_immigration.jsonl, domain: immigration}
  - {path: gold_cases/records_litigation.jsonl, domain: litigation}
cross_domain: []
```

- [ ] **Step 3: Create venv and install**

Run:
```bash
py -3 -m venv .venv && .venv/Scripts/python -m pip install -q -U pip && .venv/Scripts/python -m pip install -q -e ".[dev]"
```
Expected: exits 0.

- [ ] **Step 4: Write the failing tests** — `tests/test_config.py`
```python
import pytest

from lisa.common.config import load_dataset, load_settings


def test_load_dataset_all_has_both_sources_and_cross_rule():
    ds = load_dataset("all")
    assert ds.name == "all"
    assert [s.domain for s in ds.sources] == ["immigration", "litigation"]
    assert ds.cross_domain == [("immigration", "litigation")]
    assert ds.sources[0].fields["court"] == "issuing_body"
    assert ds.sources[1].fields["court"] == "court"
    assert "ina_section" in ds.sources[0].statute_patterns
    assert "ina_section" not in ds.sources[1].statute_patterns


def test_new_domain_needs_only_yaml(tmp_path):
    (tmp_path / "domains").mkdir()
    (tmp_path / "datasets").mkdir()
    (tmp_path / "domains" / "tax.yaml").write_text(
        "domain: tax\nfields: {id: case_no, title: name, citation: cite}\nstatute_patterns: [usc]\n",
        encoding="utf-8")
    (tmp_path / "datasets" / "tax.yaml").write_text(
        "name: tax\nsources:\n  - {path: tax.jsonl, domain: tax}\n", encoding="utf-8")
    ds = load_dataset("tax", config_dir=tmp_path)
    assert ds.sources[0].fields["id"] == "case_no"
    assert ds.sources[0].extra == []
    assert ds.cross_domain == []


def test_settings_requires_data_dir(monkeypatch):
    monkeypatch.delenv("LISA_DATA_DIR", raising=False)
    with pytest.raises(RuntimeError, match="LISA_DATA_DIR"):
        load_settings(env_file=None)


def test_settings_rejects_missing_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("LISA_DATA_DIR", str(tmp_path / "nope"))
    with pytest.raises(RuntimeError, match="does not exist"):
        load_settings(env_file=None)


def test_settings_out_dir_override(monkeypatch, tmp_path):
    monkeypatch.setenv("LISA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LISA_OUT_DIR", str(tmp_path / "o"))
    s = load_settings(env_file=None)
    assert s.data_dir == tmp_path and s.out_dir == tmp_path / "o"
```

- [ ] **Step 5: Run to verify failure**

Run: `.venv/Scripts/python -m pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lisa.common.config'`.

- [ ] **Step 6: Implement** — `src/lisa/common/config.py`
```python
"""Config loader. Everything domain-specific comes from YAML; secrets come from the environment."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIG_DIR = REPO_ROOT / "config"


@dataclass(frozen=True)
class Source:
    path: str
    domain: str
    fields: dict[str, str]
    extra: list[str] = field(default_factory=list)
    statute_patterns: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DatasetConfig:
    name: str
    sources: list[Source]
    cross_domain: list[tuple[str, str]]


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    out_dir: Path
    neo4j_uri: str
    neo4j_user: str
    neo4j_password: str | None


def _yaml(path: Path) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}


def load_settings(config_dir: Path = CONFIG_DIR, env_file: Path | None = REPO_ROOT / ".env") -> Settings:
    if env_file is not None:
        load_dotenv(env_file)
    s = _yaml(config_dir / "settings.yaml")
    raw = os.environ.get("LISA_DATA_DIR")
    if not raw:
        raise RuntimeError("LISA_DATA_DIR is not set (copy .env.example to .env)")
    data_dir = Path(raw)
    if not data_dir.is_dir():
        raise RuntimeError(f"LISA_DATA_DIR does not exist: {data_dir}")
    out_dir = Path(os.environ.get("LISA_OUT_DIR") or REPO_ROOT / s.get("out_dir", "out"))
    return Settings(
        data_dir=data_dir,
        out_dir=out_dir,
        neo4j_uri=os.environ.get("NEO4J_URI") or s.get("neo4j_uri", "bolt://localhost:7687"),
        neo4j_user=os.environ.get("NEO4J_USER", "neo4j"),
        neo4j_password=os.environ.get("NEO4J_PASSWORD"),
    )


def load_dataset(name: str, config_dir: Path = CONFIG_DIR) -> DatasetConfig:
    d = _yaml(config_dir / "datasets" / f"{name}.yaml")
    sources = []
    for s in d["sources"]:
        dom = _yaml(config_dir / "domains" / f"{s['domain']}.yaml")
        sources.append(Source(
            path=s["path"],
            domain=s["domain"],
            fields=dict(dom["fields"]),
            extra=list(dom.get("extra") or []),
            statute_patterns=list(dom.get("statute_patterns") or []),
        ))
    cross = [(c["from_domain"], c["to_domain"]) for c in d.get("cross_domain") or []]
    return DatasetConfig(name=d["name"], sources=sources, cross_domain=cross)
```

- [ ] **Step 7: Run to verify pass**

Run: `.venv/Scripts/python -m pytest tests/test_config.py -v`
Expected: 5 passed.

- [ ] **Step 8: Commit**
```bash
git add pyproject.toml .env.example config src tests
git commit -m "feat: project scaffold and YAML-driven config loader"
```

---

### Task 2: Citation normalizer (`canon`)

**Files:**
- Create: `src/lisa/graph/canon.py`
- Test: `tests/test_canon.py`

**Interfaces:**
- Produces: `squash(s: str) -> str`; `Canon(id: str, kind: str, display: str)` (frozen dataclass; kind ∈ case/statute/regulation/other); `canon(cite: str) -> Canon`.
- Id formats: `in_dec:<vol>_<page>`, `us:<vol>_<page>`, `usc:<title>_<section lowercase>`, `cfr:<title>_<part>`, `<reporter slug>:<vol>_<page>` (e.g. `f3d:721_1064`), `other:<slug>`.

- [ ] **Step 1: Write the failing tests** — `tests/test_canon.py`
```python
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
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python -m pytest tests/test_canon.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lisa.graph.canon'`.

- [ ] **Step 3: Implement** — `src/lisa/graph/canon.py`
```python
"""Canonical citation ids: the same real-world authority gets the same id regardless of typography."""
from __future__ import annotations

import re
from dataclasses import dataclass

_FED = r"F\.\s?(?:2d|3d|4th)|F\.\s?Supp\.(?:\s?[23]d)?|S\.\s?Ct\.|L\.\s?Ed\.(?:\s?2d)?|Fed\.\s?Appx\."


@dataclass(frozen=True)
class Canon:
    id: str
    kind: str      # case | statute | regulation | other
    display: str


def squash(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def canon(cite: str) -> Canon:
    c = squash(cite)
    if m := re.search(r"(\d+)\s*I&N\s*Dec\.?\s*(\d+)", c):
        return Canon(f"in_dec:{m[1]}_{m[2]}", "case", f"{m[1]} I&N Dec. {m[2]}")
    if m := re.search(r"(\d+)\s*U\.\s*S\.\s*C\.\s*(?:A\.\s*)?§*\s*(\d+[a-z]?)", c):
        return Canon(f"usc:{m[1]}_{m[2].lower()}", "statute", f"{m[1]} U.S.C. § {m[2]}")
    if m := re.search(r"(\d+)\s*C\.\s*F\.\s*R\.\s*§*\s*(\d+)", c):
        return Canon(f"cfr:{m[1]}_{m[2]}", "regulation", f"{m[1]} C.F.R. Part {m[2]}")
    if m := re.search(r"(\d+)\s*U\.\s*S\.\s*(\d+)", c):
        return Canon(f"us:{m[1]}_{m[2]}", "case", f"{m[1]} U.S. {m[2]}")
    if m := re.search(rf"(\d+)\s+({_FED})\s*(\d+)", c):
        rep = re.sub(r"[^a-z0-9]+", "", m[2].lower())
        return Canon(f"{rep}:{m[1]}_{m[3]}", "case", f"{m[1]} {squash(m[2])} {m[3]}")
    slug = re.sub(r"[^a-z0-9]+", "_", c.lower()).strip("_")[:60]
    return Canon(f"other:{slug}", "other", c)
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python -m pytest tests/test_canon.py -v`
Expected: 15 passed.

- [ ] **Step 5: Commit**
```bash
git add src/lisa/graph/canon.py tests/test_canon.py
git commit -m "feat: canonical citation normalizer"
```

---

### Task 3: Statute and regulation mentions

**Files:**
- Create: `src/lisa/graph/statutes.py`
- Test: `tests/test_statutes.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (pages are plain dicts `{"page": int, "text": str}`).
- Produces: `Mention(canon_id: str, kind: str, display: str, page: int, quote: str)`; `INA_TO_USC: dict[str,str]`; `extract_mentions(pages: list[dict], patterns: list[str], ctx: int = 60) -> list[Mention]` (pattern names: `usc`, `cfr`, `ina_symbol`, `ina_section`; unknown name → `ValueError`).

- [ ] **Step 1: Write the failing tests** — `tests/test_statutes.py`
```python
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
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python -m pytest tests/test_statutes.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lisa.graph.statutes'`.

- [ ] **Step 3: Implement** — `src/lisa/graph/statutes.py`
```python
"""Statute / regulation mentions in page text, each with page number and verbatim quote."""
from __future__ import annotations

import re
from dataclasses import dataclass

# INA section -> 8 U.S.C. section (most-cited sections in the immigration corpus)
INA_TO_USC = {
    "101": "1101", "208": "1158", "212": "1182", "235": "1225", "237": "1227",
    "239": "1229", "240": "1229a", "240A": "1229b", "240B": "1229c", "241": "1231",
}

_PATTERNS = {
    "usc": re.compile(r"(?<!\d)(\d+)\s*U\.\s*S\.\s*C\.\s*(?:A\.\s*)?§*\s*(\d+[a-z]?)"),
    "cfr": re.compile(r"(?<!\d)(\d+)\s*C\.\s*F\.\s*R\.\s*(?:§+\s*)?(\d+)(?:\.\d+)?"),
    "ina_symbol": re.compile(r"\bINA\s*§+\s*(\d+[A-Z]?)"),
    "ina_section": re.compile(
        r"\bsection\s+(\d+[A-Z]?)(?:\([0-9a-zA-Z]+\))*\s+of\s+the\s+(?:Immigration\s+and\s+Nationality\s+)?Act\b",
        re.IGNORECASE),
}


@dataclass(frozen=True)
class Mention:
    canon_id: str
    kind: str      # statute | regulation
    display: str
    page: int
    quote: str


def _ina(section: str) -> tuple[str, str, str]:
    sec = section.upper()
    usc = INA_TO_USC.get(sec)
    if usc:
        return f"usc:8_{usc.lower()}", "statute", f"8 U.S.C. § {usc}"
    return f"ina:{sec}", "statute", f"INA § {sec}"


def _resolve(name: str, m: re.Match) -> tuple[str, str, str]:
    if name == "usc":
        return f"usc:{m[1]}_{m[2].lower()}", "statute", f"{m[1]} U.S.C. § {m[2]}"
    if name == "cfr":
        return f"cfr:{m[1]}_{m[2]}", "regulation", f"{m[1]} C.F.R. Part {m[2]}"
    return _ina(m[1])


def extract_mentions(pages: list[dict], patterns: list[str], ctx: int = 60) -> list[Mention]:
    unknown = [p for p in patterns if p not in _PATTERNS]
    if unknown:
        raise ValueError(f"unknown statute pattern(s): {unknown}")
    out: list[Mention] = []
    for p in pages:
        text = p["text"]
        for name in patterns:
            for m in _PATTERNS[name].finditer(text):
                cid, kind, display = _resolve(name, m)
                quote = text[max(0, m.start() - ctx): m.end() + ctx]
                out.append(Mention(cid, kind, display, p["page"], quote))
    return out
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python -m pytest tests/test_statutes.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**
```bash
git add src/lisa/graph/statutes.py tests/test_statutes.py
git commit -m "feat: statute and regulation mention extraction with INA crosswalk"
```

---

### Task 4: Record loader with manifest verification

**Files:**
- Create: `src/lisa/graph/loader.py`, `tests/conftest.py`
- Test: `tests/test_loader.py`

**Interfaces:**
- Consumes: `DatasetConfig`, `Source` (Task 1).
- Produces: `Record(id, domain, title, citation, props: dict, pages: list[dict], text: str, citations: list[str])`; `ChecksumError(RuntimeError)`; `verify_manifest(data_dir: Path, rel_paths: list[str]) -> None`; `load_records(data_dir: Path, ds: DatasetConfig) -> tuple[list[Record], list[dict]]` (second item = quarantine entries `{source, line, id?, reason}`).
- Test fixture `mini_data` (in `tests/conftest.py`) → `Path` of a data dir laid out like the real pack: `pack_immigration/records.jsonl`, `pack_litigation/records.jsonl`, `manifest.json`, `selection_report.json`. Module-level constants `IMM`, `LIT`, `REPORT` are importable from `conftest`.

- [ ] **Step 1: Create the mini dataset fixture** — `tests/conftest.py`
```python
import hashlib
import json
from pathlib import Path

import pytest

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
```

- [ ] **Step 2: Write the failing tests** — `tests/test_loader.py`
```python
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
```

- [ ] **Step 3: Run to verify failure**

Run: `.venv/Scripts/python -m pytest tests/test_loader.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lisa.graph.loader'`.

- [ ] **Step 4: Implement** — `src/lisa/graph/loader.py`
```python
"""Read dataset JSONL files into Records, after verifying SHA-256 against manifest.json."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from lisa.common.config import DatasetConfig

REQUIRED = ("id", "title", "citation")


class ChecksumError(RuntimeError):
    pass


@dataclass
class Record:
    id: str
    domain: str
    title: str
    citation: str
    props: dict
    pages: list[dict]
    text: str
    citations: list[str]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_manifest(data_dir: Path, rel_paths: list[str]) -> None:
    manifest = json.loads((data_dir / "manifest.json").read_text(encoding="utf-8"))
    expected = {f["path"]: f["sha256"] for f in manifest["files"]}
    for rel in rel_paths:
        if rel not in expected:
            raise ChecksumError(f"{rel}: not listed in manifest.json")
        actual = _sha256(data_dir / rel)
        if actual != expected[rel]:
            raise ChecksumError(f"{rel}: sha256 mismatch (manifest {expected[rel][:12]}, file {actual[:12]})")


def load_records(data_dir: Path, ds: DatasetConfig) -> tuple[list[Record], list[dict]]:
    records: list[Record] = []
    quarantine: list[dict] = []
    for src in ds.sources:
        with open(data_dir / src.path, encoding="utf-8") as f:
            for lineno, line in enumerate(f, 1):
                if not line.strip():
                    continue
                try:
                    raw = json.loads(line)
                except json.JSONDecodeError as e:
                    quarantine.append({"source": src.path, "line": lineno, "reason": f"bad json: {e}"})
                    continue
                missing = [k for k in REQUIRED if not raw.get(src.fields[k])]
                pages = raw.get("pages") or []
                if not pages:
                    missing.append("pages")
                if missing:
                    quarantine.append({"source": src.path, "line": lineno, "id": raw.get(src.fields["id"]),
                                       "reason": f"missing: {missing}"})
                    continue
                props = {k: raw.get(v) for k, v in src.fields.items()}
                props.update({k: raw.get(k) for k in src.extra})
                pages = [{"page": p["page"], "text": p["text"]} for p in pages]
                records.append(Record(
                    id=raw[src.fields["id"]],
                    domain=src.domain,
                    title=raw[src.fields["title"]],
                    citation=raw[src.fields["citation"]],
                    props=props,
                    pages=pages,
                    text=raw.get("text") or "\n".join(p["text"] for p in pages),
                    citations=list(raw.get("citations_detected") or []),
                ))
    return records, quarantine
```

- [ ] **Step 5: Run to verify pass**

Run: `.venv/Scripts/python -m pytest tests/test_loader.py -v`
Expected: 5 passed.

- [ ] **Step 6: Commit**
```bash
git add src/lisa/graph/loader.py tests/conftest.py tests/test_loader.py
git commit -m "feat: checksum-verified JSONL record loader with quarantine"
```

---

### Task 5: Deterministic extraction (cases, pages, citations, authorities, statutes)

**Files:**
- Create: `src/lisa/graph/evidence.py`, `src/lisa/graph/extract_det.py`
- Modify: `tests/conftest.py` (append `graph_all` / `graph_imm` fixtures)
- Test: `tests/test_extract_det.py`

**Interfaces:**
- Consumes: `canon`, `squash` (Task 2), `extract_mentions` (Task 3), `Record`, `load_records` (Task 4), `DatasetConfig` (Task 1).
- Produces:
  - `evidence.cite_pattern(cite: str) -> re.Pattern`, `evidence.find_evidence(pages: list[dict], pattern: re.Pattern, ctx: int = 60) -> dict | None` (`{"page", "quote"}`).
  - `extract_det.EXTRACTOR = "lisa.graph.extract_det/1"`, `extract_det.Graph(dataset)` with `add_node(node_id, label, props, evidence=None, provenance="deterministic", confidence=1.0) -> dict`, `add_edge(etype, source, target, *, basis=None, confidence=1.0, evidence=None, props=None) -> dict`, `to_json() -> dict`.
  - `extract_det.build_graph(records: list[Record], ds: DatasetConfig) -> Graph`.
  - Graph JSON shape: `{"dataset", "extractor", "nodes": [{"id","label","props","provenance","confidence","evidence","extractor"}], "edges": [{"type","source","target","source_label","target_label","props","provenance","confidence","evidence","extractor"}]}`, nodes sorted by id, edges sorted by (type, source, target).
  - Node ids: Case = record id; Page = `<case_id>#p<n>`; Authority = `auth:<canon id>`; Statute/Regulation = canon id (`usc:8_1182`, `cfr:8_1003`, `ina:245`).

- [ ] **Step 1: Append fixtures to `tests/conftest.py`**
```python
from lisa.common.config import load_dataset
from lisa.graph.extract_det import build_graph
from lisa.graph.loader import load_records


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
```
(Put the three `from lisa...` imports at the top of the file with the other imports.)

- [ ] **Step 2: Write the failing tests** — `tests/test_extract_det.py`
```python
import json

from conftest import IMM, build_json, edges_of, nodes_of
from lisa.graph.evidence import cite_pattern, find_evidence


def test_case_nodes_carry_metadata_and_unverified_status(graph_all):
    cases = nodes_of(graph_all, "Case")
    assert set(cases) == {"eoir_1", "eoir_2", "scotus_2017_17-459"}
    c = cases["eoir_1"]
    assert c["props"]["canon_cite"] == "in_dec:22_100"
    assert c["props"]["legal_status"] == "not verified"
    assert c["props"]["domain"] == "immigration"
    assert c["props"]["dataset"] == "all"
    assert c["provenance"] == "deterministic" and c["confidence"] == 1.0
    assert c["extractor"] == "lisa.graph.extract_det/1"


def test_pages_are_nodes(graph_all):
    assert set(nodes_of(graph_all, "Page")) == {"eoir_1#p1", "eoir_1#p2", "eoir_2#p1", "scotus_2017_17-459#p1"}
    assert ("eoir_1", "eoir_1#p2") in edges_of(graph_all, "HAS_PAGE")


def test_internal_cite_dedups_whitespace_variants_and_has_verbatim_quote(graph_all):
    e = edges_of(graph_all, "CITES")[("eoir_1", "eoir_2")]
    assert e["props"] == {"scope": "internal", "bases": ["detected_citation"]}
    assert e["provenance"] == "deterministic" and e["confidence"] == 1.0
    assert len(e["evidence"]) == 1
    ev = e["evidence"][0]
    assert ev["page"] == 1
    assert "22 I&N\nDec. 200" in ev["quote"]
    assert ev["quote"] in IMM[0]["pages"][0]["text"]


def test_out_of_corpus_citation_becomes_unverified_authority(graph_all):
    a = nodes_of(graph_all, "Authority")["auth:in_dec:19_546"]
    assert a["props"]["in_corpus"] is False and a["props"]["resolved"] is False
    assert a["props"]["display"] == "19 I&N Dec. 546"
    e = edges_of(graph_all, "CITES")[("eoir_1", "auth:in_dec:19_546")]
    assert e["props"]["scope"] == "external"
    assert e["provenance"] == "unverified" and e["confidence"] == 0.5 and e["evidence"] == []


def test_statute_and_regulation_mentions(graph_all):
    m = edges_of(graph_all, "MENTIONS_STATUTE")
    assert m[("eoir_1", "usc:8_1182")]["props"]["count"] == 2
    assert ("eoir_1", "cfr:8_1003") in m
    assert ("scotus_2017_17-459", "usc:28_1253") in m
    assert ("scotus_2017_17-459", "usc:8_1229") in m
    assert nodes_of(graph_all, "Regulation")["cfr:8_1003"]["props"]["display"] == "8 C.F.R. Part 1003"
    assert m[("eoir_1", "cfr:8_1003")]["evidence"][0]["page"] == 2


def test_statute_citations_are_not_cites_edges(graph_all):
    targets = [t for (_, t) in edges_of(graph_all, "CITES")]
    assert not any(t.startswith(("auth:usc", "auth:cfr")) for t in targets)


def test_edges_know_endpoint_labels(graph_all):
    e = edges_of(graph_all, "CITES")[("eoir_1", "auth:in_dec:19_546")]
    assert (e["source_label"], e["target_label"]) == ("Case", "Authority")


def test_output_is_deterministic(mini_data):
    assert json.dumps(build_json(mini_data, "all")) == json.dumps(build_json(mini_data, "all"))


def test_find_evidence_respects_digit_boundaries():
    pages = [{"page": 1, "text": "see 115 I&N Dec. 7750 and later"},
             {"page": 2, "text": "and 15 I&N\nDec. 775 here"}]
    ev = find_evidence(pages, cite_pattern("15 I&N Dec. 775"))
    assert ev["page"] == 2
    assert "15 I&N\nDec. 775" in ev["quote"]
```

- [ ] **Step 3: Run to verify failure**

Run: `.venv/Scripts/python -m pytest tests/test_extract_det.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lisa.graph.extract_det'` (raised from conftest import).

- [ ] **Step 4: Implement** — `src/lisa/graph/evidence.py`
```python
"""Locate a match in page text and return a verbatim, page-anchored quote."""
from __future__ import annotations

import re

from lisa.graph.canon import squash


def cite_pattern(cite: str) -> re.Pattern:
    """Whitespace-insensitive pattern for a citation string, bounded so 15 never matches inside 115."""
    chars = [ch for ch in squash(cite) if not ch.isspace()]
    return re.compile(r"(?<!\d)" + r"\s*".join(re.escape(ch) for ch in chars) + r"(?!\d)")


def find_evidence(pages: list[dict], pattern: re.Pattern, ctx: int = 60) -> dict | None:
    for p in pages:
        text = p["text"]
        m = pattern.search(text)
        if m:
            return {"page": p["page"], "quote": text[max(0, m.start() - ctx): m.end() + ctx]}
    return None
```

- [ ] **Step 5: Implement** — `src/lisa/graph/extract_det.py`
```python
"""Deterministic extraction tier: case metadata, detected citations, statute mentions. No LLM."""
from __future__ import annotations

from lisa.common.config import DatasetConfig
from lisa.graph.canon import canon
from lisa.graph.evidence import cite_pattern, find_evidence
from lisa.graph.loader import Record
from lisa.graph.statutes import extract_mentions

EXTRACTOR = "lisa.graph.extract_det/1"
MAX_EVIDENCE = 3
METADATA = {"page": None, "quote": None, "basis": "record_metadata"}


class Graph:
    def __init__(self, dataset: str):
        self.dataset = dataset
        self.nodes: dict[str, dict] = {}
        self.edges: dict[tuple[str, str, str], dict] = {}

    def add_node(self, node_id, label, props, evidence=None, provenance="deterministic", confidence=1.0) -> dict:
        n = self.nodes.get(node_id)
        if n is None:
            n = {"id": node_id, "label": label, "props": props, "provenance": provenance,
                 "confidence": confidence, "evidence": list(evidence or []), "extractor": EXTRACTOR}
            self.nodes[node_id] = n
        elif evidence and n["provenance"] == "unverified":
            n.update(evidence=list(evidence), provenance=provenance, confidence=confidence)
        return n

    def add_edge(self, etype, source, target, *, basis=None, confidence=1.0, evidence=None, props=None) -> dict:
        key = (etype, source, target)
        e = self.edges.get(key)
        if e is None:
            e = {"type": etype, "source": source, "target": target, "props": {},
                 "provenance": "unverified", "confidence": 0.5, "evidence": [], "extractor": EXTRACTOR}
            self.edges[key] = e
        e["props"].update(props or {})
        if basis and basis not in e["props"].setdefault("bases", []):
            e["props"]["bases"].append(basis)
        if evidence:
            if e["provenance"] == "unverified":
                e["provenance"], e["confidence"] = "deterministic", confidence
            else:
                e["confidence"] = max(e["confidence"], confidence)
            if evidence not in e["evidence"] and len(e["evidence"]) < MAX_EVIDENCE:
                e["evidence"].append(evidence)
        return e

    def to_json(self) -> dict:
        edges = []
        for key in sorted(self.edges):
            e = dict(self.edges[key])
            e["source_label"] = self.nodes[e["source"]]["label"]
            e["target_label"] = self.nodes[e["target"]]["label"]
            edges.append(e)
        return {"dataset": self.dataset, "extractor": EXTRACTOR,
                "nodes": [self.nodes[k] for k in sorted(self.nodes)], "edges": edges}


def _add_cases_and_pages(g: Graph, records: list[Record], ds: DatasetConfig) -> None:
    for r in records:
        g.add_node(r.id, "Case", {**r.props, "canon_cite": canon(r.citation).id, "dataset": ds.name,
                                  "domain": r.domain, "legal_status": "not verified"}, evidence=[METADATA])
        for p in r.pages:
            pid = f"{r.id}#p{p['page']}"
            g.add_node(pid, "Page", {"case_id": r.id, "page_no": p["page"], "text": p["text"]}, evidence=[METADATA])
            g.add_edge("HAS_PAGE", r.id, pid, evidence={"page": p["page"], "quote": None})


def _add_citations(g: Graph, records: list[Record]) -> None:
    own = {canon(r.citation).id: r for r in records}
    for r in records:
        self_id = canon(r.citation).id
        for raw in r.citations:
            c = canon(raw)
            if c.kind != "case" or c.id == self_id:
                continue
            ev = find_evidence(r.pages, cite_pattern(raw))
            if c.id in own:
                target = own[c.id]
                tgt_id, scope = target.id, ("internal" if target.domain == r.domain else "cross_domain")
            else:
                tgt_id, scope = f"auth:{c.id}", "external"
                g.add_node(tgt_id, "Authority",
                           {"canon_id": c.id, "display": c.display, "kind": c.kind,
                            "in_corpus": False, "resolved": False},
                           evidence=[ev] if ev else [],
                           provenance="deterministic" if ev else "unverified",
                           confidence=1.0 if ev else 0.5)
            g.add_edge("CITES", r.id, tgt_id, basis="detected_citation", confidence=1.0, evidence=ev,
                       props={"scope": scope})


def _add_statutes(g: Graph, records: list[Record], ds: DatasetConfig) -> None:
    patterns = {s.domain: s.statute_patterns for s in ds.sources}
    for r in records:
        grouped: dict[str, list] = {}
        for m in extract_mentions(r.pages, patterns[r.domain]):
            grouped.setdefault(m.canon_id, []).append(m)
        for cid, ms in grouped.items():
            label = "Regulation" if ms[0].kind == "regulation" else "Statute"
            g.add_node(cid, label, {"canon_id": cid, "display": ms[0].display},
                       evidence=[{"page": ms[0].page, "quote": ms[0].quote}])
            for m in ms[:MAX_EVIDENCE]:
                g.add_edge("MENTIONS_STATUTE", r.id, cid, confidence=1.0,
                           evidence={"page": m.page, "quote": m.quote}, props={"count": len(ms)})


def build_graph(records: list[Record], ds: DatasetConfig) -> Graph:
    g = Graph(ds.name)
    _add_cases_and_pages(g, records, ds)
    _add_citations(g, records)
    _add_statutes(g, records, ds)
    return g
```

- [ ] **Step 6: Run to verify pass**

Run: `.venv/Scripts/python -m pytest -v`
Expected: all tests pass (config 5, canon 15, statutes 6, loader 5, extract 9).

- [ ] **Step 7: Commit**
```bash
git add src/lisa/graph/evidence.py src/lisa/graph/extract_det.py tests/conftest.py tests/test_extract_det.py
git commit -m "feat: deterministic extraction tier with provenance and page-anchored evidence"
```

---

### Task 6: Cross-domain edges (BIA → SCOTUS by name and reporter)

**Files:**
- Create: `src/lisa/graph/crossdomain.py`
- Modify: `src/lisa/graph/extract_det.py` (add `_add_cross_domain`, call it in `build_graph`)
- Test: `tests/test_crossdomain.py`

**Interfaces:**
- Consumes: `Record` (Task 4), `canon`, `squash` (Task 2), `find_evidence` (Task 5), `Graph` (Task 5).
- Produces: `CONFIDENCE = {"name": 0.9, "reporter": 1.0}`; `Match(source: str, target: str, basis: str, evidence: dict | None)`; `find_matches(sources: list[Record], targets: list[Record]) -> list[Match]`. A match found only in the full text (e.g. split across a page break) has `evidence=None` → edge becomes `unverified`.

- [ ] **Step 1: Write the failing tests** — `tests/test_crossdomain.py`
```python
from conftest import edges_of, nodes_of
from lisa.graph.crossdomain import find_matches
from lisa.graph.loader import Record


def rec(id_, domain, title, citation, pages):
    return Record(id=id_, domain=domain, title=title, citation=citation, props={},
                  pages=pages, text="\n".join(p["text"] for p in pages), citations=[])


PEREIRA = rec("scotus_x", "litigation", "Pereira v. Sessions", "585 U.S. 198", [{"page": 1, "text": "x"}])


def test_cross_domain_edge_has_both_bases(graph_all):
    e = edges_of(graph_all, "CITES")[("eoir_1", "scotus_2017_17-459")]
    assert e["props"]["scope"] == "cross_domain"
    assert sorted(e["props"]["bases"]) == ["name", "reporter"]
    assert e["confidence"] == 1.0 and e["provenance"] == "deterministic"
    assert e["evidence"][0]["page"] == 2


def test_name_only_match_scores_0_9_and_tolerates_line_breaks():
    src = rec("eoir_x", "immigration", "X", "1 I&N Dec. 1", [{"page": 4, "text": "as held in Pereira v.\nSessions, the"}])
    [m] = find_matches([src], [PEREIRA])
    assert (m.source, m.target, m.basis) == ("eoir_x", "scotus_x", "name")
    assert m.evidence["page"] == 4


def test_reporter_match_tolerates_spaced_us():
    src = rec("eoir_x", "immigration", "X", "1 I&N Dec. 1", [{"page": 1, "text": "see 585 U. S. 198, 201"}])
    assert [(m.basis, m.evidence["page"]) for m in find_matches([src], [PEREIRA])] == [("reporter", 1)]


def test_reporter_does_not_match_longer_page_number():
    src = rec("eoir_x", "immigration", "X", "1 I&N Dec. 1", [{"page": 1, "text": "see 585 U.S. 1980"}])
    assert find_matches([src], [PEREIRA]) == []


def test_match_split_across_pages_is_kept_without_evidence():
    src = rec("eoir_x", "immigration", "X", "1 I&N Dec. 1",
              [{"page": 1, "text": "relying on Pereira v."}, {"page": 2, "text": "Sessions, we hold"}])
    [m] = find_matches([src], [PEREIRA])
    assert m.basis == "name" and m.evidence is None


def test_immigration_only_config_builds_without_cross_edges(graph_imm):
    assert "scotus_2017_17-459" not in nodes_of(graph_imm, "Case")
    assert all(e["props"].get("scope") != "cross_domain" for e in graph_imm["edges"])
    assert ("eoir_1", "eoir_2") in edges_of(graph_imm, "CITES")
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python -m pytest tests/test_crossdomain.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lisa.graph.crossdomain'`.

- [ ] **Step 3: Implement** — `src/lisa/graph/crossdomain.py`
```python
"""Cross-domain CITES derived from full text: target case titles and U.S.-reporter citations."""
from __future__ import annotations

import re
from dataclasses import dataclass

from lisa.graph.canon import canon, squash
from lisa.graph.evidence import find_evidence
from lisa.graph.loader import Record

CONFIDENCE = {"name": 0.9, "reporter": 1.0}


@dataclass(frozen=True)
class Match:
    source: str
    target: str
    basis: str
    evidence: dict | None


def _name_pattern(title: str) -> re.Pattern:
    return re.compile(r"\s+".join(re.escape(w) for w in squash(title).split(" ")), re.IGNORECASE)


def _reporter_pattern(citation: str) -> re.Pattern | None:
    c = canon(citation)
    if not c.id.startswith("us:"):
        return None
    vol, page = c.id[3:].split("_")
    return re.compile(rf"(?<!\d){vol}\s*U\.\s*S\.\s*{page}(?!\d)")


def find_matches(sources: list[Record], targets: list[Record]) -> list[Match]:
    pats = []
    for t in targets:
        pats.append((t.id, "name", _name_pattern(t.title)))
        rp = _reporter_pattern(t.citation)
        if rp is not None:
            pats.append((t.id, "reporter", rp))
    out = []
    for s in sources:
        for tid, basis, pat in pats:
            ev = find_evidence(s.pages, pat)
            if ev is not None:
                out.append(Match(s.id, tid, basis, ev))
            elif pat.search(s.text):
                out.append(Match(s.id, tid, basis, None))
    return out
```

- [ ] **Step 4: Wire into `build_graph`** — in `src/lisa/graph/extract_det.py` add import and function, and call it:
```python
from lisa.graph import crossdomain
```
```python
def _add_cross_domain(g: Graph, records: list[Record], ds: DatasetConfig) -> None:
    for from_domain, to_domain in ds.cross_domain:
        sources = [r for r in records if r.domain == from_domain]
        targets = [r for r in records if r.domain == to_domain]
        for m in crossdomain.find_matches(sources, targets):
            g.add_edge("CITES", m.source, m.target, basis=m.basis, confidence=crossdomain.CONFIDENCE[m.basis],
                       evidence=m.evidence, props={"scope": "cross_domain"})
```
and in `build_graph`, after `_add_statutes(g, records, ds)`:
```python
    _add_cross_domain(g, records, ds)
```

- [ ] **Step 5: Run to verify pass**

Run: `.venv/Scripts/python -m pytest -v`
Expected: all pass (previous 40 + 6 new).

- [ ] **Step 6: Commit**
```bash
git add src/lisa/graph/crossdomain.py src/lisa/graph/extract_det.py tests/test_crossdomain.py
git commit -m "feat: cross-domain CITES edges by case name and U.S. reporter citation"
```

---

### Task 7: Acceptance check and the build command (real data)

**Files:**
- Create: `src/lisa/graph/check.py`, `src/lisa/graph/cli.py`, `scripts/build_graph.py`
- Test: `tests/test_check.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: everything above; `Settings.out_dir`, `Settings.data_dir`.
- Produces: `CheckResult(expected: int, missing: list[tuple], extra: list[tuple])` with `.ok`; `check(graph: dict, report: dict) -> CheckResult` (triples `(from, to, "internal" | "name" | "reporter" | "detected_citation")`; expectations whose endpoints are not both loaded are ignored); `cli.main(argv: list[str] | None = None) -> int` (exit 0 ok, 1 check failed, 2 config/checksum error, 3 Neo4j load failed). Lazy-imports `lisa.graph.neo4j_load` (Task 8) only when loading.

- [ ] **Step 1: Write the failing tests** — `tests/test_check.py`
```python
import json

from lisa.graph.check import check


def test_check_passes_on_mini(graph_all, mini_data):
    report = json.loads((mini_data / "selection_report.json").read_text(encoding="utf-8"))
    r = check(graph_all, report)
    assert r.ok and r.expected == 3 and r.missing == [] and r.extra == []


def test_check_reports_missing_edge(graph_all, mini_data):
    report = json.loads((mini_data / "selection_report.json").read_text(encoding="utf-8"))
    report["immigration_internal_edges_list"].append({"from": "eoir_2", "to": "eoir_1"})
    r = check(graph_all, report)
    assert not r.ok and r.missing == [("eoir_2", "eoir_1", "internal")]


def test_check_ignores_cases_not_loaded(graph_imm, mini_data):
    report = json.loads((mini_data / "selection_report.json").read_text(encoding="utf-8"))
    r = check(graph_imm, report)
    assert r.ok and r.expected == 1
```

`tests/test_cli.py`:
```python
import json

from lisa.graph.cli import main


def test_cli_builds_checks_and_writes_json(mini_data, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LISA_DATA_DIR", str(mini_data))
    monkeypatch.setenv("LISA_OUT_DIR", str(tmp_path / "out"))
    assert main(["--dataset", "all", "--check", "--no-load"]) == 0
    g = json.loads((tmp_path / "out" / "graph_all.json").read_text(encoding="utf-8"))
    assert len([n for n in g["nodes"] if n["label"] == "Case"]) == 3
    assert json.loads((tmp_path / "out" / "quarantine_all.json").read_text(encoding="utf-8")) == []
    assert "missing 0" in capsys.readouterr().out


def test_cli_bad_data_dir_is_clean_error(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LISA_DATA_DIR", str(tmp_path / "missing"))
    assert main(["--dataset", "all", "--no-load"]) == 2
    assert "config error" in capsys.readouterr().err


def test_cli_checksum_error_is_clean_error(mini_data, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LISA_DATA_DIR", str(mini_data))
    monkeypatch.setenv("LISA_OUT_DIR", str(tmp_path / "out"))
    p = mini_data / "pack_litigation" / "records.jsonl"
    p.write_text(p.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    assert main(["--dataset", "all", "--no-load"]) == 2
    assert "checksum error" in capsys.readouterr().err
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python -m pytest tests/test_check.py tests/test_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lisa.graph.check'`.

- [ ] **Step 3: Implement** — `src/lisa/graph/check.py`
```python
"""Acceptance check: the graph must contain every edge documented in selection_report.json."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CheckResult:
    expected: int
    missing: list[tuple] = field(default_factory=list)
    extra: list[tuple] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.missing


def _expected(report: dict, case_ids: set[str]) -> set[tuple]:
    exp = set()
    for key in ("immigration_internal_edges_list", "litigation_internal_edges_list"):
        for e in report.get(key, []):
            exp.add((e["from"], e["to"], "internal"))
    for e in report.get("cross_domain_edges_list", []):
        exp.add((e["from"], e["to"], e["basis"]))
    return {x for x in exp if x[0] in case_ids and x[1] in case_ids}


def _actual(graph: dict) -> set[tuple]:
    out = set()
    for e in graph["edges"]:
        if e["type"] != "CITES" or e["target_label"] != "Case":
            continue
        if e["props"]["scope"] == "internal":
            out.add((e["source"], e["target"], "internal"))
        else:
            for b in e["props"].get("bases", []):
                out.add((e["source"], e["target"], b))
    return out


def check(graph: dict, report: dict) -> CheckResult:
    case_ids = {n["id"] for n in graph["nodes"] if n["label"] == "Case"}
    exp, act = _expected(report, case_ids), _actual(graph)
    return CheckResult(expected=len(exp), missing=sorted(exp - act), extra=sorted(act - exp))
```

- [ ] **Step 4: Implement** — `src/lisa/graph/cli.py`
```python
"""Build the knowledge graph for one dataset config: verify -> extract -> (check) -> (load)."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter

from lisa.common.config import load_dataset, load_settings
from lisa.graph.check import check
from lisa.graph.extract_det import build_graph
from lisa.graph.loader import ChecksumError, load_records, verify_manifest


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dataset", required=True, help="name of config/datasets/<name>.yaml (all, immigration, litigation, gold_eval)")
    ap.add_argument("--check", action="store_true", help="compare edges with selection_report.json")
    ap.add_argument("--no-load", action="store_true", help="write graph JSON only; skip Neo4j")
    a = ap.parse_args(argv)

    try:
        settings = load_settings()
    except RuntimeError as e:
        print(f"config error: {e}", file=sys.stderr)
        return 2
    ds = load_dataset(a.dataset)
    try:
        verify_manifest(settings.data_dir, [s.path for s in ds.sources])
    except ChecksumError as e:
        print(f"checksum error: {e}", file=sys.stderr)
        return 2

    records, quarantine = load_records(settings.data_dir, ds)
    graph = build_graph(records, ds).to_json()
    settings.out_dir.mkdir(parents=True, exist_ok=True)
    (settings.out_dir / f"graph_{ds.name}.json").write_text(
        json.dumps(graph, ensure_ascii=False, indent=1), encoding="utf-8")
    (settings.out_dir / f"quarantine_{ds.name}.json").write_text(
        json.dumps(quarantine, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"{ds.name}: {len(records)} records, {len(quarantine)} quarantined")
    print("nodes:", dict(sorted(Counter(n["label"] for n in graph["nodes"]).items())))
    print("edges:", dict(sorted(Counter(e["type"] for e in graph["edges"]).items())))
    print("unverified edges:", sum(e["provenance"] == "unverified" for e in graph["edges"]))

    rc = 0
    if a.check:
        report = json.loads((settings.data_dir / "selection_report.json").read_text(encoding="utf-8"))
        r = check(graph, report)
        print(f"check vs selection_report: expected {r.expected}, missing {len(r.missing)}, extra {len(r.extra)}")
        for m in r.missing:
            print("  MISSING", *m)
        for x in r.extra:
            print("  extra  ", *x)
        rc = 0 if r.ok else 1

    if not a.no_load:
        from lisa.graph.neo4j_load import Neo4jUnavailable, load
        try:
            print("neo4j:", load(graph, settings))
        except Neo4jUnavailable as e:
            print(f"neo4j load failed: {e} (graph JSON was written)", file=sys.stderr)
            return rc or 3
    return rc
```

`scripts/build_graph.py`:
```python
"""Thin wrapper: py -3 scripts/build_graph.py --dataset all --check"""
import sys

from lisa.graph.cli import main

if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run to verify pass**

Run: `.venv/Scripts/python -m pytest -v`
Expected: all pass.

- [ ] **Step 6: Run on the real packs**

Create `.env` from `.env.example` with `LISA_DATA_DIR` pointing at `C:/Users/91837/Desktop/Adway Con/Final_Project (1)/LISA_Project_Package/data`, then:
```bash
.venv/Scripts/python scripts/build_graph.py --dataset all --check --no-load
.venv/Scripts/python scripts/build_graph.py --dataset gold_eval --no-load
```
Expected (all): `all: 60 records, 0 quarantined`, `Case: 60`, and `check vs selection_report: expected 138, missing 0` (27 + 61 internal + 50 cross-domain). Any `extra` lines are reported, not failures — list them in the commit message body. Expected (gold_eval): `gold_eval: 20 records, 0 quarantined`.
If `missing` is non-zero: stop and debug the missing edges before continuing.

- [ ] **Step 7: Commit**
```bash
git add src/lisa/graph/check.py src/lisa/graph/cli.py scripts/build_graph.py tests/test_check.py tests/test_cli.py
git commit -m "feat: build command with selection-report acceptance check"
```

---

### Task 8: Neo4j loader and compose service

**Files:**
- Create: `src/lisa/graph/neo4j_load.py`, `docker-compose.yml`
- Test: `tests/test_neo4j_load.py`

**Interfaces:**
- Consumes: graph JSON (Task 5 shape), `Settings` (Task 1).
- Produces: `Neo4jUnavailable(RuntimeError)`; `node_props(item: dict) -> dict` (drops `None`, adds provenance/confidence/extractor, `evidence` as JSON string); `load(graph: dict, settings: Settings) -> dict` (`{"nodes": int, "edges": int}`), idempotent via `MERGE` on `id`; uniqueness constraint per label.

- [ ] **Step 1: Write the failing tests** — `tests/test_neo4j_load.py`
```python
import copy
import json

import pytest

from lisa.common.config import load_settings
from lisa.graph.neo4j_load import Neo4jUnavailable, load, node_props

PREFIX = "zz_test:"


def test_node_props_flattens_for_neo4j():
    p = node_props({"props": {"a": 1, "b": None, "bases": ["name"]}, "provenance": "deterministic",
                    "confidence": 0.9, "evidence": [{"page": 2, "quote": "§ x"}], "extractor": "e/1"})
    assert p == {"a": 1, "bases": ["name"], "provenance": "deterministic", "confidence": 0.9,
                 "evidence": json.dumps([{"page": 2, "quote": "§ x"}], ensure_ascii=False), "extractor": "e/1"}


def _prefixed(graph):
    g = copy.deepcopy(graph)
    for n in g["nodes"]:
        n["id"] = PREFIX + n["id"]
    for e in g["edges"]:
        e["source"], e["target"] = PREFIX + e["source"], PREFIX + e["target"]
    return g


def test_load_is_idempotent(graph_all):
    try:
        settings = load_settings()
    except RuntimeError:
        pytest.skip("LISA settings not configured")
    from neo4j import GraphDatabase
    g = _prefixed(graph_all)
    try:
        load(g, settings)
        load(g, settings)
    except Neo4jUnavailable as e:
        pytest.skip(f"Neo4j not available: {e}")
    with GraphDatabase.driver(settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password)) as d:
        with d.session() as s:
            n = s.run("MATCH (n) WHERE n.id STARTS WITH $p RETURN count(n) AS c", p=PREFIX).single()["c"]
            r = s.run("MATCH (a)-[r]->() WHERE a.id STARTS WITH $p RETURN count(r) AS c", p=PREFIX).single()["c"]
            s.run("MATCH (n) WHERE n.id STARTS WITH $p DETACH DELETE n", p=PREFIX).consume()
    assert n == len(g["nodes"]) and r == len(g["edges"])
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python -m pytest tests/test_neo4j_load.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lisa.graph.neo4j_load'`.

- [ ] **Step 3: Implement** — `src/lisa/graph/neo4j_load.py`
```python
"""Load graph JSON into Neo4j. Idempotent: MERGE on id; labels/types are whitelisted (never from data)."""
from __future__ import annotations

import json
from collections import defaultdict

from neo4j import GraphDatabase
from neo4j.exceptions import AuthError, ServiceUnavailable

from lisa.common.config import Settings

LABELS = ("Case", "Authority", "Statute", "Regulation", "Page")
REL_TYPES = ("CITES", "MENTIONS_STATUTE", "HAS_PAGE")
BATCH = 500


class Neo4jUnavailable(RuntimeError):
    pass


def node_props(item: dict) -> dict:
    p = {k: v for k, v in item["props"].items() if v is not None}
    p.update(provenance=item["provenance"], confidence=item["confidence"],
             evidence=json.dumps(item["evidence"], ensure_ascii=False), extractor=item["extractor"])
    return p


def _chunks(rows: list) -> list[list]:
    return [rows[i:i + BATCH] for i in range(0, len(rows), BATCH)]


def load(graph: dict, settings: Settings) -> dict:
    if not settings.neo4j_password:
        raise Neo4jUnavailable("NEO4J_PASSWORD is not set")
    driver = GraphDatabase.driver(settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password))
    try:
        driver.verify_connectivity()
    except (ServiceUnavailable, AuthError, OSError) as e:
        driver.close()
        raise Neo4jUnavailable(str(e)) from e

    nodes: dict[str, list] = defaultdict(list)
    edges: dict[tuple, list] = defaultdict(list)
    for n in graph["nodes"]:
        if n["label"] not in LABELS:
            raise ValueError(f"unknown node label {n['label']!r}")
        nodes[n["label"]].append({"id": n["id"], "props": node_props(n)})
    for e in graph["edges"]:
        if e["type"] not in REL_TYPES:
            raise ValueError(f"unknown edge type {e['type']!r}")
        edges[(e["type"], e["source_label"], e["target_label"])].append(
            {"source": e["source"], "target": e["target"], "props": node_props(e)})

    try:
        with driver.session() as s:
            for label in LABELS:
                s.run(f"CREATE CONSTRAINT {label.lower()}_id IF NOT EXISTS "
                      f"FOR (n:{label}) REQUIRE n.id IS UNIQUE").consume()
            for label, rows in nodes.items():
                for chunk in _chunks(rows):
                    s.run(f"UNWIND $rows AS row MERGE (n:{label} {{id: row.id}}) SET n += row.props",
                          rows=chunk).consume()
            for (etype, sl, tl), rows in edges.items():
                for chunk in _chunks(rows):
                    s.run(f"UNWIND $rows AS row MATCH (a:{sl} {{id: row.source}}) MATCH (b:{tl} {{id: row.target}}) "
                          f"MERGE (a)-[r:{etype}]->(b) SET r += row.props", rows=chunk).consume()
    finally:
        driver.close()
    return {"nodes": sum(len(v) for v in nodes.values()), "edges": sum(len(v) for v in edges.values())}
```

`docker-compose.yml` (Phase 6 adds the other services):
```yaml
services:
  neo4j:
    image: neo4j:5-community
    ports:
      - "7474:7474"
      - "7687:7687"
    environment:
      NEO4J_AUTH: neo4j/${NEO4J_PASSWORD:?set NEO4J_PASSWORD in .env}
    volumes:
      - neo4j_data:/data
    healthcheck:
      test: ["CMD-SHELL", "wget -qO- http://localhost:7474 || exit 1"]
      interval: 5s
      retries: 30
volumes:
  neo4j_data: {}
```

- [ ] **Step 4: Run unit test (DB test may skip)**

Run: `.venv/Scripts/python -m pytest tests/test_neo4j_load.py -v`
Expected: `test_node_props_flattens_for_neo4j` PASS; `test_load_is_idempotent` SKIPPED if Neo4j is down.

- [ ] **Step 5: Start Neo4j and load the real graph** (needs Docker Desktop running and `NEO4J_PASSWORD` in `.env`)
```bash
docker compose --env-file .env up -d neo4j
docker compose ps   # wait until neo4j is "healthy"
.venv/Scripts/python -m pytest tests/test_neo4j_load.py -v
.venv/Scripts/python scripts/build_graph.py --dataset all --check
docker compose exec neo4j cypher-shell -u neo4j -p "$(grep NEO4J_PASSWORD .env | cut -d= -f2)" \
  "MATCH (c:Case) RETURN c.domain AS domain, count(*) AS n ORDER BY domain"
```
Expected: idempotency test PASS (not skipped); build prints `neo4j: {'nodes': ..., 'edges': ...}`; cypher returns `immigration 30`, `litigation 30`. Running the build a second time leaves those counts unchanged.

- [ ] **Step 6: Commit**
```bash
git add src/lisa/graph/neo4j_load.py docker-compose.yml tests/test_neo4j_load.py
git commit -m "feat: idempotent Neo4j loader and compose service"
```

---

### Task 9: README (Phase 1) and publish

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write `README.md`**
````markdown
# LISA — Legal Knowledge-Graph Research Agent

Self-hosted legal research over two U.S. case-law corpora (30 BIA/AG immigration decisions, 30 Supreme Court
opinions): a knowledge graph exposed as MCP tools, driven by an LLM agent, with mechanically verified citations.

> Status: **Phase 1 — graph foundation** (deterministic extraction tier + Neo4j). Later phases: LLM extraction &
> gold-standard eval, four MCP servers, agent, evaluation, security/ops.

## Setup
```bash
py -3 -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"
cp .env.example .env        # set LISA_DATA_DIR to LISA_Project_Package/data and NEO4J_PASSWORD
docker compose --env-file .env up -d neo4j
```
The case data is **not** in this repo. Every input file is verified against the package's `manifest.json` SHA-256 before use.

## Build the graph
```bash
.venv/Scripts/python scripts/build_graph.py --dataset all --check   # both corpora + cross-domain edges
.venv/Scripts/python scripts/build_graph.py --dataset immigration   # one domain — same code, different YAML
.venv/Scripts/python -m pytest
```
`--check` asserts every edge in `selection_report.json` (27 immigration-internal, 61 SCOTUS-internal,
50 cross-domain entries) is present. Output: `out/graph_<dataset>.json`; Neo4j browser at http://localhost:7474.

## Graph schema (deterministic tier)
Nodes: `Case`, `Authority` (out-of-corpus citation), `Statute`, `Regulation`, `Page`.
Edges: `CITES` (`scope`: internal / cross_domain / external; `bases`: detected_citation / name / reporter),
`MENTIONS_STATUTE`, `HAS_PAGE`. Every node and edge has `provenance`, `confidence`, and page-anchored `evidence`.
Case legal status is always `not verified`.

## Domains are configuration
`config/domains/*.yaml` maps record fields and statute patterns; `config/datasets/*.yaml` picks files and cross-domain
rules. Adding or switching a corpus requires no code changes.
````

- [ ] **Step 2: Full test run**

Run: `.venv/Scripts/python -m pytest -v`
Expected: all pass (DB test passes if Neo4j is up).

- [ ] **Step 3: Commit**
```bash
git add README.md
git commit -m "docs: Phase 1 README"
```

- [ ] **Step 4: Publish (ask the user first)**

Confirm with the user, then:
```bash
gh repo create bhargavlukka/lisa-legal-kg --public --source . --push
```
Expected: repo URL printed; `git status` clean; `git log origin/main` matches local.
````
