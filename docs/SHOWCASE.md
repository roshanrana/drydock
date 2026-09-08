# DRYDOCK — Showcase

The feature tour, with commands and files. [OVERVIEW.md](OVERVIEW.md) has the reasoning; [runbook.md](runbook.md) is the operator's version.

## Ten minutes

```bash
uv sync --all-extras
uv run python scripts/check.py        # lint, strict types, 505 tests, bench, card drift: one gate, offline
uv run drydock build blue-harbour-fx  # a heal scenario: iteration 1 fails, iteration 2 passes, then it stops
uv run drydock runs
```

`build` exits at the approval gate with the run in `awaiting_approval`. Nothing is in `deploy/` yet.

```bash
uv run drydock show <run_id>          # both iterations, the checks each failed, the repair note
uv run drydock replay <run_id>        # every LangGraph checkpoint, oldest first
uv run drydock approve <run_id> --approver you --note "trailer fix verified"
ls deploy/blue-harbour-fx             # pipeline.py dag.py mapping.yaml approval.json
```

`approve` runs in a new process. It opens the same SQLite file, loads the checkpoint by run id, resumes the graph with the decision, and `publish` writes the artifacts.

## Twenty minutes, with the dashboard and the MCP server

```bash
uv run drydock serve                  # http://127.0.0.1:8787
```

Pick a run. The timeline shows one card per iteration with six chips, green or red; the findings table shows the evidence the generator was given; the code tabs show `pipeline.py`, `dag.py` and `mapping.yaml` with a diff against the previous iteration; the checkpoint list is the same history `replay` prints. An awaiting run shows the approve and reject form.

```bash
uv run drydock mcp                    # DRYDOCK as an MCP server over stdio
```

Register it in Claude Desktop or Cursor with the snippet in [mcp.md](mcp.md), then ask the client to build `acme-treasury`, inspect the run, and approve it. The approve tool refuses without a named approver; the reject tool refuses without a note.

## Feature tour

### 1. The graph (`drydock/graph/`)

| Look at | What it shows |
|---|---|
| `build.py` | Eight nodes, one conditional edge out of `evaluate`: approve, repair, or escalate |
| `nodes.py` | One method per node; `await_approval` calls `interrupt()` and nothing else can publish |
| `service.py` | `start_run` and `decide`; the only place `Command(resume=...)` is issued, after validation |
| `store.py` | Runs and iterations in SQLite, artifacts on disk, unified diffs between iterations |

**Why it matters:** the loop is provably bounded and resumable across processes. `tests/test_graph.py` proves the heal path takes exactly two iterations, the escalate path exactly three, and that a second service instance on the same database can decide a run the first one started.

### 2. The corpus (`corpus/`, `drydock/corpus.py`)

| Look at | What it shows |
|---|---|
| `<client>/spec.md` | Prose a client would write, plus one fenced `yaml feed-contract` block the loader parses |
| `<client>/manifest.json` | sha256, size, expected rows, amount sum and column statistics, pinned; and the scenario: which defect is injected and what outcome is expected |
| `_adversarial/*/` | Five hand-written almost-right artifacts and the check each must fail |
| `meridian-legacy/` | The spec says fifteen rows; the sample has fourteen. Correct code fails forever, and the loop must escalate |

### 3. The providers (`drydock/providers/`)

| Look at | What it shows |
|---|---|
| `templates.py` | The generated code, readable and commented, and `inject_defect` with six named defects |
| `fake.py` | The deterministic provider: three MCP evidence calls, defect on iteration 1, repair on iteration 2 |
| `llm.py`, `prompts.py` | The same contract as a prompt, JSON output validated with Pydantic, one retry with the error appended |
| `backends.py` | `openai_compat` (Ollama, vLLM), `bedrock`, `anthropic`; under 80 lines each, keys from the environment only |
| `../../configs/providers/*.yaml` | No secrets, just the name of the variable that holds one |

### 4. The harness (`drydock/harness/`, `docs/security.md`)

| Look at | What it shows |
|---|---|
| `guard.py` | Import allowlist, attribute and name denylists, forbidden calls; runs before anything executes |
| `runner.py` | Stdlib-only entry point that installs the jail (jailed `open`, capability-stripped `os`, poisoned modules, import finder) and then imports the pipeline |
| `sandbox.py` | Process group or session, tree kill on timeout, POSIX rlimits, a Windows Job Object, and a Docker mode with a read-only work mount and every capability dropped |
| `checks.py` | H1 to H6 with evidence capped so a report is readable |
| `airflow_shim/` | A stub `airflow` package that records the DAG structure at import |

`tests/test_sandbox_escapes.py` holds twenty-five payloads, each asserting the side effect did not happen and naming the layer that stopped it.

### 5. MCP in both directions (`drydock/mcp/`)

| Look at | What it shows |
|---|---|
| `sources_server.py` | What the planner is allowed to see: five tools, five-line peek cap, path traversal rejected |
| `toolbox.py` | A sync facade over a real MCP session so graph nodes can call tools; in-memory in tests, stdio in production |
| `server.py` | DRYDOCK itself as seven MCP tools; approve and reject enforce the gate before the service is called |

### 6. The bench and the card (`drydock/bench.py`, `metrics/`)

Six clients through the graph, five adversarial artifacts through the harness, in a temporary directory, with seed 42. Every KPI in `metrics/headline.json` carries a note saying how it was computed; `metrics/render.py` draws the card and the README table from it, and `scripts/check.py` fails when either drifts.

### 7. The gate (`scripts/check.py`, `.github/workflows/check.yml`)

ruff, ruff format, mypy on the host and on the Linux target, pytest with a coverage floor, the bench, the bench drift check, the card drift check. CI runs the same script and nothing else.

## Things worth noticing

- **The escalate scenario is a wrong spec, not a broken generator.** The pin is the client's asserted row count. A correct pipeline cannot invent a row, so the harness fails it three times and a person gets the contradiction. That is the behaviour a bank wants.
- **The guard was beaten before ship, and the repo says so.** The security review's payloads are committed as tests. The static guard is now one of three layers rather than the boundary.
- **The planner's evidence is on the plan.** `IngestionPlan.tool_calls` records which MCP tools were used, so a reviewer can see the model looked before it wrote.
- **The bench cannot see Docker.** Its output is byte-identical with or without a daemon, so the numbers in the README mean the same thing on every machine.
