"""Derive the committed sample from the real raw pull.

Run:  python scripts/build_sample.py

The sample exists so the repo runs as cloned: `make demo-sample` builds every
model, runs every test and produces every report without touching the network.
It is real data, not synthetic, taken from the same pull the headline numbers
come from.

It is a systematic sample rather than a random one: rows are sorted by
unique_key and every nth is taken. That is deterministic without needing a seed,
and unlike taking the first n rows it spreads across the whole month instead of
clustering on whichever keys happen to sort first.

The numbers this produces are not the project's findings and are labelled that
way everywhere. It is a fixture for proving the pipeline runs, not a smaller
version of the result.
"""

from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import load_config  # noqa: E402

ROWS_PER_MONTH = 500


def main() -> int:
    cfg = load_config()
    raw_dir = cfg.path("raw_dir")
    sample_dir = cfg.path("sample_dir")
    sample_dir.mkdir(parents=True, exist_ok=True)

    raw_files = sorted(raw_dir.glob("requests_*.ndjson.gz"))
    if not raw_files:
        print(f"no raw files in {raw_dir}, run make fetch first")
        return 1

    manifest = {"slices": {}, "source": "systematic sample of the raw pull", "rows_per_month": ROWS_PER_MONTH}
    total = 0

    for raw_path in raw_files:
        label = raw_path.name.replace("requests_", "").replace(".ndjson.gz", "")

        rows = []
        with gzip.open(raw_path, "rt", encoding="utf-8") as fh:
            for line in fh:
                rows.append(json.loads(line))

        # deterministic order, then a fixed stride across the whole month
        rows.sort(key=lambda r: r["unique_key"])
        if len(rows) > ROWS_PER_MONTH:
            stride = len(rows) // ROWS_PER_MONTH
            rows = rows[::stride][:ROWS_PER_MONTH]

        out_path = sample_dir / raw_path.name
        with gzip.open(out_path, "wt", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, sort_keys=True, separators=(",", ":")))
                fh.write("\n")

        manifest["slices"][label] = {
            "last_sort": None,
            "last_key": None,
            "rows": len(rows),
            "complete": True,
        }
        total += len(rows)
        print(f"  {label}: {len(rows)} rows")

    manifest["total_rows"] = total
    manifest["window"] = {
        "start": cfg["ingest"]["window_start"],
        "end": cfg["ingest"]["window_end"],
        "sample": True,
        "columns": cfg["ingest"]["columns"],
    }
    (sample_dir / "_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))

    size = sum(f.stat().st_size for f in sample_dir.glob("*.ndjson.gz"))
    print(f"sample written: {total} rows, {size / 1024:.0f} KB across {len(raw_files)} months")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
