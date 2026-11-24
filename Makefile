PY ?= .venv/bin/python
FM ?= .venv/bin/fm

.PHONY: install lint test test-live ingest synth

install:
	python3.12 -m venv .venv
	$(PY) -m pip install -q -e '.[dev]'

lint:
	$(PY) -m ruff check src tests
	$(PY) -m ruff format --check src tests

test:
	$(PY) -m pytest -q

test-live:
	$(PY) -m pytest -q --live -m live

ingest:
	$(FM) ingest --mode record

synth:
	$(FM) synth generate --seed 42 --out tests/fixtures/synthetic
	$(FM) synth load --db data/fm_synth.sqlite
