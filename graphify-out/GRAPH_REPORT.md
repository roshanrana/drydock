# Graph Report - drydock  (2026-09-10)

## Corpus Check
- 93 files · ~87,406 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1734 nodes · 5782 edges · 80 communities (71 shown, 9 thin omitted)
- Extraction: 68% EXTRACTED · 32% INFERRED · 0% AMBIGUOUS · INFERRED: 1867 edges (avg confidence: 0.5)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `861ca895`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- [[_COMMUNITY_Community 0|Community 0]]
- [[_COMMUNITY_Community 1|Community 1]]
- [[_COMMUNITY_Community 2|Community 2]]
- [[_COMMUNITY_Community 3|Community 3]]
- [[_COMMUNITY_Community 4|Community 4]]
- [[_COMMUNITY_Community 5|Community 5]]
- [[_COMMUNITY_Community 6|Community 6]]
- [[_COMMUNITY_Community 7|Community 7]]
- [[_COMMUNITY_Community 8|Community 8]]
- [[_COMMUNITY_Community 9|Community 9]]
- [[_COMMUNITY_Community 10|Community 10]]
- [[_COMMUNITY_Community 11|Community 11]]
- [[_COMMUNITY_Community 12|Community 12]]
- [[_COMMUNITY_Community 13|Community 13]]
- [[_COMMUNITY_Community 14|Community 14]]
- [[_COMMUNITY_Community 15|Community 15]]
- [[_COMMUNITY_Community 16|Community 16]]
- [[_COMMUNITY_Community 17|Community 17]]
- [[_COMMUNITY_Community 18|Community 18]]
- [[_COMMUNITY_Community 19|Community 19]]
- [[_COMMUNITY_Community 20|Community 20]]
- [[_COMMUNITY_Community 21|Community 21]]
- [[_COMMUNITY_Community 22|Community 22]]
- [[_COMMUNITY_Community 23|Community 23]]
- [[_COMMUNITY_Community 24|Community 24]]
- [[_COMMUNITY_Community 25|Community 25]]
- [[_COMMUNITY_Community 26|Community 26]]
- [[_COMMUNITY_Community 27|Community 27]]
- [[_COMMUNITY_Community 28|Community 28]]
- [[_COMMUNITY_Community 29|Community 29]]
- [[_COMMUNITY_Community 30|Community 30]]
- [[_COMMUNITY_Community 31|Community 31]]
- [[_COMMUNITY_Community 32|Community 32]]
- [[_COMMUNITY_Community 33|Community 33]]
- [[_COMMUNITY_Community 34|Community 34]]
- [[_COMMUNITY_Community 35|Community 35]]
- [[_COMMUNITY_Community 36|Community 36]]
- [[_COMMUNITY_Community 37|Community 37]]
- [[_COMMUNITY_Community 38|Community 38]]
- [[_COMMUNITY_Community 39|Community 39]]
- [[_COMMUNITY_Community 40|Community 40]]
- [[_COMMUNITY_Community 41|Community 41]]
- [[_COMMUNITY_Community 42|Community 42]]
- [[_COMMUNITY_Community 43|Community 43]]
- [[_COMMUNITY_Community 44|Community 44]]
- [[_COMMUNITY_Community 45|Community 45]]
- [[_COMMUNITY_Community 46|Community 46]]
- [[_COMMUNITY_Community 47|Community 47]]
- [[_COMMUNITY_Community 48|Community 48]]
- [[_COMMUNITY_Community 49|Community 49]]
- [[_COMMUNITY_Community 50|Community 50]]
- [[_COMMUNITY_Community 51|Community 51]]
- [[_COMMUNITY_Community 52|Community 52]]
- [[_COMMUNITY_Community 53|Community 53]]
- [[_COMMUNITY_Community 54|Community 54]]
- [[_COMMUNITY_Community 55|Community 55]]
- [[_COMMUNITY_Community 56|Community 56]]
- [[_COMMUNITY_Community 57|Community 57]]
- [[_COMMUNITY_Community 58|Community 58]]
- [[_COMMUNITY_Community 59|Community 59]]
- [[_COMMUNITY_Community 60|Community 60]]
- [[_COMMUNITY_Community 61|Community 61]]
- [[_COMMUNITY_Community 63|Community 63]]
- [[_COMMUNITY_Community 64|Community 64]]
- [[_COMMUNITY_Community 65|Community 65]]
- [[_COMMUNITY_Community 66|Community 66]]
- [[_COMMUNITY_Community 67|Community 67]]
- [[_COMMUNITY_Community 68|Community 68]]
- [[_COMMUNITY_Community 70|Community 70]]
- [[_COMMUNITY_Community 72|Community 72]]
- [[_COMMUNITY_Community 73|Community 73]]
- [[_COMMUNITY_Community 74|Community 74]]
- [[_COMMUNITY_Community 75|Community 75]]
- [[_COMMUNITY_Community 76|Community 76]]
- [[_COMMUNITY_Community 77|Community 77]]
- [[_COMMUNITY_Community 78|Community 78]]
- [[_COMMUNITY_Community 79|Community 79]]

## God Nodes (most connected - your core abstractions)
1. `PipelineArtifact` - 190 edges
2. `HarnessReport` - 186 edges
3. `CheckId` - 124 edges
4. `FeedSpec` - 116 edges
5. `DrydockError` - 112 edges
6. `RunStore` - 109 edges
7. `RunRecord` - 104 edges
8. `RunStatus` - 100 edges
9. `IngestionPlan` - 98 edges
10. `RunService` - 87 edges

## Surprising Connections (you probably didn't know these)
- `test_decision_request_model_is_frozen()` --calls--> `DecisionRequest`  [EXTRACTED]
  tests/test_dashboard.py → drydock/dashboard/app.py
- `CliRunner` --uses--> `DrydockError`  [INFERRED]
  tests/test_cli.py → drydock/errors.py
- `TwoRuns` --uses--> `DrydockError`  [INFERRED]
  tests/test_bench.py → drydock/errors.py
- `MonkeyPatch` --uses--> `DrydockError`  [INFERRED]
  tests/test_cli.py → drydock/errors.py
- `Path` --uses--> `DrydockError`  [INFERRED]
  tests/test_cli.py → drydock/errors.py

## Import Cycles
- 1-file cycle: `drydock/models.py -> drydock/models.py`
- 1-file cycle: `drydock/harness/checks.py -> drydock/harness/checks.py`
- 1-file cycle: `drydock/dashboard/app.py -> drydock/dashboard/app.py`

## Communities (80 total, 9 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.05
Nodes (124): AdversarialCase, _body_lines(), build_manifest(), _build_parser(), _canonical_row(), _client_dir(), _convert(), _expected_rows() (+116 more)

### Community 1 - "Community 1"
Cohesion: 0.08
Nodes (85): AST, Call, Decimal, Any, CheckId, CheckResult, FeedSpec, SampleProfile (+77 more)

### Community 2 - "Community 2"
Cohesion: 0.06
Nodes (75): Any, FeedSpec, MCPServer, Path, SampleProfile, Any, CallToolResult, MCP surface of DRYDOCK (docs/design/03-lld.md section 6).  - :mod:`drydock.mcp.s (+67 more)

### Community 3 - "Community 3"
Cohesion: 0.09
Nodes (72): AdversarialCase, ArgumentParser, ArtifactFile, Counter, AdversarialOutcome, _load_reports(), _open(), _published_clients() (+64 more)

### Community 4 - "Community 4"
Cohesion: 0.06
Nodes (65): CliRunner, Context, approve(), bench(), build(), corpus_rebuild_manifests(), corpus_verify(), dump_json() (+57 more)

### Community 5 - "Community 5"
Cohesion: 0.09
Nodes (55): BaseCheckpointSaver, CompiledStateGraph, EventWriter, Append-only JSONL event log, one file per run (docs/design/03-lld.md section 1)., Appends JSON lines to ``path``; the parent directory is created on first emit., Deps, Decision, RunStatus (+47 more)

### Community 6 - "Community 6"
Cohesion: 0.14
Nodes (44): _artifact(), awaiting(), call(), _install_fake_graph(), Any, MCPServer, RunRecord, Tests for the DRYDOCK MCP server (T-007).  The server is exercised over the in-m (+36 more)

### Community 7 - "Community 7"
Cohesion: 0.09
Nodes (30): _bars(), BenchResult, _code_lines(), dump_headline(), _error_counts(), _fact(), headline(), _kpi() (+22 more)

### Community 8 - "Community 8"
Cohesion: 0.19
Nodes (22): _artifact(), _command_lines(), failing_is_runtime(), _guard_values(), _h1(), _h1_stderr(), _judge(), HarnessReport (+14 more)

### Community 9 - "Community 9"
Cohesion: 0.09
Nodes (51): Path, Replays canned replies in order and records every request it received., ScriptedBackend, FakeProvider, Template provider with scenario-declared fault injection., load_provider(), Build the provider named by ``configs/providers/<name>.yaml``.      ``fault_plan, Load and validate one provider yaml; missing ``api_key_env`` gets the backend de (+43 more)

### Community 10 - "Community 10"
Cohesion: 0.14
Nodes (19): Any, FeedSpec, HarnessReport, IngestionPlan, ToolBox, _checked(), collect_evidence(), Evidence (+11 more)

### Community 11 - "Community 11"
Cohesion: 0.10
Nodes (50): ChatResult, FeedSpec, Frozen, IngestionPlan, Immutable base: contracts are values, never mutated in place., Parsed form of the fenced yaml feed-contract block in corpus/<client>/spec.md., What the Planner decides before any code is written., PipelineArtifact (+42 more)

### Community 12 - "Community 12"
Cohesion: 0.09
Nodes (29): FakeDag, FakeOperator, imported_modules(), inject_and_run(), load_module(), Any, IngestionPlan, ModuleType (+21 more)

### Community 13 - "Community 13"
Cohesion: 0.15
Nodes (13): Any, Path, RunRecord, artifact_files(), _finding_dump(), _iteration_summary(), Run store: SQLite rows plus per-iteration files (docs/design/03-lld.md section 7, Apply ``fields`` to the run and return the new record (``updated_at`` refreshed) (+5 more)

### Community 14 - "Community 14"
Cohesion: 0.06
Nodes (45): create_app(), _dump(), _dump_rows(), _known_iterations(), FastAPI application for the DRYDOCK review dashboard (LLD section 9).  The app i, Return the iteration summaries for a run, raising ``RunNotFound`` for unknown id, Build the dashboard application bound to ``service``., Run the dashboard under uvicorn. ``drydock serve`` (LLD section 7.4) calls this. (+37 more)

### Community 15 - "Community 15"
Cohesion: 0.09
Nodes (32): Error taxonomy (docs/design/03-lld.md section 8).  The CLI maps any ``DrydockErr, The evaluation sandbox could not run the candidate pipeline., The candidate pipeline exceeded the sandbox wall-clock budget.      ``run_in_san, SandboxError, SandboxTimeout, Path, _build_command(), _child_env() (+24 more)

### Community 16 - "Community 16"
Cohesion: 0.11
Nodes (35): Client, OpenAICompatBackend, AnthropicBackend, BedrockBackend, OpenAICompatBackend, Bedrock ``converse`` API. Credentials come from the usual AWS chain, never from, Anthropic Messages API via the official SDK (``client.messages.create``).      `, POST ``{base_url}/chat/completions`` with the OpenAI request shape.      ``clien (+27 more)

### Community 17 - "Community 17"
Cohesion: 0.29
Nodes (10): ProviderError, A generation provider failed or returned an unusable artifact., Any, _as_int(), ChatResult, _elapsed_ms(), _parse_anthropic_message(), _parse_converse() (+2 more)

### Community 18 - "Community 18"
Cohesion: 0.10
Nodes (25): Any, ColumnSpec, IngestionPlan, _defect_dag_missing_dependency(), _defect_date_format_swapped(), _describe_transform(), inject_defect(), parse_options() (+17 more)

### Community 19 - "Community 19"
Cohesion: 0.11
Nodes (14): _as_list(), BaseOperator, current_dag(), DAG, Minimal Airflow stand-in used only inside the harness sandbox.  Records DAG stru, Recorder for one DAG declaration. Supports ``with DAG(...) as dag:`` and ``dag=`, JSON-ready structure consumed by the harness (LLD section 4)., Common recorder for operators; implements the ``>>`` / ``<<`` dependency syntax. (+6 more)

### Community 20 - "Community 20"
Cohesion: 0.09
Nodes (30): RunService, Any, Decision, HarnessReport, MCPServer, Path, PipelineArtifact, RunRecord (+22 more)

### Community 21 - "Community 21"
Cohesion: 0.14
Nodes (25): Any, RunRecord, _approve_run(), _build_pipeline(), build_server(), _build_service(), _get_history(), _get_iteration() (+17 more)

### Community 22 - "Community 22"
Cohesion: 0.12
Nodes (26): clip(), load(), main(), md_cell(), Path, Render metrics/headline.json into a results card.  Outputs:   docs/assets/met, render_markdown(), render_svg() (+18 more)

### Community 23 - "Community 23"
Cohesion: 0.18
Nodes (12): BaseModel, DecisionRequest, Subset of ``RunStore`` (LLD section 7.2) the dashboard reads., Body of ``POST /api/runs/{run_id}/decision``., RunStoreLike, FileName, HarnessReport, PipelineArtifact (+4 more)

### Community 24 - "Community 24"
Cohesion: 0.14
Nodes (15): Any, Decision, GraphState, HarnessReport, approval_payload(), initial_state(), The state handed to ``compiled.invoke`` when a run starts., LLD 7.1: passed -> approval gate; failed with budget left -> repair; else escala (+7 more)

### Community 25 - "Community 25"
Cohesion: 0.19
Nodes (26): Write UTF-8 text with ``\\n`` newlines regardless of platform., write_text(), make_artifact(), make_record(), make_report(), RunStore, RunStore: SQLite rows, iteration files and diffs (LLD section 7.2)., test_artifact_files_covers_the_three_deployables() (+18 more)

### Community 26 - "Community 26"
Cohesion: 0.22
Nodes (27): failing_checks(), fixture(), judge(), make_artifact(), CheckId, HarnessReport, result_for(), test_docker_sandbox_runs_good_pipeline() (+19 more)

### Community 27 - "Community 27"
Cohesion: 0.14
Nodes (28): Path, Load every event line; a missing file is an empty log, not an error., read_events(), latest_state(), Path, RunService, Graph, service and events against the real corpus with the fake provider (LLD se, _report() (+20 more)

### Community 28 - "Community 28"
Cohesion: 0.08
Nodes (23): 03 — Low-level design, 10. Bench and metrics (T-009), 11. Test strategy, 1. Repository layout, 2.1 `corpus/<client>/spec.md`, 2.2 `corpus/<client>/manifest.json`, 2.3 Clients (six) and adversarial set (five), 2.4 `corpus.py` API (+15 more)

### Community 29 - "Community 29"
Cohesion: 0.15
Nodes (15): canonical_row(), docker_available(), make_run(), Any, Tests for drydock.harness: sandbox, static guard, the six checks, runner and Air, sandbox_result(), test_check_dag_contract_extra_edge_and_missing_output(), test_check_drift_null_rate_distinct_and_unparseable_amounts() (+7 more)

### Community 30 - "Community 30"
Cohesion: 0.28
Nodes (10): Any, GraphState, Nodes, _parse_decision(), Human gate: a real LangGraph interrupt, resumed with ``Command(resume=...)``., Validate the resume payload ``{"decision", "approver", "note"}``., Node functions bound to one ``Deps``; ``build_graph`` registers them by name., _require() (+2 more)

### Community 31 - "Community 31"
Cohesion: 0.21
Nodes (16): isolated_modules(), CaptureFixture, MonkeyPatch, Path, stage(), test_docker_argv_matches_lld(), test_docker_kind_without_binary_raises(), test_docker_timeout_attempts_container_cleanup() (+8 more)

### Community 32 - "Community 32"
Cohesion: 0.15
Nodes (13): Approve, Inspect a run, Invariants an operator can rely on, Prerequisites, Reject, Replay, Reset, Run the Airflow profile (+5 more)

### Community 33 - "Community 33"
Cohesion: 0.17
Nodes (11): 1. Gate evidence, 2. What the bench observed (fake provider, seed 42, offline), 3. Review findings and dispositions, 4. Environment and secrets matrix, 5. Observability, 6. Deployment and rollback, 7. Known issues and honest limits, 8. Recommendation (+3 more)

### Community 34 - "Community 34"
Cohesion: 0.17
Nodes (12): 1. The graph (`drydock/graph/`), 2. The corpus (`corpus/`, `drydock/corpus.py`), 3. The providers (`drydock/providers/`), 4. The harness (`drydock/harness/`, `docs/security.md`), 5. MCP in both directions (`drydock/mcp/`), 6. The bench and the card (`drydock/bench.py`, `metrics/`), 7. The gate (`scripts/check.py`, `.github/workflows/check.yml`), DRYDOCK — Showcase (+4 more)

### Community 35 - "Community 35"
Cohesion: 0.17
Nodes (12): At a glance, DRYDOCK, Guarantees, Honest limits, How it works, License, Local or cloud models, Relationship to sibling repos (+4 more)

### Community 36 - "Community 36"
Cohesion: 0.18
Nodes (10): ADR-000 — Autonomous gate approval (2026-09-07), ADR-001 — Name: DRYDOCK (2026-09-07), ADR-002 — LangGraph with SQLite checkpointer (2026-09-07), ADR-003 — Python `mcp` 2.x, in-memory transport for tests (2026-09-07), ADR-004 — Airflow validated through a stub package, not installed (2026-09-07), ADR-005 — Raw backend adapters instead of LangChain chat models (2026-09-07), ADR-006 — Fault injection lives in the corpus manifest, not the generator (2026-09-07), ADR-007 — Wave 1 integration reconciliations (2026-09-07) (+2 more)

### Community 37 - "Community 37"
Cohesion: 0.24
Nodes (5): BaseException, Hold one Client session open until ``close`` asks the loop to stop., Shut the session and its loop down. Safe to call repeatedly., ServerSpec, TracebackType

### Community 38 - "Community 38"
Cohesion: 0.20
Nodes (9): 02 — High-level design, 1. Architecture style, 2. System context, 3. Components, 4. Data architecture, 5. Critical flows, 6. Cross-cutting, 7. Tech-stack recommendation (+1 more)

### Community 39 - "Community 39"
Cohesion: 0.20
Nodes (9): Calling it from Python, Claude Code, Claude Desktop, Cursor, Demo transcript, DRYDOCK as an MCP server, Registering the server, Running it (+1 more)

### Community 40 - "Community 40"
Cohesion: 0.50
Nodes (3): Any, Append ``{ts, node, **fields}`` as one JSON line and return the record written., Provider ``on_usage`` callback: records token counts as an ``llm_usage`` event.

### Community 41 - "Community 41"
Cohesion: 0.20
Nodes (9): Acceptance criteria, Goal, Handoff notes (≤10 lines), Integration notes from Wave 1, LangGraph facts (langgraph 1.2, verified), Read first, Scope (only these files), T-005 — Graph, store, service, events, CLI core (+1 more)

### Community 42 - "Community 42"
Cohesion: 0.31
Nodes (9): deploy_dir(), Path, RunService, RunStore, Shared fixtures: temp database, runs dir, deploy dir, store and service (T-005)., runs_dir(), service(), store() (+1 more)

### Community 43 - "Community 43"
Cohesion: 0.25
Nodes (7): 01 — Requirements, 1. Problem, 2. Users, 3. Functional requirements, 4. Non-functional requirements, 5. Constraints and assumptions, 6. Out of scope

### Community 44 - "Community 44"
Cohesion: 0.08
Nodes (23): For /graphify add and --watch, For /graphify query, For the commit hook and native CLAUDE.md integration, For --update and --cluster-only, /graphify, Honesty Rules, Interpreter guard for subcommands, Part A - Structural extraction for code files (+15 more)

### Community 45 - "Community 45"
Cohesion: 0.19
Nodes (19): Any, ModuleType, Path, _cli(), _DenyFinder, _disabled(), _empty_dag(), install_jail() (+11 more)

### Community 46 - "Community 46"
Cohesion: 0.25
Nodes (7): Acceptance criteria, Goal, Handoff notes (fill in when done, ≤10 lines), Read first, Scope (only these files), T-001 — Corpus, loader, paths, errors, Validation

### Community 47 - "Community 47"
Cohesion: 0.25
Nodes (7): Acceptance criteria, Goal, Handoff notes (≤10 lines), Read first, Scope (only these files), T-002 — Harness: sandbox, six checks, Airflow shim, Validation

### Community 48 - "Community 48"
Cohesion: 0.25
Nodes (7): Acceptance criteria, Goal, Handoff notes (≤10 lines), Read first, Scope (only these files), T-003 — Providers: fake, templates, LLM, backends, configs, Validation

### Community 49 - "Community 49"
Cohesion: 0.25
Nodes (7): Acceptance criteria, Goal, Handoff notes (≤10 lines), Read first, Scope (only these files), T-004 — Sources MCP server and sync toolbox, Validation

### Community 50 - "Community 50"
Cohesion: 0.25
Nodes (7): Acceptance criteria, Goal, Handoff notes (≤10 lines), Read first, Scope (only these files), T-006 — Dashboard API and trace viewer, Validation

### Community 51 - "Community 51"
Cohesion: 0.25
Nodes (7): Acceptance criteria, Goal, Handoff notes (≤10 lines), Read first, Scope (only these files), T-007 — DRYDOCK MCP server, Validation

### Community 52 - "Community 52"
Cohesion: 0.25
Nodes (7): Acceptance criteria, Goal, Handoff notes (≤10 lines), Read first, Scope (only these files), T-008 — Documentation: README body, serving guide, runbook, Validation

### Community 53 - "Community 53"
Cohesion: 0.25
Nodes (7): Acceptance criteria, Goal, Handoff notes (≤10 lines), Read first, Scope (only these files), T-009 — Bench, headline.json, results card, Validation

### Community 54 - "Community 54"
Cohesion: 0.25
Nodes (7): Acceptance criteria, Goal, Handoff notes (≤10 lines), Read first, Scope (only these files), T-010 — Airflow compose profile and deploy README, Validation

### Community 55 - "Community 55"
Cohesion: 0.25
Nodes (7): Acceptance criteria, Design (implement all; these become LLD §4 text), Handoff notes (≤10 lines), Scope (only these files), T-012 — Sandbox hardening after security review, Validation, Why

### Community 56 - "Community 56"
Cohesion: 0.29
Nodes (6): 04 — Execution plan, Milestones, Rules for task agents, Task table, Validation per task, Wave schedule

### Community 57 - "Community 57"
Cohesion: 0.29
Nodes (7): Data perimeter, Provider matrix, Serving: local or cloud models, Starting each backend, Token usage and events, Tracing with LangSmith, What is and is not measured

### Community 58 - "Community 58"
Cohesion: 0.33
Nodes (6): DRYDOCK — Overview, Honest limits, The design, The setting, What is measured, Where it sits among the other projects

### Community 59 - "Community 59"
Cohesion: 0.33
Nodes (5): DRYDOCK harness sandbox — threat model and hardening (T-012), Payload table — before vs after, Residual limits (known, accepted), Threat model, Three layers (each independently tested)

### Community 60 - "Community 60"
Cohesion: 0.33
Nodes (5): Blockers, Deviations, Now / next, STATE — DRYDOCK, Task log

### Community 61 - "Community 61"
Cohesion: 0.22
Nodes (8): graphify reference: extra exports and benchmark, Step 6b - Wiki (only if --wiki flag), Step 7 - Neo4j export (only if --neo4j or --neo4j-push flag), Step 7a - FalkorDB export (only if --falkordb or --falkordb-push flag), Step 7b - SVG export (only if --svg flag), Step 7c - GraphML export (only if --graphml flag), Step 7d - MCP server (only if --mcp flag), Step 8 - Token reduction benchmark (only if total_words > 5000)

### Community 63 - "Community 63"
Cohesion: 0.40
Nodes (4): Goal, Handoff notes, Steps, T-011 — Integration, review, ship report, GitHub

### Community 65 - "Community 65"
Cohesion: 0.33
Nodes (7): ChatBackend, build_backend(), ProviderConfig, Read the API key from the environment variable the config names (None = no auth), Construct the ChatBackend for a non-fake config. Optional SDKs are imported lazi, Validated form of ``configs/providers/<name>.yaml``. No secrets, only their env, resolve_api_key()

### Community 72 - "Community 72"
Cohesion: 0.33
Nodes (5): For /graphify explain, For /graphify path, graphify reference: query, path, explain, Step 0 — Constrained query expansion (REQUIRED before traversal), Step 1 — Traversal

### Community 73 - "Community 73"
Cohesion: 0.50
Nodes (3): For /graphify add, For --watch, graphify reference: add a URL and watch a folder

### Community 74 - "Community 74"
Cohesion: 0.50
Nodes (3): For git commit hook, For native CLAUDE.md integration, graphify reference: commit hook and native CLAUDE.md integration

### Community 75 - "Community 75"
Cohesion: 0.50
Nodes (3): For --cluster-only, For --update (incremental re-extraction), graphify reference: incremental update and cluster-only

## Knowledge Gaps
- **236 isolated node(s):** `Any`, `DAG`, `ModuleType`, `Self`, `BaseException` (+231 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **9 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `PipelineArtifact` connect `Community 3` to `Community 0`, `Community 1`, `Community 5`, `Community 6`, `Community 7`, `Community 8`, `Community 9`, `Community 10`, `Community 11`, `Community 13`, `Community 14`, `Community 20`, `Community 21`, `Community 22`, `Community 23`, `Community 25`, `Community 26`, `Community 29`, `Community 31`, `Community 65`?**
  _High betweenness centrality (0.082) - this node is a cross-community bridge._
- **Why does `HarnessReport` connect `Community 3` to `Community 1`, `Community 5`, `Community 6`, `Community 7`, `Community 8`, `Community 9`, `Community 10`, `Community 11`, `Community 13`, `Community 14`, `Community 20`, `Community 21`, `Community 23`, `Community 24`, `Community 25`, `Community 26`, `Community 27`, `Community 29`, `Community 31`, `Community 65`?**
  _High betweenness centrality (0.078) - this node is a cross-community bridge._
- **Why does `FeedSpec` connect `Community 11` to `Community 0`, `Community 1`, `Community 2`, `Community 3`, `Community 65`, `Community 5`, `Community 9`, `Community 10`, `Community 20`, `Community 27`?**
  _High betweenness centrality (0.048) - this node is a cross-community bridge._
- **Are the 160 inferred relationships involving `PipelineArtifact` (e.g. with `AdversarialCase` and `ArgumentParser`) actually correct?**
  _`PipelineArtifact` has 160 INFERRED edges - model-reasoned connections that need verification._
- **Are the 156 inferred relationships involving `HarnessReport` (e.g. with `AdversarialCase` and `ArtifactFile`) actually correct?**
  _`HarnessReport` has 156 INFERRED edges - model-reasoned connections that need verification._
- **Are the 106 inferred relationships involving `CheckId` (e.g. with `AdversarialCase` and `ArgumentParser`) actually correct?**
  _`CheckId` has 106 INFERRED edges - model-reasoned connections that need verification._
- **Are the 99 inferred relationships involving `FeedSpec` (e.g. with `ArgumentParser` and `ChatResult`) actually correct?**
  _`FeedSpec` has 99 INFERRED edges - model-reasoned connections that need verification._