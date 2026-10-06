PYTHON ?= python3

.PHONY: flow test lint browser-test
flow:
	$(PYTHON) td_flow.py

test:
	$(PYTHON) tests/run_python_tests.py
	npm test

lint:
	$(PYTHON) -m ruff check td_flow.py tests/test_td_flow.py tests/check_flow_browser.py tests/run_python_tests.py
	npm run lint

browser-test:
	$(PYTHON) tests/check_flow_browser.py
