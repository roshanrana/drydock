# 04 — Execution plan

## Milestones

| M | Name | Gate |
|---|---|---|
| M0 | Walking skeleton | `scripts/check.py` steps 1–3 green on an empty package; CI workflow present |
| M1 | Foundations (corpus, harness, providers, sources MCP) | each task's tests green in isolation |
| M2 | The loop (graph, store, service, CLI) | happy/heal/escalate/reject scenarios pass end to end; cross-process resume |
| M3 | Surfaces (dashboard, DRYDOCK MCP server, docs) | dashboard TestClient green; MCP tools green |
| M4 | Evidence (bench, metrics card, Airflow profile) | `make check` fully green including drift guards |
| M5 | Ship (review, ship report, GitHub) | code review findings addressed; CI green on GitHub |

## Task table

| ID | Task | Wave | Depends on | Scope (files) |
|---|---|---|---|---|
| T-000 | Scaffold, contracts, gate, CI | 0 | — | pyproject, models.py, scripts/check.py, Makefile, .github |
| T-001 | Corpus + loader + paths + errors | 1 | T-000 | corpus/, drydock/corpus.py, drydock/paths.py, drydock/errors.py, tests/test_corpus.py |
| T-002 | Harness (sandbox, checks, airflow shim) | 1 | T-000 | drydock/harness/, tests/test_harness.py, tests/fixtures/pipelines/ |
| T-003 | Providers (fake, templates, LLM, backends, configs) | 1 | T-000 | drydock/providers/, configs/providers/, tests/test_providers.py, tests/test_backends.py |
| T-004 | Sources MCP server + toolbox | 1 | T-000 | drydock/mcp/sources_server.py, drydock/mcp/toolbox.py, drydock/mcp/__init__.py, tests/test_mcp_sources.py |
| T-005 | Graph, store, service, events, CLI core | 2 | T-001..T-004 | drydock/graph/, drydock/events.py, drydock/cli.py, tests/test_graph.py, tests/test_store.py, tests/test_cli.py |
| T-006 | Dashboard API + UI | 2 | T-005 store contract | drydock/dashboard/, tests/test_dashboard.py |
| T-007 | DRYDOCK MCP server | 2 | T-005 service contract | drydock/mcp/server.py, tests/test_mcp_server.py |
| T-008 | Docs: serving.md, runbook.md, README body, corpus README | 2 | T-000 | docs/serving.md, docs/runbook.md, README.md, corpus/README.md |
| T-009 | Bench + headline.json + card | 3 | T-005 | drydock/bench.py, metrics/headline.json, docs/assets/metrics.svg, tests/test_bench.py |
| T-010 | Airflow compose profile + deploy README | 3 | T-005 | docker-compose.yml, deploy/README.md |
| T-011 | Integration fixes, code review, ship report, CI on GitHub | 4 | all | docs/ship-report.md, any |

## Wave schedule

- **Wave 1 (parallel ×4):** T-001, T-002, T-003, T-004 — disjoint directories, all code
  against `models.py` and LLD §2–§6.
- **Wave 2 (parallel ×4):** T-005, T-006, T-007, T-008 — T-006/T-007 code against the
  LLD §7 contracts with stub services in tests; integration verified in wave 3.
- **Wave 3 (parallel ×2):** T-009, T-010.
- **Wave 4:** T-011 (orchestrator + reviewer agents).

## Validation per task

Every task: `uv run ruff check <scope> && uv run ruff format --check <scope> && uv run mypy
<scope pkg> && uv run pytest tests/<task tests> -q`. Whole-repo `scripts/check.py` is the
milestone gate from M2 onward.

## Rules for task agents

1. Touch only the files in your scope. Need something else? Write it in your task pack's
   Handoff notes and stop.
2. `models.py` and this LLD are frozen. Do not add fields; do not rename.
3. Tests must pass on Windows and Linux; no `resource` module without a POSIX guard; use
   `pathlib`; write files with `newline="\n"`.
4. No network in tests. No sleeps longer than 0.1 s except the adversarial latency fixture.
5. Keep files under 800 lines and functions under 50 where practical.
6. Two-strike rule: two failed validation attempts → write findings to the task pack,
   mark `blocked`, stop.
