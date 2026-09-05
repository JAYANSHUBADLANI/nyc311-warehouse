"""Measure how much the live source actually mutates between two snapshots.

Run:  python -m src.ingest.mutation_probe --capture
      python -m src.ingest.mutation_probe --recheck

Why this exists. The vintage replay reconstructs history from timestamps, which
recovers restatement of the close date exactly but is blind to any edit that
overwrites a value in place: a reclassified complaint type, a corrected
descriptor, a changed agency. Those leave no trace in a single snapshot, so the
replay cannot see them and the drift it measures is a lower bound.

Rather than leaving that as an unquantified caveat, this probe bounds it
empirically. It records the exact field values of a fixed sample of requests at
the start of the build, refetches those same request ids at the end, and diffs
every field. Whatever changed in the gap is real in place mutation that the
replay would have missed.

The sample is drawn from the most recent complete month rather than uniformly,
on purpose. Old requests are mostly settled and would show a mutation rate near
zero that says more about the sample than about the source. Recent requests are
where restatement actually happens, so sampling there gives the probe a chance
to find something.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.config import load_config  # noqa: E402
from src.ingest.socrata import SocrataClient, utc_now_iso  # noqa: E402

PROBE_FIELDS = [
    "unique_key",
    "created_date",
    "closed_date",
    "status",
    "agency",
    "complaint_type",
    "descriptor",
    "resolution_action_updated_date",
]


def make_client(cfg) -> SocrataClient:
    sc = cfg["socrata"]
    return SocrataClient(
        base_url=sc["base_url"],
        app_token=cfg.app_token,
        page_size=sc["page_size"],
        sort_column=sc["sort_column"],
        tiebreak_column=sc["tiebreak_column"],
        timeout_seconds=sc["request_timeout_seconds"],
        max_retries=sc["max_retries"],
        retry_backoff_seconds=sc["retry_backoff_seconds"],
    )


def capture(cfg, sample_size: int, window_days: int) -> int:
    """Snapshot A: record the current state of a fixed set of request ids."""
    client = make_client(cfg)
    probe_path = cfg.path("raw_dir") / "_mutation_probe_a.json"
    probe_path.parent.mkdir(parents=True, exist_ok=True)

    # anchor on the configured build window end rather than the wall clock, so
    # a rerun captures the same population
    end = client.scalar_query("max(created_date) as m")[0]["m"]
    end_dt = datetime.fromisoformat(end)
    start_dt = end_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    start_dt = start_dt.replace(day=1) if window_days >= 28 else start_dt

    where = (
        f"created_date >= '{start_dt.strftime('%Y-%m-%dT%H:%M:%S')}' "
        f"AND created_date <= '{end_dt.strftime('%Y-%m-%dT%H:%M:%S')}'"
    )

    print(f"capturing snapshot A over {where}")
    rows: list[dict] = []
    for page in client.paginate(PROBE_FIELDS, where):
        rows.extend(page)
        print(f"  {len(rows)} rows", flush=True)
        if len(rows) >= sample_size:
            break
    rows = rows[:sample_size]

    payload = {
        "captured_at": utc_now_iso(),
        "where": where,
        "fields": PROBE_FIELDS,
        "sample_size": len(rows),
        # sorted by key so the file is byte identical for the same input
        "rows": sorted(rows, key=lambda r: r["unique_key"]),
    }
    probe_path.write_text(json.dumps(payload, indent=2, sort_keys=True))
    print(f"snapshot A written: {len(rows)} requests to {probe_path}")
    return 0


def recheck(cfg) -> int:
    """Snapshot B: refetch the same ids and diff every field against A."""
    client = make_client(cfg)
    raw_dir = cfg.path("raw_dir")
    probe_path = raw_dir / "_mutation_probe_a.json"
    if not probe_path.exists():
        print("no snapshot A found, run --capture first")
        return 1

    snapshot_a = json.loads(probe_path.read_text())
    a_rows = {r["unique_key"]: r for r in snapshot_a["rows"]}
    keys = sorted(a_rows)
    print(f"rechecking {len(keys)} requests captured at {snapshot_a['captured_at']}")

    # refetch in id batches, which is exact rather than relying on the window
    b_rows: dict[str, dict] = {}
    batch_size = 200
    for i in range(0, len(keys), batch_size):
        batch = keys[i : i + batch_size]
        quoted = ",".join(f"'{k}'" for k in batch)
        page = client.scalar_query(
            ",".join(PROBE_FIELDS), where=f"unique_key IN ({quoted})"
        )
        for row in page:
            b_rows[row["unique_key"]] = row
        print(f"  refetched {len(b_rows)}/{len(keys)}", flush=True)

    captured_at = datetime.fromisoformat(snapshot_a["captured_at"])
    rechecked_at = datetime.now(timezone.utc)
    gap_hours = (rechecked_at - captured_at).total_seconds() / 3600.0

    field_changes = {f: 0 for f in PROBE_FIELDS if f != "unique_key"}
    changed_requests = 0
    disappeared = 0
    examples: list[dict] = []

    for key in keys:
        a = a_rows[key]
        b = b_rows.get(key)
        if b is None:
            disappeared += 1
            continue
        changed_fields = [
            f for f in field_changes if a.get(f) != b.get(f)
        ]
        if changed_fields:
            changed_requests += 1
            for f in changed_fields:
                field_changes[f] += 1
            if len(examples) < 10:
                examples.append(
                    {
                        "unique_key": key,
                        "changed_fields": changed_fields,
                        "before": {f: a.get(f) for f in changed_fields},
                        "after": {f: b.get(f) for f in changed_fields},
                    }
                )

    result = {
        "captured_at": snapshot_a["captured_at"],
        "rechecked_at": rechecked_at.isoformat(timespec="seconds"),
        "gap_hours": round(gap_hours, 2),
        "sample_size": len(keys),
        "refetched": len(b_rows),
        "disappeared_from_source": disappeared,
        "requests_changed": changed_requests,
        "requests_changed_pct": round(100.0 * changed_requests / max(len(keys), 1), 3),
        "field_change_counts": field_changes,
        "examples": examples,
    }

    out_path = raw_dir / "_mutation_probe_result.json"
    out_path.write_text(json.dumps(result, indent=2, sort_keys=True))

    print(f"\ngap {result['gap_hours']} hours")
    print(f"{changed_requests} of {len(keys)} requests changed ({result['requests_changed_pct']}%)")
    for field, n in sorted(field_changes.items(), key=lambda kv: -kv[1]):
        if n:
            print(f"  {field}: {n}")
    print(f"written to {out_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", action="store_true", help="record snapshot A")
    parser.add_argument("--recheck", action="store_true", help="refetch and diff against snapshot A")
    parser.add_argument("--sample-size", type=int, default=3000)
    parser.add_argument("--window-days", type=int, default=28)
    args = parser.parse_args()

    cfg = load_config()
    if args.capture:
        return capture(cfg, args.sample_size, args.window_days)
    if args.recheck:
        return recheck(cfg)
    parser.error("pass --capture or --recheck")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
