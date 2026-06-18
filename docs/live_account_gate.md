# Live Account Gate

This repository is currently a paper-trading monitor only. It must not place real orders or connect to a broker unless the live gate becomes eligible for manual review and the user separately authorizes a live broker integration.

## Current rule

- No broker secrets, cookies, API keys, account exports, or browser profiles may be committed.
- A live mandate must be explicit, local, dated, scoped, and revocable.
- A broker connection manifest may describe capabilities, but must not contain credentials.
- The paper account must have several audited observations before live review.
- A clean local audit and git history are required.
- Passing the live gate still does not mean automatic live trading is enabled; it only means the setup can be manually reviewed.

Run:

```bash
python3 scripts/live_account_gate.py --date 2026-06-19
```

Output:

- `data/live_gate/YYYY-MM-DD.json`

