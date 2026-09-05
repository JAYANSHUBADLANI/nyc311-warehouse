# Row count reconciliation

Every row that entered the landing table is accounted for: either it reached the fact table or it is named in a quarantine reason below. The residual line must be zero, and `assert_ledger_reconciles` fails the build if it is not.

| Stage | What it is | Rows | Change |
| --- | --- | --- | --- |
| landed_rows | rows written to the landing table by the ingest | 3,890,842 |  |
| deduplicated_to_current_state | landing is an append log, one row kept per request: the latest ingestion | 3,890,842 | 0 |
| quarantined | removed for a fatal data quality rule, itemised in the rows below | 840 |  |
| valid_for_fact | rows placed in fct_service_request | 3,890,002 | -840 |
| reconciliation_residual | staged minus quarantined minus valid, must be zero | 0 |  |
| quarantine_reason: closed_before_created | count of rows excluded under this rule | 840 |  |
