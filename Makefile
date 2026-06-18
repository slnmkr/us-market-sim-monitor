.PHONY: report test
.PHONY: validate
.PHONY: fills
.PHONY: risk
.PHONY: performance

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

validate: risk fills performance test
	python3 scripts/audit_monitor.py --date $(DATE)
