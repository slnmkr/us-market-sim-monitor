.PHONY: report test
.PHONY: validate
.PHONY: fills
.PHONY: risk
.PHONY: performance
.PHONY: apply-fills
.PHONY: live-gate

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

validate: risk apply-fills performance live-gate test
	python3 scripts/audit_monitor.py --date $(DATE)
