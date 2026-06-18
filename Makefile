.PHONY: report test
.PHONY: validate

DATE ?= $(shell date +%F)

report:
	python3 scripts/market_monitor.py --date $(DATE)

test:
	python3 -m unittest discover -s tests

validate: report test
	python3 scripts/audit_monitor.py --date $(DATE)
