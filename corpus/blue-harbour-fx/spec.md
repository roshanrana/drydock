# Blue Harbour FX — settlement instructions

Blue Harbour FX Brokerage confirms settled spot, forward and swap legs once a day. The
file is cut at 18:00 New York time and lands on our inbound share shortly after 23:00 UK
as `fx_settlements_<YYYYMMDD>.psv`. Every deal appears twice, once per currency leg, with
the deal number suffixed `-A` (currency sold) and `-B` (currency bought), so the row count
is always even and the two legs of a deal share a settlement date and counterparty.

The file is pipe-delimited (`|`) with one header row and one control row at the very end
of the form `TRAILER|<n>`, where `<n>` is the number of data rows in the file. The trailer
has only two fields and must be dropped before parsing; it is not a data row and must not
be counted. Settlement dates are compact `YYYYMMDD`. Amounts are signed with a leading
minus for the sold leg and have two decimals, except for JPY legs which Blue Harbour
emits with no decimal component at all.

Contact is the Blue Harbour settlements desk (settlements, quoting our counterparty code
BHF-CP-2210). Re-sends are available until 09:00 UK the next morning. Trailer count
mismatches indicate a truncated transfer and should be treated as a failed delivery.

```yaml feed-contract
client: blue-harbour-fx
feed_name: fx_settlements
format: csv
delimiter: "|"
encoding: utf-8
header_rows: 1
trailer_rows: 1
schedule_cron: "30 6 * * 1-5"
expected_row_count: 14
columns:
  - {source: "DealNo", target: trade_id, dtype: str}
  - {source: "Account", target: account_id, dtype: str}
  - {source: "SettlementDate", target: value_date, dtype: date, date_format: "%Y%m%d"}
  - {source: "Amount", target: amount, dtype: decimal}
  - {source: "Ccy", target: currency, dtype: str}
  - {source: "Counterparty", target: counterparty, dtype: str}
  - {source: "Notes", target: description, dtype: str}
quirks:
  - "Pipe-delimited; the last line is a control row TRAILER|<n> that must be skipped."
  - "Settlement dates are compact YYYYMMDD."
  - "JPY amounts arrive with no decimal places and must still be emitted with two."
```
