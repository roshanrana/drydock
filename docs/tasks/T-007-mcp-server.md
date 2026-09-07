# T-007 — DRYDOCK MCP server

**Wave:** 2 · **Depends on:** T-004 (SDK patterns), T-005 service contract (code against LLD §7.3; integrate when it lands) · **Status:** todo

## Goal
Any MCP client (Claude Desktop, Cursor, a script) can start a build, inspect a run's
iterations and findings, and approve or reject it. This is DRYDOCK exposing itself as a tool.

## Read first
- `drydock/models.py`; `docs/design/03-lld.md` §6.3, §7.3, §8; `docs/design/decisions.md` ADR-003
- `drydock/mcp/sources_server.py` and the Handoff notes in `docs/tasks/T-004-mcp-sources.md` (SDK gotchas)
- If `drydock/graph/service.py` exists, skim its public signatures.

## Scope (only these files)
- `drydock/mcp/server.py`, `tests/test_mcp_server.py`
- `docs/mcp.md` (how to register the server in Claude Desktop / Cursor: command `uv run --project <path> drydock mcp`, a JSON config snippet, and the five-line demo transcript)
- You may edit only the `mcp` command body in `drydock/cli.py` so `drydock mcp` calls your `main()`.

## Acceptance criteria
1. `build_server(service) -> MCPServer` named `drydock` with the seven tools in LLD §6.3; each tool has a docstring an LLM would understand; return values are `model_dump(mode="json")` dicts; `RunNotFound`/`InvalidTransition`/`DrydockError` are returned as `{"error": "..."}`.
2. `approve_run`/`reject_run` require a non-empty `approver`; `reject_run` requires a non-empty `note` (return an error dict otherwise). The server never auto-approves.
3. `main()` constructs the real `RunService` with default paths and runs stdio; `python -m drydock.mcp.server` works.
4. Tests over the in-memory `Client` against a stub service (same shape as LLD §7.3): list_tools has seven names; build returns a run dict; get_run includes iterations; approve on a non-awaiting run returns an error dict; reject without note returns an error dict; one stdio smoke test spawning `sys.executable -m drydock.mcp.server` with env `DRYDOCK_DB_PATH`/`DRYDOCK_RUNS_DIR` pointing into `tmp_path` and calling `list_runs` (read those env vars in `main()` with defaults from `drydock.paths`).
5. ruff, ruff format, mypy on `drydock/mcp`, tests green; coverage of `server.py` ≥ 85 %.

## Validation
```
uv run ruff check drydock/mcp tests/test_mcp_server.py && uv run ruff format --check drydock/mcp tests
uv run mypy drydock/mcp
uv run pytest tests/test_mcp_server.py -q --cov=drydock.mcp.server --cov-report=term-missing
```

## Handoff notes (≤10 lines)
