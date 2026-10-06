# Phase 2 — LLM Extraction Tier + Gold Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A config-driven LLM extraction tier (gold schema → verified quotes → mapped spec tier) plus a deterministic precision/recall evaluation against the 25-unit gold standard.

**Architecture:** `units` (port of the reference segmenter/chunker over Phase 1 `Record`s) → `stage_nodes` (3-page windows → nodes) → `stage_edges` (unit + node catalog → edges) → `verify` (quote lookup → provenance) → `out/llm_<ds>.json` → `mapping` (→ FOLLOWS / DISTINGUISHES / OVERRULES / CITES_LLM / AUTHORED_BY / INVOKES_DOCTRINE, joined to Phase 1 ids) → `out/graph_<ds>_llm.json`. `eval` matches predictions to gold by quote-span overlap and writes `out/eval/extraction_report.{json,md}`. Every LLM call goes through one client with a disk cache, a request budget and 429 backoff.

**Tech Stack:** Python 3.13 (`.venv`), httpx (new), PyYAML, python-dotenv, pytest; SharedLLM OpenAI-compatible gateway, model `z-ai/glm-flash-latest`.

**Spec:** `docs/design/phase2-llm-extraction.md`

## Global Constraints

- Python ≥ 3.10; run tools as `.venv/Scripts/python -m ...` (Windows, Git Bash). Every file read/write uses `encoding="utf-8"`; JSON written with `ensure_ascii=False`.
- No raw corpora, no gold content, no LLM cache and no secrets in git. Data only via `LISA_DATA_DIR`; the key only via `SHAREDLLM_API_KEY` in env / `.env` (gitignored). All of `out/` is gitignored.
- Model identity lives in `config/settings.yaml` only (`llm.model`); no model string in code.
- `temperature: 0`. Cache key = sha256(prompt_version + params incl. model + messages).
- Every LLM-tier node/edge: `provenance` ∈ {`llm`, `unverified`}, `confidence` float 0–1, `evidence` list of `{page, quote, verified}` with quotes copied verbatim, `evidence_strength` ∈ {strong, moderate, weak}.
- Phase 1 output (`out/graph_<dataset>.json`) must stay byte-identical. Baseline sha256 (main @ cd86316, rebuilt 2026-10-01): `graph_all` `8e5f4e91…3e9d`, `graph_gold_eval` `51f04874…0ee2`, `graph_immigration` `2c57762a…6a25`.
- `pytest` never touches the network. Tests that need the real data use the `real_data_dir` fixture and skip when it is absent.
- Few-shot units are fixed: `eoir_4018__u1of1` (immigration) and `scotus_2017_17-269__u1of1` (SCOTUS). They are never extracted in `gold_eval` runs and never scored (23 scored units).
- Commits are authored by the repo owner only — **no co-author / tool attribution trailers**. After every task: tests green → commit → `git push` (branch `phase2-llm-extraction`).

## Review Focus

1. **LLM reply is not clean JSON** (fenced block, prose before/after, or broken JSON) — fenced/prosed JSON must parse; broken JSON gets exactly one repair retry, then the window is marked failed and the run continues → Task 5 (`test_parse_json_*`, `test_call_json_repairs_once_then_fails`).
2. **Quote typography differs from page text** (line-break hyphenation, curly vs straight quotes, U+FFFD replacement chars, quote crossing a page break) must still verify; a tiny generic quote (`"the Court"`) must *not* verify → Task 2 (`test_locate_*`, `test_short_quote_never_verifies`).
3. **Run stopped by the request budget, then rerun** must resume from the cache without re-spending requests and produce the same output as an uninterrupted run → Task 9 (`test_budget_stop_then_resume_matches_full_run`).
4. **LLM edges referencing ids that do not exist or disallowed type signatures** must be dropped and counted in `schema_rejects`, never crash or create dangling edges → Task 7 (`test_edges_drop_unknown_ids_and_bad_signatures`).
5. **Missing `SHAREDLLM_API_KEY`, or `--offline` with an empty cache** must give a one-line error and exit 2 (offline: unit marked `not_cached`), not a traceback → Task 4 (`test_missing_key_is_clear_error`), Task 9 (`test_cli_missing_key_exits_2`, `test_offline_cache_miss_marks_unit`).

---

## File Structure

| File | Responsibility |
|---|---|
| `pyproject.toml` | + `httpx>=0.27` |
| `config/settings.yaml` | + `llm:` and `eval:` blocks |
| `.env.example` | + `SHAREDLLM_API_KEY` |
| `src/lisa/common/config.py` | + `LLMSettings`, `EvalSettings`, `load_llm_settings`, `load_eval_settings` |
| `src/lisa/graph/loader.py` | + `Record.pdf_pages` (default empty; Phase 1 output unchanged) |
| `src/lisa/extract/units.py` | `Segment`, `UnitPage`, `Unit`, `segment_record`, `build_units`, `render_pages`, `active_part` |
| `src/lisa/extract/verify.py` | `squash`, `Span`, `PageIndex`, `verify_item`, `evidence_strength`, `DEFAULT_CONFIDENCE` |
| `src/lisa/extract/schema.py` + `schema_signatures.json` | node/relation vocab, `SIGNATURES`, `validate_node`, `validate_edge`, `derive_signatures` |
| `src/lisa/llm/cache.py` | `Cache` |
| `src/lisa/llm/budget.py` | `Budget`, `BudgetExhausted`, `RunStats`, `retry_delay` |
| `src/lisa/llm/client.py` | `LLMClient`, `Completion`, `LLMError`, `CacheMiss` |
| `src/lisa/extract/calljson.py` | `parse_json`, `call_json`, `Truncated`, `ExtractionFailed` |
| `src/lisa/extract/prompts/{nodes,edges}.md` + `prompts.py` | prompt texts with `PROMPT_VERSION`, `load_prompt` |
| `src/lisa/extract/fewshot.py` | few-shot blocks built at runtime from gold (never committed) |
| `src/lisa/extract/stage_nodes.py` | `make_windows`, `extract_nodes`, `dedupe`, `assign_ids`, `slug` |
| `src/lisa/extract/stage_edges.py` | `catalog`, `plan_calls`, `extract_edges` |
| `src/lisa/extract/mapping.py` | `map_units`, `judge_id`, `surname` |
| `src/lisa/extract/pipeline.py` + `cli.py` + `scripts/extract_llm.py` | orchestration, outputs, run manifest |
| `src/lisa/eval/extraction_eval.py` | span/label matching, P/R/F1, sweep, mapped-tier P/R |
| `src/lisa/eval/error_analysis.py` | FP/FN buckets + examples |
| `src/lisa/eval/report.py` + `cli.py` + `scripts/eval_extraction.py` | markdown/JSON report |
| `scripts/derive_schema.py` | regenerate `schema_signatures.json` from gold |
| `tests/fakes.py` | `FakeClient`, `mock_transport` helpers |
| `docs/decision_log.md`, `docs/eval/extraction_report.md`, `README.md` | docs (Task 12) |

---

### Task 1: Work units (port of the reference segmenter + chunker)

**Files:**
- Modify: `src/lisa/graph/loader.py` (Record gets `pdf_pages`)
- Create: `src/lisa/extract/__init__.py` (empty), `src/lisa/extract/units.py`
- Modify: `tests/conftest.py` (add `real_data_dir` fixture)
- Test: `tests/test_units.py`, `tests/test_units_real.py`

**Interfaces:**
- Consumes: `lisa.graph.loader.Record` (`id, domain, title, citation, props, pages=[{page,text}]`).
- Produces:
  - `Record.pdf_pages: dict[int, int | None]`
  - `Segment(seg_id: str, part: str, label: str, start_page: int, start_char: int, end_page: int, end_char: int)` (frozen)
  - `UnitPage(page: int, pdf_page: int | None, text: str)` — `text` is page text with PART markers inserted
  - `Unit(unit_id, case_id, domain, header: str, pages: tuple[UnitPage,...], raw_pages: dict[int,str], segments: tuple[Segment,...], repeated_page: int | None)` with property `text -> str`
  - `segment_record(rec: Record) -> list[Segment]`
  - `build_units(rec: Record, unit_chars: int = 90_000) -> list[Unit]`
  - `render_pages(pages: Sequence[UnitPage]) -> str`
  - `active_part(segments: Sequence[Segment], page: int) -> Segment | None`

- [ ] **Step 0: Record Phase 1 baseline hashes**

Run: `sha256sum out/graph_*.json`
Expected: the three hashes listed in Global Constraints. If `out/` is missing, run `.venv/Scripts/python scripts/build_graph.py --dataset all --no-load` (and `gold_eval`, `immigration`) first and record them.

- [ ] **Step 1: Write the failing tests**

`tests/conftest.py` — append:

```python
import os


@pytest.fixture
def real_data_dir() -> Path:
    """Real LISA package data; tests using it skip on machines without the package."""
    from dotenv import load_dotenv
    from lisa.common.config import REPO_ROOT
    load_dotenv(REPO_ROOT / ".env")
    raw = os.environ.get("LISA_DATA_DIR")
    if not raw or not (Path(raw) / "gold_standard").is_dir():
        pytest.skip("real LISA data not available")
    return Path(raw)
```

`tests/test_units.py`:

```python
from lisa.extract.units import active_part, build_units, render_pages, segment_record
from lisa.graph.loader import Record


def rec(domain, pages, **props):
    return Record(id="c1", domain=domain, title="Alpha v. Beta", citation=props.pop("citation", None),
                  props=props, pages=[{"page": i + 1, "text": t} for i, t in enumerate(pages)],
                  text="\n".join(pages), citations=[], pdf_pages={i + 1: 10 + i for i in range(len(pages))})


SCOTUS = ["Syllabus\nSummary of the case.",
          "JUSTICE KAGAN delivered the opinion of the Court.\nWe hold for petitioner.",
          "JUSTICE THOMAS, dissenting.\nI disagree."]


def test_segments_litigation_parts_in_order():
    segs = segment_record(rec("litigation", SCOTUS))
    assert [s.part for s in segs] == ["syllabus", "majority", "dissent"]
    assert [s.seg_id for s in segs] == ["c1#s0", "c1#s1", "c1#s2"]
    assert (segs[1].start_page, segs[1].start_char, segs[1].end_page) == (2, 0, 3)
    assert segs[2].label == "Thomas dissenting"
    assert (segs[2].end_page, segs[2].end_char) == (3, len(SCOTUS[2]))


def test_immigration_without_markers_is_body_unsegmented():
    segs = segment_record(rec("immigration", ["Plain text.", "More text."]))
    assert [s.part for s in segs] == ["body_unsegmented"]


def test_single_unit_text_layout():
    [u] = build_units(rec("litigation", SCOTUS, citation="585 U.S. 1", docket_number="17-1",
                          court="Supreme Court of the United States", decision_date="2018-06-22"))
    assert u.unit_id == "c1__u1of1" and u.repeated_page is None
    assert u.text.startswith("CASE_ID: c1\nDATASET: litigation\nTITLE: Alpha v. Beta\nCITATION: 585 U.S. 1\n"
                             "DECISION_DATE: 2018-06-22\nDOCKET: 17-1\nCOURT/BODY: Supreme Court of the United States\n"
                             "UNIT: 1 of 1 (pages 1-3)\nPARTS IN THIS DOCUMENT (deterministic hints): syllabus[")
    assert "\n===== [[PAGE 2 | source_pdf_page 11]] =====\n" in u.text
    assert ("\n<<<PART BEGINS: majority | JUSTICE KAGAN delivered the opinion of the Court. | seg_id=c1#s1>>>\n"
            in u.text)
    assert u.raw_pages[2] == SCOTUS[1]
    assert render_pages(u.pages) in u.text


def test_unknown_metadata_prints_unknown():
    [u] = build_units(rec("immigration", ["Text."]))
    assert "CITATION: unknown\nDECISION_DATE: unknown\nDOCKET: unknown\nCOURT/BODY: unknown\n" in u.text


def test_multi_unit_overlap_and_continuation():
    units = build_units(rec("litigation", SCOTUS), unit_chars=1)
    assert [u.unit_id for u in units] == ["c1__u1of3", "c1__u2of3", "c1__u3of3"]
    assert [[p.page for p in u.pages] for u in units] == [[1], [1, 2], [2, 3]]
    assert [u.repeated_page for u in units] == [None, 1, 2]
    assert "first page repeated from previous unit for context - do not re-extract it" in units[2].header
    # same rule as the reference: the part whose start is <= (page, char 0) — the dissent starts at page 3, char 0
    assert "CONTINUING PART AT TOP OF PAGE 3 (began in an earlier unit): dissent | Thomas dissenting" in units[2].header
    assert "CONTINUING PART AT TOP OF PAGE 2 (began in an earlier unit): majority" in units[1].header


def test_active_part():
    segs = segment_record(rec("litigation", SCOTUS))
    assert active_part(segs, 2).part == "majority"
    assert active_part(segs, 3).part == "dissent"
```

`tests/test_units_real.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_units.py tests/test_units_real.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lisa.extract'` (and `TypeError ... pdf_pages`).

- [ ] **Step 3: Implement**

`src/lisa/graph/loader.py` — change the import to `from dataclasses import dataclass, field`, add the last field of `Record`:

```python
    citations: list[str]
    pdf_pages: dict[int, int | None] = field(default_factory=dict)
```

and in `load_records`, replace the `pages = [...]` line and the `Record(...)` call's tail:

```python
                pdf_pages = {p["page"]: p.get("source_pdf_page") for p in pages}
                pages = [{"page": p["page"], "text": p["text"]} for p in pages]
                records.append(Record(
                    id=raw[src.fields["id"]],
                    domain=src.domain,
                    title=raw[src.fields["title"]],
                    citation=raw.get(src.fields["citation"]) or None,
                    props=props,
                    pages=pages,
                    text=raw.get("text") or "\n".join(p["text"] for p in pages),
                    citations=list(raw.get("citations_detected") or []),
                    pdf_pages=pdf_pages,
                ))
```

`src/lisa/extract/units.py`:

```python
"""LLM work units: page-aligned chunks with inline part-boundary markers.

Port of pipeline_reference/segment.py + chunk.py that reads loader Records instead of the reference SQLite DB.
Regexes and rules are kept verbatim so units match the reference pilot_units/ (see tests/test_units_real.py)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

from lisa.graph.loader import Record

UNIT_CHARS = 90_000

JUSTICES = {"ROBERTS", "THOMAS", "GINSBURG", "BREYER", "ALITO", "SOTOMAYOR", "KAGAN", "GORSUCH",
            "KAVANAUGH", "BARRETT", "JACKSON", "KENNEDY"}
SC_MAJ = re.compile(r"^(?:CHIEF )?JUSTICE\s+([A-Z]+).{0,80}?(delivered the opinion of the Court|announced the judgment of the Court)", re.I)
_NAMES = "|".join(sorted(JUSTICES))
SC_HEAD = re.compile(rf"^(?:(?:CHIEF\s+)?JUSTICE\s+)?({_NAMES})\b.{{0,150}}?\b(concurring|dissenting)\b"
                     rf"((?:\s+in\s+(?:part|the\s+judgment|judgment))?(?:\s+and\s+(?:concurring|dissenting)(?:\s+in\s+(?:part|the\s+judgment))?)?)\s*\.?\s*$", re.I)
EO_AUTH = re.compile(r"^([A-Z][A-Z\-'’\. ]{2,40}),\s+((?:Acting |Deputy |Vice |Chief |Senior )*(?:Appellate Immigration Judge|Board Member|Chairman|Chair|Director|Commissioner|Immigration Judge|Judge)[A-Za-z ,]{0,40}):\s*$")
EO_SEP = re.compile(r"^(CONCURRING AND DISSENTING|CONCURRING|DISSENTING)\s+OPINION:", re.I)


@dataclass(frozen=True)
class Segment:
    seg_id: str
    part: str
    label: str
    start_page: int
    start_char: int
    end_page: int
    end_char: int


@dataclass(frozen=True)
class UnitPage:
    page: int
    pdf_page: int | None
    text: str


@dataclass
class Unit:
    unit_id: str
    case_id: str
    domain: str
    header: str
    pages: tuple[UnitPage, ...]
    raw_pages: dict[int, str]
    segments: tuple[Segment, ...]
    repeated_page: int | None

    @property
    def text(self) -> str:
        return self.header + "\n" + render_pages(self.pages)


def render_pages(pages: Sequence[UnitPage]) -> str:
    return "".join(f"\n===== [[PAGE {p.page} | source_pdf_page {p.pdf_page}]] =====\n{p.text}\n" for p in pages)


def active_part(segments: Sequence[Segment], page: int) -> Segment | None:
    act = [s for s in segments if (s.start_page, s.start_char) <= (page, 0)]
    return max(act, key=lambda s: (s.start_page, s.start_char)) if act else None


def _lines(text):
    raw = text.split("\n"); offs = []; off = 0
    for ln in raw:
        offs.append(off); off += len(ln) + 1
    for i, ln in enumerate(raw):
        cur = ln.strip()
        # PDF line-wrap: headings like "JUSTICE X, with whom Y joins,\ndissenting." span 2-3 lines
        if re.match(r"(?:CHIEF )?JUSTICE\b", cur, re.I) and len(cur) < 120:
            j = i; joined = cur
            while j + 1 < len(raw) and j - i < 2 and not joined.rstrip().endswith(".") and not re.search(r"(Court|dissenting|concurring)[^\n]*\.?$", joined, re.I):
                j += 1; joined += " " + raw[j].strip()
            cur = re.sub(r"\s+", " ", joined)
        yield offs[i], cur


def segment_record(rec: Record) -> list[Segment]:
    case_id, dataset = rec.id, rec.domain
    pages = sorted(((p["page"], p["text"]) for p in rec.pages), key=lambda x: x[0])
    starts = []  # (page, char_in_page, part, label)
    seen = set(); sep_cands = {}
    for pno, text in pages:
        for off, ln in _lines(text):
            if not ln or len(ln) > 260: continue
            if dataset == "litigation":
                if pno == 1 and re.fullmatch(r"Syllabus", ln, re.I) and "syllabus" not in seen:
                    seen.add("syllabus"); starts.append((pno, off, "syllabus", "Syllabus (publisher/reporter summary, not the Court's opinion)")); continue
                m = SC_MAJ.match(ln)
                if (m or (pno > 1 and re.fullmatch(r"Opinion of the Court\.?", ln, re.I))) and "majority" not in seen and "per_curiam" not in seen:
                    seen.add("majority"); starts.append((pno, off, "majority", ln[:120])); continue
                if re.fullmatch(r"PER CURIAM\.?", ln, re.I) and "per_curiam" not in seen:
                    seen.add("per_curiam"); starts.append((pno, off, "per_curiam", "PER CURIAM")); continue
                m = SC_HEAD.match(ln)
                if m and re.search(r"\bjoins?\b", ln, re.I) and not re.search(r"with whom", ln, re.I):
                    m = None   # tail of a wrapped joinder heading
                if m and (re.match(r"(?:CHIEF\s+)?JUSTICE\b", ln, re.I) or len(ln) < 70):
                    name = m.group(1).upper()
                    kind = m.group(2).lower(); qual = re.sub(r"\s+", " ", m.group(3) or "").strip().lower()
                    key = f"{kind}:{name}"
                    if name:
                        tier = "full" if re.match(r"(?:CHIEF\s+)?JUSTICE\b", ln, re.I) else "short"
                        part = "concurrence" if kind == "concurring" else "dissent"
                        sep_cands.setdefault(key, {}).setdefault(tier, (pno, off, part, f"{name.title()} {kind}{(' ' + qual) if qual else ''}"))
            else:
                m = EO_SEP.match(ln)
                if m and not any(x[2] == "majority" for x in starts):
                    continue   # caption lists "Dissenting Opinion: X" before the majority begins
                if m:
                    key = f"sep:{ln[:60]}"
                    if key not in seen:
                        seen.add(key); kind = m.group(1).lower()
                        part = "dissent" if kind == "dissenting" else "concurrence" if kind == "concurring" else "concurrence_and_dissent"
                        starts.append((pno, off, part, ln[:100]))
                    continue
                m = EO_AUTH.match(ln)
                if m and not any(s[2] == "majority" for s in starts) and not any(s[2] in ("dissent", "concurrence", "concurrence_and_dissent") for s in starts):
                    starts.append((pno, off, "majority", f"{m.group(1).title()} (author of majority)"))
    for cands in sep_cands.values():
        starts.append(cands.get("full") or cands["short"])
    if not starts or starts[0][:2] != (1, 0):
        first = "headnote" if dataset == "immigration" and starts else ("body_unsegmented" if not starts else "front_matter_or_syllabus")
        starts.insert(0, (1, 0, first, "document start (cover/syllabus/headnote; not the tribunal opinion)"))
    starts.sort(key=lambda s: (s[0], s[1]))
    segs = []
    for i, (p, o, part, label) in enumerate(starts):
        if i + 1 < len(starts): ep, eo = starts[i + 1][0], starts[i + 1][1]
        else: ep, eo = pages[-1][0], len(pages[-1][1])
        segs.append(Segment(f"{case_id}#s{i}", part, label, p, o, ep, eo))
    return segs


def _annotated_pages(rec: Record, segs: list[Segment]) -> list[UnitPage]:
    out = []
    for p in sorted(rec.pages, key=lambda p: p["page"]):
        page, text = p["page"], p["text"]
        marks = sorted([s for s in segs if s.start_page == page], key=lambda s: s.start_char)
        buf, last = [], 0
        for s in marks:
            buf.append(text[last:s.start_char])
            buf.append(f"\n<<<PART BEGINS: {s.part} | {s.label} | seg_id={s.seg_id}>>>\n")
            last = s.start_char
        buf.append(text[last:])
        out.append(UnitPage(page, rec.pdf_pages.get(page), "".join(buf)))
    return out


def build_units(rec: Record, unit_chars: int = UNIT_CHARS) -> list[Unit]:
    segs = segment_record(rec)
    pages = _annotated_pages(rec, segs)
    chunks, cur, size = [], [], 0
    for p in pages:
        L = len(p.text)
        if cur and size + L > unit_chars:
            chunks.append(cur); cur = [cur[-1]]; size = len(cur[0].text)   # 1-page overlap
        cur.append(p); size += L
    if cur: chunks.append(cur)
    raw = {p["page"]: p["text"] for p in rec.pages}
    hints = "; ".join(f"{s.part}[{s.label[:40]}] p{s.start_page}-{s.end_page}" for s in segs)
    units = []
    for i, up in enumerate(chunks):
        head = (f"CASE_ID: {rec.id}\nDATASET: {rec.domain}\nTITLE: {rec.title}\nCITATION: {rec.citation or 'unknown'}\n"
                f"DECISION_DATE: {rec.props.get('decision_date') or 'unknown'}\n"
                f"DOCKET: {rec.props.get('docket_number') or 'unknown'}\n"
                f"COURT/BODY: {rec.props.get('court') or 'unknown'}\n"
                f"UNIT: {i+1} of {len(chunks)} (pages {up[0].page}-{up[-1].page}"
                f"{'; first page repeated from previous unit for context - do not re-extract it' if i else ''})\n"
                f"PARTS IN THIS DOCUMENT (deterministic hints): {hints}\n")
        if i:
            newp = up[1].page if len(up) > 1 else up[0].page
            a = active_part(segs, newp)
            if a:
                head += (f"CONTINUING PART AT TOP OF PAGE {newp} (began in an earlier unit): "
                         f"{a.part} | {a.label} | seg_id={a.seg_id}\n")
        units.append(Unit(unit_id=f"{rec.id}__u{i+1}of{len(chunks)}", case_id=rec.id, domain=rec.domain,
                          header=head, pages=tuple(up), raw_pages={p.page: raw[p.page] for p in up},
                          segments=tuple(segs), repeated_page=up[0].page if i else None))
    return units
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest -q`
Expected: all pass (61 old + 7 new; `test_units_reproduce_pilot_units` passes, not skipped, on this machine).

- [ ] **Step 5: Verify Phase 1 output is unchanged**

Run: `.venv/Scripts/python scripts/build_graph.py --dataset all --no-load && .venv/Scripts/python scripts/build_graph.py --dataset gold_eval --no-load && .venv/Scripts/python scripts/build_graph.py --dataset immigration --no-load && sha256sum out/graph_*.json`
Expected: identical to the Step 0 hashes.

- [ ] **Step 6: Commit and push**

```bash
git add src/lisa/graph/loader.py src/lisa/extract/__init__.py src/lisa/extract/units.py tests/conftest.py tests/test_units.py tests/test_units_real.py
git commit -m "feat: LLM work units ported from reference segmenter/chunker"
git push -u origin phase2-llm-extraction
```

---

### Task 2: Quote verification and provenance

**Files:**
- Create: `src/lisa/extract/verify.py`
- Test: `tests/test_verify.py`

**Interfaces:**
- Produces:
  - `squash(s: str) -> str`; `MIN_QUOTE = 12`; `DEFAULT_CONFIDENCE = 0.7`
  - `Span(page: int, start: int, end: int)` (frozen; offsets in the unit-wide squashed text)
  - `PageIndex(raw_pages: dict[int, str])` with `.locate(quote: str, page: int | None) -> Span | None`
  - `evidence_strength(verified_quotes: list[str]) -> str`
  - `verify_item(item: dict, index: PageIndex) -> dict` — returns a copy with `evidence` (`[{page, quote, verified, span?}]`), `provenance`, `evidence_verified`, `confidence`, `evidence_strength`

- [ ] **Step 1: Write the failing tests**

`tests/test_verify.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_verify.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lisa.extract.verify'`

- [ ] **Step 3: Implement**

`src/lisa/extract/verify.py`:

```python
"""Quote verification against stored page text. Provenance, confidence and evidence_strength are set by rule."""
from __future__ import annotations

import bisect
import re
from dataclasses import dataclass

MIN_QUOTE = 12          # squashed chars; shorter quotes ("the Court") match anywhere and prove nothing
DEFAULT_CONFIDENCE = 0.7

_MARKERS = re.compile(r"<<<PART BEGINS:[^>]*>>>|=====\s*\[\[PAGE[^\]]*\]\]\s*=====")
_DROP = re.compile("[\\s\\-­‐-―\"'`‘-‟′″�]+")


def squash(s: str) -> str:
    """Matching key: page/part markers removed, then whitespace, hyphens/dashes and all quote marks dropped."""
    return _DROP.sub("", _MARKERS.sub("", s))


@dataclass(frozen=True)
class Span:
    page: int
    start: int
    end: int


class PageIndex:
    """Squashed text of a unit's pages, concatenated, with page offsets."""

    def __init__(self, raw_pages: dict[int, str]):
        self.pages = sorted(raw_pages)
        self._start: dict[int, int] = {}
        self._end: dict[int, int] = {}
        parts, pos = [], 0
        for p in self.pages:
            s = squash(raw_pages[p])
            self._start[p], self._end[p] = pos, pos + len(s)
            parts.append(s)
            pos += len(s)
        self.text = "".join(parts)
        self._starts = [self._start[p] for p in self.pages]

    def page_at(self, offset: int) -> int:
        return self.pages[bisect.bisect_right(self._starts, offset) - 1]

    def locate(self, quote: str, page: int | None) -> Span | None:
        q = squash(quote or "")
        if len(q) < MIN_QUOTE or page not in self._start:
            return None
        i = self.pages.index(page)
        prev, nxt = self.pages[max(i - 1, 0)], self.pages[min(i + 1, len(self.pages) - 1)]
        for lo, hi in ((self._start[page], self._end[nxt]), (self._start[prev], self._end[nxt])):
            k = self.text.find(q, lo, hi)
            if k >= 0:
                return Span(self.page_at(k), k, k + len(q))
        return None


def evidence_strength(verified_quotes: list[str]) -> str:
    if len(verified_quotes) >= 2 or any(len(q.split()) >= 15 for q in verified_quotes):
        return "strong"
    return "moderate" if verified_quotes else "weak"


def _as_int(v) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def verify_item(item: dict, index: PageIndex) -> dict:
    out = dict(item)
    ev = item.get("evidence")
    raw = [e for e in ev if isinstance(e, dict) and isinstance(e.get("quote"), str)] if isinstance(ev, list) else []
    kept = []
    for e in raw:
        sp = index.locate(e["quote"], _as_int(e.get("page")))
        if sp:
            kept.append({"page": sp.page, "quote": e["quote"], "verified": True, "span": [sp.start, sp.end]})
    try:
        conf = min(max(float(item.get("confidence", DEFAULT_CONFIDENCE)), 0.0), 1.0)
    except (TypeError, ValueError):
        conf = DEFAULT_CONFIDENCE
    if kept:
        evidence, prov = kept, "llm"
        if len(kept) < len(raw):
            conf *= 0.8
    else:
        evidence, prov = [{"page": _as_int(e.get("page")), "quote": e["quote"], "verified": False} for e in raw], "unverified"
        conf = min(conf, 0.3)
    out.update(evidence=evidence, provenance=prov, evidence_verified=bool(kept), confidence=round(conf, 4),
               evidence_strength=evidence_strength([e["quote"] for e in kept]))
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_verify.py -v`
Expected: PASS (13 tests).

- [ ] **Step 5: Commit and push**

```bash
git add src/lisa/extract/verify.py tests/test_verify.py
git commit -m "feat: quote verification with provenance and evidence strength"
git push
```

---

### Task 3: Gold-derived schema and validation

**Files:**
- Create: `src/lisa/extract/schema.py`, `src/lisa/extract/schema_signatures.json`, `scripts/derive_schema.py`
- Test: `tests/test_schema.py`

**Interfaces:**
- Produces:
  - constants `NODE_TYPES`, `RELATIONS`, `STANCES`, `PARTS`, `AUTHORITY_KINDS` (tuples of str), `SIGNATURES: frozenset[tuple[str, str, str]]`
  - `validate_node(raw) -> tuple[dict | None, str | None]` — cleaned node `{type,label,summary,part,author,evidence,confidence?,attrs}` or a reject reason
  - `validate_edge(raw, types: dict[str, str]) -> tuple[dict | None, str | None]` — cleaned edge `{source,target,relation,stance,basis,part,evidence,confidence?,attrs}`
  - `derive_signatures(gold_dir: Path) -> list[list[str]]`

- [ ] **Step 1: Write the failing tests**

`tests/test_schema.py`:

```python
import json
from pathlib import Path

from lisa.extract import schema
from lisa.extract.schema import SIGNATURES, derive_signatures, validate_edge, validate_node

EV = [{"page": 1, "quote": "some verbatim words"}]


def test_signatures_loaded():
    assert len(SIGNATURES) == 34
    assert ("reasoning", "supports", "holding") in SIGNATURES
    assert ("reasoning", "relies_on", "authority_ref") in SIGNATURES


def test_validate_node_ok_and_cleaned():
    n, why = validate_node({"type": "rule", "label": " Categorical approach ", "part": "majority",
                            "evidence": EV, "attrs": {"rule_kind": "doctrine", "doctrine": "categorical approach"},
                            "confidence": 0.8, "junk": 1})
    assert why is None
    assert n == {"type": "rule", "label": "Categorical approach", "summary": "", "part": "majority", "author": None,
                 "evidence": EV, "confidence": 0.8,
                 "attrs": {"rule_kind": "doctrine", "doctrine": "categorical approach"}}


def test_validate_node_coerces_unknown_part_and_kind():
    n, _ = validate_node({"type": "authority_ref", "label": "Pereira", "part": "lead",
                          "evidence": EV, "attrs": {"cite_string": "585 U.S. 198", "kind": "precedent"}})
    assert n["part"] is None and n["attrs"]["kind"] == "other"


def test_validate_node_rejects():
    assert validate_node({"type": "dog", "label": "x", "evidence": EV})[1] == "unknown node type: dog"
    assert validate_node({"type": "rule", "label": "", "evidence": EV})[1] == "missing label"
    assert validate_node({"type": "rule", "label": "x", "evidence": []})[1] == "missing evidence"
    assert validate_node({"type": "authority_ref", "label": "x", "evidence": EV, "attrs": {}})[1] == \
        "authority_ref without cite_string"
    assert validate_node("not a dict")[1] == "not an object"


TYPES = {"a:reasoning:r": "reasoning", "a:authority_ref:x": "authority_ref", "a:holding:h": "holding"}


def test_validate_edge_ok_defaults_stance_and_basis():
    e, why = validate_edge({"source": "a:reasoning:r", "target": "a:authority_ref:x", "relation": "relies_on",
                            "stance": "approves", "evidence": EV}, TYPES)
    assert why is None and e["stance"] == "relies_on" and e["basis"] == "explicit"
    e, _ = validate_edge({"source": "a:reasoning:r", "target": "a:holding:h", "relation": "supports",
                          "stance": "follows", "basis": "inferred", "evidence": EV}, TYPES)
    assert e["stance"] is None and e["attrs"]["inference_reason"] == "(not given)"


def test_validate_edge_rejects():
    assert validate_edge({"source": "zz", "target": "a:holding:h", "relation": "supports"}, TYPES)[1] == \
        "unknown node id: zz"
    assert validate_edge({"source": "a:reasoning:r", "target": "a:holding:h", "relation": "cites"}, TYPES)[1] == \
        "unknown relation: cites"
    assert validate_edge({"source": "a:holding:h", "target": "a:reasoning:r", "relation": "supports"}, TYPES)[1] == \
        "disallowed signature: holding -supports-> reasoning"


def test_derive_signatures(tmp_path):
    g = {"nodes": [{"id": "1", "type": "fact"}, {"id": "2", "type": "issue"}],
         "edges": [{"source": "1", "target": "2", "relation": "relevant_to"},
                   {"source": "1", "target": "9", "relation": "relevant_to"}]}
    (tmp_path / "u.json").write_text(json.dumps(g), encoding="utf-8")
    assert derive_signatures(tmp_path) == [["fact", "relevant_to", "issue"]]


def test_committed_signatures_match_gold(real_data_dir):
    committed = json.loads((Path(schema.__file__).parent / "schema_signatures.json").read_text(encoding="utf-8"))
    assert committed == derive_signatures(real_data_dir / "gold_standard")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_schema.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lisa.extract.schema'`

- [ ] **Step 3: Implement**

`src/lisa/extract/schema.py`:

```python
"""Gold extraction schema: vocabularies, allowed (source_type, relation, target_type) signatures, validation."""
from __future__ import annotations

import json
from pathlib import Path

NODE_TYPES = ("opinion", "issue", "fact", "rule", "holding", "reasoning", "outcome", "authority_ref")
RELATIONS = ("presents_issue", "states_fact", "states_rule", "holds", "has_outcome", "supports", "applies_rule",
             "relies_on", "relevant_to", "resolves", "agrees_with", "disagrees_with")
STANCES = ("follows", "distinguishes", "overrules", "criticizes", "relies_on", "cites_without_treatment")
PARTS = ("headnote", "syllabus", "front_matter_or_syllabus", "majority", "per_curiam", "concurrence", "dissent",
         "concurrence_and_dissent", "body_unsegmented")
AUTHORITY_KINDS = ("case", "statute", "regulation", "constitution", "other")
SIGNATURES_FILE = Path(__file__).with_name("schema_signatures.json")
SIGNATURES: frozenset[tuple[str, str, str]] = frozenset(
    tuple(s) for s in json.loads(SIGNATURES_FILE.read_text(encoding="utf-8")))


def _evidence(raw) -> list[dict]:
    if not isinstance(raw, list):
        return []
    return [{"page": e.get("page"), "quote": e["quote"]} for e in raw
            if isinstance(e, dict) and isinstance(e.get("quote"), str) and e["quote"].strip()]


def _common(raw: dict) -> dict:
    out = {"part": raw.get("part") if raw.get("part") in PARTS else None,
           "evidence": _evidence(raw.get("evidence"))}
    if "confidence" in raw:
        out["confidence"] = raw["confidence"]
    out["attrs"] = dict(raw["attrs"]) if isinstance(raw.get("attrs"), dict) else {}
    return out


def validate_node(raw) -> tuple[dict | None, str | None]:
    if not isinstance(raw, dict):
        return None, "not an object"
    if raw.get("type") not in NODE_TYPES:
        return None, f"unknown node type: {raw.get('type')}"
    label = raw.get("label").strip() if isinstance(raw.get("label"), str) else ""
    if not label:
        return None, "missing label"
    c = _common(raw)
    if not c["evidence"]:
        return None, "missing evidence"
    if raw["type"] == "authority_ref":
        if not str(c["attrs"].get("cite_string") or "").strip():
            return None, "authority_ref without cite_string"
        if c["attrs"].get("kind") not in AUTHORITY_KINDS:
            c["attrs"]["kind"] = "other"
    author = raw.get("author") if isinstance(raw.get("author"), str) and raw["author"].strip() else None
    node = {"type": raw["type"], "label": label,
            "summary": raw["summary"].strip() if isinstance(raw.get("summary"), str) else "",
            "part": c["part"], "author": author, "evidence": c["evidence"]}
    if "confidence" in c:
        node["confidence"] = c["confidence"]
    node["attrs"] = c["attrs"]
    return node, None


def validate_edge(raw, types: dict[str, str]) -> tuple[dict | None, str | None]:
    if not isinstance(raw, dict):
        return None, "not an object"
    for end in ("source", "target"):
        if raw.get(end) not in types:
            return None, f"unknown node id: {raw.get(end)}"
    rel = raw.get("relation")
    if rel not in RELATIONS:
        return None, f"unknown relation: {rel}"
    sig = (types[raw["source"]], rel, types[raw["target"]])
    if sig not in SIGNATURES:
        return None, f"disallowed signature: {sig[0]} -{rel}-> {sig[2]}"
    c = _common(raw)
    stance = (raw.get("stance") if raw.get("stance") in STANCES else "relies_on") if rel == "relies_on" else None
    basis = raw.get("basis") if raw.get("basis") in ("explicit", "inferred") else "explicit"
    if basis == "inferred" and not str(c["attrs"].get("inference_reason") or "").strip():
        c["attrs"]["inference_reason"] = "(not given)"
    edge = {"source": raw["source"], "target": raw["target"], "relation": rel, "stance": stance, "basis": basis,
            "part": c["part"], "evidence": c["evidence"]}
    if "confidence" in c:
        edge["confidence"] = c["confidence"]
    edge["attrs"] = c["attrs"]
    return edge, None


def derive_signatures(gold_dir: Path) -> list[list[str]]:
    sigs = set()
    for f in sorted(Path(gold_dir).glob("*.json")):
        g = json.loads(f.read_text(encoding="utf-8"))
        types = {n["id"]: n["type"] for n in g["nodes"]}
        for e in g["edges"]:
            if e["source"] in types and e["target"] in types:
                sigs.add((types[e["source"]], e["relation"], types[e["target"]]))
    return [list(s) for s in sorted(sigs)]
```

`scripts/derive_schema.py`:

```python
"""Regenerate src/lisa/extract/schema_signatures.json from LISA_DATA_DIR/gold_standard."""
import json
import sys

from lisa.common.config import load_settings
from lisa.extract.schema import SIGNATURES_FILE, derive_signatures

if __name__ == "__main__":
    sigs = derive_signatures(load_settings().data_dir / "gold_standard")
    SIGNATURES_FILE.write_text(json.dumps(sigs, indent=1) + "\n", encoding="utf-8")
    print(f"{len(sigs)} signatures -> {SIGNATURES_FILE}")
    sys.exit(0)
```

`schema.py` reads the JSON at import, so bootstrap the file first: create `src/lisa/extract/schema_signatures.json` containing `[]`, then run `.venv/Scripts/python scripts/derive_schema.py`.
Expected: `34 signatures -> ...schema_signatures.json`. The file is structural data (type names only, no corpus text) and is committed.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_schema.py -v`
Expected: PASS (8 tests, including the real-data one).

- [ ] **Step 5: Commit and push**

```bash
git add src/lisa/extract/schema.py src/lisa/extract/schema_signatures.json scripts/derive_schema.py tests/test_schema.py
git commit -m "feat: gold-derived extraction schema and validators"
git push
```

---

### Task 4: LLM client, cache, budget, LLM config

**Files:**
- Modify: `pyproject.toml` (deps: add `"httpx>=0.27"`), `config/settings.yaml`, `.env.example`, `src/lisa/common/config.py`
- Create: `src/lisa/llm/__init__.py` (empty), `src/lisa/llm/cache.py`, `src/lisa/llm/budget.py`, `src/lisa/llm/client.py`, `tests/fakes.py`
- Test: `tests/test_llm_client.py`, `tests/test_config.py` (append)

**Interfaces:**
- Produces:
  - `LLMSettings(base_url, model, api_key, temperature, max_output_tokens, timeout_s, max_requests_per_run, window_pages, edge_split_chars, include_unverified_in_graph, json_mode)` (frozen)
  - `EvalSettings(match_threshold: float, fewshot_units: tuple[str, ...])` (frozen)
  - `load_llm_settings(config_dir=CONFIG_DIR, env_file=REPO_ROOT/".env") -> LLMSettings`; `load_eval_settings(config_dir=CONFIG_DIR) -> EvalSettings`
  - `Cache(root: Path)`: `.key(prompt_version, params, messages) -> str` (static), `.get(key) -> dict | None`, `.put(key, payload: dict)`
  - `Budget(max_requests: int)`: `.charge()` raises `BudgetExhausted`; `.used`
  - `RunStats` dataclass: `requests, cache_hits, input_tokens, output_tokens, rate_limited, retries, repairs, truncations: int`, `failed: list[dict]`, `schema_rejects: list[dict]`, `.to_json() -> dict`
  - `retry_delay(attempt: int, retry_after: str | None, rng: random.Random) -> float`
  - `Completion(text, finish_reason, input_tokens, output_tokens, cached)`; `LLMError`, `CacheMiss(LLMError)`
  - `LLMClient(settings, cache, budget, stats, *, offline=False, transport=None, sleep=time.sleep, rng=None)`: `.complete(messages: list[dict], prompt_version: str) -> Completion`
  - `tests/fakes.py`: `llm_settings(**over) -> LLMSettings`, `FakeClient(responder)`, `chat_payload(text, finish="stop") -> dict`

- [ ] **Step 1: Write the failing tests**

`tests/fakes.py`:

```python
"""Test doubles for the LLM layer (no network)."""
from lisa.common.config import LLMSettings
from lisa.llm.client import Completion


def llm_settings(**over) -> LLMSettings:
    base = dict(base_url="https://llm.test/openai/v1", model="test-model", api_key="k-test", temperature=0.0,
                max_output_tokens=1000, timeout_s=5.0, max_requests_per_run=100, window_pages=3,
                edge_split_chars=60000, include_unverified_in_graph=False, json_mode=True)
    base.update(over)
    return LLMSettings(**base)


def chat_payload(text: str, finish: str = "stop") -> dict:
    return {"choices": [{"message": {"content": text}, "finish_reason": finish}],
            "usage": {"prompt_tokens": 11, "completion_tokens": 7}}


class FakeClient:
    """Duck-types LLMClient.complete; responder(messages) -> text | (text, finish_reason)."""

    def __init__(self, responder):
        self.responder = responder
        self.calls: list[list[dict]] = []

    def complete(self, messages, prompt_version):
        self.calls.append(messages)
        r = self.responder(messages)
        text, finish = r if isinstance(r, tuple) else (r, "stop")
        return Completion(text, finish, 10, 10, False)
```

`tests/test_llm_client.py`:

```python
import json
import random

import httpx
import pytest

from fakes import chat_payload, llm_settings
from lisa.llm.budget import Budget, BudgetExhausted, RunStats, retry_delay
from lisa.llm.cache import Cache
from lisa.llm.client import CacheMiss, LLMClient, LLMError

MSG = [{"role": "user", "content": "hi"}]


def make(tmp_path, responses, *, budget=100, offline=False, **over):
    seen, sleeps = [], []

    def handler(request):
        seen.append(request)
        status, body, headers = responses.pop(0)
        return httpx.Response(status, json=body, headers=headers)

    stats = RunStats()
    c = LLMClient(llm_settings(**over), Cache(tmp_path / "cache"), Budget(budget), stats, offline=offline,
                  transport=httpx.MockTransport(handler), sleep=sleeps.append, rng=random.Random(0))
    return c, stats, seen, sleeps


def test_success_sends_headers_body_and_caches(tmp_path):
    c, stats, seen, _ = make(tmp_path, [(200, chat_payload('{"a":1}'), {})])
    out = c.complete(MSG, "v1")
    assert out.text == '{"a":1}' and out.finish_reason == "stop" and not out.cached
    req = seen[0]
    assert str(req.url) == "https://llm.test/openai/v1/chat/completions"
    assert req.headers["X-SharedLLM-Key"] == "k-test"
    body = json.loads(req.content)
    assert body["model"] == "test-model" and body["temperature"] == 0.0 and body["max_tokens"] == 1000
    assert body["response_format"] == {"type": "json_object"} and body["messages"] == MSG
    assert (stats.requests, stats.input_tokens, stats.output_tokens) == (1, 11, 7)
    again = c.complete(MSG, "v1")
    assert again.cached and again.text == '{"a":1}' and len(seen) == 1 and stats.cache_hits == 1


def test_prompt_version_changes_cache_key(tmp_path):
    c, _, seen, _ = make(tmp_path, [(200, chat_payload("x"), {}), (200, chat_payload("y"), {})])
    assert c.complete(MSG, "v1").text == "x"
    assert c.complete(MSG, "v2").text == "y" and len(seen) == 2


def test_429_honors_retry_after(tmp_path):
    c, stats, _, sleeps = make(tmp_path, [(429, {}, {"Retry-After": "7"}), (200, chat_payload("ok"), {})])
    assert c.complete(MSG, "v1").text == "ok"
    assert sleeps == [7.0] and stats.rate_limited == 1 and stats.retries == 1 and stats.requests == 2


def test_5xx_backoff_then_give_up(tmp_path):
    c, stats, seen, sleeps = make(tmp_path, [(503, {}, {})] * 6)
    with pytest.raises(LLMError, match="gave up after 6 attempts"):
        c.complete(MSG, "v1")
    assert len(seen) == 6 and len(sleeps) == 5 and all(0 < s <= 120 for s in sleeps)


def test_4xx_is_not_retried(tmp_path):
    c, _, seen, sleeps = make(tmp_path, [(401, {"error": "bad key"}, {})])
    with pytest.raises(LLMError, match="HTTP 401"):
        c.complete(MSG, "v1")
    assert len(seen) == 1 and sleeps == []


def test_budget_exhausted_mid_retry(tmp_path):
    c, _, _, _ = make(tmp_path, [(429, {}, {}), (200, chat_payload("ok"), {})], budget=1)
    with pytest.raises(BudgetExhausted):
        c.complete(MSG, "v1")


def test_offline_hit_and_miss(tmp_path):
    online, _, _, _ = make(tmp_path, [(200, chat_payload("cached"), {})])
    online.complete(MSG, "v1")
    off, stats, _, _ = make(tmp_path, [], offline=True, api_key=None)
    assert off.complete(MSG, "v1").text == "cached" and stats.requests == 0
    with pytest.raises(CacheMiss):
        off.complete([{"role": "user", "content": "new"}], "v1")


def test_missing_key_is_clear_error(tmp_path):
    c, _, _, _ = make(tmp_path, [], api_key=None)
    with pytest.raises(LLMError, match="SHAREDLLM_API_KEY is not set"):
        c.complete(MSG, "v1")


def test_malformed_payload_is_llm_error(tmp_path):
    c, _, _, _ = make(tmp_path, [(200, {"nope": 1}, {})])
    with pytest.raises(LLMError, match="malformed response"):
        c.complete(MSG, "v1")


def test_json_mode_off_omits_response_format(tmp_path):
    c, _, seen, _ = make(tmp_path, [(200, chat_payload("x"), {})], json_mode=False)
    c.complete(MSG, "v1")
    assert "response_format" not in json.loads(seen[0].content)


def test_retry_delay_bounds():
    rng = random.Random(1)
    assert retry_delay(1, "3", rng) == 3.0
    assert retry_delay(1, "999", rng) == 120.0
    assert 1.0 <= retry_delay(1, None, rng) <= 2.0
    assert 60.0 <= retry_delay(10, "soon", rng) <= 120.0


def test_cache_put_is_atomic_and_readable(tmp_path):
    cache = Cache(tmp_path / "c")
    k = Cache.key("v", {"model": "m"}, MSG)
    assert cache.get(k) is None
    cache.put(k, {"x": "ü"})
    assert cache.get(k) == {"x": "ü"} and not list((tmp_path / "c").glob("*.tmp"))
```

`tests/test_config.py` — append:

```python
from lisa.common.config import load_eval_settings, load_llm_settings


def test_llm_settings_from_yaml_and_env(monkeypatch, tmp_path):
    (tmp_path / "settings.yaml").write_text(
        "llm:\n  base_url: https://x/v1\n  model: m-1\n  window_pages: 4\neval:\n  match_threshold: 0.4\n"
        "  fewshot_units: [a__u1of1]\n", encoding="utf-8")
    monkeypatch.setenv("SHAREDLLM_API_KEY", "sek")
    s = load_llm_settings(config_dir=tmp_path, env_file=None)
    assert (s.base_url, s.model, s.api_key, s.window_pages, s.temperature) == ("https://x/v1", "m-1", "sek", 4, 0.0)
    assert s.max_requests_per_run == 300 and s.include_unverified_in_graph is False and s.json_mode is True
    e = load_eval_settings(config_dir=tmp_path)
    assert e.match_threshold == 0.4 and e.fewshot_units == ("a__u1of1",)


def test_repo_llm_settings_have_model_and_fewshot(monkeypatch):
    monkeypatch.delenv("SHAREDLLM_API_KEY", raising=False)
    s = load_llm_settings(env_file=None)
    assert s.model == "z-ai/glm-flash-latest" and s.api_key is None
    assert load_eval_settings().fewshot_units == ("eoir_4018__u1of1", "scotus_2017_17-269__u1of1")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pip install "httpx>=0.27" && .venv/Scripts/python -m pytest tests/test_llm_client.py tests/test_config.py -v`
Expected: FAIL — `ImportError: cannot import name 'LLMSettings'`.

- [ ] **Step 3: Implement config**

`pyproject.toml`: `dependencies = ["pyyaml>=6", "python-dotenv>=1.0", "neo4j>=5.20", "httpx>=0.27"]`

`config/settings.yaml` — append:

```yaml
llm:
  base_url: https://api.sharedllm.com/openai/v1
  model: z-ai/glm-flash-latest
  temperature: 0
  max_output_tokens: 8192
  timeout_s: 180
  max_requests_per_run: 300
  window_pages: 3
  edge_split_chars: 60000
  include_unverified_in_graph: false
  json_mode: true
eval:
  match_threshold: 0.3
  fewshot_units: [eoir_4018__u1of1, scotus_2017_17-269__u1of1]
```

`.env.example` — append:

```
# SharedLLM gateway key for the Phase 2 LLM tier (secret; never commit)
SHAREDLLM_API_KEY=sk-sharedllm-REPLACE-ME
```

`src/lisa/common/config.py` — append:

```python
@dataclass(frozen=True)
class LLMSettings:
    base_url: str
    model: str
    api_key: str | None
    temperature: float
    max_output_tokens: int
    timeout_s: float
    max_requests_per_run: int
    window_pages: int
    edge_split_chars: int
    include_unverified_in_graph: bool
    json_mode: bool


@dataclass(frozen=True)
class EvalSettings:
    match_threshold: float
    fewshot_units: tuple[str, ...]


def load_llm_settings(config_dir: Path = CONFIG_DIR, env_file: Path | None = REPO_ROOT / ".env") -> LLMSettings:
    if env_file is not None:
        load_dotenv(env_file)
    s = _yaml(config_dir / "settings.yaml").get("llm") or {}
    return LLMSettings(
        base_url=s["base_url"],
        model=s["model"],
        api_key=os.environ.get("SHAREDLLM_API_KEY") or None,
        temperature=float(s.get("temperature", 0)),
        max_output_tokens=int(s.get("max_output_tokens", 8192)),
        timeout_s=float(s.get("timeout_s", 180)),
        max_requests_per_run=int(s.get("max_requests_per_run", 300)),
        window_pages=int(s.get("window_pages", 3)),
        edge_split_chars=int(s.get("edge_split_chars", 60000)),
        include_unverified_in_graph=bool(s.get("include_unverified_in_graph", False)),
        json_mode=bool(s.get("json_mode", True)),
    )


def load_eval_settings(config_dir: Path = CONFIG_DIR) -> EvalSettings:
    s = _yaml(config_dir / "settings.yaml").get("eval") or {}
    return EvalSettings(match_threshold=float(s.get("match_threshold", 0.3)),
                        fewshot_units=tuple(s.get("fewshot_units") or ()))
```

- [ ] **Step 4: Implement cache, budget, client**

`src/lisa/llm/cache.py`:

```python
"""Disk cache of raw LLM responses: out/llm_cache/<sha256>.json. Reruns are free; --offline serves only from here."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path


class Cache:
    def __init__(self, root: Path):
        self.root = Path(root)

    @staticmethod
    def key(prompt_version: str, params: dict, messages: list[dict]) -> str:
        blob = json.dumps({"v": prompt_version, "p": params, "m": messages}, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def get(self, key: str) -> dict | None:
        p = self.root / f"{key}.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    def put(self, key: str, payload: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.root / f"{key}.tmp"
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.root / f"{key}.json")
```

`src/lisa/llm/budget.py`:

```python
"""Per-run request budget, run statistics and retry delays."""
from __future__ import annotations

import random
from dataclasses import asdict, dataclass, field

BASE_DELAY_S = 2.0
MAX_DELAY_S = 120.0


class BudgetExhausted(RuntimeError):
    pass


class Budget:
    def __init__(self, max_requests: int):
        self.max_requests = max_requests
        self.used = 0

    def charge(self) -> None:
        if self.used >= self.max_requests:
            raise BudgetExhausted(f"request budget of {self.max_requests} reached")
        self.used += 1


@dataclass
class RunStats:
    requests: int = 0
    cache_hits: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    rate_limited: int = 0
    retries: int = 0
    repairs: int = 0
    truncations: int = 0
    failed: list[dict] = field(default_factory=list)
    schema_rejects: list[dict] = field(default_factory=list)

    def to_json(self) -> dict:
        return asdict(self)


def retry_delay(attempt: int, retry_after: str | None, rng: random.Random) -> float:
    if retry_after:
        try:
            return min(float(retry_after), MAX_DELAY_S)
        except ValueError:
            pass
    return min(MAX_DELAY_S, BASE_DELAY_S * 2 ** (attempt - 1)) * (0.5 + rng.random() / 2)
```

`src/lisa/llm/client.py`:

```python
"""SharedLLM chat client (OpenAI-compatible /chat/completions) with disk cache, request budget and backoff."""
from __future__ import annotations

import random
import time
from dataclasses import dataclass

import httpx

from lisa.common.config import LLMSettings
from lisa.llm.budget import Budget, RunStats, retry_delay
from lisa.llm.cache import Cache

MAX_ATTEMPTS = 6


class LLMError(RuntimeError):
    pass


class CacheMiss(LLMError):
    pass


@dataclass(frozen=True)
class Completion:
    text: str
    finish_reason: str
    input_tokens: int
    output_tokens: int
    cached: bool


def _completion(payload: dict, cached: bool) -> Completion:
    try:
        choice = payload["choices"][0]
        text = choice["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        raise LLMError(f"malformed response: {str(payload)[:200]}") from None
    usage = payload.get("usage") or {}
    return Completion(text, choice.get("finish_reason") or "stop", int(usage.get("prompt_tokens") or 0),
                      int(usage.get("completion_tokens") or 0), cached)


class LLMClient:
    def __init__(self, settings: LLMSettings, cache: Cache, budget: Budget, stats: RunStats, *,
                 offline: bool = False, transport: httpx.BaseTransport | None = None, sleep=time.sleep,
                 rng: random.Random | None = None):
        self.settings, self.cache, self.budget, self.stats = settings, cache, budget, stats
        self.offline, self.sleep, self.rng = offline, sleep, rng or random.Random()
        self._http = None
        if not offline and settings.api_key:
            self._http = httpx.Client(
                base_url=settings.base_url.rstrip("/") + "/", timeout=settings.timeout_s, transport=transport,
                headers={"X-SharedLLM-Key": settings.api_key, "Authorization": f"Bearer {settings.api_key}"})

    def _params(self) -> dict:
        p = {"model": self.settings.model, "temperature": self.settings.temperature,
             "max_tokens": self.settings.max_output_tokens}
        if self.settings.json_mode:
            p["response_format"] = {"type": "json_object"}
        return p

    def complete(self, messages: list[dict], prompt_version: str) -> Completion:
        params = self._params()
        key = Cache.key(prompt_version, params, messages)
        hit = self.cache.get(key)
        if hit is not None:
            self.stats.cache_hits += 1
            return _completion(hit, cached=True)
        if self.offline:
            raise CacheMiss(f"offline and not cached: {key[:12]}")
        if self._http is None:
            raise LLMError("SHAREDLLM_API_KEY is not set (add it to .env)")
        body = {**params, "messages": messages}
        status, err = None, ""
        for attempt in range(1, MAX_ATTEMPTS + 1):
            self.budget.charge()
            self.stats.requests += 1
            retry_after = None
            try:
                r = self._http.post("chat/completions", json=body)
            except httpx.TransportError as e:
                status, err = None, f"{type(e).__name__}: {e}"
            else:
                if r.status_code == 200:
                    payload = r.json()
                    self.cache.put(key, payload)
                    c = _completion(payload, cached=False)
                    self.stats.input_tokens += c.input_tokens
                    self.stats.output_tokens += c.output_tokens
                    return c
                status, err, retry_after = r.status_code, r.text[:300], r.headers.get("Retry-After")
                if status == 429:
                    self.stats.rate_limited += 1
                elif status < 500:
                    raise LLMError(f"HTTP {status}: {err}")
            if attempt < MAX_ATTEMPTS:
                self.stats.retries += 1
                self.sleep(retry_delay(attempt, retry_after, self.rng))
        raise LLMError(f"gave up after {MAX_ATTEMPTS} attempts: {status} {err}")
```

Note: a malformed 200 payload is cached and then raises `LLMError`; delete that cache file by hand if it ever happens (the error message is the signal).

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pip install -e ".[dev]" && .venv/Scripts/python -m pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit and push**

```bash
git add pyproject.toml config/settings.yaml .env.example src/lisa/common/config.py src/lisa/llm tests/fakes.py tests/test_llm_client.py tests/test_config.py
git commit -m "feat: SharedLLM client with disk cache, request budget and 429 backoff"
git push
```

---

### Task 5: JSON calls, prompts and few-shot blocks

**Files:**
- Create: `src/lisa/extract/calljson.py`, `src/lisa/extract/prompts.py`, `src/lisa/extract/prompts/nodes.md`, `src/lisa/extract/prompts/edges.md`, `src/lisa/extract/fewshot.py`
- Modify: `pyproject.toml` (package data for the prompt `.md` and signatures `.json`)
- Test: `tests/test_calljson.py`, `tests/test_prompts.py`

**Interfaces:**
- Consumes: `FakeClient`, `RunStats`, `Unit`, `UnitPage`, `render_pages`, `SIGNATURES`.
- Produces:
  - `parse_json(text: str) -> object` (raises `ValueError`)
  - `call_json(client, messages, prompt_version, key: str, stats: RunStats) -> list` — raises `Truncated`, `ExtractionFailed`
  - `load_prompt(name: str) -> tuple[str, str]` → `(version, body)`
  - `build_system(name: str, fewshot: str) -> tuple[str, str]` → `(version, system_text)` with `{{FEWSHOT}}` and `{{SIGNATURES}}` filled
  - `node_examples(gold: dict, unit: Unit, max_pages: int = 2) -> str`; `edge_examples(gold: dict, unit: Unit, max_pages: int = 2) -> str`
  - `build_fewshot(golds: dict[str, dict], units: dict[str, Unit], ids: Sequence[str]) -> tuple[str, str]` → `(nodes_block, edges_block)`

- [ ] **Step 1: Write the failing tests**

`tests/test_calljson.py`:

```python
import pytest

from fakes import FakeClient
from lisa.extract.calljson import ExtractionFailed, Truncated, call_json, parse_json
from lisa.llm.budget import RunStats

MSG = [{"role": "user", "content": "x"}]


def test_parse_json_plain_fenced_and_prose():
    assert parse_json('{"nodes": []}') == {"nodes": []}
    assert parse_json('```json\n{"nodes": [1]}\n```') == {"nodes": [1]}
    assert parse_json('Here you go:\n{"nodes": [2]}\nThanks!') == {"nodes": [2]}


def test_parse_json_garbage_raises():
    with pytest.raises(ValueError):
        parse_json("no json here")


def test_call_json_returns_list():
    assert call_json(FakeClient(lambda m: '{"nodes": [{"a": 1}]}'), MSG, "v", "nodes", RunStats()) == [{"a": 1}]


def test_call_json_repairs_once_then_succeeds():
    replies = iter(['{"nodes": [', '{"nodes": [{"a": 2}]}'])
    stats = RunStats()
    fc = FakeClient(lambda m: next(replies))
    assert call_json(fc, MSG, "v", "nodes", stats) == [{"a": 2}]
    assert stats.repairs == 1 and "not valid" in fc.calls[1][-1]["content"]


def test_call_json_repairs_once_then_fails():
    with pytest.raises(ExtractionFailed):
        call_json(FakeClient(lambda m: '{"edges": []}'), MSG, "v", "nodes", RunStats())


def test_call_json_truncation():
    stats = RunStats()
    with pytest.raises(Truncated):
        call_json(FakeClient(lambda m: ('{"nodes": [', "length")), MSG, "v", "nodes", stats)
    assert stats.truncations == 1
```

`tests/test_prompts.py`:

```python
from lisa.extract.fewshot import build_fewshot, edge_examples, node_examples
from lisa.extract.prompts import build_system, load_prompt
from lisa.extract.units import Unit, UnitPage

UNIT = Unit(unit_id="g1__u1of1", case_id="g1", domain="immigration", header="CASE_ID: g1\n",
            pages=(UnitPage(1, None, "Page one text."), UnitPage(2, None, "Page two text."),
                   UnitPage(3, None, "Page three text.")),
            raw_pages={1: "Page one text.", 2: "Page two text.", 3: "Page three text."}, segments=(),
            repeated_page=None)
GOLD = {"nodes": [
    {"id": "g1:opinion:majority", "type": "opinion", "label": "Majority", "summary": "s", "part": "majority",
     "author": "Jones", "evidence": [{"page": 1, "quote": "Page one text.", "verified": True}], "attrs": {},
     "case_id": "g1", "dataset": "immigration"},
    {"id": "g1:holding:h", "type": "holding", "label": "Holding", "summary": "s", "part": "majority",
     "author": None, "evidence": [{"page": 2, "quote": "Page two text."}], "attrs": {}},
    {"id": "g1:fact:late", "type": "fact", "label": "Late fact", "summary": "s", "part": "majority",
     "author": None, "evidence": [{"page": 3, "quote": "Page three text."}], "attrs": {"kind": "fact"}}],
    "edges": [
        {"source": "g1:opinion:majority", "target": "g1:holding:h", "relation": "holds", "stance": None,
         "basis": "explicit", "part": "majority", "evidence": [{"page": 2, "quote": "Page two text."}],
         "confidence": 0.9, "attrs": {}, "case_id": "g1"},
        {"source": "g1:opinion:majority", "target": "g1:fact:late", "relation": "states_fact", "stance": None,
         "basis": "explicit", "part": "majority", "evidence": [], "confidence": 0.9, "attrs": {}}]}


def test_prompts_have_versions_and_placeholders():
    for name in ("nodes", "edges"):
        version, body = load_prompt(name)
        assert version.startswith(f"{name}-v") and "{{FEWSHOT}}" in body
    assert "{{SIGNATURES}}" in load_prompt("edges")[1]


def test_build_system_fills_placeholders():
    _, text = build_system("edges", "EXAMPLE")
    assert "EXAMPLE" in text and "{{" not in text and "reasoning -supports-> holding" in text


def test_node_examples_keep_only_pages_shown_and_strip_gold_fields():
    block = node_examples(GOLD, UNIT, max_pages=2)
    assert "Page two text." in block and "Page three text." not in block
    assert '"label": "Majority"' in block and '"label": "Late fact"' not in block
    assert "case_id" not in block and "verified" not in block and "g1:opinion" not in block


def test_edge_examples_use_catalog_ids_and_drop_out_of_window_edges():
    block = edge_examples(GOLD, UNIT, max_pages=2)
    assert '"id": "g1:holding:h"' in block and '"relation": "holds"' in block
    assert "states_fact" not in block


def test_build_fewshot_skips_missing_units():
    nodes, edges = build_fewshot({"g1__u1of1": GOLD}, {"g1__u1of1": UNIT}, ["g1__u1of1", "absent__u1of1"])
    assert nodes.count("### Example input") == 1 and edges.count("### Example input") == 1
    assert build_fewshot({}, {}, []) == ("", "")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_calljson.py tests/test_prompts.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lisa.extract.calljson'`

- [ ] **Step 3: Implement calljson**

`src/lisa/extract/calljson.py`:

```python
"""Ask the model for {"<key>": [...]} and get a Python list back, with one repair retry."""
from __future__ import annotations

import json
import re

from lisa.llm.budget import RunStats


class Truncated(Exception):
    """The reply hit the output-token limit (finish_reason == "length")."""


class ExtractionFailed(Exception):
    """The reply was still unusable after one repair retry."""


def parse_json(text: str):
    t = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", t, re.S)
    if m:
        t = m.group(1).strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        i, j = t.find("{"), t.rfind("}")
        if 0 <= i < j:
            return json.loads(t[i:j + 1])
        raise


def call_json(client, messages: list[dict], prompt_version: str, key: str, stats: RunStats) -> list:
    msgs = list(messages)
    for attempt in (1, 2):
        c = client.complete(msgs, prompt_version)
        if c.finish_reason == "length":
            stats.truncations += 1
            raise Truncated()
        try:
            obj = parse_json(c.text)
            items = obj.get(key) if isinstance(obj, dict) else None
            if not isinstance(items, list):
                raise ValueError(f'expected a JSON object with a "{key}" list')
            return items
        except ValueError as e:
            if attempt == 2:
                raise ExtractionFailed(str(e)) from e
            stats.repairs += 1
            msgs = msgs + [{"role": "assistant", "content": c.text[:4000]},
                           {"role": "user", "content": f"Your reply was not valid: {e}. Reply again with only "
                                                       f'the JSON object {{"{key}": [...]}} and nothing else.'}]
    raise AssertionError("unreachable")
```

- [ ] **Step 4: Write the prompts**

`src/lisa/extract/prompts/nodes.md`:

```markdown
PROMPT_VERSION: nodes-v1
You build a legal knowledge graph from US court and agency decisions. You receive the case header and a window of
consecutive pages. Each page starts with a line `===== [[PAGE n | source_pdf_page x]] =====`. Lines
`<<<PART BEGINS: part | label | seg_id=...>>>` mark where an opinion part starts; the header line
`PART ACTIVE AT TOP OF WINDOW` tells you which part is running when the window begins.

Extract the nodes found in these pages.

## Node types
- `opinion` — one per opinion part that appears (majority, concurrence, dissent, per curiam, headnote, syllabus).
  label like "Majority opinion (Jones)". attrs: `author`, `joined_by` (list of surnames), `not_authoritative: true`
  for headnote/syllabus.
- `issue` — a legal question the tribunal must decide.
- `fact` — a fact or procedural step the opinion relies on. attrs.kind = `fact` | `procedural_posture`.
- `rule` — a legal rule, standard, test, canon, or quoted statutory text. attrs.rule_kind = `doctrine` |
  `statute_text` | `standard` | `canon` | `test` | `other`; attrs.doctrine = a short canonical doctrine name,
  2-6 lower-case words (e.g. "categorical approach", "third-party doctrine", "chevron deference").
- `holding` — the answer an opinion gives to an issue.
- `reasoning` — one step of argument that supports a holding.
- `outcome` — the disposition. attrs.disposition (e.g. "affirmed", "dismissed", "reversed and remanded"),
  attrs.vote when stated.
- `authority_ref` — a cited case, statute, regulation or constitutional provision that the reasoning uses.
  attrs.cite_string = the citation as printed (e.g. "Matter of Michel, 21 I&N Dec. 1101"),
  attrs.kind = `case` | `statute` | `regulation` | `constitution` | `other`.

## Fields of every node
- `type`, `label` (at most 12 words), `summary` (one sentence),
- `part` — the part the text belongs to: one of headnote, syllabus, front_matter_or_syllabus, majority, per_curiam,
  concurrence, dissent, concurrence_and_dissent, body_unsegmented,
- `author` — surname of the judge who wrote that part, or null,
- `evidence` — 1 or 2 items `{"page": n, "quote": "..."}`. The quote is copied character-for-character from ONE
  page: 8 to 40 consecutive words, no ellipses, no paraphrase, no added words. `page` is the n of that page's marker.
- `confidence` — 0 to 1, how sure you are the node is correct,
- `attrs` — as listed above (use {} if none). Headnote and syllabus items get attrs.not_authoritative = true.

## Rules
- Use only the pages shown. If the header says the first page is repeated from the previous unit, do not extract
  anything that appears only on that page.
- One node per distinct idea; do not split one holding into several nodes or merge two issues into one.
- Do not invent citations: an authority_ref must be cited in the text.
- Reply with a single JSON object `{"nodes": [...]}` and nothing else.

{{FEWSHOT}}
```

`src/lisa/extract/prompts/edges.md`:

```markdown
PROMPT_VERSION: edges-v1
You build a legal knowledge graph from US court and agency decisions. You receive the case text (pages marked
`===== [[PAGE n | ...]] =====`) and a NODE CATALOG of nodes already extracted from it. Extract the relations
(edges) between catalog nodes that the text states or clearly implies.

## Relations
- `presents_issue` opinion -> issue; `states_fact` opinion -> fact; `states_rule` opinion -> rule;
  `holds` opinion -> holding; `has_outcome` opinion -> outcome
- `supports` reasoning -> holding
- `applies_rule` holding or reasoning -> rule
- `relies_on` reasoning, rule, holding or fact -> authority_ref. Set `stance`:
  `follows` (treated as controlling and applied), `distinguishes` (held not to apply on these facts),
  `overrules` (expressly overruled), `criticizes` (disapproved but not overruled),
  `relies_on` (cited as support), `cites_without_treatment` (mentioned only)
- `relevant_to` fact -> issue; `resolves` holding -> issue
- `agrees_with` / `disagrees_with` between items of different opinion parts (e.g. a dissent's holding disagrees
  with the majority's holding)

Only these (source type, relation, target type) combinations are allowed:
{{SIGNATURES}}

## Fields of every edge
`source`, `target` (catalog ids, copied exactly), `relation`, `stance` (relies_on only, else null),
`basis` (`explicit` if the text says it, `inferred` if you infer it; inferred edges need
attrs.inference_reason), `part`, `evidence` (1 item `{"page": n, "quote": "..."}`, 8 to 30 consecutive words copied
exactly from one page), `confidence` (0 to 1), `attrs`.

## Rules
- Use only ids from the catalog. Only output edges whose source id is listed under SOURCE NODES.
- Reply with a single JSON object `{"edges": [...]}` and nothing else.

{{FEWSHOT}}
```

`src/lisa/extract/prompts.py`:

```python
"""Prompt texts (versioned) and system-message assembly."""
from __future__ import annotations

import re
from pathlib import Path

from lisa.extract.schema import SIGNATURES

PROMPT_DIR = Path(__file__).with_name("prompts")


def load_prompt(name: str) -> tuple[str, str]:
    text = (PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8")
    first, _, body = text.partition("\n")
    m = re.fullmatch(r"PROMPT_VERSION:\s*(\S+)", first.strip())
    if not m:
        raise ValueError(f"{name}.md: first line must be 'PROMPT_VERSION: <id>'")
    return m[1], body.strip()


def build_system(name: str, fewshot: str) -> tuple[str, str]:
    version, body = load_prompt(name)
    sigs = "\n".join(f"- {s} -{r}-> {t}" for s, r, t in sorted(SIGNATURES))
    examples = f"## Examples\n{fewshot}" if fewshot else ""
    return version, body.replace("{{SIGNATURES}}", sigs).replace("{{FEWSHOT}}", examples).strip()
```

`pyproject.toml` — append:

```toml
[tool.setuptools.package-data]
"lisa.extract" = ["prompts/*.md", "schema_signatures.json"]
```

- [ ] **Step 5: Implement few-shot builder**

`src/lisa/extract/fewshot.py`:

```python
"""Few-shot blocks built at run time from two fixed gold units (never committed; excluded from scoring)."""
from __future__ import annotations

import json
from typing import Sequence

from lisa.extract.units import Unit, render_pages

NODE_KEYS = ("type", "label", "summary", "part", "author", "attrs")
EDGE_KEYS = ("source", "target", "relation", "stance", "basis", "part", "attrs")


def _ev(item: dict) -> list[dict]:
    return [{"page": e["page"], "quote": e["quote"]} for e in item.get("evidence") or []]


def _in_window(item: dict, pages: set[int]) -> bool:
    ev = item.get("evidence") or []
    return bool(ev) and all(e.get("page") in pages for e in ev)


def _window(gold: dict, unit: Unit, max_pages: int):
    pages = unit.pages[:max_pages]
    keep = {p.page for p in pages}
    nodes = [n for n in gold["nodes"] if _in_window(n, keep)]
    return pages, keep, nodes


def node_examples(gold: dict, unit: Unit, max_pages: int = 2) -> str:
    pages, _, nodes = _window(gold, unit, max_pages)
    out = [{**{k: n.get(k) for k in NODE_KEYS[:5]}, "evidence": _ev(n), "attrs": n.get("attrs") or {}}
           for n in nodes]
    return (f"### Example input\n{unit.header}{render_pages(pages)}\n### Example output\n"
            + json.dumps({"nodes": out}, ensure_ascii=False))


def edge_examples(gold: dict, unit: Unit, max_pages: int = 2) -> str:
    pages, keep, nodes = _window(gold, unit, max_pages)
    ids = {n["id"] for n in nodes}
    cat = [{"id": n["id"], "type": n["type"], "label": n["label"], "part": n.get("part"),
            "pages": sorted({e["page"] for e in n["evidence"]})} for n in nodes]
    edges = [{**{k: e.get(k) for k in EDGE_KEYS[:6]}, "evidence": _ev(e), "confidence": e.get("confidence"),
              "attrs": e.get("attrs") or {}}
             for e in gold["edges"] if e["source"] in ids and e["target"] in ids and _in_window(e, keep)]
    return (f"### Example input\n{unit.header}{render_pages(pages)}\nNODE CATALOG:\n"
            + "\n".join(json.dumps(c, ensure_ascii=False) for c in cat)
            + "\nSOURCE NODES: all\n### Example output\n" + json.dumps({"edges": edges}, ensure_ascii=False))


def build_fewshot(golds: dict[str, dict], units: dict[str, Unit], ids: Sequence[str]) -> tuple[str, str]:
    present = [i for i in ids if i in golds and i in units]
    return ("\n\n".join(node_examples(golds[i], units[i]) for i in present),
            "\n\n".join(edge_examples(golds[i], units[i]) for i in present))
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pip install -e ".[dev]" && .venv/Scripts/python -m pytest -q`
Expected: all pass.

- [ ] **Step 7: Commit and push**

```bash
git add pyproject.toml src/lisa/extract/calljson.py src/lisa/extract/prompts.py src/lisa/extract/prompts src/lisa/extract/fewshot.py tests/test_calljson.py tests/test_prompts.py
git commit -m "feat: JSON call helper, versioned node/edge prompts, gold few-shot builder"
git push
```

---

### Task 6: Stage 1 — nodes

**Files:**
- Create: `src/lisa/extract/stage_nodes.py`
- Test: `tests/test_stage_nodes.py`

**Interfaces:**
- Consumes: `Unit`, `UnitPage`, `render_pages`, `active_part` (Task 1); `PageIndex`, `verify_item`, `evidence_strength` (Task 2); `validate_node` (Task 3); `RunStats` (Task 4); `call_json`, `Truncated`, `ExtractionFailed` (Task 5).
- Produces:
  - `slug(s: str, n: int = 60) -> str`
  - `make_windows(unit: Unit, window_pages: int) -> list[tuple[UnitPage, ...]]`
  - `window_message(unit: Unit, pages: Sequence[UnitPage]) -> str`
  - `dedupe(nodes: list[dict]) -> list[dict]`
  - `assign_ids(case_id: str, nodes: list[dict]) -> list[dict]` — adds `id`, `case_id`
  - `extract_nodes(unit: Unit, client, system: str, version: str, window_pages: int, stats: RunStats) -> list[dict]` — verified, deduped, with ids

- [ ] **Step 1: Write the failing tests**

`tests/test_stage_nodes.py`:

```python
import json
import re

from fakes import FakeClient
from lisa.extract.stage_nodes import assign_ids, dedupe, extract_nodes, make_windows, slug, window_message
from lisa.extract.units import Segment, Unit, UnitPage
from lisa.llm.budget import RunStats

TEXTS = {i: f"Page {i} says the respondent number {i} was admitted lawfully in the year {1990 + i}." for i in range(1, 6)}


def unit(n=5, repeated=None):
    pages = tuple(UnitPage(i, None, TEXTS[i]) for i in range(1, n + 1))
    seg = Segment("c#s0", "majority", "Opinion", 1, 0, n, 10)
    return Unit("c__u1of1", "c", "immigration", "CASE_ID: c\n", pages, {i: TEXTS[i] for i in range(1, n + 1)},
                (seg,), repeated)


def node(page, label="Admission", type_="fact", conf=0.8):
    return {"type": type_, "label": label, "summary": "", "part": "majority", "author": None, "confidence": conf,
            "evidence": [{"page": page, "quote": TEXTS[page][:50]}], "attrs": {}}


def test_slug():
    assert slug("Section 212(h) waiver — LPR!") == "section_212_h_waiver_lpr"
    assert slug("!!!") == "x"


def test_make_windows_overlap_one_page():
    assert [[p.page for p in w] for w in make_windows(unit(5), 3)] == [[1, 2, 3], [3, 4, 5]]
    assert [[p.page for p in w] for w in make_windows(unit(2), 3)] == [[1, 2]]
    assert [[p.page for p in w] for w in make_windows(unit(4), 3)] == [[1, 2, 3], [3, 4]]


def test_window_message_has_header_part_and_pages():
    msg = window_message(unit(5), unit(5).pages[2:4])
    assert msg.startswith("CASE_ID: c\nPART ACTIVE AT TOP OF WINDOW (page 3): majority | Opinion\n")
    assert "[[PAGE 3 |" in msg and "[[PAGE 5 |" not in msg


def test_assign_ids_suffixes_collisions():
    out = assign_ids("c", [{"type": "fact", "label": "A b"}, {"type": "fact", "label": "a-b"},
                           {"type": "rule", "label": "a b"}])
    assert [n["id"] for n in out] == ["c:fact:a_b", "c:fact:a_b_2", "c:rule:a_b"]
    assert all(n["case_id"] == "c" for n in out)


def _verified(n):
    from lisa.extract.verify import PageIndex, verify_item
    return verify_item(n, PageIndex(TEXTS))


def test_dedupe_merges_overlapping_same_type():
    a, b = _verified(node(3, "Admission", conf=0.6)), _verified(node(3, "Lawful admission", conf=0.9))
    [m] = dedupe([a, b])
    assert m["confidence"] == 0.9 and m["label"] == "Admission" and len(m["evidence"]) == 1


def test_dedupe_merges_equal_labels_and_unions_evidence():
    a, b = _verified(node(1, "Admission")), _verified(node(2, "admission"))
    [m] = dedupe([a, b])
    assert sorted(e["page"] for e in m["evidence"]) == [1, 2] and m["evidence_strength"] == "strong"


def test_dedupe_keeps_different_types_apart():
    assert len(dedupe([_verified(node(3, "A", "fact")), _verified(node(3, "B", "issue"))])) == 2


def reply_for_pages(messages):
    pages = [int(x) for x in re.findall(r"\[\[PAGE (\d+) \|", messages[-1]["content"])]
    return json.dumps({"nodes": [node(p, f"Fact on page {p}") for p in pages] + [{"type": "dog"}]})


def test_extract_nodes_end_to_end_with_rejects_and_overlap_dedupe():
    stats = RunStats()
    nodes = extract_nodes(unit(5), FakeClient(reply_for_pages), "SYS", "nodes-v1", 3, stats)
    assert [n["label"] for n in nodes] == [f"Fact on page {p}" for p in range(1, 6)]   # page 3 seen twice, merged
    assert all(n["provenance"] == "llm" and n["id"].startswith("c:fact:") for n in nodes)
    assert len(stats.schema_rejects) == 2 and stats.schema_rejects[0]["reason"] == "unknown node type: dog"


def test_extract_nodes_drops_items_only_on_repeated_page():
    nodes = extract_nodes(unit(3, repeated=1), FakeClient(reply_for_pages), "SYS", "v", 3, RunStats())
    assert [n["label"] for n in nodes] == ["Fact on page 2", "Fact on page 3"]


def test_truncated_window_is_split_in_half_once():
    def responder(messages):
        if messages[-1]["content"].count("[[PAGE") == 3:
            return ("{", "length")
        return reply_for_pages(messages)
    stats = RunStats()
    fc = FakeClient(responder)
    nodes = extract_nodes(unit(3), fc, "SYS", "v", 3, stats)
    assert len(fc.calls) == 3 and len(nodes) == 3 and stats.failed == []


def test_unsplittable_truncation_and_bad_json_are_recorded_as_failed():
    stats = RunStats()
    assert extract_nodes(unit(1), FakeClient(lambda m: ("{", "length")), "S", "v", 3, stats) == []
    assert stats.failed == [{"unit": "c__u1of1", "stage": "nodes", "pages": [1], "reason": "truncated"}]
    stats = RunStats()
    extract_nodes(unit(1), FakeClient(lambda m: "nope"), "S", "v", 3, stats)
    assert stats.failed[0]["reason"].startswith("invalid output")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_stage_nodes.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lisa.extract.stage_nodes'`

- [ ] **Step 3: Implement**

`src/lisa/extract/stage_nodes.py`:

```python
"""Stage 1: page windows -> gold-schema nodes, verified, deduped across windows, with code-assigned ids."""
from __future__ import annotations

import re
from typing import Sequence

from lisa.extract.calljson import ExtractionFailed, Truncated, call_json
from lisa.extract.schema import validate_node
from lisa.extract.units import Unit, UnitPage, active_part, render_pages
from lisa.extract.verify import PageIndex, evidence_strength, verify_item
from lisa.llm.budget import RunStats

MERGE_OVERLAP = 0.5


def slug(s: str, n: int = 60) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")[:n].strip("_") or "x"


def make_windows(unit: Unit, window_pages: int) -> list[tuple[UnitPage, ...]]:
    pages, step = unit.pages, max(window_pages - 1, 1)
    if len(pages) <= window_pages:
        return [pages]
    out, i = [], 0
    while True:
        out.append(pages[i:i + window_pages])
        if i + window_pages >= len(pages):
            return out
        i += step


def window_message(unit: Unit, pages: Sequence[UnitPage]) -> str:
    a = active_part(unit.segments, pages[0].page)
    part = f"PART ACTIVE AT TOP OF WINDOW (page {pages[0].page}): {a.part} | {a.label}\n" if a else ""
    return f"{unit.header}{part}{render_pages(pages)}\nExtract the nodes from the pages above."


def _norm(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", label.lower()).strip()


def _overlap(a: list[int], b: list[int]) -> float:
    inter = min(a[1], b[1]) - max(a[0], b[0])
    return inter / max(min(a[1] - a[0], b[1] - b[0]), 1) if inter > 0 else 0.0


def _spans(n: dict) -> list[list[int]]:
    return [e["span"] for e in n["evidence"] if e.get("span")]


def _same(a: dict, b: dict) -> bool:
    if a["type"] != b["type"]:
        return False
    if _norm(a["label"]) == _norm(b["label"]):
        return True
    return any(_overlap(x, y) >= MERGE_OVERLAP for x in _spans(a) for y in _spans(b))


def _merge(into: dict, other: dict) -> None:
    seen = {(e["page"], e["quote"]) for e in into["evidence"]}
    for e in other["evidence"]:
        if (e["page"], e["quote"]) not in seen and not any(
                e.get("span") and f.get("span") and _overlap(e["span"], f["span"]) >= MERGE_OVERLAP
                for f in into["evidence"]):
            into["evidence"].append(e)
            seen.add((e["page"], e["quote"]))
    if any(e["verified"] for e in into["evidence"]):
        into["evidence"] = [e for e in into["evidence"] if e["verified"]]
        into["provenance"], into["evidence_verified"] = "llm", True
    into["confidence"] = max(into["confidence"], other["confidence"])
    into["evidence_strength"] = evidence_strength([e["quote"] for e in into["evidence"] if e["verified"]])


def dedupe(nodes: list[dict]) -> list[dict]:
    out: list[dict] = []
    for n in nodes:
        for m in out:
            if _same(m, n):
                _merge(m, n)
                break
        else:
            out.append({**n, "evidence": list(n["evidence"])})
    return out


def assign_ids(case_id: str, nodes: list[dict]) -> list[dict]:
    seen, out = set(), []
    for n in nodes:
        base = f"{case_id}:{n['type']}:{slug(n['label'])}"
        nid, k = base, 2
        while nid in seen:
            nid, k = f"{base}_{k}", k + 1
        seen.add(nid)
        out.append({"id": nid, **n, "case_id": case_id})
    return out


def _window(unit, pages, client, system, version, stats, splits_left=1) -> list[dict]:
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": window_message(unit, pages)}]
    where = {"unit": unit.unit_id, "stage": "nodes", "pages": [p.page for p in pages]}
    try:
        items = call_json(client, msgs, version, "nodes", stats)
    except Truncated:
        if splits_left and len(pages) > 1:
            h = len(pages) // 2
            return (_window(unit, pages[:h], client, system, version, stats, splits_left - 1)
                    + _window(unit, pages[h:], client, system, version, stats, splits_left - 1))
        stats.failed.append({**where, "reason": "truncated"})
        return []
    except ExtractionFailed as e:
        stats.failed.append({**where, "reason": f"invalid output: {e}"})
        return []
    out = []
    for it in items:
        n, why = validate_node(it)
        if n is None:
            stats.schema_rejects.append({**where, "reason": why})
        else:
            out.append(n)
    return out


def extract_nodes(unit: Unit, client, system: str, version: str, window_pages: int, stats: RunStats) -> list[dict]:
    index = PageIndex(unit.raw_pages)
    raw: list[dict] = []
    for pages in make_windows(unit, window_pages):
        raw += _window(unit, pages, client, system, version, stats)
    nodes = [verify_item(n, index) for n in raw]
    if unit.repeated_page is not None:
        nodes = [n for n in nodes
                 if not (n["evidence_verified"] and all(e["page"] == unit.repeated_page for e in n["evidence"]))]
    return assign_ids(unit.case_id, dedupe(nodes))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_stage_nodes.py -v`
Expected: PASS (12 tests).

- [ ] **Step 5: Commit and push**

```bash
git add src/lisa/extract/stage_nodes.py tests/test_stage_nodes.py
git commit -m "feat: stage 1 node extraction over page windows with verification and dedupe"
git push
```

---

### Task 7: Stage 2 — edges

**Files:**
- Create: `src/lisa/extract/stage_edges.py`
- Test: `tests/test_stage_edges.py`

**Interfaces:**
- Consumes: `Unit`, `render_pages`; `PageIndex`, `verify_item`; `validate_edge`; `call_json`, `Truncated`, `ExtractionFailed`; `RunStats`.
- Produces:
  - `catalog(nodes: list[dict]) -> list[dict]` — `[{id, type, label, part, pages}]`
  - `plan_calls(unit: Unit, nodes: list[dict], split_chars: int) -> list[tuple[tuple[UnitPage, ...], list[dict], list[str] | None]]` — `(pages, catalog_nodes, source_ids or None=all)`
  - `extract_edges(unit: Unit, nodes: list[dict], client, system: str, version: str, split_chars: int, stats: RunStats) -> list[dict]`

- [ ] **Step 1: Write the failing tests**

`tests/test_stage_edges.py`:

```python
import json
import re

from fakes import FakeClient
from lisa.extract.stage_edges import catalog, extract_edges, plan_calls
from lisa.extract.units import Segment, Unit, UnitPage
from lisa.llm.budget import RunStats

TEXTS = {1: "The majority holds that the waiver under section 212(h) is unavailable to this respondent.",
         2: "The respondent relies on Matter of Michel, 21 I&N Dec. 1101, which we distinguish today.",
         3: "Board Member Rosenberg dissents because the statute plainly allows this waiver here."}
SEGS = (Segment("c#s0", "majority", "Jones", 1, 0, 3, 0), Segment("c#s1", "dissent", "Rosenberg", 3, 0, 3, 90))
UNIT = Unit("c__u1of1", "c", "immigration", "CASE_ID: c\n", tuple(UnitPage(i, None, t) for i, t in TEXTS.items()),
            dict(TEXTS), SEGS, None)


def n(id_, type_, part, page):
    return {"id": id_, "type": type_, "label": id_, "part": part,
            "evidence": [{"page": page, "quote": TEXTS[page][:40], "verified": True}]}


NODES = [n("c:reasoning:r", "reasoning", "majority", 1), n("c:holding:h", "holding", "majority", 1),
         n("c:authority_ref:michel", "authority_ref", "majority", 2), n("c:holding:d", "holding", "dissent", 3)]


def edge(src, tgt, rel, page, **kw):
    return {"source": src, "target": tgt, "relation": rel, "evidence": [{"page": page, "quote": TEXTS[page][:45]}],
            "confidence": 0.8, **kw}


GOOD = [edge("c:reasoning:r", "c:holding:h", "supports", 1),
        edge("c:reasoning:r", "c:authority_ref:michel", "relies_on", 2, stance="distinguishes"),
        edge("c:holding:d", "c:holding:h", "disagrees_with", 3)]


def test_catalog_shape():
    assert catalog(NODES)[2] == {"id": "c:authority_ref:michel", "type": "authority_ref",
                                 "label": "c:authority_ref:michel", "part": "majority", "pages": [2]}


def test_plan_single_call_when_small():
    [(pages, nodes, sources)] = plan_calls(UNIT, NODES, 60000)
    assert len(pages) == 3 and len(nodes) == 4 and sources is None


def test_plan_splits_per_part_when_large():
    calls = plan_calls(UNIT, NODES, 10)
    assert [[p.page for p in c[0]] for c in calls] == [[1, 2, 3], [3]]
    assert calls[0][2] == ["c:reasoning:r", "c:holding:h", "c:authority_ref:michel"]
    assert calls[1][2] == ["c:holding:d"]
    assert {x["id"] for x in calls[1][1]} == {"c:holding:d", "c:holding:h", "c:authority_ref:michel"}


def test_extract_edges_verified_and_typed():
    stats = RunStats()
    out = extract_edges(UNIT, NODES, FakeClient(lambda m: json.dumps({"edges": GOOD})), "S", "edges-v1", 60000, stats)
    assert [(e["relation"], e["stance"]) for e in out] == [("supports", None), ("relies_on", "distinguishes"),
                                                          ("disagrees_with", None)]
    assert all(e["provenance"] == "llm" and e["case_id"] == "c" for e in out)
    assert out[0]["part"] == "majority" and stats.schema_rejects == []


def test_edges_drop_unknown_ids_and_bad_signatures():
    bad = GOOD + [edge("c:ghost", "c:holding:h", "supports", 1),
                  edge("c:holding:h", "c:reasoning:r", "supports", 1),
                  GOOD[0]]   # duplicate
    stats = RunStats()
    out = extract_edges(UNIT, NODES, FakeClient(lambda m: json.dumps({"edges": bad})), "S", "v", 60000, stats)
    assert len(out) == 3
    assert [r["reason"] for r in stats.schema_rejects] == ["unknown node id: c:ghost",
                                                           "disallowed signature: holding -supports-> reasoning"]


def test_edges_outside_source_set_are_rejected_in_split_mode():
    stats = RunStats()
    out = extract_edges(UNIT, NODES, FakeClient(lambda m: json.dumps({"edges": GOOD})), "S", "v", 10, stats)
    assert sorted(e["relation"] for e in out) == ["disagrees_with", "relies_on", "supports"]
    assert sum(r["reason"] == "source not in this request" for r in stats.schema_rejects) == 3


def test_truncation_halves_source_ids():
    def responder(messages):
        user = messages[-1]["content"]
        if "SOURCE NODES: all" in user:
            return ("{", "length")
        ids = json.loads(re.search(r"SOURCE NODES: (\[.*\])", user).group(1))
        return json.dumps({"edges": [e for e in GOOD if e["source"] in ids]})
    fc, stats = FakeClient(responder), RunStats()
    out = extract_edges(UNIT, NODES, fc, "S", "v", 60000, stats)
    assert len(out) == 3 and len(fc.calls) == 3 and stats.failed == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_stage_edges.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lisa.extract.stage_edges'`

- [ ] **Step 3: Implement**

`src/lisa/extract/stage_edges.py`:

```python
"""Stage 2: unit text + node catalog -> gold-schema edges (signature-checked, verified)."""
from __future__ import annotations

import json

from lisa.extract.calljson import ExtractionFailed, Truncated, call_json
from lisa.extract.schema import validate_edge
from lisa.extract.units import Unit, UnitPage, render_pages
from lisa.extract.verify import PageIndex, verify_item
from lisa.llm.budget import RunStats

SHARED_TYPES = ("issue", "authority_ref", "holding", "outcome")   # visible to every part-split call
MAX_SPLIT_DEPTH = 3


def _pages(n: dict) -> list[int]:
    return sorted({e["page"] for e in n["evidence"] if isinstance(e.get("page"), int)})


def catalog(nodes: list[dict]) -> list[dict]:
    return [{"id": n["id"], "type": n["type"], "label": n["label"], "part": n.get("part"), "pages": _pages(n)}
            for n in nodes]


def plan_calls(unit: Unit, nodes: list[dict], split_chars: int):
    if len(unit.text) <= split_chars:
        return [(unit.pages, nodes, None)]
    calls, claimed = [], set()
    for seg in unit.segments:
        pages = tuple(p for p in unit.pages if seg.start_page <= p.page <= seg.end_page)
        if not pages:
            continue
        own = [n for n in nodes if n["id"] not in claimed and n.get("part") == seg.part
               and any(seg.start_page <= pg <= seg.end_page for pg in _pages(n))]
        if not own:
            continue
        claimed.update(n["id"] for n in own)
        own_ids = [n["id"] for n in own]
        shared = [n for n in nodes if n["type"] in SHARED_TYPES and n["id"] not in own_ids]
        calls.append((pages, own + shared, own_ids))
    rest = [n for n in nodes if n["id"] not in claimed]
    if rest:
        calls.append((unit.pages, nodes, [n["id"] for n in rest]))
    return calls


def _message(unit: Unit, pages, cat_nodes, sources) -> str:
    cat = "\n".join(json.dumps(c, ensure_ascii=False) for c in catalog(cat_nodes))
    src = "all" if sources is None else json.dumps(sources)
    return f"{unit.header}{render_pages(pages)}\nNODE CATALOG:\n{cat}\nSOURCE NODES: {src}\nExtract the edges."


def _call(unit, pages, cat_nodes, sources, client, system, version, stats, depth=0) -> list[tuple[dict, list | None]]:
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": _message(unit, pages, cat_nodes, sources)}]
    where = {"unit": unit.unit_id, "stage": "edges", "pages": [pages[0].page, pages[-1].page]}
    try:
        return [(it, sources) for it in call_json(client, msgs, version, "edges", stats)]
    except Truncated:
        ids = sources if sources is not None else [n["id"] for n in cat_nodes]
        if depth < MAX_SPLIT_DEPTH and len(ids) > 1:
            h = len(ids) // 2
            return (_call(unit, pages, cat_nodes, ids[:h], client, system, version, stats, depth + 1)
                    + _call(unit, pages, cat_nodes, ids[h:], client, system, version, stats, depth + 1))
        stats.failed.append({**where, "reason": "truncated"})
    except ExtractionFailed as e:
        stats.failed.append({**where, "reason": f"invalid output: {e}"})
    return []


def extract_edges(unit: Unit, nodes: list[dict], client, system: str, version: str, split_chars: int,
                  stats: RunStats) -> list[dict]:
    if not nodes:
        return []
    types = {n["id"]: n["type"] for n in nodes}
    parts = {n["id"]: n.get("part") for n in nodes}
    index = PageIndex(unit.raw_pages)
    out: dict[tuple[str, str, str], dict] = {}
    for pages, cat_nodes, sources in plan_calls(unit, nodes, split_chars):
        for raw, allowed in _call(unit, pages, cat_nodes, sources, client, system, version, stats):
            where = {"unit": unit.unit_id, "stage": "edges"}
            e, why = validate_edge(raw, types)
            if e is None:
                stats.schema_rejects.append({**where, "reason": why})
                continue
            if allowed is not None and e["source"] not in allowed:
                stats.schema_rejects.append({**where, "reason": "source not in this request"})
                continue
            key = (e["source"], e["relation"], e["target"])
            if key in out:
                continue
            e = verify_item(e, index)
            e["part"] = e["part"] or parts[e["source"]]
            e["case_id"] = unit.case_id
            out[key] = e
    return list(out.values())
```

Note on `test_edges_outside_source_set_are_rejected_in_split_mode`: with `split_chars=10` the fake returns all 3 GOOD edges for each of the 2 calls; each edge is accepted once in the call that owns its source and rejected (3 times total) in the other.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_stage_edges.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit and push**

```bash
git add src/lisa/extract/stage_edges.py tests/test_stage_edges.py
git commit -m "feat: stage 2 edge extraction with signature checks and part splitting"
git push
```

---

### Task 8: Mapping to the spec tier

**Files:**
- Create: `src/lisa/extract/mapping.py`
- Test: `tests/test_mapping.py`

**Interfaces:**
- Consumes: `lisa.graph.canon.canon`; `slug` (Task 6); `Record`.
- Produces:
  - `EXTRACTOR = "lisa.extract.mapping/1"`
  - `surname(author: str) -> str`; `judge_id(court: str | None, author: str) -> str`
  - `map_units(units: list[dict], records: list[Record], include_unverified: bool = False) -> dict` — `{"extractor", "nodes": [...], "edges": [...]}`; units are `{"unit_id", "case_id", "nodes", "edges"}` (both our output and raw gold files fit). Items without a `provenance` key (gold) count as verified.

- [ ] **Step 1: Write the failing tests**

`tests/test_mapping.py`:

```python
from lisa.extract.mapping import judge_id, map_units, surname
from lisa.graph.loader import Record

RECS = [Record("eoir_1", "immigration", "ALPHA", "22 I&N Dec. 100", {"court": "BIA"}, [], "", []),
        Record("eoir_2", "immigration", "BETA", "22 I&N Dec. 200", {"court": "BIA"}, [], "", [])]
EV = [{"page": 1, "quote": "We follow Matter of Beta", "verified": True}]


def nd(id_, type_, prov="llm", **kw):
    return {"id": id_, "type": type_, "label": kw.pop("label", id_), "part": kw.pop("part", "majority"),
            "author": kw.pop("author", None), "evidence": EV, "attrs": kw.pop("attrs", {}), "provenance": prov,
            "confidence": 0.9, **kw}


def ed(src, tgt, stance, prov="llm"):
    return {"source": src, "target": tgt, "relation": "relies_on", "stance": stance, "evidence": EV,
            "provenance": prov, "confidence": 0.8}


def unit(nodes, edges):
    return {"unit_id": "eoir_1__u1of1", "case_id": "eoir_1", "nodes": nodes, "edges": edges}


def by_type(g, t):
    return {(e["source"], e["target"]): e for e in g["edges"] if e["type"] == t}


def test_surname_and_judge_id():
    assert surname("Kennedy, J.") == "Kennedy"
    assert surname("Lory Diana Rosenberg, Board Member") == "Rosenberg"
    assert judge_id("BIA", "JONES") == "judge:bia:jones"
    assert judge_id(None, "Thomas") == "judge:unknown:thomas"


def test_stance_edges_resolve_in_corpus_and_external():
    nodes = [nd("r", "reasoning"),
             nd("a1", "authority_ref", attrs={"cite_string": "Matter of Beta, 22 I&N Dec. 200", "kind": "case"}),
             nd("a2", "authority_ref", attrs={"cite_string": "Pereira v. Sessions, 585 U.S. 198", "kind": "case"}),
             nd("a3", "authority_ref", attrs={"cite_string": "Old case, 9 I&N Dec. 1", "kind": "case"}),
             nd("s", "authority_ref", attrs={"cite_string": "8 U.S.C. § 1182(h)", "kind": "statute"})]
    edges = [ed("r", "a1", "follows"), ed("r", "a2", "distinguishes"), ed("r", "a3", "overrules"),
             ed("r", "s", "follows"), ed("r", "a2", "cites_without_treatment")]
    g = map_units([unit(nodes, edges)], RECS)
    assert set(by_type(g, "FOLLOWS")) == {("eoir_1", "eoir_2")}
    assert set(by_type(g, "DISTINGUISHES")) == {("eoir_1", "auth:us:585_198")}
    assert set(by_type(g, "OVERRULES")) == {("eoir_1", "auth:in_dec:9_1")}
    cites = by_type(g, "CITES_LLM")
    assert cites[("eoir_1", "auth:us:585_198")]["props"]["treatment"] == ["cites_without_treatment"]
    auth = {n["id"]: n for n in g["nodes"] if n["label"] == "Authority"}
    assert set(auth) == {"auth:us:585_198", "auth:in_dec:9_1"}
    assert auth["auth:us:585_198"]["props"]["kind"] == "case"
    f = by_type(g, "FOLLOWS")[("eoir_1", "eoir_2")]
    assert f["provenance"] == "llm" and f["evidence"][0]["quote"] == "We follow Matter of Beta"
    assert f["evidence"][0]["unit_id"] == "eoir_1__u1of1" and f["extractor"] == "lisa.extract.mapping/1"


def test_self_citation_is_skipped():
    nodes = [nd("r", "reasoning"),
             nd("a", "authority_ref", attrs={"cite_string": "22 I&N Dec. 100", "kind": "case"})]
    assert map_units([unit(nodes, [ed("r", "a", "follows")])], RECS)["edges"] == []


def test_judges_and_doctrines_merge_across_units():
    u1 = unit([nd("o", "opinion", author="Jones", part="dissent"),
               nd("k", "rule", label="Categorical approach rule", attrs={"doctrine": "Categorical Approach"})], [])
    u2 = {"unit_id": "eoir_2__u1of1", "case_id": "eoir_2",
          "nodes": [nd("k2", "rule", label="Categorical approach", attrs={})], "edges": []}
    g = map_units([u1, u2], RECS)
    ab = by_type(g, "AUTHORED_BY")
    assert ab[("eoir_1", "judge:bia:jones")]["props"]["part"] == ["dissent"]
    inv = by_type(g, "INVOKES_DOCTRINE")
    assert set(inv) == {("eoir_1", "doctrine:categorical_approach"), ("eoir_2", "doctrine:categorical_approach")}
    doc = [n for n in g["nodes"] if n["label"] == "Doctrine"]
    assert len(doc) == 1 and doc[0]["props"]["name"] == "categorical approach"


def test_unverified_excluded_unless_asked_and_gold_counts_as_verified():
    nodes = [nd("o", "opinion", prov="unverified", author="Jones")]
    assert map_units([unit(nodes, [])], RECS)["edges"] == []
    assert len(map_units([unit(nodes, [])], RECS, include_unverified=True)["edges"]) == 1
    gold = unit([{k: v for k, v in nd("o", "opinion", author="Jones").items() if k != "provenance"}], [])
    assert len(map_units([gold], RECS)["edges"]) == 1


def test_output_is_sorted_and_deterministic():
    nodes = [nd("o", "opinion", author="Jones"), nd("k", "rule", attrs={"doctrine": "x"})]
    a = map_units([unit(nodes, [])], RECS)
    assert a == map_units([unit(list(reversed(nodes)), [])], RECS)
    assert [e["type"] for e in a["edges"]] == ["AUTHORED_BY", "INVOKES_DOCTRINE"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_mapping.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lisa.extract.mapping'`

- [ ] **Step 3: Implement**

`src/lisa/extract/mapping.py`:

```python
"""Deterministic mapping from the gold-schema LLM tier to the spec tier, joined to Phase 1 node ids.

relies_on + stance follows/distinguishes/overrules -> FOLLOWS/DISTINGUISHES/OVERRULES (case -> Case or Authority)
other relies_on stances on case authorities        -> CITES_LLM (props.treatment)
opinion.author                                     -> Judge + AUTHORED_BY (props.part)
rule                                               -> Doctrine + INVOKES_DOCTRINE (id from attrs.doctrine or label)"""
from __future__ import annotations

import re

from lisa.extract.stage_nodes import slug
from lisa.graph.canon import canon
from lisa.graph.loader import Record

EXTRACTOR = "lisa.extract.mapping/1"
STANCE_EDGE = {"follows": "FOLLOWS", "distinguishes": "DISTINGUISHES", "overrules": "OVERRULES"}
MAX_EVIDENCE = 3
_TITLES = {"j", "jj", "c", "chief", "justice", "board", "member", "judge", "appellate", "immigration", "acting",
           "vice", "chairman", "chair", "deputy", "senior", "temporary"}


def surname(author: str) -> str:
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z'’\-]*", author) if w.lower().strip(".") not in _TITLES]
    return words[-1].title() if words else author.strip().title()


def judge_id(court: str | None, author: str) -> str:
    return f"judge:{slug(court or 'unknown', 30)}:{slug(surname(author), 30)}"


class _G:
    def __init__(self):
        self.nodes: dict[str, dict] = {}
        self.edges: dict[tuple[str, str, str], dict] = {}

    def node(self, nid: str, label: str, props: dict) -> None:
        self.nodes.setdefault(nid, {"id": nid, "label": label, "props": props, "provenance": "llm",
                                    "confidence": 1.0, "evidence": [], "extractor": EXTRACTOR})

    def edge(self, etype, src, tgt, item: dict, unit_id: str, props: dict | None = None) -> None:
        e = self.edges.setdefault((etype, src, tgt), {
            "type": etype, "source": src, "target": tgt, "props": {}, "provenance": "unverified",
            "confidence": 0.0, "evidence": [], "extractor": EXTRACTOR})
        for k, v in (props or {}).items():
            if v not in e["props"].setdefault(k, []):
                e["props"][k].append(v)
        if item.get("provenance", "llm") == "llm":
            e["provenance"] = "llm"
        e["confidence"] = max(e["confidence"], float(item.get("confidence") or 0.0))
        for ev in item.get("evidence") or []:
            x = {"page": ev.get("page"), "quote": ev.get("quote"), "unit_id": unit_id}
            if x not in e["evidence"] and len(e["evidence"]) < MAX_EVIDENCE:
                e["evidence"].append(x)

    def to_json(self) -> dict:
        return {"extractor": EXTRACTOR, "nodes": [self.nodes[k] for k in sorted(self.nodes)],
                "edges": [self.edges[k] for k in sorted(self.edges)]}


def map_units(units: list[dict], records: list[Record], include_unverified: bool = False) -> dict:
    own = {canon(r.citation).id: r.id for r in records if r.citation}
    court = {r.id: r.props.get("court") for r in records}
    g = _G()

    def ok(item: dict) -> bool:
        return include_unverified or item.get("provenance", "llm") == "llm"

    for u in sorted(units, key=lambda u: u["unit_id"]):
        case, uid = u["case_id"], u["unit_id"]
        nodes = {n["id"]: n for n in u["nodes"]}
        for n in sorted(nodes.values(), key=lambda n: n["id"]):
            if not ok(n):
                continue
            attrs = n.get("attrs") or {}
            author = n.get("author") or attrs.get("author")
            if n["type"] == "opinion" and author:
                jid = judge_id(court.get(case), author)
                g.node(jid, "Judge", {"name": surname(author), "court": court.get(case)})
                g.edge("AUTHORED_BY", case, jid, n, uid, {"part": n.get("part")})
            elif n["type"] == "rule":
                name = re.sub(r"\s+", " ", str(attrs.get("doctrine") or n["label"])).strip().lower()
                did = f"doctrine:{slug(name)}"
                g.node(did, "Doctrine", {"name": name})
                g.edge("INVOKES_DOCTRINE", case, did, n, uid)
        for e in u["edges"]:
            tgt = nodes.get(e["target"])
            if e["relation"] != "relies_on" or not ok(e) or not tgt or tgt["type"] != "authority_ref":
                continue
            attrs = tgt.get("attrs") or {}
            if attrs.get("kind") != "case" or not attrs.get("cite_string"):
                continue
            c = canon(attrs["cite_string"])
            if c.id in own:
                tid = own[c.id]
            else:
                tid = f"auth:{c.id}"
                g.node(tid, "Authority", {"canon_id": c.id, "display": c.display, "kind": "case",
                                          "in_corpus": False, "resolved": False})
            if tid == case:
                continue
            stance = e.get("stance") or "relies_on"
            etype = STANCE_EDGE.get(stance, "CITES_LLM")
            g.edge(etype, case, tid, e, uid, {"treatment": stance} if etype == "CITES_LLM" else None)
    return g.to_json()
```

Note: `canon("Old case, 9 I&N Dec. 1")` gives `in_dec:9_1`; a name-only cite such as "Matter of Michel" gives `other:matter_of_michel`, so the Authority id becomes `auth:other:matter_of_michel` — the same id scheme as Phase 1.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_mapping.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit and push**

```bash
git add src/lisa/extract/mapping.py tests/test_mapping.py
git commit -m "feat: deterministic mapping of LLM tier to FOLLOWS/DISTINGUISHES/OVERRULES, judges, doctrines"
git push
```

---

### Task 9: Pipeline, CLI, run manifest

**Files:**
- Create: `src/lisa/extract/pipeline.py`, `src/lisa/extract/cli.py`, `scripts/extract_llm.py`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: everything above; `load_settings`, `load_dataset`, `load_llm_settings`, `load_eval_settings`, `load_records`, `verify_manifest`, `ChecksumError`.
- Produces:
  - `RunResult(status: str, output: Path, graph: Path, manifest: Path)` — status `complete` | `budget_exhausted`
  - `run(dataset: str, *, settings: Settings, llm: LLMSettings, ev: EvalSettings, offline: bool = False, max_requests: int | None = None, only_units: set[str] | None = None, transport=None, sleep=time.sleep) -> RunResult`
  - Output `out/llm_<ds>.json`: `{"schema_version": "1.0", "dataset", "model", "prompt_versions": {"nodes", "edges"}, "units": [{"unit_id", "case_id", "dataset", "status", "nodes", "edges"}], "pending": [unit_id, ...]}`; unit status ∈ `ok | partial | not_cached`
  - `out/graph_<ds>_llm.json` (from `map_units`), `out/llm_runs/<UTC timestamp>_<ds>.json`
  - `cli.main(argv) -> int`: 0 complete, 3 budget exhausted, 2 config/data/LLM error

- [ ] **Step 1: Write the failing tests**

`tests/test_pipeline.py`:

```python
import json
import re

import httpx
import pytest

from fakes import chat_payload, llm_settings
from lisa.common.config import EvalSettings, load_settings
from lisa.extract import cli
from lisa.extract.pipeline import run

NODES = {"nodes": [
    {"type": "opinion", "label": "Majority opinion", "part": "majority", "author": "Jones", "confidence": 0.9,
     "evidence": [{"page": 1, "quote": "In re ALPHA. We follow Matter of Beta"}], "attrs": {}},
    {"type": "reasoning", "label": "Beta controls", "part": "majority", "confidence": 0.8,
     "evidence": [{"page": 1, "quote": "See section 212(h) of the Act and 8 U.S.C."}], "attrs": {}},
    {"type": "authority_ref", "label": "Matter of Beta", "part": "majority", "confidence": 0.9,
     "evidence": [{"page": 1, "quote": "We follow Matter of Beta, 22 I&N Dec. 200 (BIA 1998)"}],
     "attrs": {"cite_string": "Matter of Beta, 22 I&N Dec. 200", "kind": "case"}}]}
EDGES = {"edges": [{"source": "eoir_1:reasoning:beta_controls", "target": "eoir_1:authority_ref:matter_of_beta",
                    "relation": "relies_on", "stance": "follows", "basis": "explicit", "confidence": 0.9,
                    "evidence": [{"page": 1, "quote": "We follow Matter of Beta, 22 I&N"}]}]}


def transport(calls):
    def handler(request):
        user = json.loads(request.content)["messages"][-1]["content"]
        calls.append(user)
        case = re.search(r"CASE_ID: (\S+)", user).group(1)
        if "NODE CATALOG" in user:
            body = EDGES if case == "eoir_1" else {"edges": []}
        else:
            body = NODES if case == "eoir_1" else {"nodes": []}
        return httpx.Response(200, json=chat_payload(json.dumps(body)))
    return httpx.MockTransport(handler)


@pytest.fixture
def env(mini_data, tmp_path, monkeypatch):
    monkeypatch.setenv("LISA_DATA_DIR", str(mini_data))
    monkeypatch.setenv("LISA_OUT_DIR", str(tmp_path / "out"))
    return load_settings(env_file=None)


EV = EvalSettings(match_threshold=0.3, fewshot_units=())


def test_run_writes_tier_graph_and_manifest(env):
    calls = []
    r = run("immigration", settings=env, llm=llm_settings(), ev=EV, transport=transport(calls))
    assert r.status == "complete" and len(calls) == 3   # eoir_1 nodes+edges, eoir_2 nodes (no nodes -> no edge call)
    out = json.loads(r.output.read_text(encoding="utf-8"))
    assert out["model"] == "test-model" and out["prompt_versions"] == {"nodes": "nodes-v1", "edges": "edges-v1"}
    u1 = next(u for u in out["units"] if u["case_id"] == "eoir_1")
    assert u1["status"] == "ok" and len(u1["nodes"]) == 3 and len(u1["edges"]) == 1
    assert all(n["provenance"] == "llm" for n in u1["nodes"]) and out["pending"] == []
    g = json.loads(r.graph.read_text(encoding="utf-8"))
    assert {(e["type"], e["source"], e["target"]) for e in g["edges"]} >= {
        ("FOLLOWS", "eoir_1", "eoir_2"), ("AUTHORED_BY", "eoir_1", "judge:bia:jones")}
    m = json.loads(r.manifest.read_text(encoding="utf-8"))
    assert m["status"] == "complete" and m["requests"] == 3 and m["units_done"] == 2 and m["dataset"] == "immigration"


def test_rerun_offline_is_free_and_identical(env):
    first = run("immigration", settings=env, llm=llm_settings(), ev=EV, transport=transport([]))
    a = first.output.read_text(encoding="utf-8")
    second = run("immigration", settings=env, llm=llm_settings(api_key=None), ev=EV, offline=True)
    assert second.output.read_text(encoding="utf-8") == a
    assert json.loads(second.manifest.read_text(encoding="utf-8"))["requests"] == 0


def test_budget_stop_then_resume_matches_full_run(env, tmp_path):
    full = run("immigration", settings=env, llm=llm_settings(), ev=EV, transport=transport([])).output.read_text(
        encoding="utf-8")
    for p in (env.out_dir / "llm_cache").glob("*.json"):
        p.unlink()
    r1 = run("immigration", settings=env, llm=llm_settings(), ev=EV, max_requests=1, transport=transport([]))
    assert r1.status == "budget_exhausted"
    part = json.loads(r1.output.read_text(encoding="utf-8"))
    assert part["pending"] and len(part["units"]) + len(part["pending"]) == 2
    calls = []
    r2 = run("immigration", settings=env, llm=llm_settings(), ev=EV, transport=transport(calls))
    assert r2.status == "complete" and len(calls) == 2 and r2.output.read_text(encoding="utf-8") == full


def test_offline_cache_miss_marks_unit(env):
    r = run("immigration", settings=env, llm=llm_settings(api_key=None), ev=EV, offline=True)
    out = json.loads(r.output.read_text(encoding="utf-8"))
    assert r.status == "complete" and {u["status"] for u in out["units"]} == {"not_cached"}


def test_only_units_filter(env):
    calls = []
    r = run("immigration", settings=env, llm=llm_settings(), ev=EV, only_units={"eoir_2__u1of1"},
            transport=transport(calls))
    assert [u["unit_id"] for u in json.loads(r.output.read_text(encoding="utf-8"))["units"]] == ["eoir_2__u1of1"]


def test_cli_missing_key_exits_2(env, monkeypatch, capsys):
    monkeypatch.delenv("SHAREDLLM_API_KEY", raising=False)
    monkeypatch.setattr(cli, "load_llm_settings", lambda: llm_settings(api_key=None))
    monkeypatch.setattr(cli, "load_eval_settings", lambda: EV)   # mini data has no gold few-shot files
    assert cli.main(["--dataset", "immigration"]) == 2
    assert "SHAREDLLM_API_KEY is not set" in capsys.readouterr().err


def test_cli_bad_dataset_exits_2(env, capsys):
    assert cli.main(["--dataset", "nope"]) == 2
    assert "cannot load dataset" in capsys.readouterr().err
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_pipeline.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lisa.extract.pipeline'`

- [ ] **Step 3: Implement pipeline**

`src/lisa/extract/pipeline.py`:

```python
"""Run the LLM tier for one dataset config: units -> nodes -> edges -> verify -> outputs + run manifest."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from lisa.common.config import EvalSettings, LLMSettings, Settings, load_dataset
from lisa.extract.fewshot import build_fewshot
from lisa.extract.mapping import map_units
from lisa.extract.prompts import build_system
from lisa.extract.stage_edges import extract_edges
from lisa.extract.stage_nodes import extract_nodes
from lisa.extract.units import Unit, build_units
from lisa.graph.loader import load_records, verify_manifest
from lisa.llm.budget import Budget, BudgetExhausted, RunStats
from lisa.llm.cache import Cache
from lisa.llm.client import CacheMiss, LLMClient

SCHEMA_VERSION = "1.0"


@dataclass(frozen=True)
class RunResult:
    status: str
    output: Path
    graph: Path
    manifest: Path


def _write(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


def _fewshot(settings: Settings, ev: EvalSettings) -> tuple[str, str]:
    if not ev.fewshot_units:
        return "", ""
    gold_paths = [f"gold_standard/{u}.json" for u in ev.fewshot_units]
    ds = load_dataset("gold_eval")
    verify_manifest(settings.data_dir, [s.path for s in ds.sources] + gold_paths)
    recs, _ = load_records(settings.data_dir, ds)
    units = {u.unit_id: u for r in recs for u in build_units(r) if u.unit_id in ev.fewshot_units}
    golds = {u: json.loads((settings.data_dir / p).read_text(encoding="utf-8"))
             for u, p in zip(ev.fewshot_units, gold_paths)}
    return build_fewshot(golds, units, ev.fewshot_units)


def run(dataset: str, *, settings: Settings, llm: LLMSettings, ev: EvalSettings, offline: bool = False,
        max_requests: int | None = None, only_units: set[str] | None = None, transport=None,
        sleep=time.sleep) -> RunResult:
    t0, started = time.monotonic(), datetime.now(timezone.utc)
    ds = load_dataset(dataset)
    verify_manifest(settings.data_dir, [s.path for s in ds.sources])
    records, _ = load_records(settings.data_dir, ds)
    units: list[Unit] = [u for r in records for u in build_units(r)
                         if u.unit_id not in ev.fewshot_units and (not only_units or u.unit_id in only_units)]
    node_fs, edge_fs = _fewshot(settings, ev)
    v_nodes, sys_nodes = build_system("nodes", node_fs)
    v_edges, sys_edges = build_system("edges", edge_fs)
    stats = RunStats()
    budget = Budget(max_requests or llm.max_requests_per_run)
    client = LLMClient(llm, Cache(settings.out_dir / "llm_cache"), budget, stats, offline=offline,
                       transport=transport, sleep=sleep)

    done, status = [], "complete"
    for i, u in enumerate(units):
        failed_before = len(stats.failed)
        try:
            nodes = extract_nodes(u, client, sys_nodes, v_nodes, llm.window_pages, stats)
            edges = extract_edges(u, nodes, client, sys_edges, v_edges, llm.edge_split_chars, stats)
            ustatus = "ok" if len(stats.failed) == failed_before else "partial"
        except BudgetExhausted:
            status = "budget_exhausted"
            pending = [x.unit_id for x in units[i:]]
            break
        except CacheMiss:
            nodes, edges, ustatus = [], [], "not_cached"
        done.append({"unit_id": u.unit_id, "case_id": u.case_id, "dataset": u.domain, "status": ustatus,
                     "nodes": nodes, "edges": edges})
    else:
        pending = []

    out_dir = settings.out_dir
    output, graph = out_dir / f"llm_{ds.name}.json", out_dir / f"graph_{ds.name}_llm.json"
    _write(output, {"schema_version": SCHEMA_VERSION, "dataset": ds.name, "model": llm.model,
                    "prompt_versions": {"nodes": v_nodes, "edges": v_edges}, "units": done, "pending": pending})
    _write(graph, {"dataset": ds.name, **map_units(done, records, llm.include_unverified_in_graph)})
    manifest = out_dir / "llm_runs" / f"{started.strftime('%Y%m%dT%H%M%S%fZ')}_{ds.name}.json"
    _write(manifest, {"dataset": ds.name, "model": llm.model, "status": status, "offline": offline,
                      "started_at": started.isoformat(), "wall_s": round(time.monotonic() - t0, 1),
                      "budget": budget.max_requests, "units_total": len(units), "units_done": len(done),
                      "prompt_versions": {"nodes": v_nodes, "edges": v_edges}, **stats.to_json()})
    return RunResult(status, output, graph, manifest)
```

- [ ] **Step 4: Implement CLI and script**

`src/lisa/extract/cli.py`:

```python
"""LLM extraction tier for one dataset config. Rerunning resumes from the cache."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter

from lisa.common.config import load_eval_settings, load_llm_settings, load_settings
from lisa.extract.pipeline import run
from lisa.graph.loader import ChecksumError
from lisa.llm.client import LLMError


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dataset", required=True, help="gold_eval | immigration | litigation | all")
    ap.add_argument("--max-requests", type=int, help="override llm.max_requests_per_run")
    ap.add_argument("--offline", action="store_true", help="serve only from out/llm_cache; never call the API")
    ap.add_argument("--units", help="comma-separated unit ids to run (default: all)")
    a = ap.parse_args(argv)
    try:
        settings, llm, ev = load_settings(), load_llm_settings(), load_eval_settings()
    except (RuntimeError, KeyError) as e:
        print(f"config error: {e}", file=sys.stderr)
        return 2
    try:
        r = run(a.dataset, settings=settings, llm=llm, ev=ev, offline=a.offline, max_requests=a.max_requests,
                only_units=set(a.units.split(",")) if a.units else None)
    except (FileNotFoundError, KeyError) as e:
        print(f"config error: cannot load dataset {a.dataset!r}: {e}", file=sys.stderr)
        return 2
    except ChecksumError as e:
        print(f"checksum error: {e}", file=sys.stderr)
        return 2
    except LLMError as e:
        print(f"llm error: {e}", file=sys.stderr)
        return 2
    out = json.loads(r.output.read_text(encoding="utf-8"))
    m = json.loads(r.manifest.read_text(encoding="utf-8"))
    print(f"{a.dataset}: {r.status}; units {m['units_done']}/{m['units_total']} "
          f"({dict(Counter(u['status'] for u in out['units']))}); pending {len(out['pending'])}")
    print(f"requests {m['requests']} (cache hits {m['cache_hits']}, 429s {m['rate_limited']}), "
          f"tokens in/out {m['input_tokens']}/{m['output_tokens']}, failed {len(m['failed'])}, "
          f"schema rejects {len(m['schema_rejects'])}")
    print(f"wrote {r.output}, {r.graph}, {r.manifest}")
    if r.status == "budget_exhausted":
        print("budget reached - rerun the same command to resume from the cache", file=sys.stderr)
        return 3
    return 0
```

`scripts/extract_llm.py`:

```python
"""Thin wrapper: py -3 scripts/extract_llm.py --dataset gold_eval [--max-requests N] [--offline] [--units ID,...]"""
import sys

from lisa.extract.cli import main

if __name__ == "__main__":
    sys.exit(main())
```

Note on `test_cli_missing_key_exits_2`: the run reaches the first LLM call, `LLMClient.complete` raises `LLMError("SHAREDLLM_API_KEY is not set ...")`, and the CLI returns 2. Missing-dataset YAML raises `FileNotFoundError` → "cannot load dataset".

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit and push**

```bash
git add src/lisa/extract/pipeline.py src/lisa/extract/cli.py scripts/extract_llm.py tests/test_pipeline.py
git commit -m "feat: LLM extraction pipeline, CLI and run manifest with budget resume"
git push
```

---

### Task 10: Extraction evaluation (matching + metrics)

**Files:**
- Create: `src/lisa/eval/__init__.py` (empty), `src/lisa/eval/extraction_eval.py`
- Test: `tests/test_extraction_eval.py`

**Interfaces:**
- Consumes: `PageIndex` (Task 2), `map_units` (Task 8).
- Produces:
  - `Counts(tp=0, fp=0, fn=0)` with `.p`, `.r`, `.f1`, `.add(other)`, `.to_json()`
  - `UnitPair(unit_id: str, domain: str, pred: dict, gold: dict, index: PageIndex)` — `pred`/`gold` are `{"nodes", "edges"}` dicts
  - `spans(item: dict, index: PageIndex) -> list[tuple[int, int]]`
  - `node_score(p: dict, g: dict, pspans, gspans) -> float`
  - `match_nodes(pred: list[dict], gold: list[dict], index, threshold: float, relaxed: bool = False) -> dict[str, str]` (pred id → gold id)
  - `match_edges(pred: list[dict], gold: list[dict], node_map: dict[str, str], relaxed: bool = False) -> list[tuple[int, int]]`
  - `evaluate(pairs: list[UnitPair], threshold: float) -> dict`
  - `threshold_sweep(pairs, thresholds=(0.1, 0.2, 0.3, 0.4, 0.5, 0.6)) -> list[dict]`
  - `mapped_tier(pred_units: list[dict], gold_units: list[dict], records, node_rule: Counts) -> dict[str, dict]`

- [ ] **Step 1: Write the failing tests**

`tests/test_extraction_eval.py`:

```python
import copy
import random

from lisa.eval.extraction_eval import (Counts, UnitPair, evaluate, mapped_tier, match_edges, match_nodes,
                                       node_score, spans, threshold_sweep)
from lisa.extract.verify import PageIndex
from lisa.graph.loader import Record

WORDS = [f"word{i}" for i in range(400)]
PAGES = {1: " ".join(WORDS[:200]), 2: " ".join(WORDS[200:])}
IDX = PageIndex(PAGES)
TYPES = ["fact", "issue", "rule", "holding", "reasoning"]


def q(a, b):
    return " ".join(WORDS[a:b])


def gold_unit(n=20):
    nodes = [{"id": f"g:{TYPES[i % 5]}:{i}", "type": TYPES[i % 5], "label": f"label {i}", "summary": "",
              "evidence": [{"page": 1 + (i * 10) // 200, "quote": q(i * 10 + 1, i * 10 + 9)}]} for i in range(n)]
    edges = [{"source": nodes[i]["id"], "target": nodes[i + 1]["id"], "relation": "supports"} for i in range(n - 1)]
    return {"nodes": nodes, "edges": edges}


def as_pred(gold):
    p = copy.deepcopy(gold)
    rename = {n["id"]: n["id"].replace("g:", "p:") for n in p["nodes"]}
    for n in p["nodes"]:
        n["id"] = rename[n["id"]]
        n["provenance"] = "llm"
    for e in p["edges"]:
        e["source"], e["target"] = rename[e["source"]], rename[e["target"]]
        e["provenance"] = "llm"
    return p


def pair(pred, gold, domain="immigration", uid="u1"):
    return UnitPair(uid, domain, pred, gold, IDX)


def test_counts():
    c = Counts(tp=8, fp=2, fn=8)
    assert (c.p, c.r, round(c.f1, 4)) == (0.8, 0.5, 0.6154)
    assert Counts().p == 0.0 and Counts().f1 == 0.0


def test_spans_and_score():
    g = gold_unit()["nodes"][0]
    assert spans(g, IDX) and node_score(g, g, spans(g, IDX), spans(g, IDX)) > 0.99
    other = {"type": "fact", "label": "zzz", "summary": "", "evidence": [{"page": 2, "quote": q(300, 309)}]}
    assert node_score(other, g, spans(other, IDX), spans(g, IDX)) == 0.0


def test_gold_vs_itself_is_perfect():
    g = gold_unit()
    r = evaluate([pair(as_pred(g), g)], 0.3)
    for k in ("nodes_strict", "nodes_relaxed", "edges_strict", "edges_relaxed"):
        assert r["micro"][k]["p"] == 1.0 and r["micro"][k]["r"] == 1.0, k


def test_dropping_20pct_nodes_lowers_recall_only():
    g = gold_unit()
    p = as_pred(g)
    p["nodes"] = p["nodes"][:16]
    r = evaluate([pair(p, g)], 0.3)["micro"]["nodes_strict"]
    assert r["p"] == 1.0 and r["r"] == 0.8


def test_shuffled_relations_keep_nodes_and_drop_edges():
    g = gold_unit()
    p = as_pred(g)
    for e in p["edges"]:
        e["relation"] = "applies_rule"
    r = evaluate([pair(p, g)], 0.3)["micro"]
    assert r["nodes_strict"]["f1"] == 1.0 and r["edges_strict"]["f1"] == 0.0 and r["edges_relaxed"]["f1"] == 1.0


def test_wrong_type_matches_only_relaxed():
    g = gold_unit(5)
    p = as_pred(g)
    p["nodes"][0]["type"] = "outcome"
    m_strict = match_nodes(p["nodes"], g["nodes"], IDX, 0.3)
    m_relaxed = match_nodes(p["nodes"], g["nodes"], IDX, 0.3, relaxed=True)
    assert "p:fact:0" not in m_strict and m_relaxed["p:fact:0"] == "g:fact:0"


def test_matching_is_one_to_one():
    g = gold_unit(5)
    p = as_pred(g)
    p["nodes"].append({**p["nodes"][0], "id": "p:dup"})
    m = match_nodes(p["nodes"], g["nodes"], IDX, 0.3)
    assert len(set(m.values())) == len(m) == 5


def test_edge_matching_needs_both_endpoints():
    g = gold_unit(3)
    p = as_pred(g)
    pairs = match_edges(p["edges"], g["edges"], {"p:fact:0": "g:fact:0", "p:issue:1": "g:issue:1"})
    assert pairs == [(0, 0)]


def test_threshold_monotonic_recall():
    rng = random.Random(0)
    g = gold_unit()
    p = as_pred(g)
    for n in p["nodes"]:
        a = rng.randint(0, 6)
        i = int(n["id"].split(":")[-1])
        n["evidence"] = [{"page": 1 + (i * 10) // 200, "quote": q(i * 10 + 1 + a, i * 10 + 9 + a)}]
        n["label"] = "something else"
    sweep = threshold_sweep([pair(p, g)])
    recalls = [s["nodes_strict"]["r"] for s in sweep]
    assert recalls == sorted(recalls, reverse=True) and [s["threshold"] for s in sweep][0] == 0.1


def test_per_type_per_domain_macro_and_provenance():
    g = gold_unit()
    p = as_pred(g)
    p["nodes"][0]["provenance"] = "unverified"
    r = evaluate([pair(p, g, "immigration", "u1"), pair(as_pred(g), g, "litigation", "u2")], 0.3)
    assert set(r["by_domain"]) == {"immigration", "litigation"}
    assert r["by_node_type"]["fact"]["tp"] == 8 and r["by_relation"]["supports"]["tp"] == 38
    assert r["macro"]["nodes_strict"]["f1"] == 1.0
    assert r["provenance"]["unverified"]["count"] == 1 and r["provenance"]["unverified"]["precision"] == 1.0
    assert r["units"][0]["unit_id"] == "u1"


def test_mapped_tier():
    recs = [Record("c1", "litigation", "A", "1 U.S. 1", {"court": "SCOTUS"}, [], "", []),
            Record("c2", "litigation", "B", "2 U.S. 2", {"court": "SCOTUS"}, [], "", [])]
    ev = [{"page": 1, "quote": "x"}]
    gold = {"unit_id": "c1__u1of1", "case_id": "c1", "nodes": [
        {"id": "o", "type": "opinion", "author": "Kagan", "evidence": ev, "attrs": {}},
        {"id": "r", "type": "reasoning", "evidence": ev, "attrs": {}},
        {"id": "a", "type": "authority_ref", "evidence": ev, "attrs": {"cite_string": "2 U.S. 2", "kind": "case"}}],
        "edges": [{"source": "r", "target": "a", "relation": "relies_on", "stance": "follows", "evidence": ev}]}
    pred = copy.deepcopy(gold)
    pred["edges"][0]["stance"] = "distinguishes"
    out = mapped_tier([pred], [gold], recs, Counts(tp=3, fp=1, fn=1))
    assert out["AUTHORED_BY"]["tp"] == 1 and out["FOLLOWS"]["fn"] == 1 and out["DISTINGUISHES"]["fp"] == 1
    assert out["Doctrine(rule)"]["tp"] == 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_extraction_eval.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lisa.eval'`

- [ ] **Step 3: Implement**

`src/lisa/eval/extraction_eval.py`:

```python
"""Evidence-anchored matching of predicted vs gold extractions, and P/R/F1.

Node score = 0.8 * max span-IoU of located quotes (cited page, +-1) + 0.2 * token-Jaccard(label + summary).
Greedy 1:1 assignment by descending score above the threshold. Edges match when both endpoints matched to the
gold edge's endpoints and (strict) the relation is equal."""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

from lisa.extract.mapping import map_units
from lisa.extract.verify import PageIndex

W_SPAN, W_TEXT = 0.8, 0.2
SWEEP = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6)
MAPPED_TYPES = ("FOLLOWS", "DISTINGUISHES", "OVERRULES", "CITES_LLM", "AUTHORED_BY")


@dataclass
class Counts:
    tp: int = 0
    fp: int = 0
    fn: int = 0

    @property
    def p(self) -> float:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else 0.0

    @property
    def r(self) -> float:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else 0.0

    @property
    def f1(self) -> float:
        return 2 * self.p * self.r / (self.p + self.r) if self.p + self.r else 0.0

    def add(self, o: "Counts") -> None:
        self.tp, self.fp, self.fn = self.tp + o.tp, self.fp + o.fp, self.fn + o.fn

    def to_json(self) -> dict:
        return {"tp": self.tp, "fp": self.fp, "fn": self.fn,
                "p": round(self.p, 4), "r": round(self.r, 4), "f1": round(self.f1, 4)}


@dataclass
class UnitPair:
    unit_id: str
    domain: str
    pred: dict
    gold: dict
    index: PageIndex


def spans(item: dict, index: PageIndex) -> list[tuple[int, int]]:
    out = []
    for e in item.get("evidence") or []:
        page = e.get("page") if isinstance(e.get("page"), int) else None
        sp = index.locate(e.get("quote") or "", page)
        if sp:
            out.append((sp.start, sp.end))
    return out


def _iou(a, b) -> float:
    inter = min(a[1], b[1]) - max(a[0], b[0])
    return inter / (max(a[1], b[1]) - min(a[0], b[0])) if inter > 0 else 0.0


def _tokens(n: dict) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", f"{n.get('label', '')} {n.get('summary', '')}".lower()))


def node_score(p: dict, g: dict, pspans, gspans) -> float:
    span = max((_iou(a, b) for a in pspans for b in gspans), default=0.0)
    tp, tg = _tokens(p), _tokens(g)
    jac = len(tp & tg) / len(tp | tg) if tp | tg else 0.0
    return W_SPAN * span + W_TEXT * jac


def match_nodes(pred, gold, index, threshold, relaxed=False) -> dict[str, str]:
    ps = {n["id"]: spans(n, index) for n in pred}
    gs = {n["id"]: spans(n, index) for n in gold}
    cands = []
    for p in pred:
        for g in gold:
            if not relaxed and p["type"] != g["type"]:
                continue
            s = node_score(p, g, ps[p["id"]], gs[g["id"]])
            if s >= threshold:
                cands.append((-s, p["id"], g["id"]))
    out, used = {}, set()
    for _, pid, gid in sorted(cands):
        if pid not in out and gid not in used:
            out[pid] = gid
            used.add(gid)
    return out


def match_edges(pred, gold, node_map, relaxed=False) -> list[tuple[int, int]]:
    free = defaultdict(list)
    for j, g in enumerate(gold):
        free[(g["source"], g["target"], None if relaxed else g["relation"])].append(j)
    out = []
    for i, p in enumerate(pred):
        s, t = node_map.get(p["source"]), node_map.get(p["target"])
        key = (s, t, None if relaxed else p["relation"])
        if s and t and free.get(key):
            out.append((i, free[key].pop(0)))
    return out


def _unit(pair: UnitPair, threshold: float) -> dict:
    pn, gn, pe, ge = pair.pred["nodes"], pair.gold["nodes"], pair.pred["edges"], pair.gold["edges"]
    strict = match_nodes(pn, gn, pair.index, threshold)
    relaxed = match_nodes(pn, gn, pair.index, threshold, relaxed=True)
    es, er = match_edges(pe, ge, strict), match_edges(pe, ge, relaxed, relaxed=True)
    c = {"nodes_strict": Counts(len(strict), len(pn) - len(strict), len(gn) - len(strict)),
         "nodes_relaxed": Counts(len(relaxed), len(pn) - len(relaxed), len(gn) - len(relaxed)),
         "edges_strict": Counts(len(es), len(pe) - len(es), len(ge) - len(es)),
         "edges_relaxed": Counts(len(er), len(pe) - len(er), len(ge) - len(er))}
    return {"counts": c, "strict": strict, "relaxed": relaxed, "edge_pairs": es, "edge_pairs_relaxed": er}


def _per_key(items_p, items_g, matched_p: set, matched_g: set, key) -> dict[str, Counts]:
    out: dict[str, Counts] = defaultdict(Counts)
    for x in items_p:
        out[key(x)].tp += x["_i"] in matched_p
        out[key(x)].fp += x["_i"] not in matched_p
    for x in items_g:
        out[key(x)].fn += x["_i"] not in matched_g
    return out


def evaluate(pairs: list[UnitPair], threshold: float) -> dict:
    micro = defaultdict(Counts)
    by_domain: dict[str, dict] = defaultdict(lambda: defaultdict(Counts))
    by_type, by_rel = defaultdict(Counts), defaultdict(Counts)
    prov = defaultdict(lambda: {"count": 0, "tp": 0})
    units, results = [], {}
    for pair in pairs:
        u = _unit(pair, threshold)
        results[pair.unit_id] = u
        for k, c in u["counts"].items():
            micro[k].add(c)
            by_domain[pair.domain][k].add(c)
        pn = [{**n, "_i": n["id"]} for n in pair.pred["nodes"]]
        gn = [{**n, "_i": n["id"]} for n in pair.gold["nodes"]]
        for t, c in _per_key(pn, gn, set(u["strict"]), set(u["strict"].values()), lambda x: x["type"]).items():
            by_type[t].add(c)
        pe = [{**e, "_i": i} for i, e in enumerate(pair.pred["edges"])]
        ge = [{**e, "_i": j} for j, e in enumerate(pair.gold["edges"])]
        mp, mg = {i for i, _ in u["edge_pairs"]}, {j for _, j in u["edge_pairs"]}
        for t, c in _per_key(pe, ge, mp, mg, lambda x: x["relation"]).items():
            by_rel[t].add(c)
        for n in pair.pred["nodes"]:
            b = prov[n.get("provenance", "llm")]
            b["count"] += 1
            b["tp"] += n["id"] in u["strict"]
        units.append({"unit_id": pair.unit_id, "domain": pair.domain,
                      **{k: c.to_json() for k, c in u["counts"].items()}})
    keys = ("nodes_strict", "nodes_relaxed", "edges_strict", "edges_relaxed")
    macro = {k: {m: round(sum(x[k][m] for x in units) / len(units), 4) if units else 0.0 for m in ("p", "r", "f1")}
             for k in keys}
    return {"threshold": threshold, "micro": {k: micro[k].to_json() for k in keys}, "macro": macro,
            "by_domain": {d: {k: v[k].to_json() for k in keys} for d, v in sorted(by_domain.items())},
            "by_node_type": {t: c.to_json() for t, c in sorted(by_type.items())},
            "by_relation": {t: c.to_json() for t, c in sorted(by_rel.items())},
            "provenance": {k: {"count": v["count"], "precision": round(v["tp"] / v["count"], 4) if v["count"] else 0.0}
                           for k, v in sorted(prov.items())},
            "units": units, "_results": results}


def threshold_sweep(pairs: list[UnitPair], thresholds=SWEEP) -> list[dict]:
    out = []
    for t in thresholds:
        r = evaluate(pairs, t)
        out.append({"threshold": t, **{k: r["micro"][k] for k in ("nodes_strict", "edges_strict")}})
    return out


def mapped_tier(pred_units: list[dict], gold_units: list[dict], records, node_rule: Counts) -> dict[str, dict]:
    def keys(g):
        out = defaultdict(set)
        for e in g["edges"]:
            out[e["type"]].add((e["source"], e["target"]))
        return out
    pk = keys(map_units(pred_units, records))
    gk = keys(map_units(gold_units, records, include_unverified=True))
    out = {}
    for t in MAPPED_TYPES:
        tp = len(pk[t] & gk[t])
        out[t] = Counts(tp, len(pk[t]) - tp, len(gk[t]) - tp).to_json()
    out["Doctrine(rule)"] = node_rule.to_json()
    return out
```

`evaluate` returns `_results` (per-unit match maps) for the error analysis in Task 11; the report writer drops keys that start with `_`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_extraction_eval.py -v`
Expected: PASS (12 tests).

- [ ] **Step 5: Commit and push**

```bash
git add src/lisa/eval/__init__.py src/lisa/eval/extraction_eval.py tests/test_extraction_eval.py
git commit -m "feat: evidence-anchored extraction matching and P/R/F1 metrics"
git push
```

---

### Task 11: Error analysis, report and eval CLI

**Files:**
- Create: `src/lisa/eval/error_analysis.py`, `src/lisa/eval/report.py`, `src/lisa/eval/cli.py`, `scripts/eval_extraction.py`
- Test: `tests/test_error_analysis.py`, `tests/test_eval_cli.py`

**Interfaces:**
- Consumes: `UnitPair`, `evaluate`, `threshold_sweep`, `mapped_tier`, `spans`, `Counts` (Task 10); `build_units`, `PageIndex`, `load_*`.
- Produces:
  - `BUCKETS = ("wrong_type", "granularity", "quote_miss", "endpoint_missed", "wrong_relation", "spurious", "missed")`
  - `bucket_errors(pair: UnitPair, result: dict) -> list[dict]` — each `{"unit_id", "side": "FP"|"FN", "item": "node"|"edge", "bucket", "type", "label", "quote"}`
  - `summarize(errors: list[dict], examples: int = 5) -> dict` — `{"counts": {item: {bucket: n}}, "examples": {bucket: [...]}}`
  - `render_markdown(report: dict) -> str`
  - `eval_cli.main(argv) -> int`; writes `out/eval/extraction_report.json` and `.md`

- [ ] **Step 1: Write the failing tests**

`tests/test_error_analysis.py`:

```python
from lisa.eval.error_analysis import BUCKETS, bucket_errors, summarize
from lisa.eval.extraction_eval import UnitPair, evaluate
from lisa.eval.report import render_markdown
from lisa.extract.verify import PageIndex

W = [f"w{i}" for i in range(300)]
IDX = PageIndex({1: " ".join(W)})


def q(a, b):
    return " ".join(W[a:b])


def n(id_, type_, a, b, prov="llm", label="x"):
    return {"id": id_, "type": type_, "label": label, "summary": "", "provenance": prov,
            "evidence": [{"page": 1, "quote": q(a, b)}]}


GOLD = {"nodes": [n("g1", "fact", 0, 10), n("g2", "issue", 20, 30), n("g3", "rule", 40, 60), n("g4", "holding", 100, 110),
                  n("g5", "reasoning", 200, 210)],
        "edges": [{"source": "g1", "target": "g2", "relation": "relevant_to"},
                  {"source": "g5", "target": "g4", "relation": "supports"},
                  {"source": "g4", "target": "g3", "relation": "applies_rule"}]}
PRED = {"nodes": [n("p1", "fact", 0, 10), n("p2", "holding", 20, 30),          # wrong type
                  n("p3", "rule", 40, 44, label="tiny piece"),                  # granularity (IoU 0.2 -> 0.16)
                  n("p4", "reasoning", 150, 160, prov="unverified"),            # quote_miss
                  n("p5", "holding", 100, 110), n("p6", "outcome", 250, 260)],  # match; spurious
        "edges": [{"source": "p1", "target": "p2", "relation": "relevant_to"},  # endpoint unmatched strictly
                  {"source": "p5", "target": "p3", "relation": "supports"}]}


def test_each_error_gets_exactly_one_bucket():
    pair = UnitPair("u1", "immigration", PRED, GOLD, IDX)
    res = evaluate([pair], 0.3)["_results"]["u1"]
    errs = bucket_errors(pair, res)
    got = {(e["side"], e["item"], e["label"] if e["item"] == "node" else e["type"], e["bucket"]) for e in errs}
    assert ("FP", "node", "x", "wrong_type") in got
    nodes = {(e["side"], e["type"]): e["bucket"] for e in errs if e["item"] == "node"}
    assert nodes[("FP", "holding")] == "wrong_type" and nodes[("FN", "issue")] == "wrong_type"
    assert nodes[("FP", "rule")] == "granularity" and nodes[("FN", "rule")] == "granularity"
    assert nodes[("FP", "reasoning")] == "quote_miss" and nodes[("FP", "outcome")] == "spurious"
    assert nodes[("FN", "reasoning")] == "missed"
    edges = {(e["side"], e["type"]): e["bucket"] for e in errs if e["item"] == "edge"}
    assert edges[("FN", "relevant_to")] == "endpoint_missed" and edges[("FN", "supports")] == "endpoint_missed"
    assert edges[("FN", "applies_rule")] == "endpoint_missed" and edges[("FP", "supports")] == "spurious"
    assert all(e["bucket"] in BUCKETS for e in errs)


def test_summarize_and_markdown():
    pair = UnitPair("u1", "immigration", PRED, GOLD, IDX)
    r = evaluate([pair], 0.3)
    s = summarize(bucket_errors(pair, r["_results"]["u1"]), examples=2)
    assert s["counts"]["node"]["wrong_type"] == 2 and len(s["examples"]["wrong_type"]) == 2
    md = render_markdown({"headline": {k: v for k, v in r.items() if not k.startswith("_")}, "sweep": [],
                          "mapped": {}, "errors": s, "cost": {"requests": 5}, "scored_units": 1,
                          "excluded_units": ["a"], "threshold": 0.3, "model": "m", "prompt_versions": {}})
    assert "| nodes_strict |" in md and "## Error analysis" in md and "wrong_type" in md and "a" in md
```

`tests/test_eval_cli.py`:

```python
import json

from lisa.eval import cli as eval_cli


def test_eval_cli_requires_prediction_file(mini_data, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LISA_DATA_DIR", str(mini_data))
    monkeypatch.setenv("LISA_OUT_DIR", str(tmp_path / "out"))
    assert eval_cli.main([]) == 2
    assert "run scripts/extract_llm.py --dataset gold_eval first" in capsys.readouterr().err


def test_eval_cli_on_real_gold_vs_itself(real_data_dir, tmp_path, monkeypatch):
    """Feeding the gold back as the prediction must score 1.0 everywhere (sanity check of the whole eval path)."""
    monkeypatch.setenv("LISA_OUT_DIR", str(tmp_path / "out"))
    units = []
    for f in sorted((real_data_dir / "gold_standard").glob("*.json")):
        g = json.loads(f.read_text(encoding="utf-8"))
        units.append({"unit_id": g["unit_id"], "case_id": g["case_id"], "dataset": g["provenance"]["dataset"],
                      "status": "ok", "nodes": [{**n, "provenance": "llm"} for n in g["nodes"]],
                      "edges": [{**e, "provenance": "llm"} for e in g["edges"]]})
    out = tmp_path / "out"
    out.mkdir()
    (out / "llm_gold_eval.json").write_text(json.dumps({"model": "gold", "prompt_versions": {}, "units": units,
                                                        "pending": []}), encoding="utf-8")
    assert eval_cli.main([]) == 0
    rep = json.loads((out / "eval" / "extraction_report.json").read_text(encoding="utf-8"))
    assert rep["scored_units"] == 23
    for k in ("nodes_strict", "edges_strict"):
        assert rep["headline"]["micro"][k]["f1"] >= 0.99, k
    assert (out / "eval" / "extraction_report.md").exists()
```

(The gold-vs-itself floor is 0.99 rather than 1.0 because a handful of gold quotes are cross-page or near-duplicates; if it lands lower, inspect the unmatched items before changing anything.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_error_analysis.py tests/test_eval_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lisa.eval.error_analysis'`

- [ ] **Step 3: Implement error analysis**

`src/lisa/eval/error_analysis.py`:

```python
"""Put every FP/FN in exactly one bucket (checked in BUCKETS order) and pick worked examples."""
from __future__ import annotations

from collections import Counter, defaultdict

from lisa.eval.extraction_eval import UnitPair, spans

BUCKETS = ("wrong_type", "granularity", "quote_miss", "endpoint_missed", "wrong_relation", "spurious", "missed")


def _overlaps(a_spans, b_spans) -> bool:
    return any(min(a[1], b[1]) > max(a[0], b[0]) for a in a_spans for b in b_spans)


def _quote(item: dict) -> str:
    ev = item.get("evidence") or []
    return ev[0].get("quote", "") if ev else ""


def bucket_errors(pair: UnitPair, result: dict) -> list[dict]:
    strict, relaxed = result["strict"], result["relaxed"]
    gold_hit, gold_relaxed = set(strict.values()), set(relaxed.values())
    pn, gn = pair.pred["nodes"], pair.gold["nodes"]
    ps = {n["id"]: spans(n, pair.index) for n in pn}
    gs = {n["id"]: spans(n, pair.index) for n in gn}
    errs = []

    def err(side, item, bucket, x, typ):
        errs.append({"unit_id": pair.unit_id, "side": side, "item": item, "bucket": bucket, "type": typ,
                     "label": x.get("label", f"{x.get('source')} -> {x.get('target')}"), "quote": _quote(x)})

    for p in pn:
        if p["id"] in strict:
            continue
        if p["id"] in relaxed:
            b = "wrong_type"
        elif any(g["type"] == p["type"] and _overlaps(ps[p["id"]], gs[g["id"]]) for g in gn):
            b = "granularity"
        elif p.get("provenance") == "unverified":
            b = "quote_miss"
        else:
            b = "spurious"
        err("FP", "node", b, p, p["type"])
    for g in gn:
        if g["id"] in gold_hit:
            continue
        if g["id"] in gold_relaxed:
            b = "wrong_type"
        elif any(p["type"] == g["type"] and _overlaps(ps[p["id"]], gs[g["id"]]) for p in pn):
            b = "granularity"
        else:
            b = "missed"
        err("FN", "node", b, g, g["type"])

    pe, ge = pair.pred["edges"], pair.gold["edges"]
    hit_p = {i for i, _ in result["edge_pairs"]}
    hit_g = {j for _, j in result["edge_pairs"]}
    rel_p = {i for i, _ in result["edge_pairs_relaxed"]}
    rel_g = {j for _, j in result["edge_pairs_relaxed"]}
    for i, e in enumerate(pe):
        if i in hit_p:
            continue
        b = ("quote_miss" if e.get("provenance") == "unverified"
             else "wrong_relation" if i in rel_p else "spurious")
        err("FP", "edge", b, e, e["relation"])
    for j, e in enumerate(ge):
        if j in hit_g:
            continue
        if e["source"] not in gold_hit or e["target"] not in gold_hit:
            b = "endpoint_missed"
        elif j in rel_g:
            b = "wrong_relation"
        else:
            b = "missed"
        err("FN", "edge", b, e, e["relation"])
    return errs


def summarize(errors: list[dict], examples: int = 5) -> dict:
    counts: dict[str, Counter] = defaultdict(Counter)
    ex: dict[str, list] = defaultdict(list)
    for e in errors:
        counts[e["item"]][e["bucket"]] += 1
        if len(ex[e["bucket"]]) < examples:
            ex[e["bucket"]].append(e)
    return {"counts": {k: dict(v) for k, v in counts.items()}, "examples": dict(ex)}
```

How the fixture lands: `p2` (holding on g2's span) matches g2 only in relaxed mode → both `wrong_type`. `p3` covers 4 of g3's 20 words → IoU 0.2, label Jaccard 0 → score 0.16 < 0.3 but overlap > 0 → `granularity` on both sides. `p4` is located but overlaps nothing and is `unverified` → `quote_miss`. Every gold edge touches an unmatched gold node → `endpoint_missed`.

- [ ] **Step 4: Implement report and CLI**

`src/lisa/eval/report.py`:

```python
"""Markdown rendering of the extraction report."""
from __future__ import annotations

KEYS = ("nodes_strict", "nodes_relaxed", "edges_strict", "edges_relaxed")


def _row(name: str, c: dict) -> str:
    return f"| {name} | {c.get('p', 0):.3f} | {c.get('r', 0):.3f} | {c.get('f1', 0):.3f} | {c.get('tp', '')} | {c.get('fp', '')} | {c.get('fn', '')} |"


def _table(title: str, rows: dict) -> list[str]:
    return [f"### {title}", "", "| | P | R | F1 | TP | FP | FN |", "|---|---|---|---|---|---|---|",
            *[_row(k, v) for k, v in rows.items()], ""]


def render_markdown(r: dict) -> str:
    h = r["headline"]
    out = ["# LISA Phase 2 — LLM extraction vs gold standard", "",
           f"Model `{r['model']}` · prompts {r['prompt_versions']} · match threshold {r['threshold']} · "
           f"{r['scored_units']} scored units (few-shot units excluded: {', '.join(r['excluded_units'])})", "",
           "## Headline (micro)", ""]
    out += _table("All units", {k: h["micro"][k] for k in KEYS})
    out += ["Macro (mean per unit): " + ", ".join(f"{k} F1 {h['macro'][k]['f1']:.3f}" for k in KEYS), ""]
    for d, v in h.get("by_domain", {}).items():
        out += _table(f"Domain: {d}", v)
    out += ["## Per type", ""] + _table("Node types (strict)", h.get("by_node_type", {}))
    out += _table("Relations (strict)", h.get("by_relation", {}))
    out += ["## Mapped spec tier", "", "OVERRULES occurs once in gold: its P/R is not statistically meaningful. "
            "Doctrine is scored as rule-node P/R (gold has no canonical doctrine names).", ""]
    out += _table("Mapped edges", r.get("mapped", {}))
    out += ["## Provenance", "", "| provenance | count | precision |", "|---|---|---|",
            *[f"| {k} | {v['count']} | {v['precision']:.3f} |" for k, v in h.get("provenance", {}).items()], ""]
    out += ["## Threshold sweep (strict)", "", "| threshold | node P | node R | edge P | edge R |", "|---|---|---|---|---|",
            *[f"| {s['threshold']} | {s['nodes_strict']['p']:.3f} | {s['nodes_strict']['r']:.3f} | "
              f"{s['edges_strict']['p']:.3f} | {s['edges_strict']['r']:.3f} |" for s in r.get("sweep", [])], ""]
    errs = r["errors"]
    out += ["## Error analysis", "", "Each FP/FN is in exactly one bucket, checked in this order: wrong_type, "
            "granularity, quote_miss, endpoint_missed, wrong_relation, spurious/missed.", ""]
    for item, c in errs["counts"].items():
        out.append(f"- **{item}**: " + ", ".join(f"{b} {n}" for b, n in sorted(c.items(), key=lambda x: -x[1])))
    out.append("")
    for b, exs in errs["examples"].items():
        out += [f"### {b}", ""]
        out += [f"- {e['side']} {e['item']} `{e['type']}` in `{e['unit_id']}` — {e['label']}: “{e['quote']}”"
                for e in exs]
        out.append("")
    out += ["## Run cost", "", *[f"- {k}: {v}" for k, v in r.get("cost", {}).items()], ""]
    return "\n".join(out)
```

`src/lisa/eval/cli.py`:

```python
"""Score out/llm_gold_eval.json against the gold standard -> out/eval/extraction_report.{json,md}."""
from __future__ import annotations

import argparse
import json
import sys

from lisa.common.config import load_dataset, load_eval_settings, load_settings
from lisa.eval.error_analysis import bucket_errors, summarize
from lisa.eval.extraction_eval import Counts, UnitPair, evaluate, mapped_tier, threshold_sweep
from lisa.eval.report import render_markdown
from lisa.extract.units import build_units
from lisa.extract.verify import PageIndex
from lisa.graph.loader import ChecksumError, load_records, verify_manifest

COST_KEYS = ("requests", "cache_hits", "input_tokens", "output_tokens", "rate_limited", "retries", "repairs",
             "truncations", "wall_s")


def _cost(out_dir) -> dict:
    total = dict.fromkeys(COST_KEYS, 0)
    runs = sorted((out_dir / "llm_runs").glob("*_gold_eval.json"))
    for p in runs:
        m = json.loads(p.read_text(encoding="utf-8"))
        for k in COST_KEYS:
            total[k] += m.get(k) or 0
    return {"runs": len(runs), **total}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--threshold", type=float, help="override eval.match_threshold")
    a = ap.parse_args(argv)
    try:
        settings, ev = load_settings(), load_eval_settings()
    except RuntimeError as e:
        print(f"config error: {e}", file=sys.stderr)
        return 2
    pred_path = settings.out_dir / "llm_gold_eval.json"
    if not pred_path.exists():
        print(f"{pred_path} not found - run scripts/extract_llm.py --dataset gold_eval first", file=sys.stderr)
        return 2
    pred = json.loads(pred_path.read_text(encoding="utf-8"))
    ds = load_dataset("gold_eval")
    gold_files = sorted((settings.data_dir / "gold_standard").glob("*.json"))
    try:
        verify_manifest(settings.data_dir, [s.path for s in ds.sources]
                        + [f"gold_standard/{p.name}" for p in gold_files])
    except ChecksumError as e:
        print(f"checksum error: {e}", file=sys.stderr)
        return 2
    records, _ = load_records(settings.data_dir, ds)
    units = {u.unit_id: u for r in records for u in build_units(r)}
    golds = {g["unit_id"]: g for g in (json.loads(p.read_text(encoding="utf-8")) for p in gold_files)}
    preds = {u["unit_id"]: u for u in pred["units"]}
    scored = sorted(uid for uid in golds if uid not in ev.fewshot_units)
    empty = {"nodes": [], "edges": []}
    pairs = [UnitPair(uid, units[uid].domain, preds.get(uid, empty), golds[uid], PageIndex(units[uid].raw_pages))
             for uid in scored]
    threshold = a.threshold if a.threshold is not None else ev.match_threshold
    head = evaluate(pairs, threshold)
    errors = [e for p in pairs for e in bucket_errors(p, head["_results"][p.unit_id])]
    rule = head["by_node_type"].get("rule", {})
    report = {
        "model": pred.get("model"), "prompt_versions": pred.get("prompt_versions"), "threshold": threshold,
        "scored_units": len(scored), "excluded_units": list(ev.fewshot_units),
        "missing_predictions": [u for u in scored if u not in preds],
        "headline": {k: v for k, v in head.items() if not k.startswith("_")},
        "sweep": threshold_sweep(pairs),
        "mapped": mapped_tier([preds[u] for u in scored if u in preds], [golds[u] for u in scored], records,
                              Counts(rule.get("tp", 0), rule.get("fp", 0), rule.get("fn", 0))),
        "errors": summarize(errors), "cost": _cost(settings.out_dir)}
    out = settings.out_dir / "eval"
    out.mkdir(parents=True, exist_ok=True)
    (out / "extraction_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "extraction_report.md").write_text(render_markdown(report), encoding="utf-8")
    m = report["headline"]["micro"]
    print(f"scored {len(scored)} units; node F1 strict {m['nodes_strict']['f1']:.3f} relaxed "
          f"{m['nodes_relaxed']['f1']:.3f}; edge F1 strict {m['edges_strict']['f1']:.3f} relaxed "
          f"{m['edges_relaxed']['f1']:.3f}")
    print(f"wrote {out / 'extraction_report.md'}")
    return 0
```

`scripts/eval_extraction.py`:

```python
"""Thin wrapper: py -3 scripts/eval_extraction.py [--threshold 0.3]"""
import sys

from lisa.eval.cli import main

if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest -q`
Expected: all pass (`test_eval_cli_on_real_gold_vs_itself` runs on this machine). If the gold-vs-itself F1 is below 0.99, print the unmatched gold node ids and fix the cause (usually a quote `locate` cannot find) — do not lower the floor without writing the reason into the test docstring.

- [ ] **Step 6: Commit and push**

```bash
git add src/lisa/eval/error_analysis.py src/lisa/eval/report.py src/lisa/eval/cli.py scripts/eval_extraction.py tests/test_error_analysis.py tests/test_eval_cli.py
git commit -m "feat: error buckets, extraction report and eval CLI"
git push
```

---

### Task 12: Live runs, report and docs

**Files:**
- Create: `docs/decision_log.md`, `docs/eval/extraction_report.md` (copied from `out/eval/` after review)
- Modify: `README.md` (Phase 2 section)

**Interfaces:**
- Consumes: `scripts/extract_llm.py`, `scripts/eval_extraction.py`.
- Produces: the deliverables in spec §14.

This task spends SharedLLM requests. **The user** adds `SHAREDLLM_API_KEY=...` to `.env` (Claude never sees or types the key). Stop and report after each live step; do not start pack runs until the user has seen the gold numbers.

- [ ] **Step 1: Dry run on one small gold unit**

Run: `.venv/Scripts/python scripts/extract_llm.py --dataset gold_eval --units eoir_4201__u1of1 --max-requests 15`
Expected: exit 0, `units 1/1 ({'ok': 1})`, a few requests, 0 failed. Open `out/llm_gold_eval.json` and check by eye: node types plausible, most nodes `provenance: llm`, quotes really verbatim, edges reference existing ids. If many quotes are `unverified` or replies fail to parse, fix the prompt, bump its `PROMPT_VERSION` (e.g. `nodes-v2`), and repeat this step.

- [ ] **Step 2: Full gold run (may need several runs because of the budget/daily cap)**

Run: `.venv/Scripts/python scripts/extract_llm.py --dataset gold_eval`
Expected: exit 0 (complete) or 3 (budget reached → rerun the same command later; cached work is not repeated). Repeat until `pending 0`. Each run writes a manifest in `out/llm_runs/`.

- [ ] **Step 3: Evaluate**

Run: `.venv/Scripts/python scripts/eval_extraction.py`
Expected: prints node/edge F1 strict and relaxed; writes `out/eval/extraction_report.{json,md}`. Read the report with the user. Note headline numbers, the weakest node types and the top error buckets.

- [ ] **Step 4: Check Phase 1 output still byte-identical and the suite is green**

Run: `.venv/Scripts/python -m pytest -q && .venv/Scripts/python scripts/build_graph.py --dataset all --no-load && sha256sum out/graph_all.json`
Expected: all tests pass; `graph_all.json` hash equals the Task 1 Step 0 baseline.

- [ ] **Step 5: Write docs**

`docs/decision_log.md`:

```markdown
# Decision log

## 2026-10-01 — LLM for the extraction tier: `z-ai/glm-flash-latest` via SharedLLM
Context: spec §4.2 names SharedLLM as the standard model path; evaluation must run on the path the system uses.
Decision: glm-flash for both extraction stages; model name only in `config/settings.yaml`.
Consequences: tiered daily request caps and per-minute token limits → disk cache, request budget, resumable runs,
429 backoff (see run manifests in `out/llm_runs/`). Output token limit forces two stages and page windows.

## 2026-10-01 — Extract in the gold schema, derive the spec relations deterministically
Context: the gold standard uses 8 node types / 12 relations; the spec asks for FOLLOWS / DISTINGUISHES /
OVERRULES, doctrines and judges.
Decision: extract the gold schema (P/R directly comparable) and map to the spec tier in code
(`lisa.extract.mapping`): relies_on.stance → FOLLOWS/DISTINGUISHES/OVERRULES/CITES_LLM, opinion.author →
Judge/AUTHORED_BY, rule.doctrine → Doctrine/INVOKES_DOCTRINE.
Consequences: one extraction serves both evaluation and the graph; the mapping is testable and applied to gold
identically. Gold has no canonical doctrine names, so Doctrine is scored as rule-node P/R.

## 2026-10-01 — Evidence-anchored deterministic matching for P/R
Context: predicted and gold nodes never share ids or exact labels.
Decision: match by quote-span IoU on the normalized page text (0.8) plus label/summary token Jaccard (0.2),
greedy 1:1 above 0.3; threshold sweep reported. No LLM judge.
Consequences: free, reproducible, explainable; sensitive to quote granularity (reported as the `granularity`
error bucket).

## 2026-10-01 — Units reproduce the reference pilot units
`lisa.extract.units` ports `pipeline_reference/segment.py` + `chunk.py`. 18/25 pilot units are byte-identical;
7 were built by an older segmenter (different PART markers, identical page text) and are tested on page text.

## 2026-10-01 — Quote length
Gold evidence quotes are mostly 10–40 words, so the node prompt asks for 8–40 words (spec draft said ≤ 30);
edge quotes 8–30 words.
```

`README.md` — add a section:

````markdown
## Phase 2 — LLM extraction tier and gold evaluation

Needs `SHAREDLLM_API_KEY` in `.env` (see `.env.example`). Model and limits: `config/settings.yaml` → `llm:`.

```bash
.venv/Scripts/python scripts/extract_llm.py --dataset gold_eval          # exit 3 = budget reached; rerun to resume
.venv/Scripts/python scripts/eval_extraction.py                           # -> out/eval/extraction_report.md
.venv/Scripts/python scripts/extract_llm.py --dataset immigration         # then litigation
.venv/Scripts/python scripts/extract_llm.py --dataset gold_eval --offline # replay from cache, no API calls
```

Outputs: `out/llm_<ds>.json` (gold-schema, per unit, `llm`/`unverified` provenance),
`out/graph_<ds>_llm.json` (FOLLOWS / DISTINGUISHES / OVERRULES / CITES_LLM / AUTHORED_BY / INVOKES_DOCTRINE,
joined to Phase 1 node ids), `out/llm_runs/*.json` (requests, tokens, 429s, failures).
The deterministic tier (`out/graph_<ds>.json`) is not changed by Phase 2. Results: `docs/eval/extraction_report.md`.
Decisions: `docs/decision_log.md`.
````

- [ ] **Step 6: Publish the report and commit**

```bash
mkdir -p docs/eval && cp out/eval/extraction_report.md docs/eval/extraction_report.md
git add docs/decision_log.md docs/eval/extraction_report.md README.md
git commit -m "docs: Phase 2 README, decision log and extraction report"
git push
```

Before `git add`, scan `docs/eval/extraction_report.md`: worked examples contain short quotes (≤ 40 words) from public court opinions, which the spec allows; it must contain no API key and no full page text.

- [ ] **Step 7: Pack runs (separate sessions/days as the cap allows)**

Run: `.venv/Scripts/python scripts/extract_llm.py --dataset immigration` (repeat until `pending 0`), then the same for `litigation`.
Expected: `out/graph_immigration_llm.json` and `out/graph_litigation_llm.json` written; manifests saved. Report request totals to the user after each session.

- [ ] **Step 8: Finish the branch**

Use superpowers:finishing-a-development-branch (PR `phase2-llm-extraction` → `main`, no attribution trailers).

---

## Self-review notes (spec coverage)

| Spec section | Task |
|---|---|
| §4 architecture, httpx dep, tier separation | 4, 9 (separate files; Phase 1 hash check in 1 and 12) |
| §5 units + reproduction | 1 |
| §6 stage 1 (windows, prompt, fields, IDs, dedupe) | 5, 6 |
| §7 stage 2 (one call/unit, part split, signatures from gold) | 3, 7 |
| §8 verification, provenance, evidence_strength, include_unverified flag | 2, 8, 9 |
| §9 temperature 0, JSON mode, repair, truncation split, backoff, cache, offline, budget, manifest | 4, 5, 6, 7, 9 |
| §10 mapping (4 rows + known limits) | 8, 11 (report text) |
| §11 evaluation (scope 23, scoring, sweep, per type/domain, mapped tier, provenance, buckets, report) | 10, 11 |
| §12 configuration | 4 |
| §13 testing | every task; e2e offline in 9 |
| §14 definition of done | 12 |
