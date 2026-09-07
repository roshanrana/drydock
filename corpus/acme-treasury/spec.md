# Acme Treasury — daily cash feed

Acme Treasury's group treasury team exports a daily cash movement report from their
treasury management system at 05:30 UK time every business day. The file lands on our
SFTP drop as `daily_cash_<YYYY-MM-DD>.csv` and covers all settled movements across the
operating accounts (GBP, USD and EUR nostros) for the value date in the file name. Files
are never re-sent; a correction arrives as a reversing entry in the following day's file.

The export is a plain comma-separated file with a single header row and UTF-8 encoding.
Amounts are signed, carry two decimal places and include thousands separators, which means
every amount is wrapped in double quotes (`"-12,500.00"`). Dates are already ISO-8601.
Narratives are free text keyed in by the payments desk and occasionally contain trailing
spaces. Counterparty names are taken from the static data module and are stable across
days.

Operational contact is the Acme treasury operations mailbox (treasury-ops, internal
ticket queue ACME-TSY). Escalate row-count discrepancies to the on-call cash manager
before 08:00; anything after that is picked up on the next business day.

```yaml feed-contract
client: acme-treasury
feed_name: daily_cash
format: csv
delimiter: ","
encoding: utf-8
header_rows: 1
trailer_rows: 0
schedule_cron: "0 6 * * 1-5"
expected_row_count: 12
columns:
  - {source: "TradeRef", target: trade_id, dtype: str}
  - {source: "Acct", target: account_id, dtype: str}
  - {source: "ValueDate", target: value_date, dtype: date, date_format: "%Y-%m-%d"}
  - {source: "Amount", target: amount, dtype: decimal}
  - {source: "Ccy", target: currency, dtype: str}
  - {source: "Cpty", target: counterparty, dtype: str}
  - {source: "Narrative", target: description, dtype: str}
quirks:
  - "Amounts arrive with thousands separators and are therefore double-quoted."
  - "Amounts are signed; there is no separate debit/credit indicator."
  - "Narratives may carry trailing whitespace."
```
