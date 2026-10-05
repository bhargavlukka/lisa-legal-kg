# Model-constraints memo

## Selected model path

| use | endpoint | model | how it is called |
|---|---|---|---|
| LLM extraction tier, enrichment, RAG baseline | `https://api.sharedllm.com/ollama/v1` (OpenAI-compatible) | `gpt-oss:120b` | `src/lisa/llm/client.py`, temperature 0, JSON mode |
| Research agent | `https://api.sharedllm.com/ollama` (Anthropic-compatible) | `gpt-oss:120b` | Claude Agent SDK with `ANTHROPIC_BASE_URL` (`src/lisa/agent/agent.py`) |

The model is the spec's standard path, the SharedLLM gateway, used in **bring-your-own-key** mode: the request carries the
gateway key (`X-SharedLLM-Key: $SHAREDLLM_API_KEY`) plus our Ollama Cloud key as the provider bearer
(`$OLLAMA_API_KEY`), which the gateway forwards upstream. Why not the default (`z-ai/glm-flash-latest` on pooled keys):
the pooled upstream keys returned 401/402 and glm-flash was not served on any route (decision log, 2026-10-01 and
2026-10-05). Model identity lives only in `config/settings.yaml` (`llm.model`, `agent.model`); switching model or
endpoint is a config change, and the LLM cache key includes the model, so results from different models never mix.

## Limits we engineer against

| limit | source | value / observation |
|---|---|---|
| Concurrent requests | gateway / Ollama Cloud | 12 in flight (2 runs x 6 workers) -> HTTP 429 "too many concurrent requests"; 3 workers per run is stable |
| Daily request cap, per-minute tokens | SharedLLM tiered caps (spec §6) | budgeted per run, see below |
| Output length | gpt-oss spends output tokens on hidden reasoning | `max_output_tokens: 16384`; a truncated reply (`finish_reason: length`) is recorded as a failed window, not parsed |
| Latency | measured | extraction call ~30-60 s (20k in / 15k out tokens per unit); enrichment 203 calls in 573 s with 6 workers; agent turn 6-10 min (first verified answer 589 s, pilot q01 413 s) |
| CourtListener | spec §6 | 5/min, 50/hour, 125/day per free token |

## Budget plan

- **Per-run request budget:** every LLM run takes `--max-requests` (default `llm.max_requests_per_run: 300`); the
  `Budget` raises before a request that would exceed it, the run exits with code 3 and writes its stats to
  `out/llm_runs/*.json`.
- **Cache first:** every successful response is stored in `out/llm_cache` under a hash of (prompt version, params,
  messages). Reruns, resumes after a crash and `--offline` replays cost no requests; the gold run finished its last
  23 units with 55 new calls and 291 cache hits.
- **Batching:** extraction works in windows of `llm.window_pages: 3` pages, one node call + one edge call per window;
  enrichment asks for all treatments of one citing case in one call.
- **Agent:** `agent.max_turns: 30` and `agent.max_revisions: 2` cap one question; the golden-set run is resumable per
  question (`out/eval/qa_*.jsonl`).
- **Actual spend so far:** gold extraction ~350 calls, enrichment 203, RAG baseline 28, agent pilot 5 questions
  (token totals per question in `docs/eval/qa_report.md`).
- **CourtListener:** a persisted ledger (`out/cl_cache/_quota.json`) enforces 5/min, 50/h, 125/day before the
  provider does; responses are cached on disk by request, so repeated citations cost nothing.

## Fallback behaviour

| failure | behaviour |
|---|---|
| HTTP 429 / 5xx / network error | exponential backoff with jitter, honouring `Retry-After`, up to 6 attempts; then that unit/job is recorded as failed and the run continues |
| Budget reached | run stops cleanly (exit 3); rerun the same command to continue from the cache |
| Invalid JSON | one repair request quoting the parse error; schema violations are rejected per item, not per unit |
| Truncated reply | that window is recorded as failed (`out/llm_runs`) and the run continues |
| Missing key | clear error naming the variable; `--offline` still replays cached work |
| Model unreachable during an agent turn | the turn fails closed: refusal text, status `error`, nothing unverified is delivered |
| Answer fails the citation verifier | up to 2 revisions, then salvage of verified sentences, then refusal |
| CourtListener token missing / quota exhausted / down | structured `unavailable`; the agent answers from the local corpus and leaves external authorities unverified (degradation run: `scripts/eval_qa.py --system kg --tag no_token`) |

## Laptop constraint (8 GB RAM, no GPU)

The model runs remotely; locally the heavy parts are the in-memory graph (one copy per server process) and the RAG embedding index
(fastembed bge-small on CPU, embedded in batches of 16 to keep peak memory low, index cached in `out/eval/`).
Docker Desktop is not required for development: the servers run as plain processes (`scripts/serve_all.py`) and the
in-memory store replaces Neo4j.
