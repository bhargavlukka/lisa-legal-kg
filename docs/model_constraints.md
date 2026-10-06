# Model-constraints memo

## Selected model path

| use | endpoint | model | how it is called |
|---|---|---|---|
| RAG baseline, any new LLM-tier calls | `https://api.sharedllm.com/custom-openai/v1` (OpenAI-compatible) | `~z-ai/glm-flash-latest` | `src/lisa/llm/client.py`, temperature 0, JSON mode |
| Research agent | `https://api.sharedllm.com/anthropic` (Anthropic-compatible, spec 4.3) | `~z-ai/glm-flash-latest` | Claude Agent SDK with `ANTHROPIC_BASE_URL`; the CLI sends the virtual key as bearer (`ANTHROPIC_AUTH_TOKEN`) plus `X-SharedLLM-Key` (`src/lisa/agent/agent.py`, `sdk_env`) |
| Extraction tier + enrichment, extraction evaluation (history: already run, cached) | `https://api.sharedllm.com/ollama/v1` (BYOK) | `gpt-oss:120b` | same client; results in `docs/eval/extraction_report.md` |

The model path is the spec's standard path exactly: the SharedLLM gateway, authenticated **only** with the virtual
key (`llm.auth: sharedllm`: `X-SharedLLM-Key: $SHAREDLLM_API_KEY`, no provider key; the agent CLI also sends the
virtual key as its bearer, because the gateway forwards `x-api-key` upstream as a provider key), serving `z-ai/glm-flash-latest` from the shared pool (billed to the
account balance). The gateway exposes that model under its Custom provider as `~z-ai/glm-flash-latest` (the id the
dashboard Playground exports); without the `~` the gateway routed to the account's own contributed keys, which the
upstream rejected (401), which is why the extraction tier earlier ran in bring-your-own-key mode on `gpt-oss:120b`
(decision log). Model identity lives only in `config/settings.yaml` (`llm.model`, `agent.model`); switching model or
endpoint is a config change, and the LLM cache key includes the model, so results from different models never mix.

## Limits we engineer against

| limit | source | value / observation |
|---|---|---|
| Streamed usage | SharedLLM `/anthropic` | streamed replies report `input_tokens: 0` (message_start) and never send the real count; the Claude CLI always streams -> the agent goes through a local metering proxy (`src/lisa/agent/usage_proxy.py`, `agent.usage_proxy: true`) that requests each call non-streamed, logs exact usage to `out/llm_usage.jsonl` and replays it to the CLI as Anthropic SSE |
| Response encoding | SharedLLM | replies are padded with leading whitespace, which corrupts gzip decoding -> client sends `Accept-Encoding: identity` |
| Concurrent requests | gateway / Ollama Cloud | 12 in flight (2 runs x 6 workers) -> HTTP 429 "too many concurrent requests"; 3 workers per run is stable |
| Daily request cap, per-minute tokens | SharedLLM tiered caps (spec §6) | budgeted per run, see below |
| Output length | reasoning models spend output tokens on hidden reasoning | `max_output_tokens: 16384`; glm-flash otherwise reasons until the cap, so `llm.reasoning: {max_tokens: 4096}`; a truncated (`finish_reason: length`) or empty reply is never cached and is recorded as a failed window, not parsed |
| Latency | measured | extraction call ~30-60 s (20k in / 15k out tokens per unit); enrichment 203 calls in 573 s with 6 workers; agent turn 6-10 min (first verified answer 589 s, pilot q01 413 s) |
| CourtListener | spec §6 | 5/min, 50/hour, 125/day per free token |

## Price

`llm.pricing` in `config/settings.yaml` holds the gateway's published price for `~z-ai/glm-flash-latest`
(`GET /custom-openai/v1/models`, read 2026-10-06): **$0.0214 per million input tokens, $0.50 per million output
tokens**. `scripts/eval_qa.py --report-only` multiplies each question's token counts by it to report
`cost_per_query_usd` (evaluation report section 2). Output tokens dominate the bill: the model's hidden reasoning is
billed as output.

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
| Truncated or empty reply | not cached (a rerun retries it); that window is recorded as failed (`out/llm_runs`) and the run continues |
| Missing key | clear error naming the variable; `--offline` still replays cached work |
| Model unreachable during an agent turn | the turn fails closed: refusal text, status `error`, nothing unverified is delivered |
| Answer fails the citation verifier | up to 2 revisions, then salvage of verified sentences, then refusal |
| CourtListener token missing / quota exhausted / down | structured `unavailable`; the agent answers from the local corpus and leaves external authorities unverified (degradation run: `scripts/eval_qa.py --system kg --tag no_token`) |

## Laptop constraint (8 GB RAM, no GPU)

The model runs remotely; locally the heavy parts are the in-memory graph (one copy per server process) and the RAG embedding index
(fastembed bge-small on CPU, embedded in batches of 16 to keep peak memory low, index cached in `out/eval/`).
Docker Desktop is not required for development: the servers run as plain processes (`scripts/serve_all.py`) and the
in-memory store replaces Neo4j.
The compose stack (Neo4j, Jaeger, four servers, agent image) is run live in GitHub Actions instead
(`.github/workflows/docker.yml`, synthetic corpus).
