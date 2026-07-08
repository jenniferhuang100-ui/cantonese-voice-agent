# Walkthrough Prep — Agent Design Review with Tom

Study guide for talking through this project's agent design. Grounded in the actual repo, not generic agent theory. Read once tonight, speak from it tomorrow.

---

## 1. Why an agent, not a fixed workflow

**Decision**: `docs/PRD.md`'s one journey looks linear (budget → level → style → recommend → book) but branches on open-ended input at almost every step: the customer can ask for "other options" after a recommendation, refuse to confirm a booking and loop back, bring up an out-of-scope topic (injury, stringing) mid-flow, or answer a qualifying question in a way that doesn't map cleanly to the expected slot. A scripted workflow (fixed prompts, fixed transitions) can't absorb that without an explosion of special-case branches — an LLM interpreting free text against a small tool set can.

**Tradeoff**: you trade determinism for flexibility. The mock-mode FSM in `bot.py` (`mock_reply()`) is actually proof of the tradeoff in code — it's the same conversation *as a rigid workflow*, and it already needs regex/substring special-casing (`MORE_OPTIONS_TRIGGERS`, `REFUSAL_TRIGGERS`) to approximate what the LLM does natively.

**Say out loud**: "The conversation isn't actually linear — customers ask for more options, refuse to confirm, or go off-script — so I needed something that interprets intent rather than matches fixed states. I proved that to myself by building the rigid version too, as the mock-mode fallback."

**Gap risk**: if Tom asks "show me the workflow version," you can point straight at `mock_reply()` — it's a legitimate answer, not a dodge.

---

## 2. PRD → Agent Design → Architecture as a process

**Decision**: three docs, three altitudes.
- `docs/PRD.md` — product scope: the one journey, explicit out-of-scope list, success criteria.
- `docs/AGENT_DESIGN.md` — behavioral spec: persona, conversation order, slots, guardrails, escalation, written as prose a human (or an LLM) can follow.
- `docs/ARCHITECTURE.md` — engineering reality: request flow, file responsibilities, tradeoffs, and — deliberately — a list of places where the code has drifted from the design docs.

**Tradeoff**: `AGENT_DESIGN.md` is a human-readable mirror of `agent/prompts/system_prompt.md`, not the thing the code actually reads. Nothing enforces they match. That's a real cost of this structure — the design doc can lie without anyone noticing.

**Say out loud**: "I separated product scope, behavioral spec, and implementation so each could be reviewed at the right altitude — but I know the behavioral doc and the runtime prompt can silently drift, and `ARCHITECTURE.md` §9 is me documenting the places that already have."

**Gap risk**: `AGENT_DESIGN.md` mentions `capture_lead()` as the escalation tool after 2 failed attempts — **this function does not exist in `bot.py`**. If Tom reads both docs he will find this. Decide before tomorrow: implement a stub, or say plainly "designed, not yet built."

---

## 3. Model selection

**Decision**: `claude-3-5-haiku-20241022`, pinned as a string literal at `agent/bot.py:25`. Right call for this task shape — short bounded conversation, simple tool-calling, latency and cost matter more than deep reasoning.

**Gap**: `CLAUDE.md` says the intended model is `claude-haiku-4-5`. These disagree. Only `bot.py:25` actually controls runtime behavior — whichever doc is "aspirational," the code is truth.

**Say out loud**: "I chose Haiku deliberately for cost/latency on a bounded conversation, not because it's the default — but I have a stale reference to reconcile between CLAUDE.md and the actual pinned model string."

---

## 4. The agentic loop (ReAct), hand-rolled

**Decision**: `agent/bot.py:chat()`, lines ~318–381. Raw `while response.stop_reason == "tool_use"` loop against the Anthropic Messages API directly — no framework.
- Each iteration: append the assistant's tool-use block(s) to `history`, execute the tool(s) locally and synchronously, append `tool_result`, call `messages.create()` again.
- `MAX_TOOL_ITERATIONS = 5` acts as a circuit breaker against runaway tool-call loops.
- On cap-out: the code returns a canned fallback **without appending the dangling `tool_use` block** to history — so the next turn's API call doesn't fail on an unmatched tool_use/tool_result pair. This is the detail that shows you understand the Messages API's structural invariants, not just "loop until done."

**Say out loud**: "It's a hand-rolled ReAct loop so I have exact control over what enters history — the iteration cap is a circuit breaker, and when it trips, I specifically avoid leaving an unmatched tool_use block, or the very next turn would fail."

---

## 5. Context management vs. hallucination control (two different things)

**Context management** (`ARCHITECTURE.md §6`): full transcript resent on every call, no windowing, no summarization, no caching (system prompt and catalog JSON are both re-read from disk every request). Fine for a 3-question bounded flow; will not hold up for long or multi-session conversations — cost and latency grow unbounded within a process lifetime.

**Hallucination control** — two independent mechanisms:
1. **Catalog grounding**: the model can only ever see racquets from `search_racquets()`'s output, which reads `racquets.json` — never invents products/prices (`CLAUDE.md` hard rule, enforced by the tool boundary, not by the model's honesty).
2. **`is_explicit_confirmation()`** (`bot.py:111`): before `book_fitting` writes anything, the backend independently re-scans the customer's *raw last message* for negation markers (唔係/唔好/cancel/no) and confirmation markers (係/OK/好), rather than trusting the model's claim that "the customer confirmed." Even a hallucinated confirmation from the model gets blocked if the literal text doesn't back it up.

**Say out loud**: "Grounding and confirmation are solving different problems — grounding stops invented products, the confirmation check stops the model from acting on its own mistaken belief about what the customer said. The second one is the one I'd defend hardest: never trust the model's account of user intent for an irreversible action, check the source text."

---

## 6. Memory / state, and why there's no user database

**Decision**: `sessions_history` — an in-process Python dict, keyed by `session_id`, holding the full transcript sent to Anthropic. `mock_sessions` is a second, deliberately isolated dict for the FSM demo path. No database, no persistence. This matches `PRD.md`'s explicit scope cut: "Memory across sessions (each conversation starts fresh)."

**Concrete failure modes** (know these cold):
- Server restart/redeploy/crash silently wipes every in-flight conversation — no warning to the user.
- Doesn't survive >1 worker/replica — a session pinned to instance A loses history if a later request lands on instance B.
- `session_id` is generated client-side in `voice-widget.js` as `'session_' + Math.floor(Math.random() * 999999)` — not persisted to `localStorage`, so a page refresh silently starts a "new customer," and the ~1M-value space is a real collision risk under concurrent traffic.
- No eviction — every `session_id` ever seen stays in the dict for the life of the process (slow memory leak under sustained traffic).
- Only the final booking fields survive durably (`bookings.csv`) — the reasoning that led there (budget/level/style discussed) disappears once process memory is gone.

**Say out loud**: "There's no user database because the PRD explicitly scoped memory out for v1 — but I can name every failure mode that creates, and the fix path (Redis/Postgres-backed session store with TTL) if this needs to survive a redeploy or scale past one instance."

---

## 7. Tool design

**Decision**: exactly two tools, split by risk.
- `search_racquets` — read-only, freely callable, degrades gracefully (tries exact filters, then relaxes play_style, then level, then budget, so the model is never handed a dead end).
- `book_fitting` — side-effecting, gated behind `handle_book_fitting()` → `is_explicit_confirmation()`.

This split — cheap/idempotent tools the model can call at will vs. one dangerous tool with a backend-enforced check — **is** the safety architecture, not a side detail of it.

**Tradeoff in `search_racquets`'s graceful degradation**: relaxing filters means a "beginner" search can silently return advanced racquets if nothing matches beginner + style. Optimizes for "always have something to say" over "only return what was literally asked for" — a defensible v1 choice, but worth naming as a choice.

**Gap risk**: `agent/tools/catalog.py` and `agent/tools/booking.py` exist as standalone, cleaner reimplementations of these two tools — **but `bot.py` never imports them**. It has its own inline versions, and they disagree: `bot.py`'s `search_racquets` defaults missing `in_stock` to `True`, while `tools/catalog.py`'s defaults it to falsy (excluded). This is dead code today. If Tom asks "which file is actually running," the honest answer is `bot.py`'s inline functions — the `tools/` module does nothing at runtime. Decide before tomorrow: delete `tools/*`, or wire it in and remove the duplication.

---

## 8. Orchestration: why no framework

**Decision**: raw `anthropic` Python SDK (`client.messages.create`), no LangChain/LlamaIndex/agent framework.

**Tradeoff**: full visibility and control over exactly what gets appended to history and when — which is what makes the iteration cap and the confirmation guardrail possible to implement precisely — at the cost of hand-implementing things a framework gives for free: retries/backoff, streaming, structured tracing, automatic context trimming.

**Say out loud**: "For two tools and a bounded conversation, a framework would add abstraction I'd have to fight to get the same guarantees out of. If this grows — more tools, longer conversations, multi-agent handoff — that calculus changes, and I'd revisit it then rather than pre-adopt one now."

---

## 9. Guardrails and human-in-the-loop

**Implemented**: confirmation-before-booking (`is_explicit_confirmation`), refusal script for out-of-scope topics (injury, stringing, medical) both in `system_prompt.md` and mirrored in the mock FSM's `REFUSAL_TRIGGERS`.

**Documented but not implemented**: `AGENT_DESIGN.md` specifies escalation — "if customer is confused or frustrated after 2 failed attempts... call `capture_lead()`" — this function doesn't exist anywhere in `bot.py`. This is the single most likely design-doc-vs-code gap Tom could catch. Have an answer ready either way.

---

## 10. Evals and success metrics

**Today's metrics** are `PRD.md`'s success criteria: recommendations only from `racquets.json`, confirmation always before booking, natural colloquial Cantonese, voice works on Chrome zh-HK, works on a public URL. All currently verified manually/by inspection, not by an automated eval suite.

**Gap**: `CLAUDE.md` references `agent/eval/conversations/` as the location of test conversations — **this directory does not exist in the repo**. This is a real, nameable next step, not a hidden flaw — say so directly.

**Say out loud**: "Success criteria exist and are precise, but they're not automated yet — the next concrete step is a small eval harness of recorded conversations that assert catalog-only recommendations and confirmation-gated bookings, which CLAUDE.md already points at a path for."

---

## 11. Scaling limits

Single Flask process, `debug=False` dev server, everything in-memory, tool execution synchronous and in-thread, CORS fully open (`CORS(app)` no origin restriction), no rate limiting on `/chat`, CSV writes not concurrency-safe (open/append/close per call, no locking). Fine for a local demo or a low-traffic pilot; not fine the moment this fronts real public marketing traffic — someone could script requests directly against the endpoint and run up API cost, or corrupt `bookings.csv` under concurrent writes.

**Say out loud**: "This is sized for a demo and a soft pilot, not for a marketing push — before that, it needs rate limiting, restricted CORS, and a real session store so it can run more than one worker."

---

## 12. Tradeoffs and roadmap ("if I had more time")

Pull directly from `ARCHITECTURE.md §10`, in priority order — this already reads as "I know exactly what's next":
1. Delete or wire up `agent/tools/*` (stop the dead-code trap).
2. Single source of truth for the catalog (`web/index.html` currently hardcodes a second, divergent racquet list — have `web/index.html` fetch from `racquets.json` or a `/catalog` endpoint instead).
3. Session TTL/eviction so `sessions_history`/`mock_sessions` don't grow unbounded.
4. Persist `session_id` to `localStorage` so a page refresh doesn't start a "new customer."
5. Real context strategy (summarize/trim) once conversations are expected to run long.
6. Reconcile the model ID between `CLAUDE.md` and `bot.py`; read it from an env var.
7. Structured logging around tool calls (name, args, latency, result size).
8. Decide the mock-mode maintenance story explicitly (generate it from the real prompt, or accept and guard the duplication).
9. Rate limiting + restricted CORS before any public push.
10. Create the `agent/eval/conversations/` fixtures `CLAUDE.md` already references.

---

## Things Tom will probably ask — and the one-line answer

| Likely question | Answer |
|---|---|
| "Which file actually runs — `bot.py`'s inline tools or `agent/tools/*`?" | `bot.py`'s inline versions; `agent/tools/*` is currently dead code, not imported anywhere. |
| "Does `capture_lead()` actually get called?" | No — it's specified in `AGENT_DESIGN.md`'s escalation flow but not implemented yet. Named gap, not a surprise. |
| "What happens if the server restarts mid-conversation?" | Silent history loss — in-memory only, no persistence, matches the PRD's explicit "no cross-session memory" scope for v1. |
| "How do you know the model isn't hallucinating a booking confirmation?" | It doesn't matter what the model believes — `is_explicit_confirmation()` re-checks the customer's literal last message server-side before any write. |
| "Why not use LangChain / an agent framework?" | Two tools, bounded conversation — hand-rolling gives exact control over history and the confirmation guardrail; would reconsider if scope grows. |
| "What's your eval story — how do you know a prompt change didn't break something?" | Today: manual. `CLAUDE.md` already points at `agent/eval/conversations/` as the intended location; it doesn't exist yet — that's the next concrete step. |
| "The website shows a racquet — does the agent actually recommend that exact one?" | Maybe not — `web/index.html` has its own hardcoded catalog copy, separate from `racquets.json`, and nothing keeps them in sync. Known issue, on the roadmap. |
| "What's your actual model — Haiku 4.5 or 3.5?" | `bot.py:25` pins `claude-3-5-haiku-20241022`; `CLAUDE.md` says `claude-haiku-4-5` — needs reconciling, code is the source of truth today. |
| "How would this scale past one user at a time?" | It wouldn't yet — single process, in-memory sessions, no rate limiting, non-concurrency-safe CSV writes. That's the honest v1 boundary. |

---

## 13. If I had more tools/resources

Framed around the actual weak points already named above (no streaming, fragile browser STT/TTS, no durable memory, no evals) — not a generic "cool tools" list.

**Voice layer — the biggest upgrade available**
Today's design does full-cycle HTTP request/response (client waits for the entire tool loop to resolve before hearing anything) and leans on browser `SpeechRecognition`/`SpeechSynthesis`, which has patchy zh-HK support outside Chrome desktop.
- **Pipecat** (Daily) or **LiveKit Agents** — open-source real-time voice-agent frameworks with pluggable STT/LLM/TTS over WebRTC, built-in turn-taking and interruption handling, streaming — would remove the "wait for the whole loop" latency problem outright and open a phone/telephony path (Twilio) almost for free.
- **Dedicated STT/TTS with real Cantonese support**: Azure Speech (native zh-HK neural voices, e.g. `HiuMaanNeural`) or Google Cloud Speech-to-Text/Text-to-Speech (`yue-Hant-HK` locale) are the two vendors with genuine Cantonese coverage, not just "zh" that quietly means Mandarin. Worth verifying actual Cantonese quality against real audio before committing, rather than trusting a docs page.

**Orchestration**
- Anthropic's own **Claude Agent SDK** — memory/tool-orchestration scaffolding while staying close to the low-level control the confirmation guardrail currently depends on; a smaller jump than LangChain.
- **LangGraph** if the conversation flow needs to become an explicit, inspectable state graph — useful once "why did it skip a question" becomes a real support question, not just a hypothetical one.

**Memory/state**
- **Redis** for session storage with real TTL/eviction — directly fixes the "process restart wipes everything" and "no eviction" gaps.
- **Postgres** (or SQLite to start) for durable conversation + booking history — replaces the CSV and preserves the "why did they book this" context currently lost once process memory is gone.
- **pgvector/Pinecone** only once the catalog outgrows simple JSON filtering — not needed at 10 racquets; worth naming the trigger condition rather than pre-adopting it.

**Guardrails/safety**
- Keep the backend-side confirmation-check pattern — it's the strongest piece already here — but add rate limiting (even simple Flask-Limiter) and restrict CORS to the real storefront origin before any public traffic.

**Evals**
- Lightweight first: pytest + the `agent/eval/conversations/` fixtures `CLAUDE.md` already references, asserting catalog-only recommendations and confirmation-gated bookings — gets most of the value cheaply.
- **Braintrust** or **promptfoo** for regression tracking across prompt changes, once conversation volume is high enough that manual spot-checking stops working.
