"""Unit tests for the vintage reconstruction and the incremental strategies.

These run against a small synthetic fixture built in memory, not against the
real pull, so they are fast, deterministic and need no network. The fixture is
hand built precisely because the cases that matter here are rare in real data
and would be tedious to find: a request that closes exactly on a vintage
boundary, a request that closes between two vintages, a request that never
closes at all.

The distinction matters and is respected: a synthetic fixture
for the test suite is good, a synthetic number presented as a finding is not.
Nothing in this file produces a reported result.
"""

from __future__ import annotations

import duckdb
import pytest


@pytest.fixture()
def con():
    connection = duckdb.connect(":memory:")
    connection.execute("""
        CREATE TABLE requests (
            request_id VARCHAR,
            created_at TIMESTAMP,
            closed_at  TIMESTAMP
        )
    """)
    connection.execute("""
        INSERT INTO requests VALUES
            -- created and closed before the first vintage: settled throughout
            ('settled_early',    '2025-01-05 09:00:00', '2025-01-06 09:00:00'),
            -- created before vintage 1, closed between vintage 1 and 2:
            -- this is the restatement case the whole project turns on
            ('restated',         '2025-01-20 09:00:00', '2025-02-10 09:00:00'),
            -- closed exactly at the vintage 1 cutoff instant: boundary case
            ('closed_on_cutoff', '2025-01-10 09:00:00', '2025-01-31 23:59:59'),
            -- closed one second after the cutoff: must read as open at vintage 1
            ('closed_after_cutoff', '2025-01-10 09:00:00', '2025-02-01 00:00:00'),
            -- created after vintage 1: must not exist at vintage 1 at all
            ('created_later',    '2025-02-15 09:00:00', '2025-02-16 09:00:00'),
            -- never closes
            ('never_closes',     '2025-01-25 09:00:00', NULL)
    """)
    yield connection
    connection.close()


def state_at(con, cutoff: str):
    """Reconstruct request state at a cutoff, mirroring the SQL in the models."""
    return {
        row[0]: {"closed_at": row[1], "is_closed": row[2]}
        for row in con.execute(
            f"""
            SELECT
                request_id,
                CASE WHEN closed_at IS NOT NULL AND closed_at <= TIMESTAMP '{cutoff}'
                     THEN closed_at END,
                (closed_at IS NOT NULL AND closed_at <= TIMESTAMP '{cutoff}')
            FROM requests
            WHERE created_at <= TIMESTAMP '{cutoff}'
            """
        ).fetchall()
    }


V1 = "2025-01-31 23:59:59"
V2 = "2025-02-28 23:59:59"


def test_request_created_after_cutoff_is_absent(con):
    assert "created_later" not in state_at(con, V1)
    assert "created_later" in state_at(con, V2)


def test_close_after_cutoff_reads_as_open(con):
    at_v1 = state_at(con, V1)
    assert at_v1["restated"]["is_closed"] is False
    assert at_v1["restated"]["closed_at"] is None


def test_same_request_reads_as_closed_at_the_later_vintage(con):
    # the restatement: identical row, different answer, purely because time passed
    assert state_at(con, V1)["restated"]["is_closed"] is False
    assert state_at(con, V2)["restated"]["is_closed"] is True


def test_close_exactly_on_cutoff_counts_as_closed(con):
    # the cutoff is inclusive, so a close landing on the boundary instant is in
    assert state_at(con, V1)["closed_on_cutoff"]["is_closed"] is True


def test_close_one_second_after_cutoff_counts_as_open(con):
    assert state_at(con, V1)["closed_after_cutoff"]["is_closed"] is False


def test_never_closed_request_is_open_at_every_vintage(con):
    assert state_at(con, V1)["never_closes"]["is_closed"] is False
    assert state_at(con, V2)["never_closes"]["is_closed"] is False


def test_append_only_freezes_first_seen_state_and_merge_does_not(con):
    """The core claim of the comparison, proven on a fixture where it is checkable.

    Both strategies are fed the same two batches. Append only keeps whatever it
    saw first, merge takes the newer version. The request that closed between
    the vintages is the one they disagree about.
    """
    con.execute("CREATE TABLE append_only (request_id VARCHAR, is_closed BOOLEAN)")
    con.execute("CREATE TABLE merged     (request_id VARCHAR, is_closed BOOLEAN)")

    for cutoff in (V1, V2):
        batch = f"""
            SELECT request_id,
                   (closed_at IS NOT NULL AND closed_at <= TIMESTAMP '{cutoff}') AS is_closed
            FROM requests
            WHERE created_at <= TIMESTAMP '{cutoff}'
        """
        # append: skip keys already present
        con.execute(f"""
            INSERT INTO append_only
            SELECT * FROM ({batch}) b
            WHERE b.request_id NOT IN (SELECT request_id FROM append_only)
        """)
        # merge: delete the keys in this batch, then insert them fresh
        con.execute(f"DELETE FROM merged WHERE request_id IN (SELECT request_id FROM ({batch}) b)")
        con.execute(f"INSERT INTO merged SELECT * FROM ({batch}) b")

    append = dict(con.execute("SELECT request_id, is_closed FROM append_only").fetchall())
    merged = dict(con.execute("SELECT request_id, is_closed FROM merged").fetchall())

    # neither strategy duplicates or loses a key
    assert set(append) == set(merged)

    # the restated request is the disagreement: append froze it open, merge
    # updated it to closed
    assert append["restated"] is False
    assert merged["restated"] is True

    # a request that was already settled when first seen is identical in both,
    # which is why an append only pipeline looks fine on a static source
    assert append["settled_early"] == merged["settled_early"] is True

    # Every request that was open at the first vintage and closed by the second
    # is missed, not just the one named "restated". closed_after_cutoff closes
    # one second into February and is exactly the same kind of miss. Writing
    # this assertion as a set rather than a single name is the point: the
    # append only failure is a category, not one unlucky row.
    missed = {k for k in merged if merged[k] and not append[k]}
    assert missed == {"restated", "closed_after_cutoff"}

    # and a request that never closes is not a miss, because there is nothing
    # to miss yet
    assert "never_closes" not in missed
