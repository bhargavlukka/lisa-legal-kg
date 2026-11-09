# LISA live demo: presenter's runbook

## Before reviewers arrive (5 minutes)

1. Open Terminal and go to the project:
   ```bash
   cd ~/lisa-legal-kg
   scripts/demo.sh
   ```
   It starts Docker Desktop if needed, then the database, the trace viewer, the four tool servers and the web
   page, and opens http://127.0.0.1:8200. You can run it again at any time. If everything is already running it
   only opens the page.
2. Check the pill in the top-right corner of the page. It should say **4/4 MCP servers up** with a green dot.
   Hover over it to see the four servers.
3. Ask one warm-up question (for example the "Lookup" chip) so the first answer in front of reviewers isn't the
   first one of the day.
4. Ask only one question at a time. The model gateway is shared, and running questions in parallel causes
   rate-limit (429) errors.

When you're done:
```bash
scripts/demo_stop.sh      # stops the web page and the Docker stack (the data is kept)
```

## URLs

| What | URL | Notes |
|---|---|---|
| LISA web UI | http://127.0.0.1:8200 | The main demo screen |
| Neo4j browser | http://127.0.0.1:7474 | User `neo4j`. The password is `NEO4J_PASSWORD` in `.env` (don't show `.env` on screen) |
| Jaeger traces | http://127.0.0.1:16686 | One trace per tool call, across all servers |

## What to click

1. Click one of the grey example chips (or type a question) and press **Ask** or Enter.
2. Watch the left panel, **What LISA is doing**, and the 4-step strip above it. The current step is highlighted
   in blue and finished steps turn green.
3. The answer appears on the right. It has a coloured status badge, the answer with [n] citation markers, and
   then a **Sources** list where each source carries its verifier result.

## What each live step means (plain words)

| You see | What it means |
|---|---|
| ▶ Started research | The question reached the agent. The timer starts. |
| 🧠 Thinking → decided to use *tool* | The AI model is deciding which tool to use next. The time shows how long it thought. |
| 🔧 Searching the knowledge graph / Finding cases that cite / Reading page N | A **graph tool** call. LISA looks things up in its database of 60 cases and their citations, or reads the actual page of a decision. The grey lines under it show what came back. |
| ↳ (indented) | A helper sub-agent doing a side task, such as chasing citations. |
| 📝 Draft answer ready with N citation(s) | LISA wrote an answer where every legal claim has a [n] citation. |
| ✅ Citation verifier: every citation checks out | A separate **citation-verifier** server checked every citation (and every quote, word for word, against the case page). |
| ⚠️ Citation verifier found N problem(s) / ✏️ Revising | The verifier rejected something. LISA fixes the draft or drops the unsupported claim. This shows the safety net working. |
| ⏱️ Time limit reached | Fast mode has a time budget (about 45 s). LISA stops researching and verifies the best draft it has. |
| 🛡️ Gate decision | The final check. **verified** means every citation passed. **salvaged** means unsupported sentences were removed and the rest passed. **refused** means LISA would rather not answer than give unverified law. |
| 🏁 Finished | Total time is shown at the top of the panel and under the answer. |

Source tags in the answer:
- **green "verified in-corpus"**: the case is in LISA's corpus and the quoted text was found on that page.
- **amber "resolved externally"**: the case isn't in the corpus, but CourtListener confirmed the citation is real.
- **red "unverified"**: the citation could not be confirmed. LISA's gate normally stops these from reaching the answer.

## Recommended demo script (in this order)

1. **Lookup**: "What is Matter of Yajure Hurtado about?"
   Point out: a quick answer, a page read from the real decision, and green "verified in-corpus" sources with page numbers.
2. **Citing cases**: "Which BIA decisions cite Sessions v. Dimaya on the residual clause of 18 U.S.C. 16(b)?"
   Point out: this is a graph traversal (`find_citing_cases`), not keyword search. The citation links come from the knowledge graph.
3. **Analytics**: "Which case in the corpus is the most cited precedent?"
   Point out: the analytics server ranks the whole graph in one call. The model doesn't count anything itself.
4. **Precedent chain**: "Trace the citation path from Matter of Laparra to Supreme Court precedent on notices to appear."
   Point out: this connects the immigration corpus (BIA) with the Supreme Court corpus, hop by hop.
5. **Still good law?**: "Is Matter of Arambula-Bravo, 28 I&N Dec. 388, still good law?"
   Point out: LISA does **not** claim a case is still good law. It reports what the corpus shows and says the
   status is "not verified; may have subsequent treatment". This is honest uncertainty instead of a made-up answer.

Optional extras:
- **Neo4j** (http://127.0.0.1:7474): run `MATCH (c:Case)-[r:CITES]->(d) RETURN c,r,d LIMIT 50` to show the graph visually.
- **Jaeger** (http://127.0.0.1:16686): pick Service `lisa-agent` (or `graph` / `verifier`), click **Find Traces**
  and open the latest one. It shows every tool call of the question you just asked, with its timing. This is the
  "observability" story: you can see which server was called, in what order, and how long each call took.

## Troubleshooting

| Problem | What to do |
|---|---|
| **Docker not running** ("Cannot connect to the Docker daemon") | `scripts/demo.sh` starts Docker Desktop for you. If that fails, open Docker Desktop from Applications, wait for the whale icon to stop animating, then run `scripts/demo.sh` again. |
| **Pill shows less than 4/4 servers** | Run `scripts/demo.sh` again. If a server keeps failing, run `docker compose --env-file .env logs --tail 50 graph` (or `verifier`, `analytics`, `external`). |
| **Port busy** ("address already in use", or the page doesn't load) | See what holds the port with `lsof -nP -iTCP:8200 -sTCP:LISTEN`. If it's an old LISA web UI that is stuck, run `scripts/demo_stop.sh` and then `scripts/demo.sh`. For Neo4j or server ports (7474, 7687, 8101-8104), make sure no other copy of the stack is running (`docker ps`). |
| **Page loads but nothing happens after Ask** | Another question may still be running. The feed says "Another question is running - waiting...". Wait, or reload the page. The web UI log is `out/web.log` (when started by demo.sh). |
| **SharedLLM 429 (rate limit) or a model timeout** | The shared model gateway is busy. Wait 30-60 s and ask again, and never run two questions at once. If it times out, LISA still verifies whatever draft it has (⏱️ step), so you may get a **salvaged** answer. That is expected behaviour, not a crash. |
| **CourtListener token missing** (`COURTLISTENER_TOKEN` empty in `.env`) | Graceful degradation: questions about cases in the corpus work normally. External lookups (cases outside the corpus) report "unavailable", and those citations can't get the amber "resolved externally" tag. Avoid CourtListener questions in the demo, or add the token to `.env` and run `docker compose --env-file .env up -d` (this restarts the verifier and external servers). |
| **Answer says "refused"** | This is the safety gate working: LISA wouldn't give an answer it couldn't verify. Rephrase the question more narrowly or name a specific case. |
