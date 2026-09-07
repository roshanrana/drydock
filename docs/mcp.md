# DRYDOCK as an MCP server

DRYDOCK exposes itself as a tool. Any MCP client (Claude Desktop, Cursor, Claude Code, a
script) can start a build, inspect a run's iterations and harness findings, and approve or
reject it. The server is `drydock/mcp/server.py`; it speaks stdio and wraps the same
`RunService` the CLI and dashboard use, so a run started from an MCP client shows up in
`drydock runs` and on the dashboard, and vice versa.

The human gate survives the MCP boundary. The server never approves on its own:
`approve_run` requires a named `approver`, `reject_run` requires an `approver` and a
`note`, and either decision is refused (`InvalidTransition`) unless the run is
`awaiting_approval`.

This is a different server from `drydock-sources` (`drydock/mcp/sources_server.py`), which
is the read-only corpus view the Planner queries during a build.

## Running it

```bash
uv run --project <path-to-repo> drydock mcp            # once cli.py has the `mcp` command
uv run --project <path-to-repo> python -m drydock.mcp.server   # always works
```

The process reads from stdin and writes MCP frames to stdout; run it from an MCP client,
not a terminal. Tracebacks and SDK warnings go to stderr.

| Environment variable | Default | Meaning |
|---|---|---|
| `DRYDOCK_DB_PATH` | `data/drydock.db` | SQLite store and LangGraph checkpointer |
| `DRYDOCK_RUNS_DIR` | `runs/` | Per-run artifacts `runs/<run_id>/iter-N/` |

Both directories are created on start if missing. Point them at a scratch location to run
the server against an empty state.

## Registering the server

### Claude Desktop

Edit `claude_desktop_config.json` (`%APPDATA%\Claude\` on Windows,
`~/Library/Application Support/Claude/` on macOS) and restart Claude Desktop:

```json
{
  "mcpServers": {
    "drydock": {
      "command": "uv",
      "args": ["run", "--project", "C:/Code-Central/drydock", "drydock", "mcp"]
    }
  }
}
```

### Cursor

Add the same block to `.cursor/mcp.json` in the workspace (or `~/.cursor/mcp.json` for
every workspace):

```json
{
  "mcpServers": {
    "drydock": {
      "command": "uv",
      "args": ["run", "--project", "C:/Code-Central/drydock", "drydock", "mcp"],
      "env": { "DRYDOCK_DB_PATH": "C:/Code-Central/drydock/data/drydock.db" }
    }
  }
}
```

### Claude Code

```bash
claude mcp add drydock -- uv run --project C:/Code-Central/drydock drydock mcp
```

Until `drydock/cli.py` gains the `mcp` command, replace `"drydock", "mcp"` with
`"python", "-m", "drydock.mcp.server"` in any of the snippets above.

## Tools

Every tool returns a JSON object. Expected failures are returned, not raised, as
`{"error": "<ExceptionType>: <message>"}`, for example `RunNotFound: no run 'x'` or
`InvalidTransition: acme-... is rejected, not awaiting_approval`.

| Tool | Arguments | Returns |
|---|---|---|
| `build_pipeline` | `client`, `provider="fake"`, `max_iterations=3` | `RunRecord` dict. Blocks until the run pauses at `awaiting_approval`, or ends `escalated`/`failed`. |
| `list_runs` | `limit=20` | `{"runs": [RunRecord, ...]}`, newest first |
| `get_run` | `run_id` | `{"run": RunRecord, "iterations": [{"iteration", "passed", "errors": [Finding...], "wall_ms"}]}` |
| `get_iteration` | `run_id`, `iteration` | `{"artifact": {pipeline_py, dag_py, mapping_yaml, ...}, "report": HarnessReport or null}` |
| `get_history` | `run_id` | `{"run_id", "history": [{"step", "node", "status", "iteration", "checkpoint_id", "created_at"}]}` |
| `approve_run` | `run_id`, `approver`, `note=""` | `RunRecord` with `status: approved`; publishes to `deploy/<client>/` |
| `reject_run` | `run_id`, `approver`, `note` | `RunRecord` with `status: rejected`; nothing published |

`RunRecord` fields: `run_id`, `client`, `provider`, `status`, `iterations`,
`max_iterations`, `created_at`, `updated_at`, `approved_by`, `decision_note`,
`final_passed`, `artifact_dir`. `status` is one of `planning`, `generating`, `evaluating`,
`awaiting_approval`, `approved`, `rejected`, `escalated`, `failed`.

Argument checks made by the server itself, before the service is touched:

- `approve_run`: `approver` must be non-empty after stripping whitespace.
- `reject_run`: `approver` and `note` must both be non-empty.
- `build_pipeline`: `max_iterations >= 1`; `list_runs`: `limit >= 1`.

## Demo transcript

Five turns in Claude Desktop with the server registered (tool calls abbreviated):

```
> Build the acme-treasury feed with the fake provider.
  build_pipeline(client="acme-treasury") -> {run_id: "acme-treasury-20260907101500-3f9a1c", status: "awaiting_approval", iterations: 2}
> Why did it take two iterations?
  get_run(run_id=...) -> iterations[0].errors = [{check: "H2_schema", message: "missing column currency"}]; iterations[1].passed = true
> Show me the final pipeline.
  get_iteration(run_id=..., iteration=2) -> artifact.pipeline_py (extract/transform), report.passed = true, rows_emitted = 6
> Approve it.
  approve_run(run_id=..., approver="") -> {"error": "ValueError: approver is required and must not be empty"}   # the model must name a human
> Approve it as Roshan, note "H2 fix verified".
  approve_run(run_id=..., approver="Roshan", note="H2 fix verified") -> {status: "approved", approved_by: "Roshan"}
```

## Calling it from Python

`drydock.mcp.toolbox.McpToolBox` fronts the same server synchronously, in memory or over
stdio:

```python
import sys
from mcp.client.stdio import StdioServerParameters
from drydock.mcp.toolbox import McpToolBox

params = StdioServerParameters(command=sys.executable, args=["-m", "drydock.mcp.server"])
with McpToolBox(params) as tools:
    print(tools.call("list_runs", limit=5))
```

For tests, `build_server(service)` accepts any object with the `RunService` shape
(LLD section 7.3) and a `Client(server)` from the `mcp` package talks to it without a
subprocess; see `tests/test_mcp_server.py`.
