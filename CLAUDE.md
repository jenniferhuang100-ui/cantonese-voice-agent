\# Tennis Voice Agent — Instructions for Claude Code



\## What this is

A Cantonese voice agent for a Hong Kong tennis store called "拍友".

Customer speaks or types Cantonese → gets racquet recommendations → books a fitting.



\## Stack

\- Backend: Python + Flask server in agent/bot.py

\- LLM: Anthropic claude-haiku-4-5 via the Anthropic Python SDK

\- Voice: Browser Web Speech API (SpeechRecognition + SpeechSynthesis, lang=zh-HK) — no paid STT/TTS

\- Website: Plain HTML/CSS/JS in web/ (no frameworks, no build step)



\## Where things live

\- Flask server: agent/bot.py

\- System prompt: agent/prompts/system\_prompt.md

\- Tools: agent/tools/catalog.py and agent/tools/booking.py

\- Catalog (source of truth): agent/data/racquets.json

\- Website: web/index.html, web/style.css, web/voice-widget.js

\- Test conversations: agent/eval/conversations/



\## How to run

\- Backend: python agent/bot.py (starts Flask on http://localhost:5000)

\- Frontend: open web/index.html in Chrome (no server needed locally)

\- For deployment: Railway or Render, set ANTHROPIC\_API\_KEY as environment variable



\## Hard rules

\- NEVER hardcode API keys. Always use .env via python-dotenv.

\- Agent ONLY recommends racquets that exist in agent/data/racquets.json. Never invent products, prices, or stock.

\- Always read back name + phone + date and get explicit user confirmation before calling book\_fitting().

\- System prompt is written in colloquial Cantonese (口語), not formal 書面語.

\- Keep responses short and natural — this is a conversation, not an essay.

\- Flask server must have CORS enabled so web/index.html can call it.



