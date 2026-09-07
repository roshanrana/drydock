# Northwind Custody — settlement confirmations

Northwind Custody Services sends a settlement confirmation file for every safekeeping
account we hold with them. The file is produced by their end-of-day batch around 02:00 UK
time and delivered by 06:30 on the following business day as
`custody_settlements_<YYYYMMDD>.csv`. One file covers the whole account family; each row is
one cash leg of a settled securities transaction, coupon, dividend or fee.

The format is comma-separated with a single header row. Dates use the UK convention
`DD/MM/YYYY`, which has caused problems before: several days in every file have a day
number above 12, so a month-first parser silently mangles roughly half the rows and
throws on the rest. Amounts are always positive and the direction is carried in the
separate `DrCr` column, where `DR` means cash left the account and `CR` means cash
arrived. Narratives quote nominal values and ISIN-style descriptions from Northwind's
static data.

Contact is the Northwind client service desk (client-services, reference our mandate
number NWC-4471). They will regenerate a file on request within the same business day
but will not alter the date format, which is fixed across all of their clients.

```yaml feed-contract
client: northwind-custody
feed_name: custody_settlements
format: csv
delimiter: ","
encoding: utf-8
header_rows: 1
trailer_rows: 0
schedule_cron: "0 7 * * 1-5"
expected_row_count: 15
columns:
  - {source: "Ref", target: trade_id, dtype: str}
  - {source: "SafekeepingAcct", target: account_id, dtype: str}
  - {source: "SettleDate", target: value_date, dtype: date, date_format: "%d/%m/%Y"}
  - {source: "Amount", target: amount, dtype: decimal, sign_column: "DrCr", negative_marker: "DR"}
  - {source: "DrCr", target: null, dtype: str}
  - {source: "Ccy", target: currency, dtype: str}
  - {source: "Counterparty", target: counterparty, dtype: str}
  - {source: "Narrative", target: description, dtype: str}
quirks:
  - "Dates are day-first (DD/MM/YYYY); many rows have a day above 12."
  - "Amounts are unsigned; DrCr = DR means the amount is a debit and must be negated."
  - "The DrCr column is not part of the canonical output."
```
