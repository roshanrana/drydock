# T-009 — Bench, headline.json, results card

**Wave:** 3 · **Depends on:** T-005 · **Status:** done

## Goal
One command replays the whole corpus offline and writes the numbers the README shows.
Byte-stable across runs and machines. CI fails if the committed numbers drift.

## Read first
- `docs/design/03-lld.md` §10, §2.3, §7.3; `metrics/card.json` (kpi_order is fixed: scenarios, first_pass_rate, healed_rate, adversarial_rejected, mean_iterations, checkpoints); `metrics/render.py` docstring and `validate()` (headline schema: kpis with label/value/note/accent in {teal,blue,amber,violet,red}; bars with title/rows[label,value,max,display,accent]; facts with title/rows[label,value,status in {ok,pending,blocked}])
- `C:\Code-Central\LedgerLens\metrics\headline.json` as a style example
- `drydock/graph/service.py`, `drydock/corpus.py`, `drydock/harness/__init__.py` public signatures

## Scope (only these files)
- `drydock/bench.py`, `tests/test_bench.py`, `metrics/headline.json`, `docs/assets/metrics.svg`
- `README.md` **only** the generated block between the metrics markers (via `python metrics/render.py`)
- The `bench` command body in `drydock/cli.py`

## Acceptance criteria
1. `drydock bench [--out metrics/headline.json] [--keep]` runs against a fresh temp DB, temp runs dir and temp deploy dir (never the developer's `data/`), seed 42, fake provider, `max_iterations=3`; approves every `awaiting_approval` run as `bench`; evaluates the five adversarial cases through `harness.evaluate`.
2. KPIs exactly in card order: `scenarios` "6 / 6" (outcomes matched declared `expected_outcome`), `first_pass_rate` (runs passing at iteration 1 / runs), `healed_rate` (heal scenarios repaired within budget / heal scenarios), `adversarial_rejected` "5 / 5", `mean_iterations` (2 dp), `checkpoints` (total snapshots across runs from `service.history`). Notes explain how each was measured.
3. Bars: "Defects caught by check" rows H1–H6 with counts across all iteration reports and adversarial reports (value = count, max = total error findings).
4. Facts (status ok/pending): MCP tool calls made (count, "over an in-memory MCP session"), escalations ("1 of 6: meridian-legacy, spec contradicts sample"), artifacts published ("5 clients under deploy/"), sandbox kind, generated code lines (sum over final artifacts), live provider accuracy (pending), Docker sandbox (pending unless docker present: still write pending so output is stable), Airflow real import (pending).
5. Byte-stable: no timestamps, no wall-clock ms, no absolute paths in `headline.json`. Running bench twice yields identical files (test asserts this).
6. Run `python metrics/render.py` to produce `docs/assets/metrics.svg` and the README block; `python metrics/render.py --check` then passes; `git diff --exit-code -- metrics/headline.json` passes after you commit-ready the file (the orchestrator commits).
7. `tests/test_bench.py`: bench into `tmp_path` produces headline with the six KPI keys in order, `scenarios == "6 / 6"`, `adversarial_rejected == "5 / 5"`, and determinism over two runs. Mark the test `slow` but enabled.
8. Whole-repo gate `uv run python scripts/check.py` passes end to end.

## Validation
```
uv run drydock bench && uv run python metrics/render.py && uv run python metrics/render.py --check
uv run python scripts/check.py
```

## Handoff notes (≤10 lines)
- Validation 2026-09-07 (Windows 11, py3.12): `uv run python scripts/check.py` -> ruff `All checks passed!`, ruff format clean, `mypy drydock` `Success: no issues found in 33 source files`, `pytest --cov=drydock` `473 passed`, `TOTAL 2707 stmts, 36 miss, 99%` (bench.py 100 %), `drydock bench` -> `scenarios 6 / 6, adversarial 5 / 5, checkpoints 59`, `git diff --exit-code -- metrics/headline.json` passes (file is new/untracked until the orchestrator commits, so the diff step is trivially clean this once), `metrics/render.py --check` -> `metrics card is current`, `all checks passed`.
- KPIs (all computed from run records, iteration reports and harness reports): scenarios 6 / 6, first_pass_rate 1 / 6 (acme-treasury), healed_rate 4 / 4, adversarial_rejected 5 / 5, mean_iterations 2.00, checkpoints 59 = `len(service.history(run_id))` summed over the 6 runs, i.e. every LangGraph checkpoint including each run's step -1 input checkpoint (8+10+10+11+10+10).
- Bars: 40 error-severity findings across 12 iteration reports + 5 adversarial reports (H1 2, H2 4, H3 6, H4 25, H5 2, H6 1); `max` = total. Facts: 18 MCP tool calls (3 per run from `IngestionPlan.tool_calls` at the final checkpoint), 1 escalation, 5 clients published, sandbox subprocess over 17 reports, 1689 generated lines; live provider / Docker / Airflow rows are always `pending` so Docker presence cannot change the bytes.
- `drydock.bench.main(out, *, keep=False, corpus_root, seed=42, max_iterations=3, workdir=None, echo=typer.echo) -> dict` runs in `tempfile.mkdtemp(prefix="drydock-bench-")` (or `workdir`), closes `RunService`/`RunStore`, then `shutil.rmtree` unless `keep`. `headline(BenchResult)` and `dump_headline` are pure so tests can hit edge cases without a replay.
- Deviation: `cli.bench` gained a `--keep` option (one parameter + `keep=keep` pass-through, nothing else in `cli.py`) because acceptance criterion 1 names it; revert those two lines if the CLI must stay untouched, `main(out=...)` still works.
- Byte-stability proven by `tests/test_bench.py` (two runs into `tmp_path`, bytes equal; no absolute path, `wall_ms`, `ts` or date in the file) and by identical sha256 of `metrics/headline.json` (1c6613e9...) and `docs/assets/metrics.svg` (89236577...) across three bench invocations. Bench wall time is ~16 s (sleeps_past_budget sleeps 6 s x 2 samples); the test module runs it twice, so `tests/test_bench.py` costs ~35 s of the 70 s pytest step.
- `slow_network_import` never gets a sandbox scratch dir: the static AST guard rejects `socket` before execution, so `evaluate` returns without staging; the test asserts 4 adversarial scratch dirs, not 5.
