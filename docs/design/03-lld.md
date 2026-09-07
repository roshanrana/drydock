# 03 — Low-level design

Interfaces in this document are **frozen contracts**. Parallel task agents code against
them without talking to each other. A change here is a plan change (update this file,
list affected task packs, record in decisions.md).

## 1. Repository layout

```
drydock/
  __init__.py
  models.py                 # frozen contracts (exists)
  errors.py                 # error taxonomy §8
  corpus.py                 # T-001
  events.py                 # append-only JSONL event writer (T-005)
  cli.py                    # T-005 (+ serve/mcp/bench subcommands added by T-006/T-007/T-009)
  bench.py                  # T-009
  harness/                  # T-002
    __init__.py             # evaluate()
    sandbox.py              # run_in_sandbox()
    runner.py               # sandbox entrypoint (stdlib only!)
    checks.py               # H1..H6
    airflow_shim/airflow/   # stub package: __init__.py, operators/python.py
  providers/                # T-003
    __init__.py             # Provider protocol, load_provider()
    fake.py                 # FakeProvider
    templates.py            # render_pipeline/render_dag/render_mapping
    llm.py                  # LLMProvider (prompting + JSON parsing)
    backends.py             # ChatBackend protocol + OpenAICompatBackend, BedrockBackend, AnthropicBackend
    prompts.py              # system/user prompt templates
  mcp/
    __init__.py
    sources_server.py       # T-004
    toolbox.py              # T-004
    server.py               # T-007
  graph/                    # T-005
    __init__.py
    state.py                # GraphState helpers, node names
    nodes.py                # node functions
    build.py                # build_graph(checkpointer, deps) -> CompiledGraph
    store.py                # RunStore (SQLite)
    service.py              # start_run / decide / get_run / list_runs / history
  dashboard/                # T-006
    __init__.py
    app.py                  # create_app(store, service) -> FastAPI
    static/index.html
corpus/                     # T-001
  README.md
  <client>/spec.md, samples/*, manifest.json
  _adversarial/<name>/{pipeline.py, dag.py, mapping.yaml, expect.json}
configs/providers/{fake,ollama,vllm,bedrock,anthropic}.yaml   # T-003
tests/                      # one file per module, fixtures under tests/fixtures/
metrics/{render.py,card.json,headline.json}
docs/{design/,tasks/,serving.md,runbook.md,ship-report.md,assets/}
scripts/check.py
docker-compose.yml          # T-010 (airflow profile)
```

Repository root is resolved once: `drydock.paths.ROOT = Path(__file__).resolve().parent.parent`
(create `drydock/paths.py` in T-001 with `ROOT`, `CORPUS_DIR`, `RUNS_DIR`, `DEPLOY_DIR`,
`DATA_DIR`, `DB_PATH`; every module imports paths from there; tests override via
`monkeypatch` or by passing explicit paths).

## 2. Corpus format (T-001)

### 2.1 `corpus/<client>/spec.md`

Markdown prose describing the feed, containing exactly one fenced block:

    ```yaml feed-contract
    client: acme-treasury
    feed_name: daily_cash
    format: csv
    delimiter: ","
    header_rows: 1
    trailer_rows: 0
    schedule_cron: "0 6 * * 1-5"
    expected_row_count: 12
    columns:
      - {source: "TradeRef", target: trade_id, dtype: str}
      - {source: "Acct", target: account_id, dtype: str}
      - {source: "ValueDate", target: value_date, dtype: date, date_format: "%Y-%m-%d"}
      - {source: "Amount", target: amount, dtype: decimal}
      - {source: "Ccy", target: currency, dtype: str}
      - {source: "Cpty", target: counterparty, dtype: str}
      - {source: "Narrative", target: description, dtype: str}
    quirks:
      - "Amounts arrive with thousands separators."
    ```

`corpus.load_spec(client) -> FeedSpec` extracts that block and validates it. Prose quirks
outside the block are **not** parsed; the `quirks` list inside the block is what the
planner receives.

Fixed-width columns use `source: "0:12"` (half-open slice). JSONL uses the key name.

### 2.2 `corpus/<client>/manifest.json`

```json
{
  "client": "acme-treasury",
  "samples": [ { "name": "daily_cash_2026-09-01.csv", "sha256": "...", "bytes": 1234,
                 "expected_rows": 12, "amount_sum": "-1523.40",
                 "null_rate": {"counterparty": 0.0}, "distinct": {"currency": 2} } ],
  "scenario": { "injected_defect": null | "<defect-id>",
                "expected_outcome": "pass" | "heal" | "escalate",
                "notes": "why this scenario exists" }
}
```

Defect ids (frozen): `date_format_swapped`, `trailer_not_skipped`, `wrong_slice`,
`amount_sign_dropped`, `thousands_separator_kept`, `dag_missing_dependency`. The escalate
scenario has `injected_defect: null` and a spec whose `expected_row_count` disagrees with
the sample by design. `manifest.expected_rows` is the spec's `expected_row_count` when declared
(the client's assertion), otherwise the observed count, so the escalate scenario fails H3 forever.

### 2.3 Clients (six) and adversarial set (five)

| client | format | defect | outcome |
|---|---|---|---|
| acme-treasury | csv, thousands separators | none | pass |
| northwind-custody | csv, DR/CR sign column, `%d/%m/%Y` | date_format_swapped | heal |
| blue-harbour-fx | pipe csv, 1 trailer row | trailer_not_skipped | heal |
| orion-prime | fixed_width | wrong_slice | heal |
| kestrel-payments | jsonl, sign column | amount_sign_dropped | heal |
| meridian-legacy | csv; spec says 15 rows, sample has 14 | none (spec wrong) | escalate |

Adversarial (evaluated against `acme-treasury` samples), `expect.json` lists checks that
must fail: `drops_last_row` (H3), `wrong_amount_format` (H2), `slow_network_import` (H1: the
static guard rejects `socket` before execution, so its sleep is never observed),
`sleeps_past_budget` (H5: correct output, 6 s per sample), `dag_missing_dependency` (H6).

Every sample is 10–20 rows. Amount sums are exact decimals. Manifests are regenerated by
`python -m drydock.corpus --rebuild-manifests` and CI fails if `corpus.verify_all()` fails.

### 2.4 `corpus.py` API

```python
class Scenario(Frozen): injected_defect: str | None; expected_outcome: Literal["pass","heal","escalate"]; notes: str = ""
class Manifest(Frozen): client: str; samples: tuple[SampleProfile, ...]; scenario: Scenario
class AdversarialCase(Frozen): name: str; against_client: str; artifact: PipelineArtifact; must_fail: tuple[CheckId, ...]

def list_clients(root: Path = CORPUS_DIR) -> list[str]
def load_spec(client: str, root: Path = CORPUS_DIR) -> FeedSpec
def load_manifest(client: str, root: Path = CORPUS_DIR) -> Manifest
def samples_dir(client: str, root: Path = CORPUS_DIR) -> Path
def list_samples(client: str, root: Path = CORPUS_DIR) -> list[Path]
def verify_manifest(client: str, root: Path = CORPUS_DIR) -> None          # raises CorpusError on sha/bytes mismatch
def verify_all(root: Path = CORPUS_DIR) -> None
def list_adversarial(root: Path = CORPUS_DIR) -> list[AdversarialCase]
def profile_rows(rows: list[dict[str, str]]) -> dict[str, Any]               # {"rows": n, "amount_sum": "...", "null_rate": {...}, "distinct": {...}}
def reference_transform(spec: FeedSpec, path: Path) -> list[dict[str, str]]  # spec-driven reference parser used to build manifests
```

`reference_transform` is the corpus author's oracle; it is *not* used by the harness at
run time (the manifest is), so the generator cannot pass by calling it.

## 3. Contracts

See `drydock/models.py`. Additional frozen rules:

- `pipeline.py` must define `extract(path: str) -> list[dict[str, str]]` and
  `transform(rows: list[dict[str, str]]) -> list[dict[str, str]]`, stdlib only, no network,
  no file writes. `load()` may exist but is never called by the harness.
- `transform` output rows have exactly `CANONICAL_COLUMNS` as keys, in order; `value_date`
  is `YYYY-MM-DD`; `amount` matches `^-?\d+\.\d{2}$`; `currency` matches `^[A-Z]{3}$`.
- `dag.py` may import only `from airflow import DAG`, `from airflow.operators.python import
  PythonOperator`, `datetime`, and `pipeline`. It must declare `dag_id = "<client>__<feed>"`,
  `schedule=<spec.schedule_cron>`, tasks with ids `extract`, `transform`, `load`, and edges
  `extract >> transform >> load`.
- `mapping.yaml` shape: `client`, `feed`, `format`, `fields: [{source, target, dtype, transform?}]`.

## 4. Harness (T-002)

```python
# drydock/harness/__init__.py
def evaluate(artifact: PipelineArtifact, spec: FeedSpec, manifest: Manifest, samples: list[Path], *,
             iteration: int, sandbox: Literal["subprocess","docker"] = "subprocess",
             timeout_s: float = 30.0, latency_budget_ms: int = 5000,
             drift_tolerance: float = 0.05, workdir: Path | None = None) -> HarnessReport

# drydock/harness/sandbox.py
class SandboxResult(Frozen): exit_code: int; stdout: str; stderr: str; wall_ms: int; timed_out: bool
def run_in_sandbox(workdir: Path, argv: list[str], *, timeout_s: float, kind: Literal["subprocess","docker"]) -> SandboxResult
```

Procedure per sample: write `pipeline.py`, `dag.py`, copy sample, copy `runner.py` and the
`airflow_shim` into `workdir`; run `python -I runner.py pipeline.py <sample> out.json dag.py
dag_out.json`; parent reads `out.json` (rows) and `dag_out.json` (`{"dag_id","schedule",
"tasks":[...],"edges":[["extract","transform"],...]}`) and applies checks:

| Check | Fails when |
|---|---|
| H1 runtime | non-zero exit, timeout, missing `out.json`, or stderr contains a traceback |
| H2 schema | any row's keys ≠ CANONICAL_COLUMNS, or any regex/format rule in §3 violated (evidence: first 3 offending rows) |
| H3 completeness | `len(rows) != manifest.sample.expected_rows` (evidence: expected, actual) |
| H4 drift | `abs(sum(amount) - amount_sum) > 0.005` or any `null_rate` differs by > tolerance or `distinct` differs |
| H5 latency | sample wall time > `latency_budget_ms` (warning if > 50 % of budget) |
| H6 dag_contract | dag_id/schedule/tasks/edges differ from §3, or dag import fails, or forbidden import found by AST scan of `dag.py` |

`runner.py` imports the pipeline via `importlib`, calls `extract` then `transform`, writes
JSON, then imports `dag.py` under the shim and dumps the recorded structure. Static
guard before execution: AST scan of `pipeline.py` rejects imports outside an allowlist
(`csv, json, decimal, datetime, re, io, os.path, pathlib, typing, dataclasses, collections,
itertools, functools, math, string, time`) and any `open(..., "w")`. A violation is an H1 error
with `evidence.forbidden_import`.

Docker kind: `docker run --rm --network none -v <workdir>:/work -w /work python:3.12-slim
python -I runner.py ...`; skipped (test marked) when the docker binary is absent.

## 5. Providers (T-003)

```python
class ToolBox(Protocol):
    calls: list[str]
    def call(self, name: str, /, **arguments: Any) -> dict[str, Any]: ...   # positional-only: peek_sample/profile_sample take their own `name`

class Provider(Protocol):
    name: str
    def plan(self, spec: FeedSpec, tools: ToolBox) -> IngestionPlan: ...
    def generate(self, plan: IngestionPlan, spec: FeedSpec, *, iteration: int, seed: int,
                 previous: PipelineArtifact | None, report: HarnessReport | None) -> PipelineArtifact: ...

def load_provider(name: str, *, fault_plan: Mapping[str, str | None] | None = None,
                  config_dir: Path = ROOT / "configs" / "providers") -> Provider
```

`FakeProvider(fault_plan)`:
- `plan`: calls `tools.call("list_samples", client=...)`, `tools.call("peek_sample", ...)`,
  `tools.call("profile_sample", ...)` for evidence, then maps spec → plan deterministically
  (`parse_options` carries delimiter/header_rows/trailer_rows/encoding; `column_map = spec.columns`).
- `generate`: `templates.render_*` from the plan; if `iteration == 1` and
  `fault_plan.get(plan.client)` is a defect id, apply that defect to the rendered code
  (`templates.inject_defect(pipeline_py, dag_py, defect_id) -> tuple[str, str]`). If
  `iteration > 1` render clean code and put a one-line repair note referencing
  `report.errors[0].check` in `notes`.

`LLMProvider(backend: ChatBackend, name: str)`:
- `plan`: calls the same three tools, then prompts for an `IngestionPlan` JSON (schema from
  `IngestionPlan.model_json_schema()`), validates, retries once on validation error.
- `generate`: prompt includes plan, §3 contract, the clean template output as a worked
  example, and (on repair) the previous artifact plus `report.errors`. Parses a JSON object
  `{"pipeline_py","dag_py","mapping_yaml","notes"}`; strips code fences; validates.
- Records `{"prompt_tokens","completion_tokens","model","latency_ms"}` per call via an
  optional `on_usage` callback (the graph wires it to the events file).

```python
class ChatBackend(Protocol):
    model: str
    def complete(self, system: str, user: str, *, temperature: float = 0.0, max_tokens: int = 4096) -> ChatResult
class ChatResult(Frozen): text: str; prompt_tokens: int; completion_tokens: int; latency_ms: int
```

Config yaml: `backend: fake|openai_compat|bedrock|anthropic`, `model`, `base_url`
(openai_compat), `api_key_env` (name of env var, default `OPENAI_API_KEY`), `region`
(bedrock). Secrets are never in yaml. `load_provider` raises `ProviderError` with a clear
message when an optional dependency or env var is missing.

## 6. MCP (T-004, T-007)

### 6.1 Sources server — `drydock/mcp/sources_server.py`

```python
def build_server(corpus_root: Path = CORPUS_DIR) -> MCPServer      # name "drydock-sources"
# tools (all return JSON-serialisable dicts; errors -> {"error": "..."} not exceptions):
list_clients() -> {"clients": [str]}
read_spec(client: str) -> {"client", "markdown": str, "contract": FeedSpec.model_dump()}
list_samples(client: str) -> {"samples": [{"name","bytes","sha256"}]}
peek_sample(client: str, name: str, rows: int = 5) -> {"name","lines": [str]}    # rows capped at 5 (NFR-5)
profile_sample(client: str, name: str) -> SampleProfile.model_dump()
def main() -> None   # python -m drydock.mcp.sources_server  (stdio)
```

### 6.2 Toolbox — `drydock/mcp/toolbox.py`

```python
class McpToolBox:  # implements ToolBox
    def __init__(self, server: MCPServer | StdioServerParameters): ...   # in-memory or stdio
    calls: list[str]
    def call(self, name: str, **arguments) -> dict[str, Any]           # sync; uses result.structured_content, falls back to json.loads(content[0].text)
    def close(self) -> None
    # context manager support
```
Implementation: a background thread owns an asyncio loop and a persistent `mcp.client.Client`
session; `call` uses `asyncio.run_coroutine_threadsafe(...).result(timeout)`.

### 6.3 DRYDOCK server — `drydock/mcp/server.py`

```python
def build_server(service: RunService) -> MCPServer   # name "drydock"
build_pipeline(client: str, provider: str = "fake", max_iterations: int = 3) -> RunRecord dict
list_runs(limit: int = 20) -> {"runs": [...]}
get_run(run_id: str) -> {"run": RunRecord, "iterations": [{"iteration","passed","errors":[...]}]}
get_iteration(run_id: str, iteration: int) -> {"artifact": {...}, "report": {...}}
approve_run(run_id: str, approver: str, note: str = "") -> RunRecord dict
reject_run(run_id: str, approver: str, note: str) -> RunRecord dict
def main() -> None   # `drydock mcp` / python -m drydock.mcp.server
```

## 7. Graph, store, service (T-005)

### 7.1 Nodes and edges (`graph/build.py`)

```
START → load_spec → plan → generate → evaluate → [route]
  route: report.passed → await_approval
         not passed and iteration < max_iterations → generate
         otherwise → escalate → END
await_approval: decision = interrupt({"run_id", "client", "iteration", "summary"})   # {"decision": "approve"|"reject", "approver", "note"}
  → publish (approve) → END
  → record_rejection (reject) → END
```

State: `GraphState` (Pydantic). Node functions take `GraphState` and return `dict` partials.
Dependencies injected via a `Deps` dataclass: `provider`, `toolbox`, `store`, `events`,
`sandbox`, `paths`. `build_graph(deps, checkpointer) -> CompiledStateGraph`.
Checkpointer: `SqliteSaver(sqlite3.connect(DB_PATH, check_same_thread=False))`.
`thread_id = run_id`. `run_id = f"{client}-{YYYYmmddHHMMSS}-{6 hex}"` (seeded hex when `seed != 0`
for bench determinism: `hashlib.sha256(f"{client}:{seed}").hexdigest()[:6]` and a fixed
timestamp `00000000000000`).

Each node: writes an event, persists artifact/report via `store`, updates `status`.
`generate` increments `iteration`. `evaluate` appends `report` to `history`.
`publish` writes `deploy/<client>/*` + `approval.json`; `record_rejection` only updates store.

### 7.2 Store (`graph/store.py`)

```python
class RunStore:
    def __init__(self, db_path: Path = DB_PATH, runs_dir: Path = RUNS_DIR): ...   # creates tables
    def create(self, record: RunRecord) -> None
    def update(self, run_id: str, **fields) -> RunRecord                       # returns new record (immutability at the API)
    def get(self, run_id: str) -> RunRecord                                     # RunNotFound
    def list(self, limit: int = 50) -> list[RunRecord]
    def save_iteration(self, run_id: str, artifact: PipelineArtifact, report: HarnessReport | None) -> Path   # runs/<id>/iter-N/, writes files + report.json
    def list_iterations(self, run_id: str) -> list[dict[str, Any]]              # [{"iteration","passed","errors":[Finding...],"wall_ms"}]
    def load_iteration(self, run_id: str, iteration: int) -> tuple[PipelineArtifact, HarnessReport | None]
    def diff(self, run_id: str, iteration: int, file: Literal["pipeline.py","dag.py","mapping.yaml"]) -> str   # unified diff vs iteration-1 ("" for iteration 1)
```
DDL: `runs(run_id TEXT PK, client, provider, status, iterations INT, max_iterations INT,
created_at, updated_at, approved_by, decision_note, final_passed INT, artifact_dir)`;
`iterations(run_id, iteration, passed INT, wall_ms INT, report_json, PRIMARY KEY(run_id, iteration))`.

### 7.3 Service (`graph/service.py`)

```python
class RunService:
    def __init__(self, *, store: RunStore, db_path: Path = DB_PATH, corpus_root: Path = CORPUS_DIR,
                 deploy_dir: Path = DEPLOY_DIR, sandbox: str = "subprocess"): ...
    def start_run(self, client: str, provider: str = "fake", *, seed: int = 0, max_iterations: int = 3) -> RunRecord
    def decide(self, run_id: str, decision: Literal["approve","reject"], approver: str, note: str = "") -> RunRecord   # InvalidTransition unless AWAITING_APPROVAL
    def get_run(self, run_id: str) -> RunRecord
    def list_runs(self, limit: int = 50) -> list[RunRecord]
    def history(self, run_id: str) -> list[dict[str, Any]]    # from graph.get_state_history: [{"step","node","status","iteration","checkpoint_id","created_at"}]
    def state_at(self, run_id: str, step: int) -> dict[str, Any]   # GraphState dump at that checkpoint
```

### 7.4 CLI (`cli.py`, Typer app named `app`)

`build CLIENT [--provider fake] [--seed 0] [--max-iterations 3] [--sandbox subprocess]`,
`runs [--limit]`, `show RUN_ID`, `approve RUN_ID [--approver] [--note]`, `reject RUN_ID --note`,
`replay RUN_ID [--step N]`, `serve [--port 8787]` (T-006), `mcp` (T-007), `bench [--out]` (T-009),
`corpus verify|rebuild-manifests` (T-001). Output is plain text tables; `--json` flag on
`runs`/`show` prints JSON.

## 8. Error taxonomy (`drydock/errors.py`, T-001 creates it)

```python
class DrydockError(Exception): ...


class CorpusError(DrydockError): ...


class ProviderError(DrydockError): ...


class SandboxError(DrydockError): ...


class SandboxTimeout(SandboxError): ...


class RunNotFound(DrydockError): ...


class InvalidTransition(DrydockError): ...
```
CLI maps `DrydockError` → exit 2 with the message; unexpected → exit 1 with traceback.

## 9. Dashboard (T-006)

`create_app(service: RunService) -> FastAPI`. Routes: `GET /api/runs`, `GET /api/runs/{id}`
(record + iterations), `GET /api/runs/{id}/iterations/{n}` (artifact + report),
`GET /api/runs/{id}/diff/{n}?file=pipeline.py`, `GET /api/runs/{id}/history`,
`POST /api/runs/{id}/decision {decision, approver, note}`, `GET /` serves
`static/index.html`. UI: left pane run list with status badges; right pane iteration
timeline (H1–H6 chips green/red), findings table, tabbed code view with diff, checkpoint
history list, approve/reject form when `awaiting_approval`. No build step, no CDN.

## 10. Bench and metrics (T-009)

`drydock bench [--out metrics/headline.json] [--db <tmp>]`: fresh temp DB and runs dir;
for each client run `start_run(client, "fake", seed=42)`; for `awaiting_approval` runs
call `decide(..., "approve", "bench")`; for each adversarial case call `harness.evaluate`
directly. KPIs: `scenarios` ("6 / 6 outcomes as declared"), `first_pass_rate`,
`healed_rate` ("4 of 4 heal scenarios repaired within 3 iterations"), `adversarial_rejected`
("4 / 4"), `mean_iterations`, `checkpoints` (total checkpoints written). Bars: defects
caught per check H1–H6. Facts: MCP tool calls made, escalations, artifacts published,
sandbox kind, live-provider rows marked pending. Must be byte-stable across runs
(no timestamps, no wall-clock ms in headline; wall time reported as a bucket, e.g. "< 5 s").

## 11. Test strategy

| Component | Tests |
|---|---|
| corpus | manifests verify; spec parse for all six; adversarial load; profile_rows exactness |
| harness | good fixture passes all six; one fixture per check fails exactly that check; forbidden import blocked; timeout → H1; docker test skipped without docker |
| providers | fake plan records 3 tool calls; every defect id changes the code and is repaired on iteration 2; LLMProvider parses fenced JSON, retries once, raises ProviderError; backends unit-tested with a fake transport (no network) |
| mcp | sources tools over in-memory Client; peek capped at 5; toolbox sync facade; drydock server tools against a stub service |
| graph | happy path reaches interrupt; approve publishes; reject does not; heal scenario takes 2 iterations; escalate after 3; resume in a fresh process (second `RunService` instance on same DB) |
| dashboard | TestClient over seeded store; decision endpoint transitions |
| bench | produces headline with all KPI keys in card order; deterministic twice |

Coverage target 80 % on `drydock/` (airflow shim excluded).
