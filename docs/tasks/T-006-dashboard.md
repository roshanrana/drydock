# T-006 — Dashboard API and trace viewer

**Wave:** 2 · **Depends on:** T-005 store/service contract (code against LLD §7.2–7.3; integrate when T-005 lands) · **Status:** done

## Goal
A reviewer opens one page and sees every run, every iteration's six checks, the findings,
the code diff between iterations, the checkpoint history, and an approve/reject form.

## Read first
- `drydock/models.py`; `docs/design/03-lld.md` §7.2, §7.3, §9
- If `drydock/graph/service.py` exists, skim its public signatures; otherwise code to the LLD and use a stub service in tests.

## Scope (only these files)
- `drydock/dashboard/__init__.py`, `drydock/dashboard/app.py`, `drydock/dashboard/static/index.html`
- `tests/test_dashboard.py`

## Acceptance criteria
1. `create_app(service) -> FastAPI` with the routes in LLD §9; JSON via Pydantic `model_dump(mode="json")`; 404 for unknown run (`RunNotFound`), 409 for `InvalidTransition`.
2. `GET /` serves `static/index.html` (read from package path with `importlib.resources` or `Path(__file__).parent`).
3. `index.html`: single file, no external requests (no CDN, no fonts), dark theme consistent with the results card palette (bg `#0f172a`, panel `#1e293b`, text `#e2e8f0`, accents teal `#2dd4bf` / amber `#fbbf24` / red `#f87171`). Left pane: run list with status badge and client; right pane: header (run id, provider, status), iteration timeline as a row of cards each with six H1–H6 chips (green pass / red fail / grey n/a), findings table for the selected iteration, tabs `pipeline.py | dag.py | mapping.yaml` showing code and a `diff vs previous` toggle rendering unified diff lines with +/- colouring, a "Checkpoints" list from `/history`, and an approve/reject form (approver, note) shown only when status is `awaiting_approval`. Auto-refresh every 5 s while any run is not terminal. Vanilla JS, `fetch`, no framework.
4. Tests with `fastapi.testclient.TestClient` against a stub `RunService` (in-memory dicts) that implements the §7.3 methods: list, get, iterations, diff, history, decision success, decision on wrong status → 409, unknown → 404, `/` returns HTML containing `DRYDOCK`.
5. `drydock serve --port 8787` (T-005 leaves a lazy hook; if `cli.py` exists, ensure `serve` calls `uvicorn.run(create_app(RunService(...)), host="127.0.0.1", port=port)` — you may edit only the `serve` function body in `drydock/cli.py`).
6. ruff, ruff format, mypy on `drydock/dashboard`, tests green; coverage of `app.py` ≥ 85 %.

## Validation
```
uv run ruff check drydock/dashboard tests/test_dashboard.py && uv run ruff format --check drydock/dashboard tests
uv run mypy drydock/dashboard
uv run pytest tests/test_dashboard.py -q --cov=drydock.dashboard --cov-report=term-missing
```

## Handoff notes (≤10 lines)
- Validation: `ruff check` All checks passed · `ruff format --check` 12 files already formatted · `mypy drydock/dashboard` Success: no issues found in 2 source files · `pytest tests/test_dashboard.py` 25 passed · coverage `app.py` 76 stmts 0 miss 100 %, TOTAL 100 %.
- Service is typed structurally (`RunServiceLike` / `RunStoreLike` Protocols in `app.py`); the real `RunService` needs no adapter. `drydock/graph/` was not read or touched.
- ORCHESTRATOR: `drydock/cli.py` did not exist, so AC 5 is not wired. `serve` body should be: `from drydock.dashboard import serve; serve(RunService(store=RunStore()), port=port)` (binds 127.0.0.1).
- Unknown iteration → 404 via `list_iterations` membership check, so the store's own behaviour for a missing iteration never leaks as a 500.
- Dict-shaped payloads (`/history`, `iterations` summaries with nested `Finding`s) are dumped via a Pydantic `TypeAdapter` in JSON mode so datetimes serialise as `...Z` like `RunRecord`.
- UI verified in-browser against the stub: run list, chips, findings, code tabs, +/- diff colouring, checkpoints, approve flow; typed form input and focus survive the 5 s refresh.
- Auto-refresh stops once every run is terminal (status line says so); the Refresh button restarts it.
