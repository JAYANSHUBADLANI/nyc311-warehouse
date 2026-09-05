"""Pull the configured window of 311 requests into data/raw as gzipped NDJSON.

Run:  python -m src.ingest.fetch_raw

The window is sliced by calendar month. Each slice is fetched with keyset
pagination and appended to its own file, and a manifest records the last key
committed per slice so an interrupted run resumes instead of restarting. The
pull is long, hours rather than minutes on the anonymous tier, so resumability
is a requirement rather than a nicety.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from dateutil.relativedelta import relativedelta

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.config import load_config  # noqa: E402
from src.ingest.socrata import (  # noqa: E402
    SocrataClient,
    append_ndjson_gz,
    utc_now_iso,
)


def month_slices(start: datetime, end: datetime) -> list[tuple[str, datetime, datetime]]:
    """Split [start, end) into calendar month slices, labelled YYYY-MM."""
    slices = []
    cursor = datetime(start.year, start.month, 1)
    while cursor < end:
        nxt = cursor + relativedelta(months=1)
        slice_start = max(cursor, start)
        slice_end = min(nxt, end)
        slices.append((cursor.strftime("%Y-%m"), slice_start, slice_end))
        cursor = nxt
    return slices


def soql_ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


class Manifest:
    """Per slice progress, so an interrupted pull resumes where it stopped."""

    def __init__(self, path: Path):
        self.path = path
        self.data = json.loads(path.read_text()) if path.exists() else {"slices": {}}

    def slice_state(self, label: str) -> dict:
        return self.data["slices"].setdefault(
            label,
            {"last_sort": None, "last_key": None, "rows": 0, "complete": False},
        )

    def save(self) -> None:
        self.path.write_text(json.dumps(self.data, indent=2, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sample",
        action="store_true",
        help="fetch a small committed sample instead of the full window",
    )
    parser.add_argument(
        "--sample-rows-per-month",
        type=int,
        default=2000,
        help="rows per month when --sample is set",
    )
    args = parser.parse_args()

    cfg = load_config()
    sc = cfg["socrata"]
    ing = cfg["ingest"]

    client = SocrataClient(
        base_url=sc["base_url"],
        app_token=cfg.app_token,
        page_size=sc["page_size"],
        sort_column=sc["sort_column"],
        tiebreak_column=sc["tiebreak_column"],
        timeout_seconds=sc["request_timeout_seconds"],
        max_retries=sc["max_retries"],
        retry_backoff_seconds=sc["retry_backoff_seconds"],
    )
    if cfg.app_token:
        print("using app token from environment")
    else:
        print("no app token found, running on the throttled anonymous tier")

    window_start = datetime.fromisoformat(ing["window_start"])
    window_end = (
        datetime.fromisoformat(ing["window_end"])
        if ing["window_end"]
        else datetime.now().replace(microsecond=0)
    )

    out_dir = cfg.path("sample_dir") if args.sample else cfg.path("raw_dir")
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = Manifest(out_dir / "_manifest.json")
    manifest.data.setdefault("window", {})
    manifest.data["window"] = {
        "start": soql_ts(window_start),
        "end": soql_ts(window_end),
        "sample": args.sample,
        "columns": ing["columns"],
    }

    agency_filter = ing.get("agency_filter")
    slices = month_slices(window_start, window_end)
    print(f"window {soql_ts(window_start)} to {soql_ts(window_end)}, {len(slices)} month slices")

    total_rows = 0
    for label, s_start, s_end in slices:
        state = manifest.slice_state(label)
        out_path = out_dir / f"requests_{label}.ndjson.gz"

        if state["complete"]:
            print(f"  {label}: already complete, {state['rows']} rows")
            total_rows += state["rows"]
            continue

        where = (
            f"created_date >= '{soql_ts(s_start)}' "
            f"AND created_date < '{soql_ts(s_end)}'"
        )
        if agency_filter:
            quoted = ",".join(f"'{a}'" for a in agency_filter)
            where += f" AND agency IN ({quoted})"

        ingested_at = utc_now_iso()
        rows_this_slice = state["rows"]
        start_after = (
            (state["last_sort"], state["last_key"])
            if state["last_key"] is not None
            else None
        )

        # The manifest and the file on disk have to agree, or the walk silently
        # duplicates. Starting a slice with no cursor means starting from the
        # first row, so any file already sitting there is from an abandoned run
        # and has to go. Appending to it instead would write every row twice and
        # the duplicates would only surface as a distinct count mismatch three
        # models downstream.
        if start_after is None and out_path.exists():
            print(f"  {label}: discarding {out_path.name} from an earlier run, restarting slice")
            out_path.unlink()
        try:
            for page in client.paginate(
                columns=ing["columns"],
                where=where,
                start_after=start_after,
            ):
                append_ndjson_gz(out_path, page, ingested_at)
                rows_this_slice += len(page)
                state["last_sort"] = page[-1][sc["sort_column"]]
                state["last_key"] = page[-1][sc["tiebreak_column"]]
                state["rows"] = rows_this_slice
                manifest.save()
                print(f"  {label}: {rows_this_slice} rows", flush=True)

                if args.sample and rows_this_slice >= args.sample_rows_per_month:
                    break
        except KeyboardInterrupt:
            manifest.save()
            print("interrupted, manifest saved, rerun to resume")
            return 130

        state["complete"] = True
        manifest.save()
        total_rows += rows_this_slice
        print(f"  {label}: complete, {rows_this_slice} rows")

    manifest.data["total_rows"] = total_rows
    manifest.data["finished_at"] = utc_now_iso()
    manifest.save()
    print(f"done, {total_rows} rows in {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
