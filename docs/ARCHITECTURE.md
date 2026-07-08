# Architecture — Tennis Voice Agent

Technical companion to `PRD.md` (product scope) and `AGENT_DESIGN.md` (persona/conversation spec). This document covers how the system is actually built: request flow, file responsibilities, context/memory/loop/orchestration design, the tradeoffs behind those choices, and a concrete list of what to fix next. It reflects the code as of the current `main` branch, not the aspirational design.

## 1. System overview

```
Browser (web/index.html)
  ├─ static hardcoded catalog grid (display only)
  └─ chat widget (web/voice-widget.js)
        ├─ Web Speech API: SpeechRecognition (mic → text, zh-HK)
        ├─ Web Speech API: SpeechSynthesis (text → voice, zh-HK)
        └─ fetch POST /chat  ──────────────►  Flask app (agent/bot.py)
                                                  ├─ loads system_prompt.md
                                                  ├─ loads racquets.json (per tool call)
                                                  ├─ in-memory session history (dict)
                                                  ├─ Anthropic Messages API (tool-use loop)
                                                  └─ appends to bookings.csv on confirmed booking
```

There is no database, no message queue, no background worker, and no persistent session store. Everything lives in one Flask process and two flat data files.

## 2. Request/response workflow (the agentic loop)

This is the core of the system, all in `agent/bot.py:chat()`:

1. Client POSTs `{message, session_id}` to `/chat`.
2. If `MOCK_MODE` is on (no API key, or `MOCK=1`), the request is routed entirely to `mock_reply()` — a scripted finite-state machine — and the Anthropic API is never called. See §5.
3. Otherwise: `system_prompt.md` is read from disk on **every request** (no caching), the per-session `history` list is fetched from the in-process `sessions_history` dict, and the new user message is appended to it.
4. The full `history` array is sent to `client.messages.create()` along with the system prompt and the two tool schemas (`search_racquets`, `book_fitting`).
5. If `response.stop_reason == "tool_use"`, the code enters a hand-rolled ReAct loop:
   - Append the assistant's tool-use content block(s) to `history`.
   - Execute each requested tool locally (`search_racquets()` or `handle_book_fitting()`), synchronously, in-process.
   - Append a `tool_result` message (JSON-encoded) back into `history`.
   - Call `messages.create()` again with the updated history.
   - Repeat until the model returns plain text (`stop_reason != "tool_use"`) or `MAX_TOOL_ITERATIONS` (5) is hit.
6. On the 5-iteration cap, the loop **bails without appending the dangling tool_use block**, so the next turn's history stays well-formed for the API (an unmatched `tool_use`/`tool_result` pair would make the next API call fail validation). A canned Cantonese fallback is returned instead.
7. The final text response is appended to `history` and returned to the client as `{reply}`.
8. The widget renders the bubble and immediately calls `speakOutLoud()` to read it aloud via `SpeechSynthesis`.

There is no streaming — the client waits for the full loop (including any tool calls) to resolve before it sees anything.

## 3. File-by-file responsibilities

| File | Role |
|---|---|
| `agent/bot.py` | Everything: Flask routes, tool implementations, tool schemas, the agentic loop, the booking confirmation guardrail, and the entire mock-mode state machine. This is the whole backend in one file. |
| `agent/prompts/system_prompt.md` | The actual behavioral spec the model follows at runtime — question order, tone, refusal script, response-length limit. This is the **source of truth for live behavior**; `docs/AGENT_DESIGN.md` is a human-readable mirror of it and can drift out of sync since nothing enforces they match. |
| `agent/tools/catalog.py`, `agent/tools/booking.py` | Standalone, reasonably clean reimplementations of the two tools. **Not imported anywhere** — `bot.py` defines its own inline `search_racquets`/`book_fitting`. Currently dead code (see §7). |
| `agent/data/racquets.json` | The only catalog the agent is allowed to recommend from, per the hard rule in `CLAUDE.md`. Backend-side source of truth. |
| `agent/data/bookings.csv` | Append-only ledger written by `book_fitting()`. Created on first booking; not committed to git. |
| `web/index.html` | Storefront shell plus a **second, hardcoded copy of the racquet catalog** (inline `<script>` array) used only to render the display grid — independent of `racquets.json` (see §7). |
| `web/voice-widget.js` | Chat UI state, mic input via `SpeechRecognition`, voice output via `SpeechSynthesis`, and the `fetch` call to the backend. Also decides the API base URL (localhost vs. hardcoded Railway URL). |
| `web/style.css` | Presentation only. |
| `railway.json`, `Procfile.txt` | Deployment start-command declarations for Railway (belt-and-suspenders — both say `python agent/bot.py`). |
| `docs/PRD.md` | v1 scope, explicitly excludes cross-session memory, payments, non-Cantonese languages. |
| `docs/AGENT_DESIGN.md` | Persona and conversation-flow spec at the product level — parallels `system_prompt.md` but is not read by any code. |

## 4. Agent design

- **Persona**: 拍友, colloquial Cantonese (口語), casually mixes English brand names. Enforced entirely through the system prompt text, not through code-level filtering of output language.
- **Fixed question order**: budget → level → play style → recommend → (optional) book. This is a scripted slot-filling flow expressed as *prose instructions* to the LLM, not as explicit code-tracked state — the model itself is trusted to remember which slots are filled and what to ask next, using the conversation history as its only state.
- **Two-tool design**: `search_racquets` (read-only, freely callable) and `book_fitting` (side-effecting, gated). This split — cheap/idempotent tools the model can call at will vs. one dangerous tool with a backend-enforced check — is the main safety mechanism in the system.
- **Backend-enforced confirmation guardrail** (`is_explicit_confirmation` / `handle_book_fitting`): this is the most deliberate piece of defensive design in the codebase. Rather than trusting the model's judgment that "the customer confirmed," the backend independently re-examines the customer's literal last message for negation markers (唔係/唔好/cancel/no) and confirmation markers (係/OK/好) before allowing the CSV write to happen. Even if the model hallucinates a confirmation or calls the tool prematurely, the write is blocked unless the raw text backs it up. This is a good pattern: **never trust the model's own account of user intent for an irreversible action — check the source text.**
- **Graceful catalog degradation**: `search_racquets` in `bot.py` tries exact filters first, then progressively relaxes play-style, then level, then budget, so the model is never handed a hard empty result for a plausible ask. Tradeoff: this makes the search function stateful-feeling and harder to reason about (a "beginner" filter can silently return advanced racquets if nothing matches) — it optimizes for "always have something to say" over "only return what was literally asked for."

## 5. Mock mode: a parallel, non-LLM orchestrator

`MOCK_MODE` (triggered by `MOCK=1` or a missing API key) routes every message to `mock_reply()`, a hand-written finite-state machine (`step` field per session: `budget → level → style → ask_book → name → phone → datetime → confirm → done`) that mirrors the exact question order in `system_prompt.md` using regex/substring matching instead of an LLM.

This is a real design choice, not a stub: it lets the whole demo — including "show me more options," refusal topics, and the booking confirmation flow — run with **zero API calls and zero cost**, which matters for rehearsing a demo repeatedly. The tradeoff is that the conversation logic now exists **twice**: once as prose in `system_prompt.md` (interpreted by the LLM) and once as an explicit state machine in Python (`MOCK_PROMPTS`, `REFUSAL_TRIGGERS`, etc.). Nothing keeps these two in sync — if the real prompt's question order or wording changes, the mock path has to be updated by hand or the demo diverges from the real behavior it's supposed to rehearse.

## 6. Context management

- **What's sent**: the entire per-session message list (every user turn, every assistant turn, every tool-use/tool-result pair) is sent on every single API call, unmodified, with no summarization or windowing.
- **What's cached**: nothing. The system prompt file is re-read from disk on every request; the catalog JSON is re-read from disk on every `search_racquets` call.
- **What's not handled**: there is no token-budget awareness. A long conversation (many racquet searches, several rounds of "show me more") grows the history indefinitely within the process lifetime, increasing latency and cost turn over turn with no trimming, summarization, or sliding window.
- **Tradeoff being made**: simplicity over scalability. For a v1 with a short, bounded conversation (3 qualifying questions → recommend → book), full-history-every-time is easy to reason about and debug. It will not hold up if conversations get long or multi-session.

## 7. Memory: what "memory" means here today

There are two, unrelated stores, both in-process Python dicts with no persistence:

- `sessions_history` — the real conversation transcript sent to Anthropic, keyed by `session_id`.
- `mock_sessions` — separate state for the scripted mock flow, keyed by the same `session_id` but deliberately isolated so the two code paths never cross-contaminate.

Properties of this design (from `PRD.md`'s explicit out-of-scope: "Memory across sessions (each conversation starts fresh)"):

- **Scoped to one process lifetime.** A server restart (redeploy, crash, Railway dyno cycle) silently wipes every in-flight conversation. There's no warning to the user — the widget will just start a "fresh" agent turn with a `session_id` the server no longer recognizes as anything but an empty new history.
- **Scoped to one server instance.** If this were ever run with >1 worker/replica, a session pinned to instance A would lose all history if a later request lands on instance B — there's no shared/external store (Redis, DB) behind it.
- **`session_id` itself is weak.** It's generated client-side in `voice-widget.js` as `'session_' + Math.floor(Math.random() * 999999)` on page load — not persisted (e.g. to `localStorage`), so refreshing the page silently starts a new "customer" with no history, and the ~1M-value space is a collision risk under any real concurrent traffic (two tabs could theoretically share a session).
- **Unbounded growth, no eviction.** Nothing ever removes an entry from `sessions_history` or `mock_sessions` for the life of the process — a long-running deployment with many unique visitors leaks memory slowly (every session_id ever seen stays in the dict forever).
- **No durable record of the conversation itself** — only the booking's final fields (name/phone/datetime) survive, in `bookings.csv`. The reasoning that led there (what budget/level/style was discussed) is not persisted anywhere once the process history is gone.

This is a reasonable, deliberate tradeoff for a v1 demo (matches the PRD's explicit scope cut) but is the single biggest thing to revisit before this looks like a production support channel — see §9.

## 8. Orchestration and tooling choices

- **No agent framework.** The tool-calling loop is hand-rolled directly against the raw Anthropic Messages API (`anthropic` SDK's `client.messages.create`), not LangChain/LlamaIndex/an Anthropic agent framework. Tradeoff: full visibility and control over exactly what gets appended to history and when (which is what makes the iteration cap and the confirmation guardrail possible to implement precisely) — at the cost of having to hand-implement things a framework would give for free: retries/backoff, streaming, structured tracing, automatic context trimming.
- **Model pinned by string literal**: `MODEL = "claude-3-5-haiku-20241022"` in `bot.py`. `CLAUDE.md` documents the intended model as `claude-haiku-4-5` — these currently disagree; whichever is intended, only one place (`bot.py:25`) actually controls runtime behavior.
- **Tool execution is synchronous and untraced.** Tool calls run inline in the request thread with no logging of which tool was called with what arguments beyond a bare `print()` on exceptions — debugging a bad recommendation in production means reproducing it, not reading a log.
- **Iteration cap as a circuit breaker** (`MAX_TOOL_ITERATIONS = 5`): protects against runaway tool-call loops (e.g., a model repeatedly calling `search_racquets` with slightly different args) turning into unbounded latency/cost. Good defensive default; the fallback message it returns is generic rather than telling the user anything about *why* it stopped.
- **Error handling is string-sniffing.** The single `except Exception` handler classifies billing errors by checking whether `"credit"` or `"balance"` appears (case-insensitively) in `str(e)` — fragile if the SDK's error message wording changes, and it collapses all other failure modes (network, auth, malformed tool args, rate limit) into one generic "try again later" reply.

## 9. Known inconsistencies found in this review

These are concrete, verifiable issues in the current tree, not style opinions:

1. **`agent/tools/catalog.py` and `agent/tools/booking.py` are dead code.** `agent/bot.py` never imports either module; it reimplements both functions inline with different (and inconsistent) behavior — e.g. `bot.py`'s `search_racquets` defaults missing `in_stock` to `True` (`r.get("in_stock", True)`), while `tools/catalog.py`'s version defaults it to falsy (`r.get("in_stock")`, i.e. excluded). If anyone edits `tools/catalog.py` expecting it to change live behavior, nothing will happen.
2. **Two divergent racquet catalogs.** `agent/data/racquets.json` (used by the backend/agent) and the inline `RACQUET_CATALOG` array hardcoded in `web/index.html` (used only for the display grid) are separately maintained lists of the same 10 products, in different shapes (`best_for` is a tagged array in one, a single Traditional-Chinese string in the other). Nothing keeps them in sync — the storefront grid could show a racquet the agent will never actually recommend, or vice versa, whenever one file is edited without the other.
3. **Model ID mismatch** between `CLAUDE.md` (`claude-haiku-4-5`) and `agent/bot.py:25` (`claude-3-5-haiku-20241022`).
4. **`CLAUDE.md` references `agent/eval/conversations/`** as the location of test conversations; this directory does not exist in the repository yet.
5. **CORS is fully open** (`CORS(app)` with no origin restriction) and there is no rate limiting or auth on `/chat` — acceptable for a local/demo deployment, a gap before this fronts a real store with a public URL (someone could script requests directly against the Railway endpoint and run up API costs, or spam `bookings.csv`).
6. **CSV writes are not concurrency-safe.** `book_fitting()` opens, appends, and closes the file per call with no locking; fine under Flask's single-threaded dev server, a latent race if this is ever run with multiple workers/threads.

## 10. Where to improve, roughly in priority order

1. **Delete or wire up `agent/tools/*`.** Either import and use them from `bot.py` (removing the inline duplicates) or delete them — right now they're a trap for the next person who edits them expecting an effect.
2. **Single source of truth for the catalog.** Have `web/index.html` fetch/render from `racquets.json` (or from a `/catalog` endpoint the backend serves) instead of maintaining a second hardcoded array.
3. **Give sessions a TTL and an eviction policy**, even a crude one (e.g., drop entries untouched for >N minutes on each request), so `sessions_history`/`mock_sessions` don't grow unbounded in a long-running process.
4. **Persist `session_id` client-side** (`localStorage`) so a page refresh doesn't silently start a new customer — small change, meaningfully better continuity for the one thing this app's memory currently supports (single-session, single-process continuity).
5. **If conversations are expected to run long**, add a real context strategy: summarize or drop early turns once history crosses a token/turn threshold, rather than sending the full transcript every time.
6. **Reconcile the model ID** between `CLAUDE.md` and `bot.py`, and consider reading it from an env var so deploy-time model changes don't require a code edit.
7. **Structured logging around tool calls** (tool name, args, latency, result size) — currently a bad recommendation or a missed booking is a "reproduce it locally" problem, not a "read the log" problem.
8. **Decide the mock-mode maintenance story.** Either generate `MOCK_PROMPTS`/state transitions from `system_prompt.md` at load time so the two can't drift, or accept the duplication explicitly and add a comment/test that fails when the real prompt's question order changes without a corresponding mock update.
9. **Basic abuse protection before any public marketing push**: rate-limit `/chat`, and consider restricting CORS to the actual storefront origin instead of `*`.
10. **Create the `agent/eval/conversations/` fixtures** `CLAUDE.md` already references, or update `CLAUDE.md` to stop pointing at a path that doesn't exist.
