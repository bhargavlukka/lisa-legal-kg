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
