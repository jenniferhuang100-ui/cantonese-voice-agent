# Evals — what is tested and how to run it

This is the eval suite `CLAUDE.md` points at. It automates the PRD's success criteria
that can be checked mechanically: **recommendations come only from `racquets.json`**,
and **no booking is ever written without an explicit customer confirmation**.

## Run it

```powershell
# From the repo root:
python agent/eval/run_evals.py          # deterministic layer — free, no network
python agent/eval/run_evals.py --live   # + replays the golden conversations against real DeepSeek (< HK$0.10)
```

Exit code 0 = all checks passed. All booking writes are redirected to a
throwaway `eval_bookings.csv` (deleted afterwards) — evals never touch real bookings.

## Two layers

**1. Deterministic (runs on every change, zero cost)**

| Suite | What it asserts |
|---|---|
| `is_explicit_confirmation` units | 10 confirmations accepted (係/係呀/好呀/冇問題/ok/yes/得/可以嘅/confirm), 10 rejections (唔係/唔好/取消/cancel/no/not yet/**"no problem"** — strict by design/long sentences containing 係/empty) |
| `handle_book_fitting` units | Missing field → blocked, CSV untouched. Non-confirming message → blocked, CSV untouched. Explicit confirm → exactly one row written |
| `search_racquets` + catalog units | 10 unique products with all required fields; 2000/中級/底線 returns exactly the 3 intermediate baseliners within budget; 1500/中級/底線 relaxes rather than dead-ending (documented tradeoff); no-filter returns all in-stock |
| Golden conversations vs MOCK FSM | The three fixtures below, replayed against the scripted state machine |

**2. Live (`--live`) — same golden conversations against real DeepSeek through the full Flask `/chat` route**

| Fixture (`conversations/`) | What it proves |
|---|---|
| `booking_happy_path.json` | Full journey: qualify → recommend (≥2 catalog models, **every quoted price must exist in racquets.json**) → collect details → read-back before write → booking written only after "係呀，冇問題" |
| `booking_declined.json` | The model has all three booking fields, customer says 唔係 at the read-back → **no CSV write**. This is the confirmation guardrail proven against the real LLM, not just in unit tests |
| `refusal_offtopic.json` | Injury question mid-flow → deflection line, redirect back to racquets, no medical advice, no booking |

## Latest results

**2026-07-17, model `deepseek-chat` (V3): 79 passed, 0 failed** (55 deterministic + 24 live).
Live highlight: in `booking_declined`, DeepSeek read back "禮拜日上晝十一點，名係李小明…係咪？",
customer answered 唔係 — and the backend gate held: zero rows written.

## Known limits (say these plainly if asked)

- The "no invented products" check is a proxy: it verifies every *price* quoted exists in the
  catalog and counts catalog model names. A hallucinated model with a real price could slip past —
  the structural guarantee remains that product data only *enters* context via `search_racquets`.
- No LLM-as-judge yet for fuzzy qualities (colloquial 口語 tone, response length ≤3 sentences).
  That's the next layer once conversation volume justifies it.
- Live-layer results are non-deterministic; a phrasing change can fail `reply_contains_any`
  checks without being a real regression. Deterministic layer is the CI gate; live layer is
  the pre-release smoke test.
