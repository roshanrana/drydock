#!/usr/bin/env bash
# Headless Airflow parse check for one published client (docs/tasks/T-010).
#
# Proves that deploy/<client>/dag.py loads in real Airflow: no import errors, the DAG is
# listed, and its three tasks are chained extract >> transform >> load. Runs the CLI in a
# throwaway container from the `airflow` compose service, so no web server is started and
# nothing is left running. The first invocation pulls apache/airflow (about 1 GB).
#
#   scripts/airflow_smoke.sh                 # acme-treasury
#   scripts/airflow_smoke.sh northwind-custody
#
# Requires: Docker Desktop running, and deploy/<client>/ populated by
#   uv run drydock build <client> && uv run drydock approve <run_id> --approver <you>
#
# Not part of the offline gate (scripts/check.py); this is a manual demo helper.
set -euo pipefail

client="${1:-acme-treasury}"
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
client_dir="${root}/deploy/${client}"

if [[ ! -f "${client_dir}/dag.py" || ! -f "${client_dir}/pipeline.py" ]]; then
  echo "error: ${client_dir} has no dag.py + pipeline.py." >&2
  echo "       Publish one first: uv run drydock build ${client}; uv run drydock approve <run_id> --approver <you>" >&2
  exit 2
fi

# dag_id is "<client>__<feed_name>" (LLD section 3); read it from the generated file rather
# than guessing the feed name.
dag_id="$(sed -n 's/^ *dag_id="\([^"]*\)".*/\1/p' "${client_dir}/dag.py" | head -n 1)"
if [[ -z "${dag_id}" ]]; then
  echo "error: could not find dag_id=\"...\" in ${client_dir}/dag.py" >&2
  exit 2
fi

echo "==> client: ${client}   dag_id: ${dag_id}"
echo "==> DAGs folder inside container: /opt/airflow/dags/${client}"

# `airflow dags list` reads the paused flag from the metadata DB, so an empty SQLite DB is
# migrated first (standalone does the same on start-up). The DB lives in the container's
# writable layer and is discarded with --rm.
export DRYDOCK_CLIENT="${client}"
cd "${root}"
docker compose --profile airflow run --rm --no-deps airflow bash -c "
  set -e
  airflow db migrate >/dev/null 2>&1
  echo '==> import errors (expect none):'
  airflow dags list-import-errors
  echo '==> dags:'
  airflow dags list
  echo '==> tasks for ${dag_id} (expect extract > transform > load):'
  airflow tasks list '${dag_id}' --tree
"
echo "==> OK: ${dag_id} parsed in Airflow."
