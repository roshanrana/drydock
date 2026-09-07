# Kestrel Payments — executed payments stream

Kestrel Payments operates the outbound and inbound payment rails for the group's UK and
euro-area entities. Rather than a daily file, Kestrel publishes executed payments as
newline-delimited JSON, with one object per line, batched every thirty minutes into
`payments_<YYYYMMDD>T<HHMM>.jsonl`. A batch contains everything that reached a final
executed state since the previous batch. Batches are never amended; a failed or returned
payment shows up later as a separate object with its own id.

Each line is a flat JSON object. `amount` is a JSON number, always positive, and the
direction of cash is given by `direction`, which is `DEBIT` when money leaves the debtor
account and `CREDIT` when it arrives. `execution_date` is a UTC timestamp in
`YYYY-MM-DDTHH:MM:SSZ` form and only the date component is meaningful to us. `scheme`
(FPS, CHAPS, SEPA, SWIFT) is informational and not part of the canonical output.
Beneficiary names and remittance information are as keyed by the initiating entity, so
punctuation and casing vary.

Contact is the Kestrel integration team (integrations, tenant KP-GRP-0930). They expose
a replay endpoint for any batch within the last 30 days; requests must quote the batch
file name.

```yaml feed-contract
client: kestrel-payments
feed_name: executed_payments
format: jsonl
encoding: utf-8
header_rows: 0
trailer_rows: 0
schedule_cron: "*/30 * * * *"
expected_row_count: 16
columns:
  - {source: "payment_id", target: trade_id, dtype: str}
  - {source: "debtor_account", target: account_id, dtype: str}
  - {source: "execution_date", target: value_date, dtype: date, date_format: "%Y-%m-%dT%H:%M:%SZ"}
  - {source: "amount", target: amount, dtype: decimal, sign_column: "direction", negative_marker: "DEBIT"}
  - {source: "direction", target: null, dtype: str}
  - {source: "currency", target: currency, dtype: str}
  - {source: "beneficiary_name", target: counterparty, dtype: str}
  - {source: "remittance_info", target: description, dtype: str}
  - {source: "scheme", target: null, dtype: str}
quirks:
  - "One JSON object per line; amount is an unsigned JSON number."
  - "direction = DEBIT means the amount must be negated; CREDIT stays positive."
  - "execution_date is a UTC timestamp; only the date part is kept."
  - "scheme and direction are dropped from the canonical output."
```
