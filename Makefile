PYTHON ?= python3
VENV := .venv
BIN := $(VENV)/bin

.PHONY: venv install test

venv:
	$(PYTHON) -m venv $(VENV)

install: venv
	$(BIN)/pip install -e ".[dev]"

test:
	$(BIN)/pytest
