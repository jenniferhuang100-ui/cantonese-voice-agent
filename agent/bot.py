import json
import sys
from pathlib import Path

from dotenv import load_dotenv
from anthropic import Anthropic

sys.stdout.reconfigure(encoding="utf-8")
sys.stdin.reconfigure(encoding="utf-8")

from tools.catalog import search_racquets
from tools.booking import book_fitting

load_dotenv()

MODEL = "claude-haiku-4-5"
SYSTEM_PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "system_prompt.md"

TOOLS = [
    {
        "name": "search_racquets",
        "description": "搵符合客人預算、程度同打法嘅網球拍。",
        "input_schema": {
            "type": "object",
            "properties": {
                "budget_max_hkd": {
                    "type": "number",
                    "description": "客人預算上限（港幣）",
                },
                "level": {
                    "type": "string",
                    "enum": ["beginner", "intermediate", "advanced"],
                    "description": "球手程度",
                },
                "play_style": {
                    "type": "string",
                    "enum": ["baseliner", "net-rush", "all-court", "doubles"],
                    "description": "打法風格",
                },
            },
        },
    },
    {
        "name": "book_fitting",
        "description": "幫客人 book fitting，要有名、電話同時間先可以call呢個function。",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "客人名字"},
                "phone": {"type": "string", "description": "客人電話"},
                "datetime": {"type": "string", "description": "客人想book嘅日期時間"},
            },
            "required": ["name", "phone", "datetime"],
        },
    },
]

TOOL_FUNCTIONS = {
    "search_racquets": lambda **kwargs: search_racquets(**kwargs),
    "book_fitting": lambda **kwargs: book_fitting(**kwargs),
}


def run_tool(name, tool_input):
    result = TOOL_FUNCTIONS[name](**tool_input)
    return json.dumps(result, ensure_ascii=False)


def main():
    system_prompt = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
    client = Anthropic()
    messages = []

    print("拍友：你好！歡迎嚟到拍友網球店，有咩可以幫到你？（輸入 exit 離開）")

    while True:
        user_input = input("你：").strip()
        if not user_input:
            continue
        if user_input.lower() == "exit":
            break

        messages.append({"role": "user", "content": user_input})

        while True:
            response = client.messages.create(
                model=MODEL,
                max_tokens=1024,
                system=system_prompt,
                tools=TOOLS,
                messages=messages,
            )

            messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason != "tool_use":
                for block in response.content:
                    if block.type == "text":
                        print(f"拍友：{block.text}")
                break

            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    output = run_tool(block.name, block.input)
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": output,
                        }
                    )

            messages.append({"role": "user", "content": tool_results})


if __name__ == "__main__":
    main()
