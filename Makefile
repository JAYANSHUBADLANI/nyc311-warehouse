SHELL := /bin/bash
VENV := .venv
PY := $(VENV)/bin/python
DBT := $(VENV)/bin/dbt
DBT_DIR := dbt/nyc311_warehouse
PROFILES_DIR := dbt

# Every dbt invocation reads its vars from config/config.yml through this, so a
# model and the ingest that fed it can never disagree about the window.
DBT_VARS = $$($(PY) scripts/config_to_dbt_vars.py --json)

.PHONY: help venv fetch sample load build test replay reports demo demo-sample clean check-fresh probe-capture probe-recheck

help:
	@echo "make demo          full run: fetch, load, build, test, replay, reports"
	@echo "make demo-sample   same pipeline against the committed sample, no network"
	@echo "make fetch         pull the configured window from the live API"
	@echo "make sample        refresh the committed sample from the raw pull"
	@echo "make load          load raw NDJSON into the DuckDB landing table"
	@echo "make build         run the dbt models"
	@echo "make test          run the dbt test suite"
	@echo "make replay        replay vintages through both incremental models"
	@echo "make reports       regenerate the dictionary, drift table and BI export"
	@echo "make clean         drop the warehouse and dbt artefacts, keep raw pulls"

venv:
	python3 -m venv $(VENV)
	$(VENV)/bin/pip install --upgrade pip
	$(VENV)/bin/pip install -r requirements.txt

fetch:
	$(PY) -m src.ingest.fetch_raw

probe-capture:
	$(PY) -m src.ingest.mutation_probe --capture

probe-recheck:
	$(PY) -m src.ingest.mutation_probe --recheck

sample:
	$(PY) scripts/build_sample.py

load:
	$(PY) -m src.ingest.load_landing

load-sample:
	$(PY) -m src.ingest.load_landing --sample

build:
	cd $(DBT_DIR) && DBT_PROFILES_DIR=../../$(PROFILES_DIR) ../../$(DBT) run \
		--exclude comparison --vars '$(DBT_VARS)'

test:
	cd $(DBT_DIR) && DBT_PROFILES_DIR=../../$(PROFILES_DIR) ../../$(DBT) test \
		--exclude comparison --vars '$(DBT_VARS)'

replay:
	$(PY) scripts/run_vintage_replay.py
	cd $(DBT_DIR) && DBT_PROFILES_DIR=../../$(PROFILES_DIR) ../../$(DBT) build \
		--select comparison_drift_summary --vars '$(DBT_VARS)'

reports:
	$(PY) scripts/generate_measure_dictionary.py
	$(PY) scripts/generate_reports.py

pytest:
	$(VENV)/bin/pytest -q

# The single entry point. Runs the whole thing from a clean warehouse.
demo: load build test replay reports pytest
	@echo ""
	@echo "done. see README.md, reports/memo.md and reports/measure_dictionary.md"

# Same pipeline, committed sample, no network needed. This is what makes the
# repo reproducible for someone who just cloned it.
demo-sample: load-sample build test replay reports pytest
	@echo ""
	@echo "sample run complete. numbers are from the committed sample, not the full window"

clean:
	rm -f data/warehouse.duckdb data/warehouse.duckdb.wal
	rm -rf $(DBT_DIR)/target $(DBT_DIR)/logs
	rm -rf reports/generated
