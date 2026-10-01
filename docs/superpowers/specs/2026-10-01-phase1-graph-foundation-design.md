# Phase 1 — Graph Foundation (Design Spec)

Date: 2026-10-01 · Project: LISA Legal Knowledge-Graph Research Agent · Status: approved in brainstorming, pending written review

## 1. Context

LISA is built in six phases (graph foundation → LLM extraction + gold eval → four MCP servers → agent →
evaluation → security/ops/docs). This spec covers **Phase 1 only**: the deterministic (non-LLM) tier of the
knowledge graph, loaded into **Neo4j Community Edition** (engine choice recorded in `docs/decision_log.md` later).

Inputs (never committed; located via `LISA_DATA_DIR` in `.env`):
- `pack_immigration/records.jsonl` — 30 EOIR decisions
- `pack_litigation/records.jsonl` — 30 SCOTUS opinions
- `gold_cases/records_*.jsonl` — 20 gold-standard cases (**disjoint from the 60 pack cases**)
- `manifest.json` (file-level SHA-256), `selection_report.json` (expected edge lists)

## 2. Goals / non-goals

Goals
- One config-driven codebase builds a graph for any dataset config; switching domain = editing YAML, zero code changes.
- Deterministic tier: Case nodes, in-pack CITES, cross-domain CITES, out-of-corpus Authority nodes, statute/regulation mentions, Page nodes.
- Provenance (`deterministic` / `llm` / `unverified`), confidence (0–1), and page-anchored evidence on every node and edge.
- Reproduce `selection_report.json` edge lists as an acceptance check.

Non-goals (later phases): LLM extraction (doctrines, FOLLOWS/DISTINGUISHES/OVERRULES, authorship), precision/recall vs gold,
MCP servers, agent, CourtListener resolution, docker-compose for the whole system.

## 3. Architecture (Approach A — neutral JSON, then loader)

```
records.jsonl ──► loader (verify sha256) ──► extract_det + crossdomain ──► out/graph_<dataset>.json
                                                                              │
                                                       neo4j_load (MERGE) ◄───┘   check.py vs selection_report
```
Extraction is pure Python with no database dependency. The graph JSON is the stable interface: the Neo4j loader is one
consumer; a second engine (bonus tier) would be another.

## 4. Repository layout (Phase 1 files)

```
lisa-legal-kg/
  .env.example  .gitignore  pyproject.toml  README.md
  config/settings.yaml
  config/datasets/immigration.yaml  litigation.yaml  gold_eval.yaml
  src/lisa/common/config.py
  src/lisa/graph/{loader,canon,statutes,extract_det,crossdomain,neo4j_load,check}.py
  scripts/build_graph.py
  tests/  (fixtures/ + unit tests)
  out/    (gitignored)
```

## 5. Configuration

`config/datasets/<name>.yaml` declares: `name`, `domain` (immigration|litigation), `files` (paths relative to
`LISA_DATA_DIR`), `manifest_prefix`, field mapping (`id`, `title`, `citation`, `date`, `court_field`), extra properties to
copy, and `cross_domain_targets` (dataset whose case titles/reporter cites are searched for in this dataset's text — set
to `litigation` for immigration; empty for litigation and gold_eval). `gold_eval.yaml` points at `gold_cases/`.
`config/settings.yaml` holds Neo4j URI/database and output dir; credentials come from env only
(`NEO4J_USER`, `NEO4J_PASSWORD`).

`scripts/build_graph.py --dataset immigration|litigation|gold_eval|all [--no-load] [--check]`.
`all` = immigration + litigation into one graph (cross-domain edges require both).

## 6. Graph schema

Nodes
| Label | Key | Properties |
|---|---|---|
| `Case` | `id` | title, citation, canon_cite, decision_date, decision_year, court, dataset, domain, source_url, sha256, page_count, docket (litigation), term (litigation), `legal_status="not verified"` |
| `Authority` | `canon_id` | display, kind (case/other), `in_corpus=false`, `resolved=false` |
| `Statute` | `canon_id` (e.g. `usc:8_1182`, `ina:212`) | display, title_no, section |
| `Regulation` | `canon_id` (e.g. `cfr:8_1003`) | display |
| `Page` | `id` = `<case_id>#p<n>` | case_id, page_no, text |

Edges
| Type | From → To | Properties |
|---|---|---|
| `CITES` | Case → Case \| Authority | scope (internal / cross_domain / external), bases (list: detected_citation / name / reporter) |
| `MENTIONS_STATUTE` | Case → Statute \| Regulation | count |
| `HAS_PAGE` | Case → Page | — |

Every node and edge also carries `provenance`, `confidence`, `evidence` (list of `{page, quote}`; stored in Neo4j as a JSON
string), and `extractor` (module name + version). Phase 2 adds LLM-tier labels/edges onto this same schema.

## 7. Extraction rules

1. **Normalization (`canon.py`)**: collapse whitespace (incl. embedded newlines), canonicalize `U. S.`→`U.S.`,
   `U. S. C.`→`U.S.C.`, `C. F. R.`→`C.F.R.`. Canonical ids: `in_dec:<vol>_<page>`, `us:<vol>_<page>`,
   `usc:<title>_<section>`, `cfr:<title>_<part>`, `<reporter>:<vol>_<page>` for F./F.2d/F.3d/F.4th/F. Supp./S. Ct./L. Ed.,
   else `other:<slug>`.
2. **In-pack CITES**: for each entry in `citations_detected`, canon it; if it equals another loaded case's own canon citation
   → Case→Case, `basis=detected_citation`, confidence 1.0. Self-cites skipped. Duplicates collapse to one edge.
3. **Authority**: a detected *case* citation not resolving in the loaded corpus → Case→Authority, scope `external`,
   confidence 1.0. Statute/regulation-kind citations go to rule 5 instead.
4. **Cross-domain**: for each case in a dataset with `cross_domain_targets`, search whitespace-normalized full text for
   (a) each target case title (case-insensitive, exact phrase) → `basis=name`, confidence 0.9;
   (b) each target `<vol> U.S. <page>` citation (spacing-tolerant) → `basis=reporter`, confidence 1.0.
   One Neo4j edge per pair with `bases` listing every basis found; edge confidence = max of its bases.
5. **Statutes/regulations (`statutes.py`)**: regex over page text for `<t> U.S.C. § <s>`, `INA § <s>` and
   `section <s> of the (Immigration and Nationality )?Act`, `<t> C.F.R. § <p>`. A small INA→U.S.C. crosswalk
   (101→8 U.S.C. 1101, 212→1182, 237→1227, 240→1229a, 240A→1229b, 241→1231) maps INA sections to the U.S.C. node; unmapped
   INA sections stay as `ina:<s>` nodes.
6. **Evidence**: every extracted edge records the page where the match occurs and a quote = the match ±60 chars copied
   verbatim from the stored page text. If no page contains the match, the edge is still created with
   `provenance=unverified`, confidence 0.5, empty evidence.

## 8. Error handling

- File checksum mismatch vs `manifest.json` → build aborts naming the file.
- Record missing required mapped field / malformed JSON line → skipped, written to `out/quarantine_<dataset>.json`, count printed.
- Neo4j unreachable → graph JSON still written; loader exits non-zero with a clear message; `--no-load` skips loading.
- Loader is idempotent (`MERGE` on keys), so rebuilds never duplicate.

## 9. Testing & acceptance

- Unit tests (pytest, TDD) for `canon` using Resource Pack examples: `"18\nU.S.C. § 5032"`, `"384 U. S. 73"`,
  `"22 I&N Dec. 1415"`, `"28 U. S. C. § 1253"`, `"721 F.3d 1064"`, `"8 C.F.R. 208.14(b)"`.
- Unit tests for statute extraction and INA crosswalk; cross-domain matcher on small fixtures.
- Config test: same `build` function produces graphs for two different dataset configs.
- **Acceptance (`check.py`)** against `selection_report.json`: all 50 cross-domain entries (39 unique pairs, per-basis),
  all 27 immigration-internal and 61 litigation-internal edges present. Missing edges → fail with list; extra edges → reported, not failed.
- Neo4j load test marked to skip when Neo4j is unavailable.

## 10. Done when

`py -3 scripts/build_graph.py --dataset all --check` writes the graph JSON, passes the acceptance check, loads Neo4j, and
`pytest` is green. `gold_eval` config also builds (used in Phase 2).
