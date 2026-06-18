.PHONY: report test
.PHONY: validate
.PHONY: fills
.PHONY: risk
.PHONY: performance
.PHONY: apply-fills
.PHONY: live-gate
.PHONY: run-card

DATE ?= $(shell date +%F)

report:
	python3 scripts/market_monitor.py --date $(DATE)

risk:
	python3 scripts/event_risk.py --date $(DATE)

performance: report
	python3 scripts/performance.py --date $(DATE)

test:
	python3 -m unittest discover -s tests

fills: report
	python3 scripts/paper_fill.py --date $(DATE)

apply-fills: fills
	python3 scripts/apply_paper_fills.py --date $(DATE)

live-gate: performance
	python3 scripts/live_account_gate.py --date $(DATE)

run-card: live-gate apply-fills performance risk
	python3 scripts/run_card.py --date $(DATE)

validate: run-card test
	python3 scripts/audit_monitor.py --date $(DATE)
