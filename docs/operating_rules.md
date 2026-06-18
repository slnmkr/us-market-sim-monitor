# Operating Rules

## Non-negotiable boundaries

- No live trading until the user explicitly provides a broker connection, account mandate, and written risk limits.
- Live-account review must pass `python3 scripts/live_account_gate.py --date YYYY-MM-DD`; passing the gate still does not authorize automatic live trading.
- No credential collection in this repository. Do not commit secrets, cookies, API keys, browser profiles, or account exports containing private identifiers.
- No synthetic data may be labeled as real. Paper trades are synthetic unless a broker paper-trading export proves otherwise.
- No stable-return promise. Reports can express a thesis, confidence, invalidation, and risk, but not guaranteed profits.

## Paper account policy

- Starting capital: USD 100,000 synthetic cash.
- Instruments: liquid US ETFs only until the paper process has several days of audited records.
- Max planned gross exposure: 90% of synthetic equity.
- Max single symbol planned exposure: 40% of synthetic equity.
- No options, margin, leverage, short selling, or individual equities in the first validation phase.
- A `planned` row is not a fill. Convert it to `filled` only after the next report has a real market price source and fill assumption.

## Paper fill review

- Run `python3 scripts/paper_fill.py --date YYYY-MM-DD` after the market snapshot is generated.
- The output in `journal/fill_reviews/YYYY-MM-DD.json` is a recommendation artifact, not a trade ledger mutation.
- `pending_future` means the planned trade date has not arrived.
- `blocked_stale_quote` means the local quote date does not match the planned trade date.
- `blocked_gap` means the latest price moved beyond the allowed reference gap.
- `blocked_missing_event_risk` means the local macro risk artifact is missing or mismatched, so no same-day synthetic fill can be considered.
- `blocked_event_risk` means the market is closed, the macro risk window forbids fills, or the candidate set exceeds the current event-risk gross-exposure cap.
- `fill_candidate` means a synthetic fill row can be manually copied into the ledger after review; it is still not a broker execution.
- The `risk_gate` object in each fill review records the event-risk file, risk level, max new gross exposure, and source-backed reasons used by the pre-trade gate.
- Run `python3 scripts/apply_paper_fills.py --date YYYY-MM-DD` to dry-run ledger changes from fill candidates.
- Only use `python3 scripts/apply_paper_fills.py --date YYYY-MM-DD --apply` after confirming the fill review and source-backed price. The script appends synthetic `filled` rows idempotently and writes an apply log; it never calls a broker.

## Daily checklist

1. Verify whether US equities are open.
2. Record market-moving scheduled events and fresh releases.
3. Pull quote snapshots and keep the raw JSON.
4. Generate the paper fill review.
5. Dry-run paper fill application; apply only when a paper fill is justified and source-backed.
6. Write or regenerate the daily report.
7. Run tests and audit.
8. Commit with a message like `daily: 2026-06-19 us market simulation`.

## Escalation rules

- If source data fails, mark the report as incomplete.
- If price data and news conflict, cite both and reduce confidence.
- If a real-account request appears before paper validation, refuse live operation and keep the simulation running.
