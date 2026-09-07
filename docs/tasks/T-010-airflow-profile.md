# T-010 — Airflow compose profile and deploy README

**Wave:** 3 · **Depends on:** T-005 · **Status:** todo

## Goal
Prove the generated DAGs are real Airflow DAGs: a compose profile mounts `deploy/` as the
DAGs folder of `apache/airflow` standalone. Offline gate is unaffected (profile is opt-in).

## Read first
- `docs/design/03-lld.md` §3 (dag contract), §4 (shim), `docs/design/decisions.md` ADR-004
- One generated `dag.py` under `deploy/` (run `uv run drydock build acme-treasury` then `uv run drydock approve <run_id> --approver you` if none exists) — read it to confirm imports.

## Scope (only these files)
- `docker-compose.yml`, `deploy/README.md`, `scripts/airflow_smoke.sh` (optional helper)

## Acceptance criteria
1. `docker-compose.yml` with a service `airflow` under `profiles: ["airflow"]` using `apache/airflow:2.10.5-python3.12` (or the latest 2.x tag you can verify exists via `docker manifest inspect` if Docker is available; otherwise use 2.10.5 and say so), `command: standalone`, env `AIRFLOW__CORE__LOAD_EXAMPLES=false`, `AIRFLOW__CORE__DAGS_FOLDER=/opt/airflow/dags`, volume `./deploy:/opt/airflow/dags:ro`, port `8080:8080`. Because DAG files import `pipeline`, mount each client dir so `pipeline.py` is importable: document that the DAGs folder must include the client subdir on `sys.path` OR generate the DAG to add its own directory to `sys.path`; if the latter requires a template change, do NOT change templates: instead document the limitation and provide `scripts/airflow_smoke.sh` that copies `deploy/<client>/pipeline.py` next to the dag before starting. Pick the simplest honest approach and record it in `deploy/README.md`.
2. `docker compose --profile airflow config` validates (run it if Docker is present; otherwise state that it was not run).
3. `deploy/README.md`: what lands here, who writes it (only `publish` after approval), file list, `approval.json` schema, how to run the Airflow profile, how to verify a DAG parsed (`airflow dags list` inside the container), and that nothing here is deployed anywhere by DRYDOCK itself.
4. `.gitignore` already ignores `deploy/*` except `.gitkeep` and `README.md`; verify `git status` shows only your files.

## Validation
```
docker compose --profile airflow config   # if docker present
git status --short
```

## Handoff notes (≤10 lines)
