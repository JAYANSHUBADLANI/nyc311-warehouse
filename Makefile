SHELL := /bin/bash
VENV := .venv
PY := $(VENV)/bin/python
DBT := $(VENV)/bin/dbt
DBT_DIR := dbt/nyc311_warehouse
PROFILES_DIR := dbt

# Every dbt invocation reads its vars from config/config.yml through this, so a
# model and the ingest that fed it can never disagree about the window. The
# value has to be resolved before the recipe changes directory, because the
# script path is relative to the repo root, and it has to be passed in double
# quotes so the shell substitutes it rather than handing dbt the literal text.
DBT_VARS_CMD = $(PY) scripts/config_to_dbt_vars.py --json

.PHONY: help venv fetch sample load load-sample build build-sample test test-sample replay replay-sample reports reports-sample pytest demo demo-sample clean probe-capture probe-recheck

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

# Every sample target below runs against the devsample dbt target and the sample
# paths in config/config.yml, so running the offline demo can never overwrite a
# real pull or the generated reports the README quotes.
build-sample:
	@VARS=$$($(DBT_VARS_CMD)); \
	cd $(DBT_DIR) && DBT_PROFILES_DIR=../../$(PROFILES_DIR) ../../$(DBT) run \
		--target devsample --exclude comparison --vars "$$VARS"

test-sample:
	@VARS=$$($(DBT_VARS_CMD)); \
	cd $(DBT_DIR) && DBT_PROFILES_DIR=../../$(PROFILES_DIR) ../../$(DBT) test \
		--target devsample --exclude comparison --vars "$$VARS"

replay-sample:
	$(PY) scripts/run_vintage_replay.py --sample
	@VARS=$$($(DBT_VARS_CMD)); \
	cd $(DBT_DIR) && DBT_PROFILES_DIR=../../$(PROFILES_DIR) ../../$(DBT) build \
		--target devsample --select comparison_drift_summary --vars "$$VARS"

reports-sample:
	$(PY) scripts/generate_measure_dictionary.py --sample
	$(PY) scripts/generate_reports.py --sample

build:
	@VARS=$$($(DBT_VARS_CMD)); \
	cd $(DBT_DIR) && DBT_PROFILES_DIR=../../$(PROFILES_DIR) ../../$(DBT) run \
		--exclude comparison --vars "$$VARS"

test:
	@VARS=$$($(DBT_VARS_CMD)); \
	cd $(DBT_DIR) && DBT_PROFILES_DIR=../../$(PROFILES_DIR) ../../$(DBT) test \
		--exclude comparison --vars "$$VARS"

replay:
	$(PY) scripts/run_vintage_replay.py
	@VARS=$$($(DBT_VARS_CMD)); \
	cd $(DBT_DIR) && DBT_PROFILES_DIR=../../$(PROFILES_DIR) ../../$(DBT) build \
		--select comparison_drift_summary --vars "$$VARS"

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
demo-sample: load-sample build-sample test-sample replay-sample reports-sample pytest
	@echo ""
	@echo "sample run complete. numbers are from the committed sample, not the full"
	@echo "window, and were written to reports/generated_sample. The full window"
	@echo "results in reports/generated are untouched."

# Drops what a build can regenerate. reports/generated is deliberately not in
# here: it is committed as the evidence for every number the README and the memo
# quote, so removing it deletes tracked files rather than build output. The
# sample output is regenerable and untracked, so that one does go.
clean:
	rm -f data/warehouse.duckdb data/warehouse.duckdb.wal
	rm -f data/sample_warehouse.duckdb data/sample_warehouse.duckdb.wal
	rm -rf $(DBT_DIR)/target $(DBT_DIR)/logs
	rm -rf reports/generated_sample
