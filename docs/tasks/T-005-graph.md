# T-005 — Graph, store, service, events, CLI core

**Wave:** 2 · **Depends on:** T-001, T-002, T-003, T-004 · **Status:** done

## Goal
The loop itself: a LangGraph `StateGraph` with a SQLite checkpointer that plans, generates,
evaluates, repairs, escalates or interrupts for approval, and publishes. Plus the run store,
the service facade every surface uses, the events writer, and the CLI.

## Read first
- `drydock/models.py`; `docs/design/03-lld.md` §7 (all), §8, §1 (paths)
- Handoff notes at the bottom of `docs/tasks/T-001-corpus.md`, `T-002-harness.md`, `T-003-providers.md`, `T-004-mcp-sources.md` (how to call each API)
- Skim the public signatures only: `drydock/corpus.py`, `drydock/harness/__init__.py`, `drydock/providers/__init__.py`, `drydock/providers/fake.py`, `drydock/mcp/toolbox.py`, `drydock/mcp/sources_server.py`

## Scope (only these files)
- `drydock/graph/__init__.py`, `state.py`, `nodes.py`, `build.py`, `store.py`, `service.py`
- `drydock/events.py`, `drydock/cli.py`
- `tests/test_graph.py`, `tests/test_store.py`, `tests/test_cli.py`, `tests/conftest.py` (shared fixtures: temp DB, temp runs dir, temp deploy dir; other tests may reuse)
- You MAY consolidate duplicate error classes into `drydock/errors.py` if T-002/T-003 handoff notes say they defined local ones (update their import lines only).

## LangGraph facts (langgraph 1.2, verified)
`from langgraph.graph import StateGraph, START, END`; `from langgraph.types import interrupt, Command`;
`from langgraph.checkpoint.sqlite import SqliteSaver` — construct with `SqliteSaver(sqlite3.connect(path, check_same_thread=False))`
(context-manager `from_conn_string` also exists). `graph = StateGraph(GraphState)`; `graph.add_node("plan", plan_node)`;
`graph.add_conditional_edges("evaluate", route_fn, {"approve": "await_approval", "repair": "generate", "escalate": "escalate"})`;
`compiled = graph.compile(checkpointer=saver)`; `compiled.invoke(initial_state, config={"configurable": {"thread_id": run_id}})`
returns the state at the interrupt (check `compiled.get_state(config).next` / `.tasks[0].interrupts`);
resume with `compiled.invoke(Command(resume={"decision": "approve", ...}), config)`. `compiled.get_state_history(config)`
yields `StateSnapshot`s (newest first) with `.values`, `.next`, `.metadata["step"]`, `.config["configurable"]["checkpoint_id"]`, `.created_at`.
Pydantic state: node functions receive a `GraphState` instance and return `dict` partials.

## Integration notes from Wave 1
- `McpToolBox.call(name, /, **arguments)` is positional-only (T-004). If `drydock/providers/__init__.py` declares `ToolBox.call(self, name: str, **arguments)`, change it to `call(self, name: str, /, **arguments: Any)` so mypy accepts `McpToolBox` as a `ToolBox`; fix the fake toolbox in tests/test_providers.py the same way if needed. This is the one permitted edit outside your scope in drydock/providers.
- T-004 left a `_FallbackCorpus` shim in `drydock/mcp/sources_server.py` for when corpus.py was absent; remove it and its two `*fallback*` tests in tests/test_mcp_sources.py.

## Acceptance criteria
1. `build_graph(deps, checkpointer)` wires nodes/edges exactly per LLD §7.1. `Deps` is a frozen dataclass.
2. `RunStore` per §7.2 with the DDL given; `update()` returns a fresh `RunRecord`; `diff()` uses `difflib.unified_diff`.
3. `RunService` per §7.3. `start_run` creates the record, builds the provider via `load_provider(name, fault_plan={client: manifest.scenario.injected_defect})`, builds an in-memory `McpToolBox(sources_server.build_server(corpus_root))`, runs the graph until interrupt or END, updates the record, returns it. `decide` validates status, resumes with `Command(resume=...)`, returns the record. `history`/`state_at` per §7.3.
4. `events.py`: `EventWriter(path)` with `.emit(node: str, **fields)` appending one JSON line `{ts, node, ...}`; used by every node; `on_usage` from the provider writes `{"node": "llm_usage", ...}`.
5. `publish` writes `deploy/<client>/{pipeline.py,dag.py,mapping.yaml,approval.json}`; `approval.json` has run_id, approver, note, approved_at, iteration, sha256 of each file. `record_rejection` writes nothing under deploy/.
6. Deterministic run ids when `seed != 0` per §7.1 so bench output is stable.
7. CLI (Typer `app`): `build`, `runs`, `show`, `approve`, `reject`, `replay`, `corpus verify`, `corpus rebuild-manifests`; `--json` on `runs`/`show`; `DrydockError` → exit 2. Leave `serve`, `mcp`, `bench` as thin commands that import lazily from `drydock.dashboard.app`, `drydock.mcp.server`, `drydock.bench` and print a clear message if the module is not present yet (those land in T-006/T-007/T-009).
8. Tests (all offline, using the real corpus and the fake provider, temp DB via conftest): acme reaches `awaiting_approval` in 1 iteration with `plan.tool_calls == ("list_samples","peek_sample","profile_sample")`; approve → `approved`, deploy files exist, approval.json valid; reject → `rejected`, nothing in deploy; northwind heals in exactly 2 iterations and iteration-1 report has at least one error finding (the swapped date format crashes the parser, so it surfaces as H1) while iteration 2 passes; meridian escalates after exactly 3 iterations; cross-process resume: a second `RunService` instance on the same DB path can `decide` a run started by the first; `history` has ≥ 6 snapshots and `state_at(step)` returns the state; store diff is non-empty for iteration 2; CLI via `typer.testing.CliRunner` for build/show/approve/replay.
9. `uv run python scripts/check.py` steps 1–3 pass for the whole repo (ruff, mypy, pytest ≥ 80 % coverage). If another task's code breaks the whole-repo gate, note it in Handoff and do not fix it yourself unless it is a one-line import consolidation.

## Validation
```
uv run ruff check . && uv run ruff format --check .
uv run mypy drydock
uv run pytest -q --cov=drydock --cov-report=term-missing
uv run drydock build acme-treasury --provider fake && uv run drydock runs
```

## Handoff notes (≤10 lines)
- Validation 2026-09-07 (Windows 11, py3.12): `ruff check` + `ruff format --check` → `All checks passed!` / `69 files already formatted`; `mypy drydock` → `Success: no issues found in 32 source files`; `pytest --cov=drydock` → 455 passed (66 in test_graph/test_store/test_cli), `TOTAL 2492 stmts, 35 miss, 99%` (graph/* 99–100 %, events 100 %, cli 97 % — only the serve/mcp/bench bodies are uncovered); `drydock build acme-treasury --provider fake && drydock runs` → `awaiting_approval`, 1 iteration.
- `RunStore` / `RunService` signatures are exactly LLD §7.2/§7.3. Additions only: `close()` + context-manager support on both (close them in fixtures or Windows cannot delete the tmp DB), `RunStore.runs_dir` / `RunStore.iteration_dir(run_id, n)`, `RunService.store` (dashboard/MCP use `service.store.list_iterations/load_iteration/diff`). T-006 and T-007 already run unchanged against it.
- `history()` is oldest-first (ascending `step`) and carries an extra `next` key; step −1 is LangGraph's input checkpoint (`state_at(-1) == {}`); `state_at` of a missing step raises `DrydockError`. `history`/`state_at` build an inspection graph with `_InertToolBox` (no MCP session spawned).
- Never resume the graph with an unvalidated payload: LangGraph 1.2 persists the resume value before the node runs, so a `DrydockError` from `await_approval` on resume wedges the thread for good. `RunService.decide` validates status, decision and approver *before* `Command(resume=...)`; always go through it.
- `await_approval` re-runs from the top on resume, so its pre-interrupt side effects are guarded by a store status check; `publish` reads approver/note from the store record (GraphState has no approver field). Runs that raise inside a node are marked `FAILED` and get a `{"node": "failed"}` event, then the exception propagates.
- Per-run files: `runs/<run_id>/events.jsonl` (`EventWriter`; provider `on_usage` → `llm_usage` events) and `runs/<run_id>/iter-N/{pipeline.py,dag.py,mapping.yaml,artifact.json,report.json,sandbox/}`; `deploy/<client>/{pipeline.py,dag.py,mapping.yaml,approval.json}` on approve only.
- CLI global options `--db/--runs-dir/--deploy-dir/--corpus-root` (env `DRYDOCK_DB`, `DRYDOCK_RUNS_DIR`, `DRYDOCK_DEPLOY_DIR`, `DRYDOCK_CORPUS_ROOT`) go *before* the subcommand. Stubs: `serve` → `drydock.dashboard.app.create_app(service)` under uvicorn; `mcp` → `drydock.mcp.server.main()`; `bench` → `drydock.bench.main(out=Path)` — T-009 must expose `main(out: Path)` or adjust `cli.bench`.
- The checkpointer serde allowlists the contract types (`CHECKPOINT_TYPES` in `graph/service.py`); any new model that lands in `GraphState` must be added there or LangGraph warns now and blocks later.
- Removed T-004's `_FallbackCorpus` shim and its two `*fallback*` tests as instructed; `ToolBox.call` was already positional-only, no change needed in `drydock/providers`.
