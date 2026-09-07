# Runbook

How to operate DRYDOCK on one machine: start a build, decide on it, replay it, reset it,
and what to do when a run does not end the way you expected. Commands are shown for a
POSIX shell; on Windows use PowerShell equivalents where noted. Every command runs from the
repository root.

## Prerequisites

- Python 3.12 and `uv`. `uv sync` creates `.venv` and installs the base dependencies.
- No API key, Docker or Airflow for the default provider. Docker is needed only for the
  Docker sandbox and the Airflow profile; a model backend only for a non-fake provider
  (see [`serving.md`](serving.md)).

```bash
uv sync
uv run drydock --help
```

## Where state lives

| Path | Contents | Written by | In git |
|---|---|---|---|
| `data/drydock.db` | SQLite: `runs`, `iterations`, LangGraph checkpoint tables | every run command | no |
| `runs/<run_id>/iter-N/` | `pipeline.py`, `dag.py`, `mapping.yaml`, `report.json` | `generate`, `evaluate` | no |
| `runs/<run_id>/events.jsonl` | one JSON line per node, plus token usage for real providers | every node | no |
| `deploy/<client>/` | `pipeline.py`, `dag.py`, `mapping.yaml`, `approval.json` | `publish` only, after `approve` | no |
| `corpus/` | specs, samples, pinned manifests, adversarial cases | the corpus author | yes |
| `configs/providers/` | provider yaml (no secrets) | the repository | yes |
| `metrics/headline.json` | bench output | `drydock bench` | yes |

The database and the checkpointer share one file. A run's LangGraph `thread_id` is its
`run_id`, so any process that opens `data/drydock.db` can resume any interrupted run.

Run ids look like `<client>-<YYYYmmddHHMMSS>-<6 hex>`. The bench uses a seeded hex and a
fixed zero timestamp so its ids, and therefore its output, are stable.

## Start a build

```bash
uv run drydock build acme-treasury --provider fake
```

Options: `--seed 0`, `--max-iterations 3`, `--sandbox subprocess|docker`. The command
prints the run id and ends in one of three states:

| Exit state | Meaning | Next step |
|---|---|---|
| `awaiting_approval` | All six checks passed on some iteration; the graph is interrupted | `approve` or `reject` |
| `escalated` | `max_iterations` passes all failed | Read the reports; fix the spec or the corpus; start a new build |
| `failed` | The graph raised (corpus, provider or store error) | Read the message; exit 2 known, 1 unexpected |

Clients in the corpus and the outcome each is designed to produce:

| Client | Designed outcome |
|---|---|
| `acme-treasury` | pass on iteration 1 |
| `northwind-custody` | heal (date format swapped on iteration 1) |
| `blue-harbour-fx` | heal (trailer row not skipped) |
| `orion-prime` | heal (fixed-width slice off by one) |
| `kestrel-payments` | heal (DR/CR sign dropped) |
| `meridian-legacy` | escalate (spec row count contradicts the sample) |

The `build` process exits at the interrupt. The decision can come from a different process,
a different terminal, the dashboard, or an MCP client, minutes or days later.

## Inspect a run

```bash
uv run drydock runs                     # newest first; --limit N; --json
uv run drydock show <run_id>            # record, iterations, per-check pass/fail, findings; --json
uv run drydock serve                    # http://localhost:8787, same data with diffs between iterations
```

The dashboard's right pane shows the iteration timeline with H1 to H6 chips, the findings
table, a tabbed code view with the unified diff against the previous iteration, and the
checkpoint history. When a run is `awaiting_approval` it also shows the decision form.

## Approve

```bash
uv run drydock approve <run_id> --approver <name> [--note "..."]
```

What happens: the service opens the checkpoint for `thread_id = run_id`, checks the run is
`awaiting_approval`, resumes the graph with `{"decision": "approve", "approver": ...}`,
and the `publish` node copies the passing iteration's three files to `deploy/<client>/` and
writes `approval.json` with the approver, the note and the time. The run becomes
`approved`.

`--approver` is required. There is no unattended approval path: not in the CLI, not in the
API, not in the MCP server, not in the bench (which approves as `bench`, explicitly, and
only into a temporary deploy directory).

Approving a run that is not `awaiting_approval` fails with `InvalidTransition` and exit
code 2. Nothing is written.

## Reject

```bash
uv run drydock reject <run_id> --note "reason"
```

The note is required. The graph resumes into `record_rejection`, the run becomes
`rejected`, the artifacts stay under `runs/<run_id>/` for the record, and nothing is
written to `deploy/`. A rejected run cannot be re-approved; start a new build.

## Replay

Every checkpoint of every run is kept. `replay` walks them.

```bash
uv run drydock replay <run_id>              # list steps: step, node, status, iteration, checkpoint id
uv run drydock replay <run_id> --step 4     # dump the graph state as it was after step 4
```

Use it to see what the Planner decided before the Generator ran, what findings the
Generator was handed on iteration 2, or the exact state at the interrupt. Replay is
read-only; it never re-executes a node.

## Reset

Local state is three directories and one file. Deleting them loses run history and
approvals, and nothing else; the corpus, configs and code are untouched.

POSIX:

```bash
rm -f data/drydock.db data/drydock.db-wal data/drydock.db-shm
find runs -mindepth 1 ! -name .gitkeep -exec rm -rf {} +
find deploy -mindepth 1 ! -name .gitkeep ! -name README.md -exec rm -rf {} +
```

PowerShell:

```powershell
Remove-Item -Force data\drydock.db, data\drydock.db-wal, data\drydock.db-shm -ErrorAction SilentlyContinue
Get-ChildItem runs -Exclude .gitkeep | Remove-Item -Recurse -Force
Get-ChildItem deploy -Exclude .gitkeep, README.md | Remove-Item -Recurse -Force
```

Stop `drydock serve` first; SQLite will otherwise report the database as locked or busy.

To retire one approved pipeline without touching history, delete `deploy/<client>/`. The
run stays `approved` in the store with its `approval.json` content recoverable from
`runs/<run_id>/`. That is the rollback procedure; there is no separate command for it.

## Run with the Docker sandbox

By default generated code runs in a subprocess: `python -I`, scratch working directory,
minimal environment, timeout. The Docker sandbox adds a network-less container.

```bash
uv run drydock build acme-treasury --provider fake --sandbox docker
```

Per sample the harness runs, in effect:

```
docker run --rm --network none -v <workdir>:/work -w /work python:3.12-slim \
  python -I runner.py pipeline.py <sample> out.json dag.py dag_out.json
```

Requirements: the `docker` binary on `PATH` and a running daemon. The first run pulls
`python:3.12-slim`. On Windows with Docker Desktop, the scratch directory is created under
the system temp path, which must be inside the drive shared with Docker (it is by default).
When `docker` is absent, expect the build to fail with a sandbox error rather than fall
back silently; the tests that need Docker are skipped, so the offline gate is unaffected.

The sandbox kind is recorded in each `report.json` (`"sandbox": "subprocess"` or
`"docker"`), and the bench reports which one it used.

## Run the Airflow profile

Airflow is not a dependency. The harness validates DAGs against a stub package that records
structure at import. To see a generated DAG in a real scheduler, an opt-in compose profile
runs `apache/airflow` standalone with `deploy/` mounted read-only as the DAGs folder.

```bash
uv run drydock approve <run_id> --approver <name>     # so deploy/<client>/ exists
docker compose --profile airflow up
```

The web UI is on `http://localhost:8080`; the standalone image prints the admin password to
its log on first start. To confirm the DAG parsed:

```bash
docker compose --profile airflow exec airflow airflow dags list
```

Expect `dag_id` values of the form `<client>__<feed_name>`, for example
`acme-treasury__daily_cash`. Because each `dag.py` does `import pipeline`, the client
directory must be importable inside the container; how the profile arranges that, and the
`approval.json` schema, are documented in `deploy/README.md` (written with the profile in
T-010; until then the compose file and that README are pending). Stop with
`docker compose --profile airflow down`.

The offline gate never starts this profile. Whether a generated DAG loads in real Airflow is
reported as pending on the results card until someone runs this and records the result.

## Troubleshooting

**A run reports a timeout (H1).** `report.json` shows `timed_out: true` and an H1 finding.
The sandbox timeout is 30 s per sample, and the latency budget for H5 is 5 s. Generated
code that blocks, sleeps or loops trips these; the loop treats it as a finding and the
Generator gets another iteration, or the run escalates. Read `stderr` in the report for
where it hung. The CLI does not expose the timeout; the adversarial `slow_network_import`
case is designed to trip it and is expected to be rejected.

**A run reports a forbidden import (H1).** The finding carries `evidence.forbidden_import`
with the module name. The AST scan runs before execution and allows only a stdlib
allowlist (`csv`, `json`, `decimal`, `datetime`, `re`, `io`, `os.path`, `pathlib`,
`typing`, `dataclasses`, `collections`, `itertools`, `functools`, `math`, `string`), and
rejects any `open(..., "w")`. `dag.py` is held to a stricter list: `airflow`'s `DAG` and
`PythonOperator`, `datetime`, and `pipeline`. This is the sandbox doing its job; if a real
provider keeps producing it, the fix is in the prompt or the model, not the allowlist.

**A run escalated.** Status `escalated`, three iterations under `runs/<run_id>/`, nothing in
`deploy/`. Look at the findings on the last iteration with `show`, or the diff between
iterations in the dashboard. If the same check fails three times with the same evidence,
the spec and the sample disagree and no code can pass: `meridian-legacy` is built this way,
with `expected_row_count: 15` against a fourteen-row sample. The remedy is to fix the spec
(or the sample and its manifest, via `python -m drydock.corpus --rebuild-manifests`) and
start a new build. Escalated runs cannot be approved; `approve` returns `InvalidTransition`.

**`approve` says `InvalidTransition`.** The run is not `awaiting_approval`. Check `show`;
it was already decided, or it escalated or failed. Start a new build if you need a decision.

**`ProviderError: ... OPENAI_API_KEY ...` (or another variable).** A non-fake provider was
named and its credential variable is unset, or the optional extra is not installed. The
message names the variable or the `uv sync --extra ...` to run. See
[`serving.md`](serving.md).

**`database is locked`.** Two processes hold the SQLite file with a write pending, usually
`serve` plus a CLI command mid-`build`. Wait for the build to reach the interrupt, or stop
the server. Concurrent reads are fine.

**`CorpusError` on start.** A sample's sha256 or byte count does not match its manifest.
Either the sample was edited (regenerate the manifest, deliberately) or the checkout is
damaged.

**Nothing in `deploy/` after approval.** Check `show` says `approved` and `approved_by` is
set. If the status is `approved` and the directory is missing, the publish node failed
after the status update; `runs/<run_id>/iter-N/` still has the files, and the events file
shows the `publish` outcome.

## Invariants an operator can rely on

These hold regardless of provider, sandbox kind or how the decision was delivered.

1. A run makes at most `max_iterations` generator passes (default 3). It ends as
   `awaiting_approval`, `escalated`, `approved`, `rejected` or `failed`. It cannot loop.
2. Nothing is written to `deploy/` except by `publish`, and `publish` runs only after a
   named approver resumes an `awaiting_approval` run with `approve`. No provider, flag or
   environment variable bypasses the interrupt.
3. Generated code executes only inside the sandbox: a fresh `python -I` process (or a
   network-less container), never the orchestrator. A forbidden import is refused before
   the code runs.
4. A real model provider sees the contract block, column profiles, at most five peeked
   lines per sample and, on repair, the previous artifact and findings. It never sees whole
   sample files or `deploy/`. The `fake` provider makes no network calls at all.
5. Every node writes a checkpoint and an event line. Any run can be replayed step by step
   from `data/drydock.db` and `runs/<run_id>/`, and any interrupted run can be resumed from
   any process that opens the same database.
6. `drydock bench` with the same seed writes a byte-identical `metrics/headline.json`, and
   the gate fails when the committed file or the rendered card differs from it.
