# 01 — Requirements

**Project:** DRYDOCK — agentic pipeline generation and validation harness
**Owner:** Roshan Rana · **Status:** approved 2026-09-07 (autonomous build, see decisions.md ADR-000)

## 1. Problem

Forward-deployed engineers onboard client data feeds by hand: read the client's file
specification, write an ingestion pipeline, run it against sample files, fix what breaks,
and get a reviewer to sign off before it is scheduled. The loop is slow, the fixes are
undocumented, and the sign-off is a Slack message.

DRYDOCK automates the loop and makes every step reviewable: an agent graph reads the spec,
drafts the pipeline, runs it through a deterministic test harness inside a sandbox, repairs
it when the harness finds a defect, and then **stops** at a human approval gate before any
artifact is published. Nothing sails until a person says so.

## 2. Users

| User | Needs |
|---|---|
| FDE onboarding a client feed | Draft a working pipeline from a spec in minutes; see exactly which check failed and how the agent repaired it. |
| Reviewer / data owner | Approve or reject a proposed pipeline with the full evidence trail in front of them. |
| Interviewer / reviewer of this repo | Run one command offline and see measured, not claimed, results. |

## 3. Functional requirements

| ID | Requirement |
|---|---|
| FR-1 | Parse a client feed specification (`corpus/<client>/spec.md`) into a typed `FeedSpec`. |
| FR-2 | **Planner** node produces an `IngestionPlan` and must gather evidence through MCP tools (list samples, peek rows, profile columns) rather than being handed the files. |
| FR-3 | **Generator** node produces a `PipelineArtifact`: `pipeline.py`, an Airflow `dag.py`, and a Harbormaster-compatible `mapping.yaml`. |
| FR-4 | **Evaluator** node runs the generated pipeline in a sandbox against the sample files and applies six checks: runtime, schema, completeness (truncation), drift, latency, DAG contract. |
| FR-5 | On failure the graph branches back to the Generator with the findings (self-healing), bounded by `max_iterations` (default 3). |
| FR-6 | After `max_iterations` failures the run is **escalated** to a human; the graph never loops forever. |
| FR-7 | On success the graph **interrupts** before publishing; a human approves or rejects via CLI, API, dashboard, or MCP. State is checkpointed so the decision can arrive in a later process. |
| FR-8 | Publish copies the approved artifacts to `deploy/<client>/` and records who approved and when. |
| FR-9 | Every checkpoint of every run can be replayed step by step (`drydock replay`). |
| FR-10 | Dashboard shows runs, per-iteration check results, and the code diff between iterations. |
| FR-11 | DRYDOCK exposes its own MCP server so any MCP client (Claude Desktop, Cursor, a script) can start a build, inspect a run, and approve it. |
| FR-12 | Providers: `fake` (deterministic, offline, default), `openai_compat` (Ollama, vLLM, any OpenAI-compatible endpoint), `bedrock`, `anthropic`. One graph, swappable backends. |
| FR-13 | A `bench` command replays the whole corpus offline and writes `metrics/headline.json`; the README results card is rendered from it and CI fails on drift. |
| FR-14 | Adversarial pipelines (hand-written bad code) must be rejected by the harness; the false-accept count is a published metric. |

## 4. Non-functional requirements

| ID | Target |
|---|---|
| NFR-1 Offline | `make check` runs with no network, no API key, no Docker, no Airflow, on Windows and Linux. |
| NFR-2 Deterministic | Same seed → byte-identical `metrics/headline.json`. |
| NFR-3 Bounded | Max 3 generator iterations per run; sandbox timeout 30 s per sample; latency budget 5 s per sample. |
| NFR-4 Sandbox | Generated code runs in a subprocess with isolated mode, a scratch working directory, a minimal environment and a timeout; optional Docker sandbox with `--network none`. Generated code never runs in the orchestrator process. |
| NFR-5 Data perimeter | Real LLM providers see the spec, column profiles and at most 5 peeked rows, never whole files. Documented in `docs/serving.md`. |
| NFR-6 Quality gate | ruff, mypy strict, pytest with ≥80% coverage, bench drift, card drift, all in one command, same in CI. |
| NFR-7 Observability | Every node emits a structured event; LangSmith tracing is a documented env toggle; token usage is recorded per LLM call when a real provider is used. |
| NFR-8 Size | Source files ≤800 lines; functions ≤50 lines where practical. |

## 5. Constraints and assumptions

- Python 3.12, `uv`, LangGraph ≥1.2, `mcp` SDK 2.x, Pydantic v2. No GNU make on the author's Windows host: `scripts/check.py` is the gate and `Makefile` wraps it.
- Airflow is **not** a dependency. Generated DAGs are validated against a stub `airflow` package that records structure; a `docker compose --profile airflow` target runs real Airflow for demos.
- The canonical target schema is fixed (seven columns, see `drydock/models.py`). Real clients would extend it; this repo does not.
- Corpus data is synthetic. No real client data, ever.

## 6. Out of scope

- A visual DAG editor. The dashboard is a trace viewer.
- Deploying pipelines to a live Airflow, cloud scheduler or data warehouse.
- Auto-approval of any kind. The human gate cannot be disabled.
- Multi-tenant auth on the dashboard or MCP server.
- Fine-tuning or evaluating the quality of specific LLMs. The bench measures the harness and the loop with the deterministic provider; live-model results are reported as pending until observed.
