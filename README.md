# 拍友 (Paak Yau) — Cantonese Tennis Voice Agent

A Cantonese-speaking AI concierge for a Hong Kong tennis store. Customers talk or type in colloquial Cantonese, get racquet recommendations pulled from a real catalog, and can book a fitting appointment — all through a chat widget embedded in a plain HTML storefront page.

For the full technical write-up (architecture, data flow, memory/loop design, tradeoffs, and what to improve next), see **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**.

## Stack

- **Backend**: Python + Flask (`agent/bot.py`)
- **LLM**: DeepSeek V3 (`deepseek-chat`, OpenAI-compatible chat-completions API + tool use), called directly via the `openai` Python SDK — no agent framework
- **Voice**: Browser-native Web Speech API (`SpeechRecognition` + `SpeechSynthesis`, `lang=zh-HK`) — no paid STT/TTS vendor
- **Frontend**: Plain HTML/CSS/JS, no build step, no framework
- **Storage**: Flat files — `agent/data/racquets.json` (catalog) and `agent/data/bookings.csv` (bookings), no database

## Project layout

```
agent/
  bot.py                    # Flask app: /chat, /health, tool loop, mock mode, booking guardrail
  prompts/system_prompt.md  # Cantonese system prompt (source of behavior/persona)
  tools/catalog.py          # search_racquets() — imported and called by bot.py
  tools/booking.py          # book_fitting() — imported and called by bot.py
  data/racquets.json        # Source of truth for what the agent can recommend
  data/bookings.csv         # Generated at runtime; not committed
web/
  index.html                # Storefront page + chat widget markup; catalog grid fetched from the backend /catalog endpoint
  style.css                 # Storefront + widget styling
  voice-widget.js            # Chat widget logic + mic input + speech output
docs/
  PRD.md                    # Product scope for v1
  AGENT_DESIGN.md            # Persona, conversation flow, guardrails (product-level)
  ARCHITECTURE.md            # Technical deep dive (this repo's engineering doc)
```

## How to run

**Backend**
```bash
pip install -r requirements.txt
cp .env.example .env        # then fill in DEEPSEEK_API_KEY
python agent/bot.py         # starts Flask on http://localhost:5000
```

**Frontend** — just open `web/index.html` in Chrome (Web Speech API support is best there). No build step needed — but the backend must be running, since both the catalog grid and the chat widget call it.

**Demo without an API key** — leave `DEEPSEEK_API_KEY` empty, or set `MOCK=1`. The backend falls back to a scripted, LLM-free conversation flow that walks the same question order as the real prompt (see `MOCK_MODE` in `agent/bot.py`).

## Deployment

Configured for Railway (`railway.json`, `Procfile.txt`) — set `DEEPSEEK_API_KEY` as an environment variable on the host. `bot.py` binds to the host-injected `PORT` env var (defaults to 5000 locally). The frontend's API base URL is computed once in `web/index.html` (`window.API_BASE`): localhost when served locally, the deployed Railway URL otherwise.

## Hard rules (see `CLAUDE.md` for the full list)

- Never invent racquets, prices, or stock — only what's in `racquets.json`.
- Never call `book_fitting()` without an explicit, backend-verified customer confirmation.
- System prompt stays in colloquial Cantonese (口語), not formal 書面語.
