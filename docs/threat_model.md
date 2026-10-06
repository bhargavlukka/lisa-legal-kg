# LISA threat model

Scope: the system in [architecture.md](architecture.md) as deployed by `docker-compose.yml` on one team-controlled
host. Method: list the assets, draw the trust boundaries, then walk each attack surface (STRIDE-style) with the
control that exists in code and the residual risk we accept.

## Assets

| asset | why it matters |
|---|---|
| Answer integrity | A fabricated citation or invented quote is the worst failure (spec: "fabricated citations score zero"); lawyers may rely on output. |
| Case corpus + graph | Confidential-by-policy data ("case data stays on systems the team controls"); graph correctness drives answers. |
| Secrets | `SHAREDLLM_API_KEY` (spends the account balance), `LISA_AUTH_SECRET` (mints MCP tokens; >= 32 chars enforced), `LISA_AGENT_TOKEN`, `COURTLISTENER_TOKEN`, `NEO4J_PASSWORD`. |
| Quotas | SharedLLM daily caps, CourtListener 125/day: exhausting them is a denial of service. |
| Session memory, traces | Contain questions (possibly client facts) and answers. |

## Trust boundaries

```
 [user / evaluator] --question--> (B1) agent process --JWT--> (B2) MCP servers --> graph JSON / Neo4j
                                      |                               |
                                      +--(B3) SharedLLM gateway        +--(B4) CourtListener API
                     case text from the corpus and CourtListener ---(B5)---> model context
```

- **B1 user -> agent**: questions are untrusted input (may carry injections or ask for advice).
- **B2 agent -> MCP servers**: authenticated with signed tokens; the servers trust only the token's role.
- **B3 agent/extractor -> SharedLLM**: third-party gateway; sees prompts (questions + case excerpts) and holds keys.
- **B4 servers -> CourtListener**: third-party data; responses are untrusted text.
- **B5 data -> model**: corpus opinions and CourtListener text are attacker-influenceable content (anyone can file
  a brief that gets quoted in an opinion; external API payloads can change). **Prompt injection through case text is
  the main realistic attack.**

## Attack surfaces and controls

| # | threat (STRIDE) | surface | control in code | residual risk |
|---|---|---|---|---|
| T1 | Prompt injection via case text tells the model to fabricate, skip verification, or call tools (T, E) | `read_page`, `search_case_text`, CourtListener payloads, RAG chunks | Text fenced as `<<<UNTRUSTED_CASE_TEXT ... UNTRUSTED_CASE_TEXT>>>` with fence markers inside the text defanged, so it cannot close the fence; injection phrases flagged in tool output (`common/untrusted.py`); system prompt + skill say fenced text is data. **Decisive control: the gate is outside the model** - whatever the model is persuaded to write, `verify_answer` rejects quotes not on the stored page, unknown cases, uncited legal sentences and unqualified "good law" claims, and the final text is rendered by code. | The model can still be steered to a *less complete* answer (omit cases); this shows up as lower recall, not as fabrication. |
| T2 | Injection through the user question (q28 in the golden set) (T) | B1 | Same gate; status claims without a "not verified" qualifier are blocked; golden question q28 exercises it. | As T1. |
| T3 | Tool misuse / excessive agency: model calls shell, file or web tools (E) | Claude Agent SDK built-ins | `tools` limited to Skill/Agent/Task + MCP allowlist; a PreToolUse hook denies every other tool name and logs it; `strict_mcp_config` ignores other MCP configs; `cwd` is the agent package dir. Trajectory check `only_allowed_tools` in eval. | A bug in the SDK's permission layer; mitigated by running the agent container as non-root with only `/data:ro` and `out/` mounted. |
| T4 | Privilege escalation to admin tools (`run_cypher`, `clear_cache`, `refresh_analytics`, `graph_stats`) (E) | B2 | HS256 JWT with issuer/audience/expiry; roles -> scopes (`lisa:read`, `lisa:admin`); every server requires `lisa:read`, admin tools call `require_admin()`; the agent is issued a `researcher` token. `run_cypher` additionally runs in a READ session and rejects write keywords. | One shared HMAC secret: anyone holding it can mint admin tokens; rotation is all-at-once. Asymmetric keys (RS256/EdDSA with servers holding only the public key) would remove this; deferred as out of scope for one host. |
| T5 | Spoofed or replayed tokens (S) | B2 | Signature + `exp` (8 h TTL) + `aud`/`iss` checks; ports bound to 127.0.0.1 in compose, so the servers are not reachable off-host. | Replay within TTL by a local attacker who can read process env or traffic on loopback. |
| T6 | Secret leakage (I) | `.env`, images, logs, traces | Secrets only from environment; `.env` git-ignored; never baked into images; compose passes the LLM key and a researcher token (not the signing secret) only to the agent; each server gets `LISA_AUTH_SECRET` plus only what it uses (Neo4j creds for graph-backed servers, `COURTLISTENER_TOKEN` for verifier/external); weak or placeholder signing secrets are refused; trace attributes record tool inputs, not headers. | Anyone with shell on the host reads `.env`. |
| T7 | Corpus exfiltration (I) | B3 (prompts to SharedLLM), repo | Raw corpora never committed (manifest checksums + rebuild scripts instead); only the excerpts needed for a question/unit are sent to the model. | SharedLLM and the upstream provider see those excerpts - accepted: the spec mandates this model path; the bonus local-model path would remove it. |
| T8 | Quota exhaustion / cost DoS (D) | B3, B4 | Per-run request budgets (`llm.max_requests_per_run`, `--max-requests`), bounded worker pool, response cache (reruns are free), 429 backoff with Retry-After; CourtListener persisted per-minute/hour/day ledger refuses calls before the provider does and degrades to `unavailable`; agent `max_turns` and `max_revisions` cap one question. | A user can still spend the daily cap with many questions; no per-user rate limit (single-team deployment). |
| T9 | Poisoned graph: LLM tier invents relations (T) | extraction | LLM edges carry `llm` provenance only when the supporting quote is found verbatim on the page; failures are `unverified` and excluded from the served graph; precision measured against gold. | Correct quote, wrong label (e.g. FOLLOWS vs DISTINGUISHES) - surfaced to the user as model-extracted provenance. |
| T10 | Tampered input data (T) | `LISA_DATA_DIR` | Every input file is verified against `data_manifest/manifest.json` SHA-256 before a build; mounted read-only. | Tampering before the manifest was generated. |
| T11 | Sensitive data at rest (I) | `out/sessions`, `out/traces`, `out/trajectories.jsonl` | Stay on the host volume; session names validated (no path traversal). | Not encrypted at rest; host disk encryption is the operator's job. |
| T12 | Repudiation: who asked what, which tools ran (R) | ops | OTel spans for agent turns, tools and gate decisions (Jaeger + JSONL), trajectory log per turn with token subject. | Logs are local and mutable. |

## Demonstrations

- Gate blocks fabricated quotes and uncited claims: `tests/test_verifier.py`, `tests/test_agent_guardrails.py`.
- Fence cannot be closed by case text: `tests/test_eval_qa.py::test_rag_fence_cannot_be_closed_by_case_text`.
- Auth and role separation over real HTTP: `tests/test_servers_http.py`, `tests/test_auth.py`.
- Injection question q28 and refusal question q27 in the golden set; results in [evaluation_report.md](evaluation_report.md).
