# Decision log

Append-only. Newest at the bottom.

## ADR-000 — Autonomous gate approval (2026-09-07)

The owner instructed the build to run fully autonomously and asked for an
interview-ready repository as soon as possible. The enterprise lifecycle's design
gates (requirements, HLD, LLD, execution plan) were therefore self-approved by the
orchestrating agent after writing each document, and that instruction is recorded here
as the approval. Every gate artifact still exists and is reviewable after the fact.

## ADR-001 — Name: DRYDOCK (2026-09-07)

A dry dock is where a vessel is built, tested and inspected before it is allowed into
the harbour. Harbormaster (sibling repo) controls what enters the harbour; DRYDOCK
decides what is seaworthy. Generated pipelines are drafted, tested, repaired and
inspected in dry dock; nothing sails without a signature.

## ADR-002 — LangGraph with SQLite checkpointer (2026-09-07)

Interrupts, checkpoint history and cross-process resume are requirements, not
conveniences. LangGraph provides all three; a hand-rolled state machine (as LedgerLens
ended up with) does not. SQLite keeps the offline gate at zero infrastructure.

## ADR-003 — Python `mcp` 2.x, in-memory transport for tests (2026-09-07)

`mcp` 2.x renamed FastMCP to `MCPServer` and its `Client` accepts an `MCPServer` instance
directly, so the Planner's tool calls are exercised over a real MCP session in the offline
test suite without spawning processes. Stdio is used when the sources server is run
standalone. Result payload field is `structured_content` (snake_case in v2).

## ADR-004 — Airflow validated through a stub package, not installed (2026-09-07)

Installing Airflow costs minutes and hundreds of megabytes and is irrelevant to the
skill being shown. Generated DAGs are restricted to `DAG`, `PythonOperator` and `>>`; a
stub `airflow` package on the sandbox path records the declared tasks and edges so the
harness can assert the contract. Real Airflow runs behind `docker compose --profile
airflow` for demos only.

## ADR-005 — Raw backend adapters instead of LangChain chat models (2026-09-07)

Three adapters (`openai_compat`, `bedrock`, `anthropic`) of under 80 lines each, behind
one `ChatBackend` protocol, make the local-versus-cloud story explicit and keep the base
install small. `openai_compat` covers Ollama and vLLM with one class.

## ADR-006 — Fault injection lives in the corpus manifest, not the generator (2026-09-07)

Each scenario declares `injected_defect` and `expected_outcome`. The fake generator
applies the defect on iteration 1 and repairs it when handed findings. The unfixable
scenario is expressed as a spec that contradicts its sample, so correct code still fails
and the loop must escalate. This keeps the demo honest and the behaviour published.

## ADR-007 — Wave 1 integration reconciliations (2026-09-07)

Four defects surfaced only when the independently built components met: (1) the planner
passed `sample=` where the MCP tools take `name=`, and tool errors were swallowed, so
evidence gathering now fails loudly and `ToolBox.call` takes the tool name positional-only.
(2) The escalate scenario passed because the manifest pinned the observed row count; the
pin is now the client's asserted `expected_row_count` when the contract declares one.
(3) `wrong_slice` shifted the trade id, which survives stripping; it now shifts the currency
slice so a digit bleeds into the code (H2). (4) The adversarial case expecting H1 and H5 could
only ever show H1 because the guard blocks execution; it is split into `slow_network_import`
(H1) and `sleeps_past_budget` (H5), five cases in all.
