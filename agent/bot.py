"""
拍友 (Paak Yau) backend — single-agent design, not a sequential/multi-agent
pipeline: one LLM (DeepSeek V3 via the OpenAI-compatible API), one system
prompt, one tool-calling loop
handles qualifying questions, recommendation, and booking end-to-end.
See docs/ARCHITECTURE.md §4 and docs/WALKTHROUGH_PREP.md §1a for the
"why one agent, not several" reasoning.
"""
import os
import re
import sys
import json
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
from openai import OpenAI

from tools.catalog import search_racquets, load_catalog
from tools.booking import book_fitting

# Force Windows console/server logs to print Cantonese (UTF-8) without crashing
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stdin.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

# Load environmental variables (.env)
load_dotenv()

app = Flask(__name__)
CORS(app)  # Crucial: This permits your index.html file to call the backend!

# deepseek-chat (V3), NOT deepseek-reasoner: the reasoner doesn't support
# function calling, and this agent is built around two tools.
MODEL = "deepseek-chat"
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

# Unlike the old Anthropic SDK, OpenAI's client constructor raises immediately
# if api_key is None/empty (checked at import time, before Flask even starts)
# instead of only failing when actually called. A placeholder keeps
# construction crash-free so a missing key falls through to MOCK_MODE below,
# as designed, rather than taking the whole process down before it can serve
# a single request (this is exactly what happened when DEEPSEEK_API_KEY was
# unset on Railway: crash-loop on boot, never reaching the mock fallback).
client = OpenAI(
    api_key=DEEPSEEK_API_KEY or "unset-falls-back-to-mock-mode",
    base_url="https://api.deepseek.com",
    timeout=30.0,
)

# Demo mode switch: MOCK=1 forces the scripted offline agent below even if a
# real key is present (for rehearsing without burning API credits); with no
# override, an empty/missing key falls back to the same scripted path
# automatically so the demo still runs with no DeepSeek account at all.
MOCK_MODE = os.getenv("MOCK", "0") == "1" or not DEEPSEEK_API_KEY

MAX_TOOL_ITERATIONS = 5

# In-process dict, not a database: session state only needs to survive one
# short conversation in one process, so RAM is free where a DB would add
# infra cost, a schema, and a network round-trip per turn for no benefit at
# this scale. Tradeoff: wiped on restart, doesn't survive >1 worker/replica
# (see docs/ARCHITECTURE.md §7 for the migration path once that's needed).
sessions_history = {}

# Separate, isolated state store for the scripted MOCK_MODE conversation —
# never shared with sessions_history so the two code paths can't interfere.
mock_sessions = {}

# --- CORE INTEGRATED TOOLS ---
# search_racquets and book_fitting are implemented in tools/catalog.py and
# tools/booking.py; imported at the top of this file.

# Backend-enforced confirmation check: independent of what the model claims,
# this inspects the customer's own latest message before any booking is written.
NEGATION_MARKERS_ZH = ["唔係", "唔好", "唔要", "取消", "唔啱"]
NEGATION_MARKERS_EN = ["no", "not", "cancel", "don't", "dont"]
STRONG_CONFIRM_ZH = ["冇問題", "係啊", "係呀", "係嘅", "岩喎", "可以嘅", "好呀", "好嘅", "好"]
STRONG_CONFIRM_EN = ["confirm", "okay", "yes", "sure"]
SHORT_CONFIRM = ["係", "ok", "得", "可以", "岩"]

def is_explicit_confirmation(text):
    if not text:
        return False
    t = text.strip()
    tl = t.lower()

    if any(m in t for m in NEGATION_MARKERS_ZH) or any(m in tl for m in NEGATION_MARKERS_EN):
        return False

    if any(m in t for m in STRONG_CONFIRM_ZH) or any(m in tl for m in STRONG_CONFIRM_EN):
        return True

    # Bare short replies ("係" / "ok" / "得") only count as confirmation when the
    # whole message is short, so we don't false-match those common words/particles
    # inside an unrelated, longer sentence.
    if len(t) <= 6 and any(m in t or m in tl for m in SHORT_CONFIRM):
        return True

    return False

def handle_book_fitting(tool_args, user_msg):
    name = (tool_args.get("name") or "").strip()
    phone = (tool_args.get("phone") or "").strip()
    datetime_str = (tool_args.get("datetime_str") or "").strip()

    missing = [f for f, v in [("name", name), ("phone", phone), ("datetime_str", datetime_str)] if not v]
    if missing:
        return {
            "status": "error",
            "message": f"Missing required booking field(s): {', '.join(missing)}. Ask the customer for the missing info before calling book_fitting again."
        }

    if not is_explicit_confirmation(user_msg):
        return {
            "status": "error",
            "message": "Booking blocked: the customer's latest message is not an explicit confirmation (e.g. 係 / 冇問題 / OK). Read back the name, phone, and time, and wait for a clear yes before calling book_fitting again."
        }

    return book_fitting(name, phone, datetime_str)

# --- MOCK / OFFLINE DEMO MODE ---
# A small scripted state machine that walks the exact fixed question order
# from system_prompt.md (budget -> level -> style -> recommend -> book?
# -> name -> phone -> datetime -> confirm -> book_fitting). Used only when
# MOCK_MODE is on, so a demo can run with zero Anthropic API calls.

REFUSAL_TRIGGERS = ["傷", "痛", "醫", "穿線", "拉線", "場地", "租場"]
REFUSAL_REPLY = "呢個我唔係好識，不如我幫你搵支啱嘅拍先。"

MOCK_PROMPTS = {
    "budget": "請問你個預算係幾多？（例如 1500）",
    "level": "你係初級、中級定高級球手？",
    "style": "你鍾意打底線、上網定雙打？",
}

MORE_OPTIONS_TRIGGERS = ["其他", "第二啲", "多啲", "睇多啲", "仲有", "仲有冇", "其他選擇", "other", "more"]

def _mock_get_state(session_id):
    if session_id not in mock_sessions:
        mock_sessions[session_id] = {
            "step": "budget", "budget": None, "level": None, "style": None,
            "name": None, "phone": None, "datetime": None, "shown_ids": set(),
        }
    return mock_sessions[session_id]

def _mock_more_racquets(state):
    results = search_racquets(budget_max_hkd=state["budget"], level=state["level"], play_style=state["style"])
    remaining = [r for r in results if r["id"] not in state["shown_ids"]]
    if not remaining:
        # Exact filters exhausted — relax to budget-only so there's still something new to offer.
        results = search_racquets(budget_max_hkd=state["budget"])
        remaining = [r for r in results if r["id"] not in state["shown_ids"]]
    batch = remaining[:3]
    state["shown_ids"].update(r["id"] for r in batch)
    return batch

def mock_reply(session_id, user_msg):
    state = _mock_get_state(session_id)
    step = state["step"]

    if step in MOCK_PROMPTS and any(k in user_msg for k in REFUSAL_TRIGGERS):
        return REFUSAL_REPLY + MOCK_PROMPTS[step]

    if step == "budget":
        m = re.search(r"\d+", user_msg)
        if not m:
            return "唔好意思，可唔可以講清楚少少你嘅預算？（例如 1500）"
        state["budget"] = int(m.group())
        state["step"] = "level"
        return f"明白，預算大約 HKD {state['budget']}。{MOCK_PROMPTS['level']}"

    if step == "level":
        level = next((full for ch, full in [("初", "初級"), ("中", "中級"), ("高", "高級")] if ch in user_msg), None)
        if not level:
            return f"唔該講多次，{MOCK_PROMPTS['level']}"
        state["level"] = level
        state["step"] = "style"
        return MOCK_PROMPTS["style"]

    if step == "style":
        style = next((s for s in ["底線", "上網", "雙打"] if s in user_msg), None)
        if not style:
            return f"唔該講多次，{MOCK_PROMPTS['style']}"
        state["style"] = style
        state["step"] = "ask_book"
        batch = _mock_more_racquets(state)
        lines = [f"- {r['brand']} {r['model']}（HKD {r['price_hkd']}）" for r in batch]
        return "同你搵到幾支拍：\n" + "\n".join(lines) + "\n想唔想我幫你約 fitting？"

    if step == "ask_book":
        if is_explicit_confirmation(user_msg):
            state["step"] = "name"
            return "好呀！請問你個名係？"
        if any(k in user_msg for k in MORE_OPTIONS_TRIGGERS):
            batch = _mock_more_racquets(state)
            if not batch:
                return "呢啲已經係我哋而家最啱嘅款喇，想唔想我幫你約 fitting 試吓？"
            lines = [f"- {r['brand']} {r['model']}（HKD {r['price_hkd']}）" for r in batch]
            return "仲有呢幾支你可以睇吓：\n" + "\n".join(lines) + "\n想唔想我幫你約 fitting？"
        return "好，有需要幫手隨時搵返我。"

    if step == "name":
        state["name"] = user_msg.strip()
        state["step"] = "phone"
        return "唔該畀個電話號碼？"

    if step == "phone":
        state["phone"] = user_msg.strip()
        state["step"] = "datetime"
        return "想約幾時嚟 fitting 呢？"

    if step == "datetime":
        state["datetime"] = user_msg.strip()
        state["step"] = "confirm"
        return f"你想book {state['datetime']}，名係 {state['name']}，電話係 {state['phone']}，係咪？"

    if step == "confirm":
        if not is_explicit_confirmation(user_msg):
            state["step"] = "name"
            return "冇問題，我哋再嚟一次。請問你個名係？"
        book_fitting(state["name"], state["phone"], state["datetime"])
        state["step"] = "done"
        return f"搞掂！已經幫你book咗 {state['datetime']}，到時見！🎾"

    return "多謝晒！仲有咩幫到你？"

# Tool definitions in OpenAI/DeepSeek function-calling format
TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "search_racquets",
            "description": "Search the inventory database for matching tennis racquets based on client filters. Returns matching products.",
            "parameters": {
                "type": "object",
                "properties": {
                    "budget_max_hkd": {"type": "number", "description": "Maximum budget in HKD."},
                    "level": {"type": "string", "enum": ["初級", "中級", "高級"], "description": "Player skill tier level in Cantonese."},
                    "play_style": {"type": "string", "enum": ["底線", "上網", "雙打"], "description": "Player style strategy preferences in Cantonese."}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "book_fitting",
            "description": "Appends a new customer racquet fitting session reservation into the database bookings ledger sheet.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "The customer's full name."},
                    "phone": {"type": "string", "description": "The customer's contact telephone phone number string."},
                    "datetime_str": {"type": "string", "description": "Requested appointment day and timeframe schedule string."}
                },
                "required": ["name", "phone", "datetime_str"]
            }
        }
    }
]

# --- CORE API SERVER CHANNELS ---

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})

@app.route("/catalog", methods=["GET"])
def catalog():
    # Serves racquets.json to the storefront grid, so the page displays the
    # exact same catalog the agent recommends from — no second hardcoded copy.
    return jsonify(load_catalog())

@app.route("/chat", methods=["POST"])
def chat():
    data = request.json or {}
    user_msg = data.get("message", "").strip()
    session_id = data.get("session_id", "default_sync_user")
    
    if not user_msg:
        return jsonify({"reply": "我聽唔清，可以再講一次嗎？"})

    if MOCK_MODE:
        return jsonify({"reply": mock_reply(session_id, user_msg)})

    # Read core Cantonese prompt instructions layout
    prompt_path = os.path.join(os.path.dirname(__file__), "prompts", "system_prompt.md")
    system_prompt = "You are a helpful assistant."
    if os.path.exists(prompt_path):
        with open(prompt_path, "r", encoding="utf-8") as f:
            system_prompt = f.read()

    # Load context array or initialize session history tracking list
    if session_id not in sessions_history:
        sessions_history[session_id] = []
        
    history = sessions_history[session_id]
    history.append({"role": "user", "content": user_msg})

    # OpenAI-compatible API: the system prompt is the first message, not a
    # separate parameter. It's prepended per call so history stays prompt-free.
    def call_model():
        return client.chat.completions.create(
            model=MODEL,
            max_tokens=1024,
            messages=[{"role": "system", "content": system_prompt}] + history,
            tools=TOOLS_SCHEMA,
        )

    try:
        response = call_model()

        # Process structural Agent ReAct routing block triggers
        tool_iterations = 0
        while response.choices[0].finish_reason == "tool_calls":
            tool_iterations += 1
            if tool_iterations > MAX_TOOL_ITERATIONS:
                # Bail out before appending an unanswered tool_calls message,
                # so history stays balanced for the next turn's API call.
                fallback = "唔好意思，呢個問題有啲複雜，可唔可以講清楚少少，或者我搵同事幫你？"
                history.append({"role": "assistant", "content": fallback})
                return jsonify({"reply": fallback})

            # Append assistant message stating intention to run tools
            assistant_msg = response.choices[0].message
            history.append({
                "role": "assistant",
                "content": assistant_msg.content or "",
                "tool_calls": [
                    {"id": tc.id, "type": "function",
                     "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                    for tc in (assistant_msg.tool_calls or [])
                ],
            })

            for tool_call in (assistant_msg.tool_calls or []):
                tool_name = tool_call.function.name
                tool_args = json.loads(tool_call.function.arguments)

                # Tool routing execution matrix
                if tool_name == "search_racquets":
                    result_data = search_racquets(**tool_args)
                elif tool_name == "book_fitting":
                    result_data = handle_book_fitting(tool_args, user_msg)
                else:
                    result_data = {"error": "Tool requested not found"}

                # Each result goes back as its own role="tool" message,
                # matched to the request by tool_call_id.
                history.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(result_data, ensure_ascii=False),
                })

            response = call_model()

        # Extract final chat content response bubble string
        final_reply = response.choices[0].message.content or ""

        history.append({"role": "assistant", "content": final_reply})
        return jsonify({"reply": final_reply})

    except Exception as e:
        print(f"Server Engine Core Intercept error: {str(e)}")
        # If it's a billing/credit limit, parse out nicely
        if "credit" in str(e).lower() or "balance" in str(e).lower() or "insufficient" in str(e).lower():
            return jsonify({"reply": "（系統提示：你嘅 DeepSeek API 帳戶額度不足，請到 Console 充值後重試。）"})
        return jsonify({"reply": "對唔住呀，我而家處理唔到，不如等多陣再試過？"})

if __name__ == "__main__":
    # Railway/Render inject the port to bind via the PORT env var; 5000 is the
    # local-dev default and matches the frontend's localhost fallback URL.
    port = int(os.getenv("PORT", "5000"))
    print(f"Starting Flask Web Server on http://localhost:{port} ...")
    app.run(host="0.0.0.0", port=port, debug=False)

