PYTHON ?= python3
VENV := .venv
BIN := $(VENV)/bin

.PHONY: venv install lint test check

venv:
	$(PYTHON) -m venv $(VENV)

install: venv
	$(BIN)/pip install -e ".[dev]"

lint:
	$(BIN)/ruff check .

test:
	$(BIN)/pytest

check: lint
	$(BIN)/python -m compileall -q src tests scripts
	$(BIN)/pytest
	$(BIN)/python scripts/smoke.py
	$(BIN)/python scripts/check_runnable.py
