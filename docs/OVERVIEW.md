# DRYDOCK — Overview

**What it is:** the client-onboarding loop a forward-deployed engineer runs by hand, expressed as a bounded agent graph: read the feed specification, draft the ingestion pipeline, run it against the samples, repair what breaks, and stop for a reviewer before anything is scheduled.

**Read this if** you want the design reasoning. [SHOWCASE.md](SHOWCASE.md) tours the features with commands.

---

## The setting

Every client feed arrives with a specification that is nearly right and a sample file that is nearly what the specification describes. Someone reads both, writes a parser, runs it, finds the trailer row that was counted as data, fixes it, and asks a colleague to sign off in a chat message. The work is repetitive, the fixes are undocumented, and the sign-off leaves no evidence.

Language models can write the parser. The question is whether anything they write can be trusted into a scheduler. DRYDOCK's answer is that the model's output is a proposal, a deterministic harness is the judge, and a human is the only thing that can publish.

## The design

**A state machine, not an agent loop.** The graph has eight nodes and one cycle. LangGraph runs it with a SQLite checkpointer, so every step is persisted, every run can be replayed step by step, and the approval decision can arrive from a different process hours later. The cycle is bounded by `max_iterations`; the third failure escalates and the graph ends. There is no path from `evaluate` to `publish` that does not pass through a human.

**The planner asks, it is not handed files.** A separate MCP server (`drydock-sources`) exposes the corpus. The planner calls `list_samples`, `peek_sample` (capped at five lines) and `profile_sample`, and the names of the tools it called are recorded on the plan. The data perimeter is a property of the tool server, not of the prompt.

**The generator writes three files.** A stdlib-only `pipeline.py` exposing `extract` and `transform`, an Airflow `dag.py` restricted to `DAG`, `PythonOperator` and `>>`, and a Harbormaster-compatible `mapping.yaml`. The deterministic provider renders them from templates and, when the corpus scenario says so, injects one named defect on the first attempt. Real providers (Ollama, vLLM, Bedrock, Anthropic) receive the same contract, the same worked example, and on repair the previous artifact plus the findings.

**The evaluator is a sandbox and six checks.** The artifact is copied into a scratch directory and run in a fresh interpreter with a static AST guard before execution, a runtime jail installed before the pipeline is imported, and process-group containment around the whole thing. The checks are runtime, schema, completeness against a pinned row count, drift against pinned amount sums and column statistics, latency against a budget, and DAG contract. The pinned values come from a manifest the generator never sees.

**The gate is an interrupt.** `await_approval` calls LangGraph's `interrupt()`. The CLI, the dashboard and the DRYDOCK MCP server all resume the graph through one service method that refuses anything except an explicit approve or reject with a named approver. `publish` writes `deploy/<client>/` with an `approval.json` naming who, when, and the digest of each file.

**Deterministic by default, live by explicit act.** The `fake` provider drives the tests, the bench and CI. Turning on a real model is a configuration file and an environment variable, never a side effect of having a key present.

## What is measured

One gate, `uv run python scripts/check.py`, runs offline with no network, no key and no Docker:

| Check | Result at ship |
|---|---|
| `ruff`, `ruff format`, `mypy --strict` on the host and on the Linux target | Pass |
| `pytest`, 505 tests, 98 % coverage; 25 of them are sandbox-escape payloads that must be stopped | Pass |
| `drydock bench`: six corpus scenarios and five adversarial artifacts replayed with seed 42 | 6 / 6 outcomes as declared, 4 / 4 heal scenarios repaired, 5 / 5 adversarial rejected, 59 checkpoints |
| Bench drift and results-card drift | Clean; CI fails on either |
| `pip-audit` over the locked dependency set (needs network, so not in the gate) | 0 known vulnerabilities |

An independent security review ran live payloads through the harness before ship and found that the first guard could be hopped (`os.path` to `os.system`) and that reads outside the scratch directory were unrestricted. Both were closed the same day; the before-and-after payload table is in [security.md](security.md).

## Honest limits

The bench measures the harness and the loop with the deterministic provider; it says nothing about any model's code quality, and live-provider rows are pending until a recorded run exists. The subprocess sandbox has three layers but is not an OS-level isolation boundary; the Docker mode is, and the bench does not use it. The corpus is synthetic: six clients, five adversarial cases. Airflow is validated against a stub package offline; the compose profile runs real Airflow for one client at a time because every generated module is named `pipeline`.

## Where it sits among the other projects

DRYDOCK is the agentic-orchestration project. [HARBORMASTER](https://github.com/roshanrana/Harbormaster) decides what a file is when it lands; DRYDOCK decides whether the code that will read it is seaworthy, and hands Harbormaster the field mapping. [LEDGERLENS](https://github.com/roshanrana/LedgerLens) consumes what both produce. [MARKETSAGE](https://github.com/roshanrana/MarketSage) exposes a workflow to models over MCP; DRYDOCK does that too, and also shows a model consuming MCP tools from inside a graph.
