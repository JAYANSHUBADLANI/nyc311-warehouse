"""Emit dbt vars from config/config.yml so both halves read one config.

Run:  python scripts/config_to_dbt_vars.py [--json]

Without --json it rewrites the vars block in dbt_project.yml in place. With
--json it prints a JSON object suitable for `dbt run --vars`. The Makefile uses
the JSON form, so a dbt run cannot silently disagree with the config the Python
ingest used.

build_as_of is pinned to the ingest window end rather than to the wall clock,
which is what makes two consecutive runs produce identical output. If it read
current_date, every backlog and maturity number would move between runs and
nothing could be reconciled.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import load_config  # noqa: E402


def resolve_build_as_of(cfg) -> str:
    """The instant the warehouse is built against.

    Taken from the ingest manifest when there is one, so it reflects the data
    that actually landed rather than when someone happened to run dbt. Falls
    back to the configured window end, then to today at midnight.
    """
    manifest_path = cfg.path("raw_dir") / "_manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        end = manifest.get("window", {}).get("end")
        if end:
            return end

    configured_end = cfg["ingest"]["window_end"]
    if configured_end:
        return configured_end

    return datetime.now().strftime("%Y-%m-%dT00:00:00")


def build_vars(cfg) -> dict:
    return {
        "window_start": cfg["ingest"]["window_start"],
        "window_end": resolve_build_as_of(cfg),
        "build_as_of": resolve_build_as_of(cfg),
        "sla_target_days": cfg["sla"]["default_target_days"],
        "maturity_window_days": cfg["maturity"]["window_days"],
        "vintage_cadence": cfg["vintages"]["cadence"],
        "vintage_first": cfg["vintages"]["first_vintage"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="print JSON instead of rewriting dbt_project.yml")
    args = parser.parse_args()

    cfg = load_config()
    dbt_vars = build_vars(cfg)

    if args.json:
        print(json.dumps(dbt_vars, sort_keys=True))
        return 0

    print(json.dumps(dbt_vars, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
