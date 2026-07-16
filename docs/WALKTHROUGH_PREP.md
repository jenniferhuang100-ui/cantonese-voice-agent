# Walkthrough Prep — Agent Design Review with Tom

Study guide for talking through this project's agent design. Grounded in the actual repo, not generic agent theory. Read once tonight, speak from it tomorrow.

---

## 1. Why an agent, not a fixed workflow

**Decision**: `docs/PRD.md`'s one journey looks linear (budget → level → style → recommend → book) but branches on open-ended input at almost every step: the customer can ask for "other options" after a recommendation, refuse to confirm a booking and loop back, bring up an out-of-scope topic (injury, stringing) mid-flow, or answer a qualifying question in a way that doesn't map cleanly to the expected slot. A scripted workflow (fixed prompts, fixed transitions) can't absorb that without an explosion of special-case branches — an LLM interpreting free text against a small tool set can.

**Tradeoff**: you trade determinism for flexibility. The mock-mode FSM in `bot.py` (`mock_reply()`) is actually proof of the tradeoff in code — it's the same conversation *as a rigid workflow*, and it already needs regex/substring special-casing (`MORE_OPTIONS_TRIGGERS`, `REFUSAL_TRIGGERS`) to approximate what the LLM does natively.

**Say out loud**: "The conversation isn't actually linear — customers ask for more options, refuse to confirm, or go off-script — so I needed something that interprets intent rather than matches fixed states. I proved that to myself by building the rigid version too, as the mock-mode fallback."

**Gap risk**: if Tom asks "show me the workflow version," you can point straight at `mock_reply()` — it's a legitimate answer, not a dodge.

---

## 1a. Single agent, not sequential/multi-agent

**Decision**: one LLM, one system prompt, one tool-calling loop (`agent/bot.py`) handles the whole conversation end-to-end — qualifying questions, recommendation, and booking. This is *not* a sequential pipeline of specialized agents (e.g. an "intent router" agent handing off to a "recommender" agent handing off to a "booking" agent), and not a multi-agent/orchestrator pattern.

**Why**: the task is small enough that hand-offs would cost more than they'd buy — two tools, one persona, one bounded conversation. A multi-agent split adds inter-agent coordination, extra LLM calls per turn (cost + latency), and more moving state to keep in sync, without solving a problem this task shape actually has. It becomes worth it once sub-tasks need genuinely different personas, tool access, or context windows — e.g., a completely different product line, or a human-handoff agent with its own guardrails — not before.

**Say out loud**: "It's a single agent on purpose, not a pipeline. Two tools and one bounded conversation don't need inter-agent hand-offs — that would just add latency and coordination cost. I'd revisit this the moment a sub-task genuinely needs a different persona or tool set than the rest of the conversation."

**Gap risk**: if Tom asks "why not split recommendation and booking into separate agents," the honest answer is exactly the tradeoff above — you can also point out `mock_reply()`'s FSM as proof you can name the alternative even for the *workflow* axis (§1); this section is the *single-vs-multi-agent* axis, a different question worth distinguishing if he conflates them.

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

**Decision**: `deepseek-chat` (DeepSeek V3), pinned as a string literal in `agent/bot.py`, called through DeepSeek's OpenAI-compatible API. Right call for this task shape — short bounded conversation, simple tool-calling, latency and cost matter more than deep reasoning.

**Two deliberate details worth naming**:
- `deepseek-chat`, NOT `deepseek-reasoner` — the reasoner (R1) doesn't support function calling, and this agent is built entirely around two tools. Picking the "smarter" model here would have broken the product. Model choice is task-shape analysis, not leaderboard-chasing.
- **This codebase was migrated from Claude Haiku 4.5 to DeepSeek.** The swap touched only the provider adapter: client init, tool-schema shape (Anthropic `input_schema` → OpenAI `function.parameters`), and message roles (`tool_result` blocks → `role:"tool"` messages). Both guardrails — catalog grounding and the booking confirmation check — survived without changing a line, because they're enforced server-side, not provider-side.

**Remaining gap**: still a hardcoded literal, not read from an env var — a model change at deploy time needs a code edit.

**Say out loud**: "I've migrated this agent across providers — Anthropic to DeepSeek — and the only code that changed was the SDK adapter. The guardrails didn't move, which is the payoff of enforcing them in my backend instead of trusting any provider's model. And I chose deepseek-chat over deepseek-reasoner deliberately: the reasoner doesn't do function calling, and this agent lives on tools."

---

## 4. The agentic loop (ReAct), hand-rolled

**Decision**: `agent/bot.py:chat()`. Raw `while finish_reason == "tool_calls"` loop against the OpenAI-compatible chat-completions API (DeepSeek) directly — no framework.
- Each iteration: append the assistant's message with its `tool_calls` to `history`, execute the tool(s) locally and synchronously, append one `role: "tool"` message per call (matched by `tool_call_id`), call `chat.completions.create()` again.
- `MAX_TOOL_ITERATIONS = 5` acts as a circuit breaker against runaway tool-call loops.
- On cap-out: the code returns a canned fallback **without appending the unanswered `tool_calls` message** to history — so the next turn's API call doesn't fail on a tool call with no matching tool reply. This is the detail that shows you understand the chat API's structural invariants, not just "loop until done."

**Say out loud**: "It's a hand-rolled ReAct loop so I have exact control over what enters history — the iteration cap is a circuit breaker, and when it trips, I specifically avoid leaving an unanswered tool call in history, or the very next turn would fail."

---

## 5. Context management vs. hallucination control (two different things)

**Context management** (`ARCHITECTURE.md §6/§6a`): full transcript resent on every call, no windowing, no summarization, no caching (system prompt and catalog JSON are both re-read from disk every request). Fine for a 3-question bounded flow; will not hold up for long or multi-session conversations — cost and latency grow unbounded within a process lifetime. **The fix, when needed, is summarization, not blunt truncation**: once history crosses a turn/token threshold, collapse the older turns into a short summary of the slots already filled (budget/level/style/name/phone) and keep only the last 2–3 raw turns verbatim — truncation alone risks silently dropping a slot the model then re-asks or contradicts.

**Hallucination control** — two independent mechanisms:
1. **Catalog grounding**: the model can only ever see racquets from `search_racquets()`'s output, which reads `racquets.json` — never invents products/prices (`CLAUDE.md` hard rule, enforced by the tool boundary, not by the model's honesty).
2. **`is_explicit_confirmation()`** (`bot.py`): before `book_fitting` writes anything, the backend independently re-scans the customer's *raw last message* for negation markers (唔係/唔好/cancel/no) and confirmation markers (係/OK/好), rather than trusting the model's claim that "the customer confirmed." Even a hallucinated confirmation from the model gets blocked if the literal text doesn't back it up.

**Say out loud**: "Grounding and confirmation are solving different problems — grounding stops invented products, the confirmation check stops the model from acting on its own mistaken belief about what the customer said. The second one is the one I'd defend hardest: never trust the model's account of user intent for an irreversible action, check the source text."

---

## 6. Memory / state, and why there's no user database

**Decision**: `sessions_history` — an in-process Python dict, keyed by `session_id`, holding the full transcript sent to the LLM. `mock_sessions` is a second, deliberately isolated dict for the FSM demo path. No database, no persistence. This matches `PRD.md`'s explicit scope cut: "Memory across sessions (each conversation starts fresh)."

**Why RAM over a database — the cost argument**: a database (even a small managed Postgres/Redis) is infrastructure that costs money and attention *even when idle* — provisioning, a connection to manage, a schema to migrate, a network round-trip added to every single turn. For a v1 conversation that's a few minutes long and doesn't need to survive a restart, that's pure overhead with no corresponding benefit. An in-process dict is free and faster (no network hop) for exactly this shape of workload. The calculus flips the moment either (a) sessions need to survive a redeploy/crash, or (b) this runs on more than one worker/instance — at that point RAM stops working *at all* (see failure modes below), not just becomes suboptimal, and a database stops being optional.

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

**Tool calling logic, concretely**: both tools are declared in `TOOLS_SCHEMA` (`bot.py`) in OpenAI function-calling format (`type: "function"` with name, description, JSON-schema `parameters`). The model decides when to call them based on the system prompt's instructions and the conversation so far — the code never forces a call. When the model returns `tool_calls`, `bot.py`'s loop reads each call's `function.name`/`function.arguments`, dispatches to the matching Python function (`search_racquets(**tool_args)` or `handle_book_fitting(tool_args, user_msg)`), and feeds the JSON result back as a `role: "tool"` message so the model can use it to write its next reply. `search_racquets` is imported from `agent/tools/catalog.py` and `book_fitting` from `agent/tools/booking.py` — one implementation, no inline duplicates in `bot.py`.

---

## 8. Orchestration: why no framework

**Decision**: raw `openai` Python SDK pointed at DeepSeek's endpoint (`client.chat.completions.create`), no LangChain/LlamaIndex/agent framework.

**Tradeoff**: full visibility and control over exactly what gets appended to history and when — which is what makes the iteration cap and the confirmation guardrail possible to implement precisely — at the cost of hand-implementing things a framework gives for free: retries/backoff, streaming, structured tracing, automatic context trimming.

**Say out loud**: "For two tools and a bounded conversation, a framework would add abstraction I'd have to fight to get the same guarantees out of. If this grows — more tools, longer conversations, multi-agent handoff — that calculus changes, and I'd revisit it then rather than pre-adopt one now."

---

## 9. Guardrails and human-in-the-loop

**Implemented**: confirmation-before-booking (`is_explicit_confirmation`), refusal script for out-of-scope topics (injury, stringing, medical) both in `system_prompt.md` and mirrored in the mock FSM's `REFUSAL_TRIGGERS`.

**Documented but not implemented**: `AGENT_DESIGN.md` specifies escalation — "if customer is confused or frustrated after 2 failed attempts... call `capture_lead()`" — this function doesn't exist anywhere in `bot.py`. This is the single most likely design-doc-vs-code gap Tom could catch. Have an answer ready either way.

---

## 10. Evals and success metrics

**Built and passing** (`agent/eval/`, run `python agent/eval/run_evals.py [--live]`). Two layers:
- **Deterministic (free, the CI gate)**: unit checks on `is_explicit_confirmation` (10 accepts / 10 rejects, including the strict "no problem" rejection), `handle_book_fitting` (missing fields and non-confirmations blocked, CSV untouched), `search_racquets` (exact filter results, relaxation behavior, catalog integrity) — plus three golden conversations replayed against the mock FSM.
- **Live (`--live`, the pre-release smoke test)**: the same golden conversations against real DeepSeek through the full `/chat` route — happy path (booking written only after 係呀), **declined path (model holds all three fields, customer says 唔係 at read-back → zero rows written)**, and the injury-question refusal.

**Latest run**: 2026-07-17, 79/79 passed. Booking writes are redirected to a throwaway CSV during evals.

**Honest limits, say them unprompted if asked to go deep**: the "no invented products" check is a proxy (quoted prices must exist in the catalog + catalog-model-name counting); no LLM-as-judge yet for tone/length; the live layer is non-deterministic so it's a smoke test, not the CI gate.

**Say out loud**: "The two hard rules — catalog-only recommendations and confirmation-gated bookings — are asserted automatically now, in a deterministic layer that's free to run on every change and a live layer that replays the same golden conversations against the real model. The declined-booking fixture is the one I'd show first: the model has everything it needs to book, the customer says no, and the write never happens."

---

## 11. Scaling limits

Single Flask process, `debug=False` dev server, everything in-memory, tool execution synchronous and in-thread, CORS fully open (`CORS(app)` no origin restriction), no rate limiting on `/chat`, CSV writes not concurrency-safe (open/append/close per call, no locking). Fine for a local demo or a low-traffic pilot; not fine the moment this fronts real public marketing traffic — someone could script requests directly against the endpoint and run up API cost, or corrupt `bookings.csv` under concurrent writes.

**Say out loud**: "This is sized for a demo and a soft pilot, not for a marketing push — before that, it needs rate limiting, restricted CORS, and a real session store so it can run more than one worker."

---

## 12. Tradeoffs and roadmap ("if I had more time")

Pull directly from `ARCHITECTURE.md §10`, in priority order — this already reads as "I know exactly what's next":
1. ~~Single source of truth for the catalog~~ ✅ Done — `web/index.html` now fetches the backend's `/catalog` endpoint (which serves `racquets.json`); the Cantonese display copy lives in `racquets.json` as `tagline_zh`.
2. Session TTL/eviction so `sessions_history`/`mock_sessions` don't grow unbounded.
3. Persist `session_id` to `localStorage` so a page refresh doesn't start a "new customer."
4. Real context strategy (summarize/trim) once conversations are expected to run long — see §5's summarization approach.
5. Read the model ID from an env var so a deploy-time change doesn't need a code edit.
6. Structured logging around tool calls (name, args, latency, result size).
7. Decide the mock-mode maintenance story explicitly (generate it from the real prompt, or accept and guard the duplication).
8. Rate limiting + restricted CORS before any public push.
9. Create the `agent/eval/conversations/` fixtures `CLAUDE.md` already references.

---

## Things Tom will probably ask — and the one-line answer

| Likely question | Answer |
|---|---|
| "Which file actually runs — `bot.py`'s inline tools or `agent/tools/*`?" | `agent/tools/*` — `bot.py` imports `search_racquets`/`book_fitting` from there directly, no inline duplicates. |
| "Why one agent instead of separate agents for recommending vs. booking?" | Two tools, one bounded conversation — a hand-off between specialized agents would add coordination overhead and extra LLM calls without solving a problem this task shape has. Revisit if a sub-task needs a genuinely different persona or tool set. |
| "Why RAM instead of a database for session state?" | A database costs money and ops attention even idle, plus a network round-trip per turn — not worth it for a few-minutes-long v1 conversation that doesn't need to survive a restart. The moment sessions need to survive a redeploy or run on >1 worker, RAM stops working entirely and a database becomes non-optional. |
| "Does `capture_lead()` actually get called?" | No — it's specified in `AGENT_DESIGN.md`'s escalation flow but not implemented yet. Named gap, not a surprise. |
| "What happens if the server restarts mid-conversation?" | Silent history loss — in-memory only, no persistence, matches the PRD's explicit "no cross-session memory" scope for v1. |
| "How do you know the model isn't hallucinating a booking confirmation?" | It doesn't matter what the model believes — `is_explicit_confirmation()` re-checks the customer's literal last message server-side before any write. |
| "How would you control context growth in a long conversation?" | Summarize, not truncate — once history crosses a threshold, collapse older turns into a short summary of the filled slots (budget/level/style/name/phone) and keep the last 2–3 raw turns verbatim, so truncation can't silently drop a slot the model then re-asks. Not built yet — named next step. |
| "Why not use LangChain / an agent framework?" | Two tools, bounded conversation — hand-rolling gives exact control over history and the confirmation guardrail; would reconsider if scope grows. |
| "What's your eval story — how do you know a prompt change didn't break something?" | `python agent/eval/run_evals.py` — deterministic guardrail/catalog units plus golden conversations vs the mock FSM, free on every change; `--live` replays the same conversations against real DeepSeek. Latest: 79/79. Gap left: LLM-as-judge for tone, and CI wiring. |
| "The website shows a racquet — does the agent actually recommend that exact one?" | Yes — the grid fetches the backend's `/catalog` endpoint, which serves the same `racquets.json` the agent's `search_racquets` reads. One catalog, no second copy. |
| "What's your actual model?" | `bot.py` pins `deepseek-chat` (V3) — deliberately not `deepseek-reasoner`, which doesn't support function calling. Migrated from Claude Haiku 4.5; only the SDK adapter changed, guardrails untouched. Still a hardcoded literal, not env-configurable yet. |
| "How would this scale past one user at a time?" | It wouldn't yet — single process, in-memory sessions, no rate limiting, non-concurrency-safe CSV writes. That's the honest v1 boundary. See §11 for exactly what changes first. |

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
