# T-004 — Sources MCP server and sync toolbox

**Wave:** 1 · **Depends on:** T-000 · **Status:** in_progress

## Goal
The Planner never gets handed files. It asks an MCP server for what it needs, and the
server enforces the data perimeter (peek capped at 5 rows). A sync `McpToolBox` lets graph
nodes call tools over a real MCP session, in-memory in tests and stdio in production.

## Read first
- `drydock/models.py` (FeedSpec, SampleProfile)
- `docs/design/03-lld.md` §6.1, §6.2, §5 (`ToolBox` protocol shape), §2.4 (corpus API you will call: `list_clients`, `load_spec`, `list_samples`, `load_manifest`)
- `docs/design/decisions.md` ADR-003 — `mcp` 2.x API facts: `from mcp.server.mcpserver import MCPServer`; `@server.tool()`; `from mcp.client import Client`; `async with Client(server_or_StdioServerParameters) as c: await c.call_tool(name, args)`; result has `.structured_content` (dict or None) and `.content` (list with `.text`).

## Scope (only these files)
- `drydock/mcp/__init__.py`, `drydock/mcp/sources_server.py`, `drydock/mcp/toolbox.py`
- `tests/test_mcp_sources.py`
- `corpus/` is being written concurrently by T-001. **Do not depend on it in tests.** Build a temporary corpus in a pytest fixture (one client, a spec.md with a feed-contract block, one 6-row CSV sample, a manifest.json) and pass `corpus_root=tmp_path` to `build_server`. Import `drydock.corpus` lazily inside functions so this module imports even if `corpus.py` is not there yet; if it is absent when you run tests, write a minimal private fallback loader in `sources_server.py` behind `try: from drydock import corpus` and note it in Handoff for T-005 to remove.

## Acceptance criteria
1. `build_server(corpus_root)` returns an `MCPServer` named `drydock-sources` with the five tools in LLD §6.1; every tool returns a JSON-serialisable dict; errors are returned as `{"error": "..."}` (unknown client, unknown sample, path traversal attempt like `name="../x"` → rejected).
2. `peek_sample` clamps `rows` to `1..5` and returns raw lines; `profile_sample` returns the manifest's `SampleProfile` dump (does not recompute).
3. `main()` runs stdio transport (`server.run("stdio")`), invoked by `python -m drydock.mcp.sources_server`; add `if __name__ == "__main__": main()`.
4. `McpToolBox` per LLD §6.2: constructor accepts `MCPServer` or `StdioServerParameters`; background thread + event loop + persistent `Client`; `call()` is sync, returns dict, appends `name` to `calls`; `close()` idempotent; usable as context manager; a `ProviderError`-free failure mode: tool errors surface as the returned `{"error": ...}` dict, transport failures raise `RuntimeError`.
5. Tests: list_tools shows five names; each tool via in-memory `Client`; toolbox against the in-memory server records calls in order; peek cap; traversal rejection; one stdio smoke test that spawns `sys.executable -m drydock.mcp.sources_server` with `env={"DRYDOCK_CORPUS_ROOT": str(tmp_path)}` (read that env var in `main()`) and calls `list_clients` — mark it `@pytest.mark.slow` but keep it enabled.
6. `ruff`, `ruff format --check`, `mypy drydock/mcp`, `pytest tests/test_mcp_sources.py` green; coverage of the two modules ≥ 85 %.

## Validation
```
uv run ruff check drydock/mcp tests/test_mcp_sources.py && uv run ruff format --check drydock/mcp tests
uv run mypy drydock/mcp
uv run pytest tests/test_mcp_sources.py -q --cov=drydock.mcp --cov-report=term-missing
```

## Handoff notes (≤10 lines)
