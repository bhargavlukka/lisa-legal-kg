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

## 2026-10-05 — LLM path back on SharedLLM: own provider key through the gateway (`sharedllm_byok`)
Context: the pooled upstream keys behind SharedLLM still fail (401/402), but the gateway forwards a supplied
`Authorization` header upstream. The account's SharedLLM balance is the budget for this project.
Decision: call `https://api.sharedllm.com/ollama/v1` with `X-SharedLLM-Key` (gateway) plus our Ollama key as Bearer
(`llm.auth: sharedllm_byok`). Same model (`gpt-oss:120b`), so cached Phase 2 replies stay valid.
Consequences: spec §4.2 path restored; the gateway's 1,000 requests/day cap applies, so runs are budgeted
(`--max-requests`) and resumable from `out/llm_cache`. Supersedes the 2026-10-01 direct Ollama entry.

## 2026-10-05 — Graph engine: Neo4j as the system of record, in-memory store as the default serving backend
Context: hard requirement for a real graph store, but the dev laptop cannot run Docker Desktop, and the MCP servers
must be testable without infrastructure. Alternatives considered: Neo4j only; a property-graph library (NetworkX)
only; an RDF store (no need for ontologies/SPARQL; Cypher is easier to audit).
Decision: one neutral graph JSON (`out/graph_<ds>.json` + `out/graph_<ds>_llm.json`) loaded into either Neo4j
(`scripts/load_neo4j.py`, `LISA_GRAPH_BACKEND=neo4j`) or `MemoryStore` (BM25 search over pages). Both implement the
same store interface, so servers are backend-agnostic.
Consequences: tests and demos run anywhere; Neo4j adds Cypher exploration and the admin `run_cypher` tool
(read-only). The two backends must stay behaviourally equal (shared tests).

## 2026-10-05 — Four MCP servers over Streamable HTTP with JWT roles
Context: spec asks for separately deployable tools with least privilege.
Decision: graph, citation-verifier, analytics, external-law servers (ports 8101–8104), stateless Streamable HTTP
with JSON responses; HS256 bearer tokens (`LISA_AUTH_SECRET`) with `researcher` (`lisa:read`) and `admin`
(`+lisa:admin`) scopes; admin-only tools fail with a visible `ToolError`. stdio kept for local debugging.
Consequences: each server scales/restarts independently; one shared secret is simple but must be rotated together
(asymmetric keys would remove that coupling — noted in the threat model).

## 2026-10-05 — Citation gate enforced in code, not only in the prompt
Context: the model can ignore instructions; a legal answer with an invented quote is the worst failure.
Decision: after the agent drafts, `verify_answer` runs from code; failed drafts get bounded revisions, then
salvage (drop unsupported sentences, re-verify) or refusal. Tiers: verified_in_corpus / resolved_externally /
unverified. Legal status is always reported as not verified.
Consequences: answers can be refused even when partly right; latency rises by one verifier call per revision.

## 2026-10-05 — Agent on the Claude Agent SDK driven through SharedLLM
Context: spec asks for an agent framework with skills, subagents, hooks and memory; only SharedLLM credit is
available.
Decision: Claude Agent SDK with `ANTHROPIC_BASE_URL=https://api.sharedllm.com/ollama`, model `gpt-oss:120b`,
`strict_mcp_config` (only our four servers), PreToolUse allow-list hook, `legal-research` skill, `citation-chaser`
subagent, session memory in `out/sessions`. Trajectories logged to `out/trajectories.jsonl`.
Consequences: framework features work with a non-Anthropic model, but tool-calling is slower (first verified answer
took 589 s / 27 tool calls); the prompt now asks for fewer, targeted calls.

## 2026-10-05 — LLM enrichment of the served 60 cases (separate from gold extraction)
Context: the 20 gold-standard cases do not overlap the 60 served cases, so Phase 2 output adds no LLM edges to the
served graph; full gold-schema extraction of the 60 would cost 1,000+ calls.
Decision: two targeted prompts (`lisa.extract.enrich`): one treatment call per in-corpus CITES pair
(FOLLOWS / DISTINGUISHES / OVERRULES or plain cite) and one metadata call per case (doctrines, author). A claim
enters the graph only if its quote is found verbatim on the case's pages.
Consequences: ~187 calls instead of 1,000+; precision of the enrichment is not gold-scored (the gold set measures
the extractor, this pass reuses the same quote-verification guard).

## 2026-10-05 — Parallel LLM requests
Context: sequential calls ran at ~3 replies/min (15–25 s each).
Decision: units/jobs run on a thread pool (`llm.workers: 6`, `--workers`); budget and stats are thread-safe;
outputs keep input order; 429s back off per request.
Consequences: ~17–18 replies/min observed; the daily request cap is reached sooner, so budgets stay explicit.

## 2026-10-05 — CourtListener access: cache, persisted quota ledger, graceful degradation
Decision: disk cache, self-imposed limits (5/min, 50/h, 125/day) persisted across restarts, 429 backoff; without a
token or over quota the external tools return `unavailable` and the agent answers from the corpus only.
Consequences: the external server never blocks an answer; external citations are marked `resolved_externally` or
`unverified`, never `verified_in_corpus`.

## 2026-10-05 — Observability with OpenTelemetry
Decision: spans for every MCP tool call, verifier gate and agent turn; OTLP export when
`OTEL_EXPORTER_OTLP_ENDPOINT` is set (Jaeger in compose), JSONL traces in `out/traces/` always.
Consequences: traces are available even without a collector; JSONL files can be large and stay out of git.

## 2026-10-05 — Packaging: one server image, one agent image, compose for the stack
Decision: multi-stage `Dockerfile` (`server` target runs any of the four servers via `LISA_SERVER`; `agent` adds
node + the claude CLI). Data and built graphs are bind-mounted, never baked in. `docker-compose.yml` runs neo4j,
jaeger, the four servers, and the agent on demand (`--profile agent` / `docker compose run`).
Consequences: images contain no case data or secrets. The dev laptop has no Docker engine, so the stack is run live
in CI (entry below).

## 2026-10-05 — Model path back to the spec default: `~z-ai/glm-flash-latest` from the SharedLLM pool
Context: the BYOK path (own Ollama Cloud key through the gateway) hit the Ollama free-tier usage limit (429) during
the QA runs. Diagnosis: with only `X-SharedLLM-Key`, the response header `x-sharedllm-key-source: user` showed the
gateway serving from the account's own contributed keys (all rejected upstream, 401) because the model ids we sent
(`z-ai/glm-flash-latest`, `glm-5.3-flash`, ...) did not match a pool model. The dashboard Playground export showed the
pool id `~z-ai/glm-flash-latest` on `/custom-openai`; with it every route (`/custom-openai`, `/anthropic`,
`/custom-anthropic`) returns 200 with `key-source: pool`.
Decision: LLM client on `/custom-openai/v1`, agent on `/anthropic` (spec 4.3), model `~z-ai/glm-flash-latest`, auth
virtual key only (`llm.auth: sharedllm`); the BYOK mode stays available in code but is not configured.
Consequences: QA evaluation (KG agent and RAG) runs on the spec model, billed to the SharedLLM balance; the Phase 2
extraction evaluation stays on `gpt-oss:120b` (cached; rerunning it on glm is a config change plus ~350 calls).

## 2026-10-05 — Verifier hardened after a code and security review
Context: the gate checked only each citation's own quote. Review rounds found ways to carry unverified text past it:
quotations written into the prose, meaning-changing brackets (an omission could drop "not"), ellipses stitching
distant text, and a combined alteration regex that could backtrack exponentially.
Decision: quotations in the prose are checked (double / curly / guillemet / single quotes, nested pairs), each
against the case cited by its own `[n]` marker; 1-2 word quoted terms skipped, 3-4 word terms must be in some cited
case; brackets only as case changes (`[b]ut`), omissions and insertions literal; ellipsis gaps capped
(`MAX_ELLIPSIS_GAP`), matching bounded (`MAX_PIECES`, `MAX_STARTS`, sequential search instead of a backtracking
regex); unused citations flagged; legal cues case-insensitive; headings exempt only without assertions; external
citations reject quotes and mismatched case names. `eval_qa.py --reverify` re-checks stored drafts with the new gate.
Consequences: more drafts need a revision or are salvaged; earlier QA runs are re-checked rather than re-run.

## 2026-10-05 — Docker stack validated in CI against a synthetic corpus
Context: the dev laptop has no Docker engine, and the real case package must not leave it.
Decision: `.github/workflows/docker.yml` runs the unit tests, generates a synthetic corpus
(`scripts/ci_synthetic_data.py`), builds the graph and both images, starts the compose stack with throwaway secrets
and runs `scripts/ci_smoke.py` (auth, roles, tools, no-token degradation over HTTP), then again with the graph server
on the Neo4j backend, and starts the agent image.
Consequences: compose, images and server wiring are tested live on each push and pull request; the agent's model path is not (dummy
SharedLLM key), and results on the real corpus remain local.

## 2026-10-05 — Containers run as the host UID/GID
Context: the first CI stack run showed the servers could not write to the `./out` bind mount as the image's user.
Decision: compose runs every container as `${LISA_UID:-10001}:${LISA_GID:-10001}`; the agent gets `HOME=/tmp` for
the claude CLI state.
Consequences: on Linux, `.env` sets `LISA_UID` / `LISA_GID` to the host user; Docker Desktop works with the defaults.
