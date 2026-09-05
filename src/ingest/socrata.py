"""Socrata SoQL client for the NYC 311 dataset.

Two things here are not incidental and are worth reading before changing:

Keyset pagination, not offset. Socrata accepts $offset, but deep offsets get
progressively slower and, more importantly, a plain $offset walk over a table
that is being written to while you read it can repeat or skip rows. This client
paginates by carrying the last seen sort key forward into the next request's
$where clause, with an explicit $order on the same columns. That is stable
against concurrent writes because it never asks the server to count past rows.

The sort key is the pair (created_date, unique_key), not unique_key alone, and
that is a performance requirement rather than a preference. unique_key is a
text column and sorting the dataset by it is expensive enough that a request
ordered on it alone does not return inside a 170 second timeout, measured. The
same request ordered on created_date first returns in about 35 seconds, because
created_date is the dataset's natural order. The pair is still unique, since
unique_key is unique on its own, so the keyset walk stays correct.

Resumability. The full pull takes hours, so every page is appended to a
gzipped newline-delimited JSON file and a manifest records the last key
committed for each slice. A rerun picks up from the manifest rather than
starting over.
"""

from __future__ import annotations

import gzip
import json
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterator

USER_AGENT = "nyc311-warehouse/1.0 (analytics engineering project)"


class SocrataError(RuntimeError):
    pass


@dataclass
class SocrataClient:
    base_url: str
    app_token: str | None = None
    page_size: int = 10000
    sort_column: str = "created_date"
    tiebreak_column: str = "unique_key"
    timeout_seconds: int = 180
    max_retries: int = 5
    retry_backoff_seconds: float = 2.0

    def _request(self, params: dict[str, str]) -> Any:
        query = urllib.parse.urlencode(params)
        url = f"{self.base_url}?{query}"
        headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        if self.app_token:
            headers["X-App-Token"] = self.app_token

        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            if attempt:
                # exponential backoff, deliberately patient because the
                # anonymous tier throttles hard and retrying fast makes it worse
                time.sleep(self.retry_backoff_seconds * (2 ** (attempt - 1)))
            try:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except Exception as exc:  # noqa: BLE001 network paths are varied
                last_error = exc
        raise SocrataError(
            f"request failed after {self.max_retries} attempts: {url}"
        ) from last_error

    def count(self, where: str | None = None) -> int:
        params = {"$select": "count(*) as n"}
        if where:
            params["$where"] = where
        rows = self._request(params)
        return int(rows[0]["n"])

    def scalar_query(self, select: str, where: str | None = None) -> list[dict]:
        params = {"$select": select}
        if where:
            params["$where"] = where
        return self._request(params)

    @property
    def order_clause(self) -> str:
        return f"{self.sort_column}, {self.tiebreak_column}"

    def _keyset_predicate(self, sort_value: str, tiebreak_value: str) -> str:
        """Standard composite keyset predicate, strictly after (sort, tiebreak)."""
        sort_lit = sort_value.replace("'", "''")
        tie_lit = tiebreak_value.replace("'", "''")
        return (
            f"({self.sort_column} > '{sort_lit}'"
            f" OR ({self.sort_column} = '{sort_lit}'"
            f" AND {self.tiebreak_column} > '{tie_lit}'))"
        )

    def paginate(
        self,
        columns: list[str],
        where: str,
        start_after: tuple[str, str] | None = None,
    ) -> Iterator[list[dict]]:
        """Yield pages of rows, keyset paginated on (sort, tiebreak).

        `where` is the slice predicate. `start_after` is the last committed
        (sort_value, tiebreak_value) pair, so a resumed run continues rather
        than refetching. The caller gets whole pages so it can checkpoint
        after each one.
        """
        cursor = start_after
        # the sort column must be selected, otherwise the cursor cannot advance
        select_cols = list(columns)
        for required in (self.sort_column, self.tiebreak_column):
            if required not in select_cols:
                select_cols.append(required)

        while True:
            predicate = where
            if cursor is not None:
                predicate = f"({where}) AND {self._keyset_predicate(*cursor)}"

            params = {
                "$select": ",".join(select_cols),
                "$where": predicate,
                "$order": self.order_clause,
                "$limit": str(self.page_size),
            }
            page = self._request(params)
            if not page:
                return
            yield page
            last = page[-1]
            cursor = (last[self.sort_column], last[self.tiebreak_column])
            if len(page) < self.page_size:
                return


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def append_ndjson_gz(path, rows: list[dict], ingested_at: str) -> None:
    """Append rows to a gzipped newline-delimited JSON file.

    Each row carries the ingestion timestamp of the batch that landed it, which
    is what makes the landing table an append log rather than a snapshot.
    """
    with gzip.open(path, "at", encoding="utf-8") as fh:
        for row in rows:
            row = dict(row)
            row["_ingested_at"] = ingested_at
            fh.write(json.dumps(row, sort_keys=True, separators=(",", ":")))
            fh.write("\n")
