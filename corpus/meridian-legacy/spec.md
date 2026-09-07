# Meridian Legacy — general ledger cash postings

Meridian Legacy Holdings is a run-off book we inherited in the 2024 acquisition. Its
general ledger still emits a nightly cash posting extract, `gl_cash_<YYYYMMDD>.csv`,
produced by a scheduled job on the legacy finance server at 23:30 UK time and copied to
our inbound share by 06:00. The extract lists every cash posting to the Meridian bank
accounts for the previous business day and is used solely for reconciliation, since no
new business is written on the book.

The format is unremarkable: comma-separated, one header row, ISO dates, signed amounts
with two decimals and no thousands separators, upper-case ISO currency codes. The
documentation we inherited states that the extract always contains fifteen postings: a
fixed set of standing charges plus the day's movements. In practice the sample we were
given contains fourteen. Nobody at Meridian can say whether a posting is genuinely
missing or the documentation is stale, and the original author of the extract has left.
This discrepancy must not be papered over; it needs a human decision.

Contact is the Meridian run-off finance lead via the integration mailbox (meridian-runoff).
Response times are measured in days, not hours, so any row-count question should be raised
early and the feed held rather than loaded on assumption.

```yaml feed-contract
client: meridian-legacy
feed_name: gl_cash
format: csv
delimiter: ","
encoding: utf-8
header_rows: 1
trailer_rows: 0
schedule_cron: "0 6 * * 1-5"
expected_row_count: 15
columns:
  - {source: "TXN_ID", target: trade_id, dtype: str}
  - {source: "ACCOUNT_NO", target: account_id, dtype: str}
  - {source: "VALUE_DT", target: value_date, dtype: date, date_format: "%Y-%m-%d"}
  - {source: "AMT", target: amount, dtype: decimal}
  - {source: "CUR", target: currency, dtype: str}
  - {source: "CPTY_NAME", target: counterparty, dtype: str}
  - {source: "DESC", target: description, dtype: str}
quirks:
  - "Documentation says 15 postings per file; the sample provided has 14. Unresolved."
  - "Clean csv otherwise: ISO dates, signed amounts, no thousands separators."
```
