# T-009 — Bench, headline.json, results card

**Wave:** 3 · **Depends on:** T-005 · **Status:** todo

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
