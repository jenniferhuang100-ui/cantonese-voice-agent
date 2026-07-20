"""
Eval harness for the 拍友 agent — the fixtures CLAUDE.md points at.

Two layers:
1. Deterministic (free, zero network):
   - unit checks on the booking guardrail (is_explicit_confirmation,
     handle_book_fitting) and the catalog tool (search_racquets, load_catalog)
   - the golden conversations in conversations/*.json replayed against the
     scripted MOCK state machine
2. Live (--live): the same golden conversations replayed against the real
   DeepSeek API through the full Flask /chat route. Costs a fraction of a cent.

All booking writes are redirected to an eval-only CSV (deleted afterwards),
so evals never touch agent/data/bookings.csv.

Run from the repo root:
    python agent/eval/run_evals.py          # deterministic layer only
    python agent/eval/run_evals.py --live   # deterministic + live DeepSeek

Exit code 0 = every check passed.
"""
import argparse
import csv as csv_mod
import glob
import json
import os
import re
import subprocess
import sys
import uuid

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
AGENT_DIR = os.path.dirname(EVAL_DIR)
sys.path.insert(0, AGENT_DIR)

if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

import bot
import tools.booking as booking
from tools.catalog import load_catalog, search_racquets

# Redirect every booking write into an eval-only CSV.
EVAL_CSV = os.path.join(EVAL_DIR, "eval_bookings.csv")
booking.DATA_DIR = EVAL_DIR
booking.CSV_PATH = EVAL_CSV

CATALOG = load_catalog()
CATALOG_IDS = {r["id"] for r in CATALOG}
MODEL_NAMES = [r["model"] for r in CATALOG]
CATALOG_PRICES = {r["price_hkd"] for r in CATALOG}
PRICE_RE = re.compile(r"(?:HKD|hkd|\$|＄)\s*\$?\s*([0-9][0-9,]{2,5})")

PASSED, FAILED = [], []


def check(name, cond, detail=""):
    (PASSED if cond else FAILED).append(name)
    line = ("  PASS  " if cond else "  FAIL  ") + name
    if detail and not cond:
        line += f"  — {detail}"
    print(line)


def reset_eval_csv():
    if os.path.exists(EVAL_CSV):
        os.remove(EVAL_CSV)


def eval_csv_rows():
    if not os.path.exists(EVAL_CSV):
        return []
    with open(EVAL_CSV, encoding="utf-8") as f:
        return list(csv_mod.reader(f))[1:]  # skip header


# ---------------------------------------------------------------- unit layer

def unit_confirmation_guardrail():
    print("\n== Unit: is_explicit_confirmation (the booking gate's parser) ==")
    positives = ["係", "係呀", "好呀", "冇問題", "ok", "OK", "yes", "得", "可以嘅", "confirm"]
    negatives = ["唔係", "唔好", "取消", "cancel", "no", "not yet", "no problem",
                 "我唔知係唔係啱", "個朋友話係咁樣打先啱嘅喎", ""]
    for t in positives:
        check(f"confirm accepts {t!r}", bot.is_explicit_confirmation(t) is True)
    for t in negatives:
        check(f"confirm rejects {t!r}", bot.is_explicit_confirmation(t) is False)


def unit_booking_handler():
    print("\n== Unit: handle_book_fitting (backend-enforced write gate) ==")
    full = {"name": "測試客", "phone": "9000 0000", "datetime_str": "禮拜五7點"}

    reset_eval_csv()
    r = bot.handle_book_fitting({"name": "測試客", "phone": "", "datetime_str": "禮拜五7點"}, "係呀")
    check("missing field blocks the write", r.get("status") == "error" and "phone" in r.get("message", ""))
    check("missing field: CSV untouched", eval_csv_rows() == [])

    r = bot.handle_book_fitting(dict(full), "我諗下先")
    check("non-confirmation blocks the write", r.get("status") == "error")
    check("non-confirmation: CSV untouched", eval_csv_rows() == [])

    r = bot.handle_book_fitting(dict(full), "係呀，冇問題")
    rows = eval_csv_rows()
    check("explicit confirmation writes exactly one row",
          r.get("status") == "success" and len(rows) == 1 and rows[0][0] == "測試客",
          f"result={r}, rows={rows}")
    reset_eval_csv()


def unit_boots_without_api_key():
    """Regression check for the 2026-07-17 Railway crash-loop: the openai SDK's
    client constructor raises immediately on a missing key (import time, before
    Flask starts), unlike the old anthropic SDK which only failed on first use.
    That silently broke MOCK_MODE's 'no key -> scripted fallback' design during
    the DeepSeek migration. This simulates Railway's exact condition (no
    DEEPSEEK_API_KEY, no .env file at all) in a clean subprocess and asserts
    the app still boots and serves /health instead of crash-looping.
    """
    print("\n== Regression: app boots cleanly with zero API key present ==")
    repo_root = os.path.dirname(AGENT_DIR)
    env_path = os.path.join(repo_root, ".env")
    env_backup = env_path + ".eval_backup"
    moved = False
    try:
        if os.path.exists(env_path):
            os.rename(env_path, env_backup)
            moved = True

        # Inherit the real environment (Windows needs APPDATA/USERPROFILE/etc.
        # to even resolve installed packages) and strip only the keys under
        # test, rather than a minimal env that breaks package resolution for
        # unrelated reasons.
        clean_env = {k: v for k, v in os.environ.items()
                     if k.upper() not in ("DEEPSEEK_API_KEY", "OPENAI_API_KEY", "OPENAI_ADMIN_KEY", "MOCK")}
        script = (
            "import sys; sys.path.insert(0, 'agent'); import bot; "
            "c = bot.app.test_client(); r = c.get('/health'); "
            "assert r.status_code == 200, r.status_code; "
            "print('BOOT_OK', bot.MOCK_MODE)"
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=repo_root, env=clean_env,
            capture_output=True, text=True, timeout=30,
        )
        check(
            "app boots and /health responds with no DEEPSEEK_API_KEY / no .env",
            result.returncode == 0 and "BOOT_OK True" in result.stdout,
            (result.stderr or result.stdout)[-300:],
        )
    finally:
        if moved:
            os.rename(env_backup, env_path)


def unit_catalog_tool():
    print("\n== Unit: search_racquets + catalog integrity ==")
    check("catalog has 10 unique products",
          len(CATALOG) == 10 and len(CATALOG_IDS) == 10)
    required = {"id", "brand", "model", "price_hkd", "best_for", "in_stock", "tagline_zh"}
    check("every product has all required fields",
          all(required <= set(r) for r in CATALOG))

    r = search_racquets(budget_max_hkd=2000, level="中級", play_style="底線")
    ids = {x["id"] for x in r}
    expected = {"babolat-pure-drive-2021", "yonex-ezone-100", "babolat-pure-aero-2023"}
    check("2000/中級/底線 returns exactly the 3 intermediate baseliners",
          ids == expected, f"got {ids}")
    check("exact-filter results respect the budget",
          all(x["price_hkd"] <= 2000 for x in r))

    r = search_racquets(budget_max_hkd=1500, level="中級", play_style="底線")
    check("1500/中級/底線 relaxes rather than dead-ending (documented tradeoff)",
          len(r) > 0 and all(x["id"] in CATALOG_IDS for x in r))

    r = search_racquets()
    check("no filters returns every in-stock product",
          len(r) == 10 and all(x["in_stock"] for x in r))


# -------------------------------------------------------- conversation layer

def run_conversation(fixture, live):
    bot.MOCK_MODE = not live
    reset_eval_csv()
    label = "LIVE" if live else "MOCK"
    sid = f"eval_{fixture['name']}_{uuid.uuid4().hex[:8]}"
    client = bot.app.test_client()
    print(f"\n== [{label}] conversation: {fixture['name']} ==")

    allowed_numbers = CATALOG_PRICES | set(fixture.get("allowed_extra_numbers", []))

    for i, turn in enumerate(fixture["turns"], 1):
        resp = client.post("/chat", json={"message": turn["user"], "session_id": sid})
        reply = resp.get_json()["reply"]
        print(f"  >> {turn['user']}")
        print(f"  << {reply[:110].replace(chr(10), ' | ')}")
        prefix = f"{label}:{fixture['name']}:turn{i}"
        checks = turn.get("checks", {})

        if checks.get("no_booking_yet"):
            check(f"{prefix}: no booking written yet", eval_csv_rows() == [])
        if "min_catalog_mentions" in checks:
            n = sum(1 for m in MODEL_NAMES if m.lower() in reply.lower())
            check(f"{prefix}: recommends >= {checks['min_catalog_mentions']} catalog models",
                  n >= checks["min_catalog_mentions"], f"found {n} catalog model names in reply")
        if checks.get("prices_must_be_catalog"):
            found = [int(p.replace(",", "")) for p in PRICE_RE.findall(reply)]
            bad = [p for p in found if p not in allowed_numbers]
            check(f"{prefix}: every price quoted exists in racquets.json",
                  not bad, f"non-catalog prices quoted: {bad}")
        if "reply_contains_any" in checks:
            ok = any(s in reply for s in checks["reply_contains_any"])
            check(f"{prefix}: reply contains one of {checks['reply_contains_any']}", ok, reply[:80])
        if "booking_written" in checks:
            exp = checks["booking_written"]
            rows = [",".join(row) for row in eval_csv_rows()]
            ok = any(exp["name"] in row and exp["phone"] in row for row in rows)
            check(f"{prefix}: booking written with correct name+phone", ok, f"rows={rows}")
        if checks.get("no_booking_final"):
            check(f"{prefix}: booking correctly NOT written", eval_csv_rows() == [])


def load_fixtures():
    fixtures = []
    for path in sorted(glob.glob(os.path.join(EVAL_DIR, "conversations", "*.json"))):
        with open(path, encoding="utf-8") as f:
            fixtures.append(json.load(f))
    return fixtures


# --------------------------------------------------------------------- main

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true",
                        help="also replay the golden conversations against the real DeepSeek API")
    args = parser.parse_args()

    original_mock = bot.MOCK_MODE
    fixtures = load_fixtures()
    try:
        unit_confirmation_guardrail()
        unit_booking_handler()
        unit_boots_without_api_key()
        unit_catalog_tool()

        for fx in fixtures:
            run_conversation(fx, live=False)

        if args.live:
            if not os.getenv("DEEPSEEK_API_KEY"):
                print("\n--live requested but DEEPSEEK_API_KEY is missing; skipping live layer.")
            else:
                for fx in fixtures:
                    run_conversation(fx, live=True)
    finally:
        bot.MOCK_MODE = original_mock
        reset_eval_csv()

    print(f"\n{'=' * 50}\nRESULT: {len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        print("Failed checks:")
        for name in FAILED:
            print(f"  - {name}")
    sys.exit(1 if FAILED else 0)


if __name__ == "__main__":
    main()
