# LISA evaluation report

All numbers come from committed, reproducible runs (commands in the [README](../README.md#reproduce-the-evaluation)).
Model for every LLM step: `gpt-oss:120b` through the SharedLLM gateway ([model_constraints.md](model_constraints.md)).
Raw reports: [eval/extraction_report.md](eval/extraction_report.md), [eval/qa_report.md](eval/qa_report.md).

## 1. Knowledge-graph extraction

### Deterministic tier

On the provided packs: 60 cases, **138 / 138** expected edges from `selection_report.json` found (27 immigration
internal, 61 SCOTUS internal, 50 cross-domain), 0 extra, 0 unverified (`scripts/build_graph.py --dataset all --check`).

### LLM tier vs the gold standard

23 gold units scored (2 used as few-shot examples are excluded). A predicted node matches a gold node (one-to-one,
best score first) when its score - a weighted mix of evidence-span IoU on the page and label/summary token Jaccard -
is at least 0.3 and, in strict mode, the types agree ("relaxed" ignores the type). Edges match when both endpoints matched and the relation agrees.

| | P | R | F1 |
|---|---|---|---|
| nodes, strict | 0.147 | 0.358 | 0.209 |
| nodes, relaxed | 0.204 | 0.495 | 0.289 |
| edges, strict | 0.048 | 0.027 | 0.034 |
| immigration nodes, strict | 0.211 | 0.401 | 0.277 |
| litigation nodes, strict | 0.121 | 0.332 | 0.177 |

Spec-tier relations, mapped from the gold schema:

| relation | P | R | F1 | note |
|---|---|---|---|---|
| AUTHORED_BY (judge attribution) | 0.917 | 0.978 | **0.946** | 44 / 45 gold attributions |
| CITES_LLM | 0.742 | 0.087 | 0.157 | precise but low recall - the deterministic tier already finds citations |
| Doctrine (as gold `rule` nodes) | 0.185 | 0.419 | 0.257 | |
| FOLLOWS | 0.027 | 0.053 | 0.036 | 19 gold instances |
| DISTINGUISHES | 0.000 | 0.000 | 0.000 | 21 gold instances, model predicted none in these units |
| OVERRULES | - | - | - | 0 gold instances in the scored units |

**Error analysis** (each FP/FN in exactly one bucket):

- *Over-extraction is the main node error.* The model emits 5,039 nodes against 2,076 gold nodes; 2,716 FPs are
  `spurious` (e.g. headnote lines and background facts the annotators did not label). Precision is lowest for the
  open-ended types `fact` (0.088) and `issue` (0.109), highest for `outcome` and `holding`.
- *Granularity / quote mismatch.* 1,028 FPs are `quote_miss`: right idea, but the evidence span differs from the gold
  span (a sentence vs a paragraph). Lowering the match threshold to 0.1 lifts node P/R to 0.179 / 0.435, so part of
  the gap is span granularity, not wrong content.
- *Edge errors cascade from nodes.* 2,824 of the edge errors are `endpoint_missed`: an edge cannot match unless both
  endpoints matched, so node misses multiply. Only 12 are a genuinely wrong relation label.
- *The quote check works as a filter.* 1,028 predictions whose quote was not found on the page were labelled
  `unverified`; their precision against gold is 0.000, versus 0.185 for verified `llm` items. They are excluded from
  the served graph.

What this means for the system: the served graph relies on the deterministic tier for CITES (exact, 138/138) and on
the LLM tier for attribution (F1 0.95) and, with explicit `llm` provenance, for doctrines and treatment edges. The
treatment relations (FOLLOWS / DISTINGUISHES) are the weakest part and are shown to users as model-extracted.
Improvement paths: type-specific prompts with stricter definitions of `fact` / `reasoning`, a span-granularity
instruction ("one to two sentences"), and a second pass that classifies treatment per detected citation instead of
free extraction (the approach `enrich_llm.py` already uses for the served cases).

Run cost: 72 live requests + 295 cache hits for the final scoring runs; 1.48 M input / 0.60 M output tokens.

## 2. Question answering: KG agent vs RAG baseline

_Pending: live runs blocked by the model provider's free-tier usage limit on 2026-10-05; see section 4._

## 3. Trajectory checks

_Pending with section 2._

## 4. Constraints met during evaluation

- The Ollama Cloud free tier behind our SharedLLM BYOK path returned `429 You reached the Free usage limit` after
  the extraction runs and four agent questions. The agent is the expensive part: one research turn re-sends the tool
  context on every step (q07: 24 model calls / 265 k input tokens; q24: 78 calls / 2.7 M input tokens including two
  verifier-driven revisions).
- The harness never records a turn in which the model did not answer (`qa_cli.py`), and every run is resumable.
  The first no-token degradation attempt (q24) was discarded: the quota ran out mid-turn and the agent's "refusal"
  was the provider's 429 text, not a graceful degradation. `model_failed()` now also rejects turns whose draft
  carries a provider error, so such a turn can no longer be scored.
