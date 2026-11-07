# Architecture

This document explains how the agent is put together and why. File references point into `agent/`.

## 1. The big picture

```
            ┌──────────────── CLI (agent/__main__.py)
input ──────┤
            └──────────────── FastAPI (api/main.py) ── RunManager (api/runs.py) ── SSE events
                                     │
                                     ▼
                     LangGraph StateGraph (agent/graph.py)
   fetch_and_chunk → plan → write ⇄ critique → human_review ⇢ schedule
                                     │
                     MemorySaver checkpointer (state after every node, per thread_id)
                                     │
                    LLMClient (agent/llm.py): OpenAI or FakeLLM
```

The CLI, the API and the eval runner all drive **the same compiled graph**. Nothing about the agent's logic lives in the interfaces.

## 2. State schema (`agent/state.py`)

The state is a `TypedDict`. Each node returns only the keys it changes, and LangGraph merges them.

| Key | Written by | Notes |
|---|---|---|
| `source_url`, `source_text`, `requested_platforms`, `auto_approve` | input | exactly one of url/text |
| `title`, `chunks`, `source_truncated` | `fetch_and_chunk` | chunks are numbered 1..N in prompts |
| `plan` | `plan` | `{title, key_points: [{point, chunk_ids}], angle, audience, platforms}` |
| `posts` | `write`, `human_review` (edits) | `{platform: text}` |
| `last_written` | `write` | which platforms the critique node must (re)judge |
| `critique` | `critique` | latest `{faithfulness, platform_fit, hook, unsupported_claims, feedback, chars, passed}` per platform |
| `critique_history` | `critique` | **reducer: append**. One entry per judged post per pass, so you can see scores improve |
| `revisions` | `write` | rewrite passes after the first draft |
| `review` | `human_review` | the validated human decision |
| `scheduled` | `schedule` | entries returned by the tool |
| `status` | every node | `planning → writing → critiquing → reviewing → approved/rejected → completed` |
| `usage` | every LLM node | **reducer: sum**. `{input_tokens, output_tokens, llm_calls, cost_usd}` |

Two choices worth calling out:

- **Reducers** (`Annotated[..., reducer]`) let several nodes contribute to one key without reading and rewriting it. `write` and `critique` each return just the usage of their own calls; `add_usage` sums them. That keeps nodes simple and the totals correct.
- **The state is plain JSON.** Pydantic models validate LLM output, then are stored as dicts (`model_dump()`). Any checkpointer can persist that, and the API can return it without custom serialisers.

## 3. The nodes

### `fetch_and_chunk`
- URL path: `httpx` with a timeout, redirects, and a `User-Agent`. Retries with exponential backoff (tenacity) **only** on transient errors: timeouts, network errors, HTTP 429 and 5xx. A 404 or a PDF fails immediately with a clear message.
- **SSRF guard:** an httpx request hook resolves the host on every request (redirects included) and refuses private, loopback and link-local addresses. A public API that fetches user-supplied URLs must not be usable to probe internal networks.
- Cleaning: BeautifulSoup drops `script/style/nav/footer/aside/...`, prefers `<article>` then `<main>`, keeps headings, paragraphs and list items, and skips nested duplicates.
- Chunking (`chunk_text`): paragraphs are packed greedily into chunks of up to `CHUNK_MAX_CHARS` (1500). An oversized paragraph is split at sentence ends; an oversized "sentence" falls back to word boundaries. Nothing is ever cut mid-word, and a test checks that no text is lost.
- Context budget: chunks are kept until `MAX_SOURCE_CHARS` (12k) and `source_truncated` is set if anything was dropped.

### `plan`
- One structured-output call returning a `Plan`. The important part is that **each key point cites `chunk_ids`**. That is the grounding mechanism for the rest of the graph.
- The output is not trusted blindly: platforms outside the user's request are dropped, and chunk ids that do not exist are removed.

### `write`
- One call per platform with platform rules (`agent/platforms.py`): LinkedIn up to 1,300 characters, X up to 280. The prompt asks for ~90% of the limit to leave headroom.
- The writer sees the plan plus the **evidence**: only the chunks cited by the key points.
- On a revision pass it receives its previous draft, the judge's scores, notes and the list of unsupported claims, and rewrites **only the platforms that failed**. A post that already passed is not touched (and not re-judged), which saves tokens and avoids breaking something that worked.

### `critique`
- An LLM judge (`role="judge"`, temperature 0, optionally a different model via `JUDGE_MODEL`) scores 1-10 on faithfulness, platform fit and hook, lists unsupported claims, and writes actionable feedback. The rubric has anchors (what a 10, 7, 4 and 1 look like) to make scores more consistent.
- Then `apply_guardrails` applies rules code can check exactly:
  - over the character limit → `platform_fit` capped at 3, with "cut at least N characters" in the feedback;
  - any unsupported claim listed → `faithfulness` capped at `threshold - 1`, so a post with an invented fact can never pass;
  - empty post → all scores 1.
- `passed` = all three scores ≥ `PASS_THRESHOLD` (7).

### Routing after critique (`route_after_critique`)
```
if any post failed and revisions < MAX_REVISIONS: go to write
else: go to human_review
```
The loop **always terminates**: `revisions` increases by exactly one on every rewrite pass and the condition requires it to be below a fixed cap. Worst case per run: 1 plan + 3 write passes + 3 critique passes. If posts still fail after the budget, they go to the human anyway with a visible warning; the human decides.

### `human_review`
- Calls `interrupt(payload)` with the posts, scores, revision count and warnings. LangGraph saves the state through the checkpointer and the run stops. `graph.get_state(config).next == ("human_review",)` tells the API/CLI that it is paused.
- The run is resumed with `graph.invoke(Command(resume=decision), config)`. **The node runs again from the top** and `interrupt()` now returns the decision. So everything before `interrupt()` must be safe to run twice. Here it only reads state.
- Decisions: `approve`, `edit` (replace text for one or more platforms) or `reject` (optionally with a reason). `validate_review` checks the decision before the graph is resumed (edited text must be non-empty and within the platform limit; `schedule_at` must be timezone-aware and in the future), so a bad request becomes a 422, not a broken run.
- `auto_approve=True` skips the interrupt. Only the eval runner uses it.

### `schedule`
- Reached only through the `approved` edge, and the node checks the review decision again before acting (defence in depth around the only side effect).
- Calls the LangChain tool `schedule_post` once per platform. The mock writes to `data/scheduled_posts.json` with platform, text and a UTC timestamp (`schedule_at` from the review, or now + `SCHEDULE_DELAY_MINUTES`).
- **Idempotent per (run_id, platform):** if the node is retried or re-run after a crash, it returns the existing entry instead of scheduling a duplicate. The file is written atomically (temp file + rename) under a lock.

## 4. Why a critique loop?

A single generation pass has no feedback signal. In practice first drafts fail in predictable ways: generic hooks, overlong LinkedIn posts, numbers that drift from the source. A judge with a rubric catches these, and giving the writer that specific feedback fixes most of them in one pass.

The loop is bounded (2 rewrites) because quality gains flatten quickly while cost grows linearly, and an unbounded loop between two LLMs can oscillate. The eval runner reports first-draft vs final scores and the revision rate, which is how to tell whether the loop is earning its cost.

## 5. Why human-in-the-loop before scheduling?

- Publishing under someone's name is the one action that is public and hard to undo. Everything before it is cheap to redo.
- Putting the review **after** the automatic loop means the human sees the best version the system can produce, with scores and warnings, instead of reviewing every intermediate draft.
- The judge is a model and can be wrong; a human is the final check on tone, context and anything the source text did not contain (e.g. "we shouldn't post about this client yet").
- `edit` keeps the human's time small: fix a line rather than reject and start over.

## 6. Why the checkpointer?

`interrupt()` only works with a checkpointer: the graph must save its state somewhere to stop and resume later, possibly in a different HTTP request. `MemorySaver` saves a checkpoint after every node, keyed by `thread_id` (the run id). That also gives:
- `GET /runs/{id}` reads the latest state straight from the checkpointer (one source of truth);
- after a failure, the state up to the last successful node is still there (the error reports which node failed), so a retry endpoint could resume from that point instead of starting over.

`MemorySaver` is in-process and lost on restart. For production, swap in `SqliteSaver` or `PostgresSaver` in `build_graph(checkpointer=...)`; nothing else changes because the state is JSON.

## 7. Error handling

| Failure | Handling |
|---|---|
| Network timeout, 429, 5xx on fetch | retry with exponential backoff (`FETCH_MAX_ATTEMPTS`), then `FetchError` |
| 4xx, unsupported content type, private address | `FetchError` immediately, no retry |
| Too little readable text | `ContentError` with a hint to paste the text |
| OpenAI connection error / timeout / rate limit / 5xx | retry with backoff (`LLM_MAX_ATTEMPTS`), then `LLMError` |
| Model output does not match the schema | treated as transient and retried |
| Bad or missing API key | `LLMError` immediately ("check OPENAI_API_KEY") |
| Invalid human review | `ReviewError` → HTTP 422 / CLI re-prompt; the run stays paused |
| Review on a run that is not paused | HTTP 409 (guarded by a per-run lock) |
| Unexpected exception | logged with stack trace server-side; client gets `failed` with `internal_error` |

Every failure ends in `status: failed` with `error: {type, message, node}`. Timeouts are set on every network call (`LLM_TIMEOUT_S`, `FETCH_TIMEOUT_S`). Retries in `ChatOpenAI` are disabled (`max_retries=0`) so there is one explicit retry policy rather than two stacked ones.

## 8. API and streaming

- `POST /runs` creates a run record and starts the graph in a worker thread (`asyncio.to_thread`), returning `202` immediately.
- The run manager iterates `graph.stream(..., stream_mode="updates")`. Each node update becomes an event appended to the run's event log.
- `GET /runs/{id}/events` is a Server-Sent Events stream that replays the log from the start (or from `Last-Event-ID`) and follows it until the run completes, fails, is rejected or pauses for review. Events carry an `id`, so clients can reconnect without losing anything; a heartbeat comment every 15s keeps proxies from closing idle connections.
- `POST /runs/{id}/review` validates the decision, claims the run under a lock, then resumes the graph with `Command(resume=...)`. Scheduling makes no LLM calls, so the endpoint waits for it and returns the final state.

## 9. Testing

- `FakeLLM` implements the same `structured()` interface, reads the same tagged prompts and returns schema-valid output. It writes a weak hook on the first draft, so tests exercise the full loop deterministically.
- 24 offline tests cover chunking and cleaning, fetch retries (with `httpx.MockTransport`), the SSRF guard, every graph path (approve, edit, reject, auto-approve, platform subset, too-short input), routing and guardrails, review validation, tool idempotency, and the API including SSE, 409 and 422.
- CI runs the tests and an eval smoke run with the fake model on every push.
