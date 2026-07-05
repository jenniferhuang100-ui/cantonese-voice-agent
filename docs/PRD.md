\# PRD — Tennis Voice Agent v1



\## One-line

A Cantonese voice/text concierge that recommends racquets and books fittings for a HK tennis store.



\## The one journey (only this in v1)

1\. Customer opens website, clicks "同我哋傾吓" button

2\. Agent asks 2–3 qualifying questions: budget (HKD), level, play style

3\. Agent recommends 2–3 racquets from the catalog with reasons

4\. Customer picks one; agent offers a fitting appointment

5\. Agent collects name + phone + preferred time, reads all three back, gets confirmation, books



\## Out of scope (v1)

\- Payments or order processing

\- Mandarin or English language support

\- Injury or medical advice

\- Memory across sessions (each conversation starts fresh)

\- User accounts or login



\## Success criteria

\- All recommendations come only from racquets.json

\- Confirmation step always happens before any booking is written

\- Cantonese text is natural colloquial HK Cantonese

\- Voice (when enabled) works on Chrome with zh-HK

\- Works on a real public URL (not just localhost)



