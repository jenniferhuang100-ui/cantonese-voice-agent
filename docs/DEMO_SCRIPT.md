# Demo Script — Tomorrow

Exact commands and talking points. For the design reasoning behind these choices, see `WALKTHROUGH_PREP.md` (talking points) and `ARCHITECTURE.md` (technical detail) — this doc is just the "what to actually type" companion.

## 0. Tonight: run both modes once so nothing surprises you tomorrow

**PowerShell, from the repo root** (`c:\Users\jenni\cantonese-voice-agent`):

```powershell
# Real LLM mode (uses your DEEPSEEK_API_KEY from .env, costs a small amount of API credit)
python agent/bot.py
```

Open a second terminal and confirm it's alive:

```powershell
curl.exe http://localhost:5000/health
```

Expect: `{"status":"ok"}`

Stop the server (`Ctrl+C`), then run the free, offline fallback path once too:

```powershell
$env:MOCK = "1"
python agent/bot.py
```

Same health check. This mode never calls DeepSeek — use it live tomorrow if wifi/API is flaky, or to demo repeatedly without spending credits.

To go back to real mode later in the same terminal: `$env:MOCK = "0"` (or close and reopen the terminal — env vars set with `$env:` don't persist across sessions).

## 1. Start the actual demo

```powershell
python agent/bot.py
```

Leave this terminal running and visible — if something goes wrong, the stack trace prints here.

Open `web/index.html` directly in **Chrome** (double-click it, or `start web/index.html` from PowerShell) — Web Speech API's zh-HK support is best there. No build step, no second server.

## 2. Conversation script to run live

Type or say these in order (voice: click the mic button, speak, wait for the widget to send). Each line demonstrates a specific design point — say the bracketed note out loud when it happens.

1. **"我想搵支拍"** (I want to find a racquet)
   → Agent asks budget. *[shows: agent stays on-script even from an open-ended opener]*
2. **"2000"** *(use 2000, not 1500 — at 1500 every intermediate baseliner racquet is over budget and the fallback shows beginner models, which looks wrong live)*
   → Agent asks level (初/中/高).
3. **"中級"** (intermediate)
   → Agent asks play style (底線/上網/雙打).
4. **"底線"** (baseliner)
   → Agent calls `search_racquets`, recommends 2–3 racquets with reasons. *[shows: tool call grounds the recommendation in `racquets.json` — point at `agent/tools/catalog.py`]*
5. **"仲有冇其他？"** (anything else?)
   → Agent calls `search_racquets` again, shows a different batch. *[shows: graceful degradation / more-options handling, not a dead end]*
6. **"好呀，幫我book fitting"** (yes, book me a fitting)
   → Agent asks name.
7. **"陳大文"** → asks phone.
8. **"91234567"** → asks preferred time.
9. **"聽日下晝三點"** (tomorrow 3pm)
   → Agent reads back name + phone + time, asks for confirmation. *[shows: mandatory read-back before any write]*
10. **"係啊"** (yes)
    → Agent confirms booking. *[shows: `is_explicit_confirmation()` in `agent/bot.py` gates the actual CSV write — the model's own claim of confirmation is never trusted]*

**Optional extra beat — off-topic refusal:**
At step 4 or later, try: **"我隻手好痛，應該點算？"** (my hand hurts, what should I do?)
→ Agent should redirect: "呢個我唔係好識，不如我幫你搵支啱嘅拍先" and return to the racquet flow. *[shows: scoped refusal behavior, both in `system_prompt.md` and mirrored in mock mode's `REFUSAL_TRIGGERS`]*

**If you want to show a declined booking:** at step 10, say **"唔係，等等"** (no, wait) instead of 係啊 — the agent should NOT book, and loop back to re-ask.

## 3. Backend-only proof, if voice/UI misbehaves mid-demo

Have a second terminal ready with this — it bypasses the browser entirely and hits the API directly, useful if speech recognition is unreliable on the demo machine:

```powershell
curl.exe -X POST http://localhost:5000/chat `
  -H "Content-Type: application/json" `
  -d '{\"message\":\"我想搵支拍，預算2000\",\"session_id\":\"live_demo\"}'
```

You should get back a JSON `{"reply": "..."}` in Cantonese.

## 4. If the real API fails live (rate limit, network, no wifi)

Kill the server (`Ctrl+C`), then:

```powershell
$env:MOCK = "1"
python agent/bot.py
```

Same conversation script above still works — `mock_reply()` in `agent/bot.py` is a scripted version of the exact same question order, zero API calls, zero cost. Say plainly: "switching to the offline fallback path — same conversation flow, no LLM behind it right now." That's a legitimate, prepared answer, not a failure.

## 5. Where each function lives — for you, mid-Q&A

| What | File | Function/section |
|---|---|---|
| Flask routes (`/health`, `/chat`) | `agent/bot.py` | `health()`, `chat()` |
| The agentic tool-use loop | `agent/bot.py` | inside `chat()`, the `while ... finish_reason == "tool_calls":` block |
| Racquet search + catalog filtering | `agent/tools/catalog.py` | `search_racquets()` |
| Booking write (CSV) | `agent/tools/booking.py` | `book_fitting()` |
| Backend-enforced confirmation check | `agent/bot.py` | `is_explicit_confirmation()`, `handle_book_fitting()` |
| Tool schemas the model sees | `agent/bot.py` | `TOOLS_SCHEMA` |
| Model + mock-mode switch | `agent/bot.py` | `MODEL`, `MOCK_MODE` (near the top) |
| In-memory session state | `agent/bot.py` | `sessions_history` (real), `mock_sessions` (scripted demo path) |
| Scripted offline conversation (no LLM) | `agent/bot.py` | `mock_reply()` and everything under "MOCK / OFFLINE DEMO MODE" |
| Behavioral spec the model actually reads | `agent/prompts/system_prompt.md` | whole file |
| Catalog source of truth | `agent/data/racquets.json` | — |
| Product scope / success criteria | `docs/PRD.md` | — |
| Persona + conversation flow (human-readable) | `docs/AGENT_DESIGN.md` | — |
| Full technical deep dive + tradeoffs | `docs/ARCHITECTURE.md` | — |
| Talking points for design questions | `docs/WALKTHROUGH_PREP.md` | — |

## 6. The four questions you specifically asked to be ready for

- **Single agent vs. sequential/multi-agent** → `WALKTHROUGH_PREP.md` §1a.
- **Why RAM instead of a database** → `WALKTHROUGH_PREP.md` §6 (cost argument), `ARCHITECTURE.md` §7.
- **Tool-calling logic** → `WALKTHROUGH_PREP.md` §7, this doc's file map above.
- **Hallucination control + context/summarization strategy** → `WALKTHROUGH_PREP.md` §5, `ARCHITECTURE.md` §6a.
- **Scaling** → `WALKTHROUGH_PREP.md` §11 (current limits) and §12 (roadmap, in priority order).
- **Evals** → `WALKTHROUGH_PREP.md` §10 and `agent/eval/README.md`: built and passing (79/79 incl. live DeepSeek). Live demo-able: `python agent/eval/run_evals.py` runs free in seconds; `--live` replays the golden conversations against the real model. Lead with the declined-booking fixture — the guardrail holding against the real LLM. |
