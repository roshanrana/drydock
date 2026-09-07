# Orion Prime — fixed-width trade extract

Orion Prime Brokerage still runs its client reporting off a mainframe batch. The trade
extract is a fixed-width text file written at 04:00 UK time and pushed to our SFTP
folder as `trade_extract_<YYYYMMDD>.txt`. It lists every cash movement booked to our
prime accounts in the previous session: trade settlements, financing charges, stock loan
fees and corporate action cash. Orion re-runs the batch only on request and the re-run
overwrites the original file name.

There is no delimiter. Each line is exactly 104 characters plus the line terminator, and
the first line is a column-title banner that must be skipped. Field positions are
half-open zero-based slices: trade id `0:10`, account `10:22`, value date `22:30` as
`YYYYMMDD`, amount `30:46` right-aligned and signed, currency `46:49`, counterparty
`49:74`, description `74:104`. The amount field is the usual trap: it is right-aligned
with leading spaces and the currency code starts on the very next character, so an
off-by-one slice yields amounts ending in a letter and currencies missing their first
character. Text fields are left-aligned and space-padded.

Contact is Orion's client technology team (client-tech, mandate ORN-PB-118). Layout
changes are announced by letter with 30 days' notice and have historically been rare;
the current layout has been stable since the 2021 migration.

```yaml feed-contract
client: orion-prime
feed_name: trade_extract
format: fixed_width
encoding: utf-8
header_rows: 1
trailer_rows: 0
schedule_cron: "0 5 * * 1-5"
expected_row_count: 13
columns:
  - {source: "0:10", target: trade_id, dtype: str}
  - {source: "10:22", target: account_id, dtype: str}
  - {source: "22:30", target: value_date, dtype: date, date_format: "%Y%m%d"}
  - {source: "30:46", target: amount, dtype: decimal}
  - {source: "46:49", target: currency, dtype: str}
  - {source: "49:74", target: counterparty, dtype: str}
  - {source: "74:104", target: description, dtype: str}
quirks:
  - "Fixed width, 104 characters per line; slices are half-open and zero-based."
  - "Amount is right-aligned in 30:46 and immediately followed by the currency in 46:49."
  - "The first line is a title banner, not data."
```
