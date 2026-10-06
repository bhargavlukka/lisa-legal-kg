# Phase 2 — LLM Extraction Tier + Gold Evaluation (Design Spec)

Date: 2026-10-01 · Project: LISA Legal Knowledge-Graph Research Agent · Status: draft (awaiting review)

## 1. Context

Phase 1 built the deterministic tier (Case/Authority/Statute/Regulation/Page nodes, CITES/MENTIONS_STATUTE/HAS_PAGE
edges) as neutral graph JSON. Phase 2 adds the **LLM tier** required by spec v2.1 §5 L1 and hard requirements #3–#5:

- LLM tier: legal doctrines/concepts, FOLLOWS / DISTINGUISHES / OVERRULES relations, author/judge attribution.
- Hybrid extraction with the deterministic and LLM tiers **demonstrably separate**.
- Provenance (`deterministic` / `llm` / `unverified`) + confidence on every node/edge.
- Extraction **precision/recall against the provided gold standard**, with an error analysis.

Model path: the SharedLLM gateway (spec §4.2 standard path), model `z-ai/glm-flash-latest`. Model identity lives in
configuration only. SharedLLM has tiered daily request caps and per-minute token limits (HTTP 429).

Inputs (never committed; via `LISA_DATA_DIR`, every file SHA-256-verified against `manifest.json` as in Phase 1):
- `gold_standard/*.json` — 25 verified pilot extractions (20 cases): 2,126 nodes, 3,376 edges.
- `gold_cases/records_*.jsonl` — full records of the 20 gold cases (disjoint from the 60 pack cases).
- `pilot_units/*.txt` — the 25 text units the gold was extracted from.
- `pipeline_reference/segment.py`, `chunk.py` — the reference unit builder.
- `pack_immigration/`, `pack_litigation/` — the 60 pack cases (~1.24M input tokens).

## 2. Decisions taken in brainstorming

| Decision | Choice | Why |
|---|---|---|
| Extraction schema | The gold schema (8 node types, 12 relations) + a deterministic mapping to the spec's relations | P/R directly comparable to gold; spec relations derived, not separately extracted |
| Model | `z-ai/glm-flash-latest` via SharedLLM | Spec standard path; evaluation must run on the selected path |
| Matching for P/R | Evidence-anchored, deterministic | Free, reproducible, explainable; no judge calibration needed |
| Pipeline shape | Two-stage windowed (nodes per page window, then edges per unit) | A gold unit averages ~85 nodes / ~135 edges — too much JSON for one glm-flash response |

## 3. Goals / non-goals

Goals
- An LLM extraction pipeline that runs on any dataset config (gold_eval, immigration, litigation, all) with zero code changes.
- Gold-schema output with verified, page-anchored quotes; `llm` vs `unverified` provenance decided by quote verification.
- A mapped spec tier (Doctrine, Judge, FOLLOWS, DISTINGUISHES, OVERRULES, AUTHORED_BY) joined to the Phase 1 graph by case id.
- Extraction P/R/F1 (strict + relaxed, per type, per domain) against gold, plus a categorized error analysis.
- Rate-limit engineering: disk cache, resumable runs, request budget, 429 backoff.

Non-goals: loading the LLM tier into Neo4j (blocked on the Neo4j environment; JSON only), LLM-as-judge, MCP servers,
the agent, the local Ollama comparison (bonus tier).

## 4. Architecture

```
src/lisa/llm/
  client.py      SharedLLM client (OpenAI-compatible /openai/v1/chat/completions, X-SharedLLM-Key header)
  cache.py       out/llm_cache/<sha256>.json; key = sha256(prompt_version + model + params + messages)
  budget.py      per-run request cap; 429/5xx exponential backoff with jitter, honors Retry-After
src/lisa/extract/
  units.py       port of reference segment+chunk: Record -> units with <<<PART BEGINS ...>>> markers
  schema.py      node types, relations, allowed (source_type, relation, target_type) signatures; JSON validation
  prompts/       nodes.md, edges.md — each carries a PROMPT_VERSION string
  stage_nodes.py page windows -> nodes; ID assignment; cross-window dedupe
  stage_edges.py unit text + node catalog -> edges; signature check
  verify.py      quote -> page-text verification; provenance; evidence_strength
  mapping.py     gold-schema graph -> spec tier
  pipeline.py    orchestration per dataset; run manifest
src/lisa/eval/
  extraction_eval.py  matching + P/R/F1
  error_analysis.py   FP/FN bucketing + worked examples
scripts/extract_llm.py      --dataset gold_eval|immigration|litigation|all [--max-requests N] [--offline] [--units ID,...]
scripts/eval_extraction.py  -> out/eval/extraction_report.json + extraction_report.md
```

Data flow:

```
records (manifest-verified) -> units.py -> stage_nodes -> stage_edges -> verify
   -> out/llm_<dataset>.json          (gold-schema, per unit; what eval reads)
   -> mapping.py -> out/graph_<dataset>_llm.json   (spec tier; references Phase 1 node ids)
gold_standard/ + out/llm_gold_eval.json -> extraction_eval -> error_analysis -> out/eval/extraction_report.{json,md}
```

**Tier separation.** Phase 1 output files (`out/graph_<dataset>.json`) are unchanged by Phase 2. The LLM tier is a
separate file whose nodes/edges all carry `provenance` `llm` or `unverified`; it joins the deterministic graph only by
Phase 1 node ids (case `canon_id`, Authority ids). Dropping the file yields exactly the Phase 1 graph.

**Dependencies.** Add `httpx` (HTTP client with timeouts) to `pyproject.toml`. No LLM SDK; the client is ~100 lines.

## 5. Units (`units.py`)

A port of `pipeline_reference/segment.py` + `chunk.py` that operates on our `Record` objects (Phase 1 `loader.py`)
instead of the reference SQLite DB. Same rules: page-aligned units of at most 90,000 chars, 1-page overlap between
units of a multi-unit case, a header block (CASE_ID, DATASET, TITLE, CITATION, DECISION_DATE, DOCKET, COURT/BODY,
UNIT, PARTS hints), `===== [[PAGE n | source_pdf_page X]] =====` page markers, and inline
`<<<PART BEGINS: part | label | seg_id=...>>>` markers.

Acceptance: building units from `gold_cases/` reproduces all 25 `pilot_units/*.txt` **byte-for-byte**. If exact
reproduction is impossible because of a reference-DB-only field, the difference is documented and the test asserts
identical page text and part markers.

## 6. Stage 1 — nodes (`stage_nodes.py`)

- **Windows:** each unit is split into windows of `window_pages` (default 3) pages with a 1-page overlap. Every
  window carries the unit header and its pages verbatim, including PART markers.
- **Prompt (`prompts/nodes.md`):** the definitions of the 8 node types (opinion, issue, fact, rule, holding,
  reasoning, outcome, authority_ref), field rules, and 2 few-shot examples. The few-shot examples are drawn from a
  fixed pair of gold units (one immigration, one SCOTUS) that are **excluded from scoring** (disclosed in the report).
- **Output per node:** `type`, `label`, `summary`, `part`, `author`, `evidence: [{page, quote}]` (verbatim, ≤ 30
  words), `confidence` (0–1), `attrs`. Required attrs: `authority_ref` → `cite_string`, `kind`
  (case/statute/regulation/other); `rule` → `doctrine` (short canonical doctrine name); headnote items →
  `not_authoritative: true`.
- **IDs** are assigned by code: `<case_id>:<type>:<slug(label)>`, with `_2`, `_3`, … on collision.
- **Cross-window dedupe:** two nodes from overlapping windows merge when the type is equal and the quote spans overlap
  ≥ 50% on the same page (or the normalized labels are equal). The merge unions evidence and keeps the max confidence.

## 7. Stage 2 — edges (`stage_edges.py`)

- **One call per unit.** If the unit is over 60,000 chars, it is split per opinion part (PART markers) and the node
  catalog is filtered to that part plus `issue`/`authority_ref` nodes.
- **Input:** the unit text + node catalog `[{id, type, label, part, pages}]`.
- **Output per edge:** `source`, `target`, `relation`, `stance` (for `relies_on`: follows / distinguishes /
  overrules / criticizes / relies_on / cites_without_treatment; else null), `basis` (explicit/inferred),
  `evidence: [{page, quote}]`, `confidence`, `attrs` (`inference_reason` required when `basis = inferred`).
- **Validation:** relations and `(source_type, relation, target_type)` signatures must appear in the allowed table in
  `schema.py`, which is **derived from the gold** by a script and committed as data. Unknown ids or disallowed
  signatures are dropped and recorded as `schema_reject` in the run manifest.

## 8. Verification (`verify.py`)

- **Normalization** (both sides): collapse whitespace, curly → straight quotes, join `-\n` hyphenation, strip PART
  and page markers. Case preserved.
- **Lookup:** search the cited page first, then pages ±1; on a hit, correct `page`.
- **Provenance:**
  - all quotes found → `provenance: llm`, `evidence_verified: true`
  - some found → `llm`, unverified quotes dropped, confidence × 0.8
  - none found → `provenance: unverified`, `evidence_verified: false`, confidence capped at 0.3
- `unverified` items stay in `llm_<dataset>.json` but are excluded from the mapped graph unless
  `include_unverified_in_graph: true`.
- **`evidence_strength`** is set by rule, not self-report: `strong` if ≥ 2 verified quotes or one ≥ 15 words,
  `moderate` if one verified quote, `weak` otherwise.

## 9. Robustness and budget (`client.py`, `cache.py`, `budget.py`)

- `temperature: 0`. JSON requested via the response-format setting where supported, else a fenced JSON block.
- **Parse/validation failure:** one repair retry with the validator errors appended; a second failure marks the
  window/unit `failed` in the run manifest and the run continues.
- **Truncation** (`finish_reason == "length"`): split the window in half and retry each half (once).
- **429 / 5xx:** exponential backoff with jitter (base 2 s, cap 120 s, max 6 attempts), honoring `Retry-After`.
- **Cache:** every successful response is written before parsing; reruns are free. `--offline` serves only from the
  cache and fails on a miss — used by tests and by graders without a key.
- **Budget:** `max_requests_per_run` (and `--max-requests`). On reaching it, the run stops cleanly, writes partial
  output plus a manifest, and the next run resumes from the cache.
- **Run manifest** `out/llm_runs/<timestamp>.json`: requests, cache hits, input/output tokens, 429 count, retries,
  failed windows, schema rejects, wall time. This feeds the Phase 6 model-constraints memo.

Sequencing: dry run on 1 gold unit → full gold_eval run → eval → only then the pack runs (immigration, then
litigation, possibly across days).

## 10. Mapping to the spec tier (`mapping.py`)

Deterministic; applied identically to our output and to gold (for evaluating the mapped tier).

| Spec element | Derived from |
|---|---|
| `FOLLOWS` / `DISTINGUISHES` / `OVERRULES` (case → case or Authority) | `relies_on` edges with stance follows / distinguishes / overrules whose target `authority_ref` has `kind: case`. The `cite_string` is resolved with Phase 1 `canon` + citation matching to an in-corpus Case; otherwise it maps to the Phase 1 Authority id (created if absent, same id scheme). The edge carries the stance quote as evidence. |
| `CITES_LLM` (case → case/Authority) | `relies_on` with stance relies_on / cites_without_treatment / criticizes (`attrs.treatment`) — LLM-attested citations that complement Phase 1 `CITES` |
| `Judge` node + `AUTHORED_BY` (case → Judge) | opinion nodes' `author`; Judge id = court + normalized surname; edge attr `part` (majority/concurrence/dissent/plurality) |
| `Doctrine` node + `INVOKES_DOCTRINE` (case → Doctrine) | `rule` nodes; Doctrine id from normalized `attrs.doctrine`, so doctrines merge across cases |

Known limits (stated in the report): the gold has no canonical doctrine names, so Doctrine P/R is reported as
rule-node P/R and cross-case merging is shown qualitatively (top merged doctrines). `overrules` occurs once in gold,
so its P/R is flagged as not statistically meaningful.

## 11. Evaluation (`extraction_eval.py`, `error_analysis.py`)

- **Scope:** 23 scored gold units (25 minus the 2 few-shot units), per unit, micro and macro averaged.
- **Node matching:**
  - Candidates are same-unit and same-type (relaxed: any type).
  - Score = 0.8 × max span-IoU of located quotes (same page ±1) + 0.2 × token-Jaccard(label + summary).
  - Match if score ≥ `match_threshold` (default 0.3).
  - Greedy 1:1 assignment by descending score.
  - A threshold sweep 0.1–0.6 is reported as a P/R curve.
- **Edge matching:** both endpoints matched and the same relation (relaxed: relation ignored, direction kept); 1:1.
- **Metrics:** P/R/F1 for nodes and edges — strict and relaxed, per node type, per relation, per domain
  (immigration vs SCOTUS). Mapped tier: P/R for FOLLOWS / DISTINGUISHES / OVERRULES / AUTHORED_BY / Doctrine(rule)
  versus mapped gold. Provenance breakdown: share and precision of `llm` vs `unverified`.
- **Error buckets** (each FP/FN in exactly one, checked in this order):
  1. `wrong_type` — matches in relaxed mode only
  2. `granularity` — quote overlap with a counterpart > 0 but below threshold (split/merge)
  3. `quote_miss` — prediction unverified
  4. `endpoint_missed` — edge FN whose endpoint was unmatched
  5. `wrong_relation` — edge matches in relaxed mode only
  6. `spurious` (FP) / `missed` (FN) — everything else
- **Report** `out/eval/extraction_report.md`: headline table, per-type tables, threshold curve, error buckets with
  3–5 worked examples each (quotes included), and run cost from the manifest.

## 12. Configuration

`config/settings.yaml` gains:

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
eval:
  match_threshold: 0.3
  fewshot_units: [<one immigration unit id>, <one SCOTUS unit id>]   # fixed in the plan
```

`.env` / `.env.example` gain `SHAREDLLM_API_KEY` (secret, env only). Domain and dataset YAMLs are unchanged.

## 13. Testing (all offline)

- `units`: byte-identical reproduction of the 25 pilot units (or the documented variant, §5).
- `verify`: normalization edge cases (hyphenation, curly quotes, cross-page quote, off-by-one page correction).
- `stage_nodes`: dedupe merge/no-merge cases; ID collision suffixes.
- `stage_edges`: signature rejects, unknown ids, part splitting.
- `mapping`: each row of §10 on hand-made fixtures; gold → mapped gold is stable.
- `extraction_eval`: gold vs itself → P = R = 1; gold minus 20% of nodes → R ≈ 0.8, P = 1; gold with shuffled
  relations → node P/R = 1 and edge P/R drops; threshold monotonicity.
- `client`/`budget` with a fake transport: 429 + Retry-After, 5xx backoff, truncation → split, bad JSON → repair →
  fail, budget stop and resume.
- End-to-end `--offline` on a small recorded cache fixture (1 unit; fixture contains no raw corpus text beyond
  short quotes).

## 14. Definition of done

1. `scripts/extract_llm.py --dataset gold_eval` completes against live SharedLLM; the run manifest is saved.
2. `scripts/eval_extraction.py` writes `extraction_report.{json,md}` with strict/relaxed P/R, per-type tables, the
   threshold curve, error buckets, the mapped-tier P/R and the run cost.
3. The LLM tier is built and mapped for immigration and litigation (`graph_<ds>_llm.json`).
4. `pytest` is green; Phase 1 output is byte-unchanged.
5. README gains a Phase 2 section; `docs/decision_log.md` is created with entries for glm-flash, the gold-schema +
   mapping choice, and evidence-anchored matching.
6. No secrets, no raw corpus text and no LLM cache are committed (all of `out/` is already git-ignored; the
   eval report is published by copying `extraction_report.md` into `docs/eval/` after review).
