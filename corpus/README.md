# DRYDOCK corpus

Synthetic client feeds and adversarial pipelines that every DRYDOCK component is measured
against. Everything here is invented: the counterparties, account identifiers, narratives
and amounts do not describe any real person, company or transaction.

## Layout

```
corpus/
  README.md
  <client>/
    spec.md            prose + exactly one fenced ```yaml feed-contract block (-> FeedSpec)
    samples/*          hand-written sample files, 10-20 data rows each
    manifest.json      sha256 / bytes / rows / amount_sum pins + scenario (generated)
  _adversarial/<name>/
    pipeline.py        extract(path) -> rows, transform(rows) -> rows, load(rows)
    dag.py             Airflow DAG (DAG, PythonOperator, >>)
    mapping.yaml       Harbormaster-style field mapping
    expect.json        {"against_client": ..., "must_fail": [CheckId, ...], "notes": ...}
```

## Clients

| client | feed | format | injected defect | expected outcome |
|---|---|---|---|---|
| acme-treasury | daily_cash | csv, quoted thousands separators | none | pass |
| northwind-custody | custody_settlements | csv, `DrCr` sign column, `%d/%m/%Y` | date_format_swapped | heal |
| blue-harbour-fx | fx_settlements | pipe-delimited, `TRAILER\|14` control row | trailer_not_skipped | heal |
| orion-prime | trade_extract | fixed width, 104 chars/line | wrong_slice | heal |
| kestrel-payments | executed_payments | jsonl, `direction: DEBIT/CREDIT` | amount_sign_dropped | heal |
| meridian-legacy | gl_cash | clean csv; spec says 15 rows, sample has 14 | none (spec wrong) | escalate |

The `injected_defect` names the mistake the fake provider makes on its first iteration for
that client, so the graph is exercised on a heal loop. The escalate scenario has no defect:
the spec disagrees with the sample by design and no pipeline can satisfy it.

## Adversarial set

All four are evaluated against `acme-treasury` samples and are *almost* right.

| case | what is wrong | must fail |
|---|---|---|
| drops_last_row | `transform` returns `rows[:-1]` | H3_completeness |
| wrong_amount_format | amount emitted with thousands separators | H2_schema |
| slow_network_import | imports `socket`, sleeps 6 s in `extract` | H1_runtime, H5_latency |
| dag_missing_dependency | DAG never wires `transform >> load` | H6_dag_contract |

## Tooling

```
uv run python -m drydock.corpus --verify              # check every pin, fails CI if stale
uv run python -m drydock.corpus --rebuild-manifests   # after editing a sample or spec
```

Manifests are produced by `drydock.corpus.reference_transform` (the spec-driven oracle) and
`profile_rows`. The harness never calls the oracle at run time; it compares generated
pipelines against the pinned manifest, so a generator cannot pass by importing it.

Sample files are byte-pinned. Commit them with LF line endings and never let an editor
reformat them; a CRLF conversion changes the sha256 and `--verify` will fail.
