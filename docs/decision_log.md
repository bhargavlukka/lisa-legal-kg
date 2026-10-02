# Decision log

## 2026-10-01 — LLM for the extraction tier: `gpt-oss:120b` on Ollama Cloud (planned: glm-flash via SharedLLM)
Context: spec §4.2 names the SharedLLM gateway as the standard model path, and the Phase 2 design chose
`z-ai/glm-flash-latest` through it. On the run date the gateway accepted our virtual key but every pooled upstream
key failed (Ollama 401, Anthropic "invalid x-api-key", no OpenAI key; `z-ai/glm-flash-latest` not served on any
route), and the account could not add keys. The Ollama Cloud free tier serves `gpt-oss:120b`, `gpt-oss:20b`,
`gemma4:31b` and Nemotron models; GLM models there are paid-only.
Decision: run the LLM tier on `gpt-oss:120b`, called directly at `https://ollama.com/v1` with a Bearer key
(`llm.auth: bearer`, `llm.api_key_env: OLLAMA_API_KEY`). Model identity stays in `config/settings.yaml` only.
Consequences: switching back to SharedLLM is a config change (`base_url`, `auth: sharedllm`,
`api_key_env: SHAREDLLM_API_KEY`, `model`); the cache key includes the model, so results never mix. The SharedLLM
client must send only `X-SharedLLM-Key` — the gateway forwards a supplied `Authorization` header upstream as-is.
gpt-oss spends output tokens on hidden reasoning, so `max_output_tokens` is 16384 (8192 truncated 5 of 13 replies).
Free-tier rate limits are handled by the request budget, 429 backoff and resumable cached runs.

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
error bucket). Feeding the gold back as the prediction scores ≥ 0.99 F1 (test `test_eval_cli_on_real_gold_vs_itself`).

## 2026-10-01 — Quote verification tolerates ellipses and model-added end punctuation
Context: gpt-oss splices quotes with "..." and ends a mid-sentence quote with a period, even when told not to.
Decision: a quote is split at ellipses; every piece (edge punctuation stripped) must appear verbatim, in order,
within the cited page ±1. At least one piece must be ≥ 12 normalized characters. Anything else is `unverified`.
Consequences: every word of a verified quote is on the page; a spliced quote can join two passages on adjacent pages.

## 2026-10-01 — Units reproduce the reference pilot units
`lisa.extract.units` ports `pipeline_reference/segment.py` + `chunk.py`. 18/25 pilot units are byte-identical;
7 were built by an older segmenter (different PART markers, identical page text) and are tested on page text.

## 2026-10-01 — Quote length
Gold evidence quotes are mostly 10–40 words, so the node prompt asks for 8–40 words (spec draft said ≤ 30);
edge quotes 8–30 words.
