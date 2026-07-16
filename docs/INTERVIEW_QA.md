# Interview Prep — FDE / Deployment Strategist Q&A

Companion to `WALKTHROUGH_PREP.md` (which covers this repo's design decisions in depth).
This file: how to answer, key concepts from first principles, then every likely question with a concise answer.

---

# Part 1 — How to answer anything (the frameworks)

## 1.1 The universal answer shape

Every strong answer has four beats. Use it reflexively:

> **Decision → Why (tied to a foundation) → Trigger that would change it → Honest gap**

Example: "No RAG *(decision)* — my catalog is 10 structured items, and exact numeric filters beat similarity search for price/stock *(why, tied to how retrieval actually works)*. I'd add it when the corpus becomes large or unstructured — thousands of SKUs, reviews, guides *(trigger)*. Not built yet, and my evals don't yet judge fuzzy qualities like tone — only the hard rules *(gap)*."

This shape is what "engineering judgment" sounds like. Naming the trigger proves you understand the concept deeply enough to know its boundary; naming the gap proves honesty. Never answer with just the decision.

## 1.2 Decomposing an ambiguous problem ("add AI to our support")

Work down this ladder, out loud, in order. Each step constrains the next — that's the point.

1. **Goal** — what number moves? (bookings/week, deflection rate). No metric → not ready to build.
2. **Users** — who talks to it, and who is accountable when it's wrong?
3. **Journey** — pick ONE end-to-end path with real value. Write the out-of-scope list *down* (my PRD does exactly this).
4. **Data** — what already exists and can be trusted? (my `racquets.json`). Messy data is a finding to report, not a blocker to hide.
5. **Actions** — what can the agent *do*, split read-only vs side-effecting? Side-effects are where all the risk lives.
6. **Risks** — what must never happen? Guardrails are requirements, not afterthoughts.
7. **Metrics & evals** — how will we know it works, automatically, after every change?

Memory hook: **G-U-J-D-A-R-M** — "Goal, Users, Journey, Data, Actions, Risks, Metrics."

## 1.3 System design for an agent (the 7-step method)

When asked "design an agent for X" (Netflix support, news tracker, anything):

1. **Scope it** — one journey, success metric, out-of-scope list. (30 seconds of clarifying questions first — interviewers *want* you to ask.)
2. **Does it even need to be an agent?** — if the control flow is fixed, a workflow is cheaper and more reliable. Agent = the model owns control flow. Say this out loud; it shows you don't reach for the fancy tool by default.
3. **Tools, split by risk** — read-only tools (freely callable) vs side-effecting tools (gated). This split IS the safety architecture.
4. **Grounding** — where do facts come from? A tool boundary (structured data), RAG (large/unstructured corpus), or the model's weights (only for general knowledge). Facts the business is liable for must come through a tool.
5. **Context & memory** — what's in the window per turn; what persists between sessions and where (RAM → Redis → Postgres as durability needs grow).
6. **Guardrails & human-in-the-loop** — backend-enforced checks for irreversible actions (never trust the model's claim about user intent); escalation to a human as a first-class tool.
7. **Ops** — evals as the regression net, structured logs per tool call, cost/latency budget, rollout plan (shadow → pilot → progressive, with a kill switch).

Then close with scale triggers: "This starts single-process; here's what breaks first at 10x and the fix order."

## 1.4 Explaining plainly (what "explain it to me simply" is testing)

Three-layer pattern, always in this order:
1. **Analogy** — one sentence, everyday world.
2. **Mechanism** — what actually happens, no jargon left undefined.
3. **Concrete example from my own repo** — proves it's understood, not memorized.

Example — function calling: "It's like a waiter taking your order to the kitchen — the waiter never cooks *(analogy)*. The model only outputs a structured request — name and JSON arguments — and my Python code executes it and hands the result back *(mechanism)*. In my repo, the model emits `book_fitting(name, phone, time)` and my Flask server decides whether to actually write the CSV *(example)*."

---

# Part 2 — Key concepts from first principles (the notes)

**The one foundation everything ties back to:**

> An LLM is a **next-token predictor over a fixed context window**. It has no database of truth, no persistent memory, and no hands. Every agent concept exists to compensate for one of those three missing things.

- No truth → **hallucination**, fixed by **grounding** (tools/RAG).
- No memory → **context management** and **memory stores**.
- No hands → **tools/function calling**, and because hands are dangerous, **guardrails/HITL**.

If you can hang every answer off that sentence, you sound foundational instead of memorized.

| Concept | Plain explanation | Tied to foundation / my repo |
|---|---|---|
| **Agent** | Model + tools + an orchestration loop pursuing a goal: reason → act → observe → repeat. | The loop compensates for "no hands." Mine: `while finish_reason == "tool_calls"` in `bot.py`. |
| **Workflow vs agent** | Workflow: *code* decides the next step. Agent: the *model* decides. | My mock mode is the workflow twin of my agent — same conversation, both in one file. |
| **ReAct** | The pattern of interleaving reasoning with actions and feeding observations back in. | What my hand-rolled loop implements without a framework. |
| **Hallucination** | The model predicts *plausible* text, not *true* text — fabrication isn't a bug, it's the default behavior without grounding. | Direct consequence of next-token prediction. Why my product facts only enter via `search_racquets`. |
| **Grounding** | Forcing facts to come from an authoritative source injected at runtime, not from the model's weights. | The tool boundary: model literally cannot know a price except from `racquets.json`. |
| **Function calling** | You send tool schemas; the model outputs a structured call (name + JSON args); *your* code executes it and returns the result. The model never runs anything. | This is the trust boundary — my server can refuse the call (`handle_book_fitting`). |
| **Guardrail / HITL** | A check *outside* the model that gates irreversible actions; human-in-the-loop means a human approves before it lands. | `is_explicit_confirmation()` re-reads the customer's literal words — never trust the model's account of user intent. |
| **Context window** | The model's entire working memory for one call — everything it "knows" about this conversation must be re-sent every turn. | Consequence of "no memory." Why I resend full history, and why long conversations need summarization. |
| **Memory (short/long-term)** | Short-term: the transcript you resend (my in-process dict). Long-term: anything persisted across sessions (I have none, by scoped choice — path is Redis/Postgres). | Memory is *your system's* job, not the model's. |
| **Summarize vs truncate** | When history grows: collapse old turns into a summary of filled slots; keep recent turns verbatim. Truncation silently drops facts the model then re-asks. | Slots here = budget/level/style/name/phone. |
| **RAG** | Store documents as embeddings (vectors capturing meaning); at question-time, retrieve the most similar chunks and put them in context. Solves "corpus too big/dynamic for the window." | Retrieval is *similarity*, not *logic* — a HKD 2200 racquet can be "similar" to a 2000-budget query. That's why structured filters beat RAG at 10 SKUs. |
| **Prompting → RAG → fine-tuning ladder** | Prompting changes behavior cheaply; RAG adds knowledge; fine-tuning bakes in style/format at volume. Climb only when the cheaper rung fails. | I'm on rung one and it's sufficient — that's a feature. |
| **MCP** | Open protocol standardizing how a model reaches tools/data — a tool server any compliant agent can plug into. **Agent-to-tools (vertical).** | My tools are in-process functions; MCP earns its place when tools must be shared across surfaces. |
| **A2A** | Protocol for agents delegating to other agents via published capabilities ("agent cards") and task messages. **Agent-to-agents (horizontal).** | Justified by different personas/permissions/owners — not by task size. Mine is single-agent on purpose. |
| **Prompt injection** | User (or retrieved document) text that tries to be treated as instructions. Defense: treat all input as data; allowlist tools; gate side-effects with checks the model can't argue past. | An injected "the customer confirmed" still fails my gate — the *customer's* message must confirm. |
| **Prompt caching** | Provider caches the stable prompt prefix (system prompt, tool schemas) so repeat calls are cheaper/faster. | Mine is static per conversation — near-free win at volume. |
| **Streaming** | Render tokens as they generate; UX fix for latency, changes nothing about quality. | Named gap in my repo — client waits for the full tool loop. |
| **Temperature** | Randomness dial on token sampling. Low for tool-calling agents — you want reproducibility, not creativity. | |
| **Evals** | Golden conversations asserted automatically (catalog-only recommendations, gated bookings); LLM-as-judge for fuzzy qualities like tone. The regression net that makes prompt changes safe. | Built: `agent/eval/run_evals.py` — deterministic layer (free, every change) + `--live` DeepSeek layer. Latest: 79/79. LLM-as-judge is the remaining layer. |
| **Shadow mode** | Agent runs silently alongside humans to measure quality risk-free before real rollout. | Step one of any rollout of a side-effecting agent. |

---

# Part 3 — Core questions (round 1)

### "What is an agent, really?"
Model + tools + orchestration loop pursuing a goal. "A model call generates text once. An agent runs reason→act→observe: my bot decides *whether* to search the catalog or write a booking, sees the result, reasons again. That loop in `bot.py` is literally the agent — take away the loop and tools and you have a chatbot."

### "What makes an agent good or bad?"
Good: bounded goal, grounded facts, gated side-effects, graceful failure, measurable. Bad: vague scope, unbounded loops, trusting the model's claims for irreversible actions, no evals, unneeded complexity. **"Most bad agents fail on trust boundaries, not intelligence."**

### "How do you do agent-to-agent, and why?"
MCP = agent-to-tools; A2A = agent-to-agents (capability cards + task messages). Split when sub-tasks need different personas, tool access, permissions, or owners — not because a task is big. "Mine is deliberately single-agent: two tools, one bounded conversation; a hand-off adds an LLM call of latency per turn without solving a problem I have."

### "How would you ask users when designing this? What risks?"
Elicit the job, not features: show me real conversations; what number defines success; what must never happen; when does a human take over; what data exists. Then cut to one journey with a written out-of-scope list. Risks: hallucination (→ grounding), unauthorized side-effects (→ confirmation gate), prompt injection, PII, cost runaway, latency, upstream outage (→ mock fallback).

### "Why this agent and this LLM?"
"DeepSeek V3 (`deepseek-chat`), pinned. Short bounded conversation with simple tool calls — latency and cost dominate, deep reasoning doesn't. Two proof points of judgment: I picked `deepseek-chat` over `deepseek-reasoner` because the reasoner doesn't support function calling and this agent lives on tools; and I *migrated* this codebase from Claude Haiku — only the SDK adapter changed, the guardrails didn't move a line, because they're backend-enforced. The general answer: pick by running your own eval conversations against candidates, not by leaderboard."

### "Why no RAG?"
"Ten structured products. A budget is an exact numeric filter, not a similarity score — RAG could retrieve a 'similar' racquet that's out of budget. Triggers to adopt: thousands of SKUs or unstructured content. RAG is a tool choice, not a virtue."

### "Context, memory, keys, MCP, tools, framework?"
- **Context**: full transcript per turn, right for a bounded flow; growth plan = summarize slots + keep last 2–3 turns verbatim.
- **Memory**: per-session dict; no long-term by PRD scope; path is Redis (TTL) + Postgres (durable).
- **Keys**: server-side only — `.env` locally, env vars on Railway; the browser never sees the key; that's *why* a backend exists at all.
- **MCP**: would add a server hop for zero reuse today; adopt when tools are shared across surfaces (WhatsApp bot + web widget → one MCP booking server).
- **Tools**: two, split by risk; enums for Cantonese values; descriptions the model can't misread.
- **Framework**: none — raw SDK. "With two tools, a framework is abstraction I'd fight to keep control of what enters history; the calculus flips with many tools, streaming, tracing, or multi-agent graphs."

### "How would you scale it?"
"First make it stateless — sessions to Redis, bookings to Postgres — which unlocks gunicorn workers and replicas. Then rate limiting + restricted CORS. Then streaming + prompt caching. Then observability and evals in CI. Database everything auditable: transcripts, tool calls, bookings, eval runs."

### Hypotheticals — use the 7-step method (Part 1.3)
- **Netflix service agent**: scope one journey (billing, not "all support"); tools = internal APIs split read/write; agent acts with the *user's* identity, never god-mode; confirmation gate on account changes; RAG genuinely fits (help-center corpus); metrics = resolution/deflection; human hand-off is a tool, not a failure.
- **News agent tracking companies**: different shape — scheduled/autonomous, not chat. Tools: news APIs/search, entity resolution, dedupe store. Top risk = hallucinated/stale facts with no human per-run → every claim carries source URL + timestamp. Vector store earns its keep for "seen this story before." Eval = alert precision — "a noisy monitoring agent gets muted and dies."

---

# Part 4 — Follow-up probes, FDE & strategist questions (round 2)

## Follow-up probes

- **Workflow vs agent line?** "Who owns control flow. I have both in one file — the LLM loop and the mock FSM are the same conversation."
- **Is yours actually autonomous?** "Bounded autonomy — the model picks tools; side-effects pass a gate it can't talk past. Autonomy is a dial set per-action by risk."
- **How would you know it's gone bad in production?** "Pre-release, my eval suite: deterministic guardrail checks + golden conversations free on every change, `--live` replays them against real DeepSeek (79/79 today). In production, the remaining gap is observability — tool-call logs, blocked-booking rate, transcript sampling. Evals catch regressions you anticipated; logs catch the ones you didn't."
- **What breaks first going multi-agent too early?** "Latency (extra LLM call per hop), then state sync, then debuggability. Agents should exchange explicit task messages, not share raw memory."
- **When switch models / fine-tune?** "Switch on eval regression or real capability/cost triggers — pinned version + evals makes swaps safe. No fine-tuning: the ladder is prompting → RAG → fine-tuning; climb when the cheaper rung fails."
- **How would you add RAG concretely?** "As another *tool*: embeddings over reviews/guides, semantic search alongside — not replacing — structured filters. Failure modes: retrieval misses, stale index, bad chunking, indirect injection via retrieved docs."
- **Prompt injection defense?** "Input is data, tools are allowlisted, writes are gated. An injected 'customer confirmed' still fails my gate."
- **What did no-framework cost you?** "Retries, streaming, tracing, context trimming — accepted knowingly; I can name where the trade flips."
- **10x traffic — what breaks first?** "The single process: requests queue behind 20s LLM calls. Fix order: gunicorn workers → Redis sessions → rate limiting."

## FDE questions

- **POC → production**: "Metrics first, then: security review, real session store, observability, rate limiting, evals as the regression net, rollout with kill switch, enablement. A POC proves value; production proves trust."
- **Messy customer data**: "That *is* the job: profile fast, minimum cleaning to unblock the journey, report quality findings as a deliverable."
- **Ambiguous ask**: run the decomposition ladder (Part 1.2) out loud; point at the PRD as proof of method.
- **Data can't leave their environment**: "Bedrock/Vertex keep inference in their tenancy; redaction layer for PII; self-hosted small models last, with honest capability tradeoffs. Ask which data class they actually care about — often PII, not transcripts."
- **Demo fails live**: "Never demo without an offline path — my repo has a scripted mock mode built exactly for this. Switch calmly, root-cause after. Demos fail; recoveries are remembered."
- **Skeptical exec + excited engineer**: "Same truth, two altitudes — metrics/risk for the exec, architecture for the engineer. My three docs exist so each audience has its layer."
- **When do you say no?** "When it breaks safety, the metric, or maintainability after I leave — and always with a smaller alternative attached."
- **Production incident (wrong booking)**: "Contain: disable the write tool, read-only agent keeps running. Investigate from transcripts/tool logs. Fix, add the failure as a permanent eval case, honest postmortem."
- **Rollout**: "Shadow → small pilot → progressive, kill switch the customer can pull without me. Never big-bang a side-effecting agent."
- **Build vs buy**: "Buy commodity (STT/TTS, hosting, observability); build differentiators (domain tools, guardrails, evals). Browser speech was 'free tier now, Azure/Google Cantonese voices when quality is the bottleneck.'"

## Deployment strategist questions

- **Pick the first use case**: "High frequency, bounded, measurable, error-tolerant, data exists. Fitting bookings tick all five; returns/warranty don't — that's why the PRD is what it is."
- **Quantify impact before building**: "Their numbers: conversations/week × staff minutes × loaded cost vs agent cost/conversation (fractions of a HK cent on DeepSeek V3). If the napkin math isn't compelling, the pilot won't be."
- **Adoption is low — diagnose**: "Instrument the funnel: saw widget → first message → completed questions → booked. Find the cliff, talk to five users at that step. Usually trust or discoverability, not the model."
- **Brand risk**: "The agent speaks *as* the store: tone rules and refusal scripts are requirements in the prompt; transcripts reviewed early. My injury-question redirect is brand protection as much as safety."
- **Hand off and leave**: "Docs at three altitudes, runbook for top failure modes, evals as their regression protection, and a pairing session where *they* change the prompt and watch evals respond. Success is me being unnecessary."

## Questions to ask Tom

1. "What does a great first 90 days look like in this role?"
2. "What's the hardest deployment you've had — was it the tech or the people?"
3. "How does the team decide a POC is ready for production — is there a formal bar?"

---

# Part 5 — Three lines to memorize

1. **"Never trust the model's account of user intent for an irreversible action — check the source text."**
2. **"MCP is agent-to-tools; A2A is agent-to-agents."**
3. **"RAG, multi-agent, and frameworks are trigger-conditioned decisions — I can name my triggers, and none have fired at this scale."**

And the foundation sentence, if depth is questioned: **"An LLM is a next-token predictor over a fixed context window — no truth, no memory, no hands. Every agent concept compensates for one of those three, and I can tell you which."**
