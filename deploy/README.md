# deploy/ — approved pipelines

This directory holds the pipelines a human has approved. It is the end of the DRYDOCK
graph, not the start of a deployment: **DRYDOCK writes here and stops.** Nothing under
`deploy/` is uploaded, scheduled, or shipped anywhere by DRYDOCK itself. Handing these
files to a real orchestrator is a deliberate, separate act by a person (the opt-in Airflow
profile below is the one way this repository lets you rehearse that act, locally).

## Who writes here

Only the graph's `publish` node (`drydock/graph`, T-005), and only after a run has passed
the harness and a named person has approved it:

```
uv run drydock build acme-treasury                       # ... -> awaiting_approval
uv run drydock approve <run_id> --approver <your name>   # resumes the checkpoint -> publish
```

`reject` writes nothing here; the artifacts of a rejected or escalated run stay under
`runs/<run_id>/`. There is no other code path into this directory. Everything except this
README and `.gitkeep` is ignored by git (`.gitignore`), so what you see here is local state.

## What lands here

```
deploy/
  <client>/
    pipeline.py      stdlib-only extract()/transform()/load() for the client's feed
    dag.py           Airflow DAG: three PythonOperators, extract >> transform >> load
    mapping.yaml     Harbormaster-compatible field mapping (client, feed, format, fields)
    approval.json    who approved what, when, and the hashes of the three files above
```

`<client>` is the corpus client id (`acme-treasury`, `northwind-custody`, ...). Publishing
the same client again overwrites the directory; the run history stays in `runs/` and the
SQLite store.

### `approval.json`

Written by the `publish` node (`drydock/graph/nodes.py`; contract in
`docs/tasks/T-005-graph.md`, acceptance item 5). Fields:

| Field | Meaning |
|---|---|
| `run_id` | The run that produced the files (`<client>-<timestamp>-<hex>`); look it up with `drydock show`. |
| `client` | Corpus client id; equals the directory name. |
| `approver` | The `--approver` value given to `drydock approve`. |
| `note` | Free-text `--note`, may be empty. |
| `approved_at` | UTC ISO-8601 timestamp (`+00:00` offset) taken when `publish` ran, i.e. moments after the decision. |
| `iteration` | Which generate/evaluate iteration passed and was approved. |
| `sha256` | SHA-256 hex digest of each published file, keyed by file name. An audit trail for detecting accidental drift, not a cryptographic signature: anyone with write access to this directory could rewrite both file and digest. |

Example (values invented; the shape is what `publish` writes):

```json
{
  "run_id": "acme-treasury-20260907173000-a1b2c3",
  "client": "acme-treasury",
  "approver": "r.rana",
  "note": "row count matches the client's asserted 12",
  "approved_at": "2026-09-07T17:31:04.512873+00:00",
  "iteration": 1,
  "sha256": {
    "pipeline.py": "…64 hex…",
    "dag.py": "…64 hex…",
    "mapping.yaml": "…64 hex…"
  }
}
```

To confirm nothing was edited after approval, re-hash the files and compare:

```
uv run python -c "import hashlib,pathlib,sys; p=pathlib.Path('deploy/acme-treasury'); [print(hashlib.sha256((p/f).read_bytes()).hexdigest(), f) for f in ('pipeline.py','dag.py','mapping.yaml')]"
```

## Running the DAGs in real Airflow (opt-in)

The harness validates `dag.py` against a stub `airflow` package that records the declared
structure (ADR-004). To see the same file load in a real scheduler, `docker-compose.yml` at
the repository root defines an `airflow` service behind the `airflow` profile. Nothing in
the offline gate (`scripts/check.py`) uses it.

```
docker compose --profile airflow up                       # first run pulls ~1 GB
# UI: http://localhost:8080  user: admin
# password: docker compose --profile airflow exec airflow cat standalone_admin_password.txt
docker compose --profile airflow down
```

What the service does:

- image `apache/airflow:2.10.5-python3.12`, `command: standalone` (webserver + scheduler +
  SQLite metadata DB + SequentialExecutor in one container), `LOAD_EXAMPLES=false`;
- mounts `./deploy` read-only at `/opt/airflow/dags`;
- sets `AIRFLOW__CORE__DAGS_FOLDER=/opt/airflow/dags/<client>`, defaulting to
  `acme-treasury`. Pick another published client with an environment variable:

```
DRYDOCK_CLIENT=northwind-custody docker compose --profile airflow up        # bash
$env:DRYDOCK_CLIENT = "northwind-custody"; docker compose --profile airflow up   # PowerShell
```

### Why one client at a time

Each generated `dag.py` does a bare `import pipeline` and expects its sibling
`pipeline.py`. Airflow adds `DAGS_FOLDER` itself to `sys.path` but not its subdirectories,
so pointing the folder at `deploy/` would leave every `deploy/<client>/dag.py` unable to
import its own `pipeline.py`. Putting several client directories on `sys.path` instead
would not help either: every client's module is called `pipeline`, so within one parser
process all DAGs would silently bind to whichever `pipeline.py` came first. Pointing
`DAGS_FOLDER` at a single client directory is the smallest arrangement that is correct
without changing the generated code. Running several clients side by side in one Airflow
would need each DAG to add its own directory to `sys.path` (a template change, out of
scope here) or a per-client package layout; that limitation is recorded, not papered over.

### Verifying that a DAG parsed

With the service up (replace the DAG id with `<client>__<feed_name>` from your `dag.py`):

```
docker compose --profile airflow exec airflow airflow dags list-import-errors   # expect none
docker compose --profile airflow exec airflow airflow dags list                 # acme-treasury__daily_cash
docker compose --profile airflow exec airflow airflow tasks list acme-treasury__daily_cash --tree
```

The tree should show `extract` > `transform` > `load`. Or run the headless check, which
does the same in a throwaway container and starts no server:

```
scripts/airflow_smoke.sh                 # acme-treasury
scripts/airflow_smoke.sh northwind-custody
```

Parsing is as far as the rehearsal goes: the DAG reads
`/data/inbound/<client>/<feed>/{{ ds }}.<ext>`, and no such feed drop exists in this
repository, so a triggered run would fail at `extract` on a missing file. That is expected
and is not a DRYDOCK finding; the harness has already executed `extract()` and
`transform()` against the corpus samples in a sandbox, which is what the approval covers.

## What this directory is not

- Not a deployment. No CI job, no `drydock` command and no MCP tool pushes these files to
  an Airflow instance, a bucket, or a warehouse. The compose profile runs Airflow on your
  laptop against a read-only bind mount and that is all.
- Not versioned. Publish overwrites `deploy/<client>/`; use `runs/<run_id>/` and
  `drydock replay` for history.
- Not shared. `deploy/*` is git-ignored except this README and `.gitkeep`.
