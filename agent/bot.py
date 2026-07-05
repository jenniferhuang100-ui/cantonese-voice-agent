import os
import sys
import json
import csv
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
from anthropic import Anthropic

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

MODEL = "claude-3-5-haiku-20241022"  # Current Anthropic SDK standard
client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# Memory bank dictionary to keep conversation history isolated per session_id
sessions_history = {}

# --- CORE INTEGRATED TOOLS ---

def search_racquets(budget_max_hkd=None, level=None, play_style=None):
    catalog_path = os.path.join(os.path.dirname(__file__), "data", "racquets.json")
    if not os.path.exists(catalog_path):
        return {"error": "Catalog data file missing."}
    
    with open(catalog_path, "r", encoding="utf-8") as f:
        racquets = json.load(f)
    
    results = []
    # Map mapping user Cantonese filters to data keys
    level_map = {"初": "beginner", "中": "intermediate", "高": "advanced"}
    style_map = {"底線": "baseliner", "上網": "net-rush", "雙打": "doubles"}
    
    for r in racquets:
        if not r.get("in_stock", True):
            continue
        if budget_max_hkd and r.get("price_hkd", 0) > budget_max_hkd:
            continue
            
        # Match level if provided
        if level:
            mapped_lvl = level_map.get(level[0], level)
            if not any(mapped_lvl in b for b in r.get("best_for", [])):
                continue
                
        # Match play style if provided
        if play_style:
            mapped_style = style_map.get(play_style, play_style)
            if not any(mapped_style in b for b in r.get("best_for", [])):
                continue
                
        results.append(r)
    return results

def book_fitting(name, phone, datetime_str):
    data_dir = os.path.join(os.path.dirname(__file__), "data")
    os.makedirs(data_dir, exist_ok=True)
    csv_path = os.path.join(data_dir, "bookings.csv")
    
    file_exists = os.path.exists(csv_path)
    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["Name", "Phone", "DateTime"])  # Header row
        writer.writerow([name, phone, datetime_str])
    return {"status": "success", "message": f"Successfully booked for {name}."}

# Define schemas for Anthropic tool definitions
TOOLS_SCHEMA = [
    {
        "name": "search_racquets",
        "description": "Search the inventory database for matching tennis racquets based on client filters. Returns matching products.",
        "input_schema": {
            "type": "object",
            "properties": {
                "budget_max_hkd": {"type": "number", "description": "Maximum budget in HKD."},
                "level": {"type": "string", "enum": ["初級", "中級", "高級"], "description": "Player skill tier level in Cantonese."},
                "play_style": {"type": "string", "enum": ["底線", "上網", "雙打"], "description": "Player style strategy preferences in Cantonese."}
            }
        }
    },
    {
        "name": "book_fitting",
        "description": "Appends a new customer racquet fitting session reservation into the database bookings ledger sheet.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "The customer's full name."},
                "phone": {"type": "string", "description": "The customer's contact telephone phone number string."},
                "datetime_str": {"type": "string", "description": "Requested appointment day and timeframe schedule string."}
            },
            "required": ["name", "phone", "datetime_str"]
        }
    }
]

# --- CORE API SERVER CHANNELS ---

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})

@app.route("/chat", methods=["POST"])
def chat():
    data = request.json or {}
    user_msg = data.get("message", "").strip()
    session_id = data.get("session_id", "default_sync_user")
    
    if not user_msg:
        return jsonify({"reply": "我聽唔清，可以再講一次嗎？"})
        
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

    try:
        # Request generation sequence payload
        response = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=system_prompt,
            messages=history,
            tools=TOOLS_SCHEMA
        )
        
        # Process structural Agent ReAct routing block triggers
        while response.stop_reason == "tool_use":
            # Append assistant message stating intention to run tools
            history.append({"role": "assistant", "content": response.content})
            
            tool_msg_contents = []
            for block in response.content:
                if block.type == "tool_use":
                    tool_name = block.name
                    tool_args = block.input
                    tool_id = block.id
                    
                    # Tool Routing execution execution matrix
                    if tool_name == "search_racquets":
                        result_data = search_racquets(**tool_args)
                    elif tool_name == "book_fitting":
                        result_data = book_fitting(**tool_args)
                    else:
                        result_data = {"error": "Tool requested not found"}
                        
                    tool_msg_contents.append({
                        "type": "tool_result",
                        "tool_use_id": tool_id,
                        "content": json.dumps(result_data, ensure_ascii=False)
                    })
            
            # Feed tool execution output data frames clean directly back to Anthropic
            history.append({"role": "user", "content": tool_msg_contents})
            
            response = client.messages.create(
                model=MODEL,
                max_tokens=1024,
                system=system_prompt,
                messages=history,
                tools=TOOLS_SCHEMA
            )

        # Extract final chat content response bubble string 
        final_reply = ""
        for block in response.content:
            if block.type == "text":
                final_reply += block.text

        history.append({"role": "assistant", "content": final_reply})
        return jsonify({"reply": final_reply})

    except Exception as e:
        print(f"Server Engine Core Intercept error: {str(e)}")
        # If it's a billing/credit limit, parse out nicely
        if "credit" in str(e).lower() or "balance" in str(e).lower():
            return jsonify({"reply": "（系統提示：你嘅 Anthropic API 帳戶餘額不足，請到 Console 增值，或者用 Pro Account 帳戶仿真功能進行測試。）"})
        return jsonify({"reply": "對唔住呀，我而家處理唔到，不如等多陣再試過？"})

if __name__ == "__main__":
    print("Starting Flask Web Server on http://localhost:5000 ...")
    app.run(host="0.0.0.0", port=5000, debug=True)

