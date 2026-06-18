# Operating Rules

## Non-negotiable boundaries

- No live trading until the user explicitly provides a broker connection, account mandate, and written risk limits.
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

## Daily checklist

1. Verify whether US equities are open.
2. Record market-moving scheduled events and fresh releases.
3. Pull quote snapshots and keep the raw JSON.
4. Update `journal/paper_trades.csv`.
5. Write or regenerate the daily report.
6. Run tests.
7. Commit with a message like `daily: 2026-06-19 us market simulation`.

## Escalation rules

- If source data fails, mark the report as incomplete.
- If price data and news conflict, cite both and reduce confidence.
- If a real-account request appears before paper validation, refuse live operation and keep the simulation running.

