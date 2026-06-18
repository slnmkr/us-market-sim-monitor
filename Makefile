.PHONY: report test
.PHONY: validate
.PHONY: fills

DATE ?= $(shell date +%F)

report:
	python3 scripts/market_monitor.py --date $(DATE)

test:
	python3 -m unittest discover -s tests

fills: report
	python3 scripts/paper_fill.py --date $(DATE)

validate: fills test
	python3 scripts/audit_monitor.py --date $(DATE)
