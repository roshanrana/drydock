# 02 — High-level design

## 1. Architecture style

A **bounded state machine** (LangGraph `StateGraph`) with a SQLite checkpointer, wrapping
three agent roles and one deterministic harness. Agents propose; the harness decides; a
human disposes. Chosen over a free-form ReAct agent because the loop must be auditable,
resumable across processes, and provably bounded (FR-5, FR-6, FR-7).

## 2. System context

```
                 ┌──────────────────────────────────────────────────────────────┐
  spec.md +      │                     DRYDOCK graph (LangGraph)                 │
  samples  ───▶  │  load_spec ─▶ plan ─▶ generate ─▶ evaluate ─┬─ pass ─▶ ⏸ await_approval ─▶ publish ─▶ deploy/
  (corpus)       │                 ▲        ▲                  │                     │
                 │                 │        └── fail & iter<N ─┘                     └─ reject ─▶ record_rejection
                 │      MCP tools  │                  fail & iter==N ─▶ escalate
                 │  (sources srv)  │
                 └─────────────────┼──────────────────────────────────────────────┘
                                   │
   ┌───────────────┐   ┌───────────┴─────────┐   ┌───────────────┐   ┌─────────────────┐
   │ CLI (typer)   │   │ Dashboard (FastAPI) │   │ DRYDOCK MCP   │   │ bench → metrics │
   │ build/approve │   │ runs, diffs, history│   │ server (stdio)│   │ headline.json   │
   └───────────────┘   └─────────────────────┘   └───────────────┘   └─────────────────┘
                                 all read/write through graph.service + graph.store
```

## 3. Components

| Component | Package | Responsibility |
|---|---|---|
| Contracts | `drydock/models.py` | Frozen Pydantic types shared by everything. |
| Corpus | `drydock/corpus.py`, `corpus/` | Load specs, samples, pinned manifests; verify sha256. |
| Sources MCP server | `drydock/mcp/sources_server.py` | Tools the Planner uses to look at the client's data without the orchestrator handing it files. |
| MCP toolbox | `drydock/mcp/toolbox.py` | Sync facade over the MCP client (in-memory or stdio) used inside graph nodes. |
| Providers | `drydock/providers/` | `Provider` protocol; `FakeProvider` (templates + seeded fault injection); `LLMProvider` over `ChatBackend`s (openai_compat, bedrock, anthropic). |
| Harness | `drydock/harness/` | Sandbox runner, six checks, Airflow stub. |
| Graph | `drydock/graph/` | Nodes, edges, checkpointer, run store, service API. |
| CLI | `drydock/cli.py` | `build`, `runs`, `show`, `approve`, `reject`, `replay`, `serve`, `mcp`, `bench`. |
| Dashboard | `drydock/dashboard/` | FastAPI JSON API + dependency-free HTML trace viewer. |
| DRYDOCK MCP server | `drydock/mcp/server.py` | Exposes build/inspect/approve as MCP tools. |
| Bench | `drydock/bench.py` | Corpus + adversarial replay → `metrics/headline.json`. |
| Card | `metrics/render.py` | headline.json → README block + SVG (stdlib, drift-checked). |

## 4. Data architecture

- **Corpus (committed, pinned):** `corpus/<client>/spec.md`, `samples/*`, `manifest.json` (sha256, expected rows, baseline stats, scenario). `corpus/_adversarial/<name>/` holds bad artifacts with the checks they must fail.
- **Run store (SQLite `data/drydock.db`):** `runs` and `iterations` tables plus LangGraph's checkpoint tables. Artifacts on disk under `runs/<run_id>/iter-N/`.
- **Deploy:** `deploy/<client>/{pipeline.py,dag.py,mapping.yaml,approval.json}` written only by `publish`.

## 5. Critical flows

1. **Happy path:** build → plan (MCP tool calls recorded) → generate → evaluate passes → interrupt → `approve` → publish.
2. **Self-heal:** evaluate fails H3 (trailer row parsed as data) → generate iteration 2 receives findings → passes → interrupt.
3. **Escalate:** spec contradicts the sample; three iterations fail → `escalated`; nothing is published; dashboard shows all three reports.
4. **Reject:** reviewer rejects with a note → `rejected`; artifacts stay in `runs/`, nothing in `deploy/`.
5. **Cross-process resume:** `build` exits at the interrupt; a later `approve` process loads the checkpoint by `thread_id=run_id` and resumes with `Command(resume=...)`.

## 6. Cross-cutting

- **Events:** every node appends a JSON line to `runs/<run_id>/events.jsonl` (`node`, `iteration`, `ms`, `outcome`).
- **Tracing:** LangSmith via `LANGCHAIN_TRACING_V2=true` + `LANGCHAIN_API_KEY`; documented, off by default.
- **Token economy:** `LLMProvider` records prompt/completion tokens per call into the events file; the fake provider records zero.
- **Security:** generated code never imports into the orchestrator; sandbox is subprocess `-I` with scratch cwd, minimal env, timeout; Docker `--network none` optional. Real providers receive redacted context only (NFR-5).

## 7. Tech-stack recommendation

| Layer | Options | Recommendation |
|---|---|---|
| Orchestration | LangGraph · custom state machine · Temporal | **LangGraph** — first-class interrupts, checkpointers, time travel; it is the skill being demonstrated. |
| Checkpointer | SQLite · Postgres · memory | **SQLite** — offline, zero infra, same file as run store. Postgres is a one-line swap. |
| MCP | `mcp` 2.x Python SDK · Go gateway (as in MarketSage) | **Python `mcp` 2.x** — same process as the graph, in-memory transport for tests, stdio for clients. |
| LLM backends | LangChain chat models · raw HTTP/SDKs | **Raw** `httpx` (OpenAI-compatible: Ollama, vLLM), `boto3` (Bedrock), `anthropic` SDK — three small adapters, no framework lock-in, optional extras. |
| Sandbox | subprocess · Docker · Firecracker | **subprocess by default, Docker optional** — offline gate must pass without Docker. |
| Airflow validation | real Airflow · AST only · stub package | **Stub `airflow` package** — records DAG structure at import; real Airflow behind a compose profile. |
| Dashboard | Next.js · Streamlit · FastAPI + vanilla HTML | **FastAPI + vanilla HTML/JS** — zero build step, one dependency already present. |
| CLI | Typer · argparse | **Typer** — already a dependency of the ecosystem, good `--help`. |

## 8. Risks

| Risk | Mitigation |
|---|---|
| LangGraph / mcp API churn | Versions pinned in `uv.lock`; API usage isolated in `graph/build.py` and `mcp/toolbox.py`. |
| Fake generator "too good" makes the loop look trivial | Fault injection is scenario-driven and published; one scenario is designed to be unfixable and must escalate. |
| Windows vs Linux sandbox differences | `resource` limits POSIX-only behind a guard; CI on Linux, dev on Windows, both must pass. |
| Live-model claims | Reported as pending in the card until a recorded run exists. |
