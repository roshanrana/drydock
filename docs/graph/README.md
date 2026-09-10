# Code graph

drydock carries a queryable code knowledge graph built with [graphify](https://pypi.org/project/graphifyy/)
(tree-sitter over the AST, no LLM required). It answers "what depends on this?", "how do A and B
connect?", and "what is X?" with file:line citations in a few hundred tokens, which is cheaper and
more precise than grepping the tree cold. Agents working in this repo should query the graph before
opening files for a task; see `.claude/skills/graphify/SKILL.md` and the `graphify` section in the
root `CLAUDE.md` for the standing rule.

## Build and query

```bash
# rebuild after code changes (AST only, no API key, seconds)
graphify update .

# ask a question about the codebase, get a scoped subgraph
graphify query "<question>" --budget 800

# focus on one symbol or file
graphify explain "<core class or module>"

# shortest relationship path between two symbols
graphify path "<entry point>" "<storage or external boundary>"

# everything that depends on a shared symbol, before you change it
graphify affected "<symbol>" --depth 2
```

`make graph` runs `graphify update . && graphify cluster-only . --no-viz --no-label` for a quick
refresh without opening the HTML viewer.

## Three real queries

### `graphify explain "graph_service_runservice"`

`RunService` is defined twice in this repo (`drydock/bench.py` and `drydock/graph/service.py`);
`graphify explain "RunService"` resolves to the `bench.py` copy by name match. The LangGraph
service module facade needed the graph's internal node id instead:

```
Node: RunService
  ID:        graph_service_runservice
  Source:    drydock/graph/service.py L95
  Type:      code
  Community: 20
  Degree:    87

Connections (87):
  --> PipelineArtifact [uses] [INFERRED]
  --> HarnessReport [uses] [INFERRED]
  --> CheckId [uses] [INFERRED]
  --> FeedSpec [uses] [INFERRED]
  --> DrydockError [uses] [INFERRED]
  --> RunStore [uses] [INFERRED]
  --> RunRecord [uses] [INFERRED]
  --> RunStatus [uses] [INFERRED]
  --> IngestionPlan [uses] [INFERRED]
  --> Severity [uses] [INFERRED]
  --> CheckResult [uses] [INFERRED]
  --> Finding [uses] [INFERRED]
  <-- test_graph.py [imports] [EXTRACTED]
  --> InvalidTransition [uses] [INFERRED]
  --> McpToolBox [uses] [INFERRED]
  --> ColumnSpec [uses] [INFERRED]
  --> SourceFormat [uses] [INFERRED]
  ... and 71 more
```

Degree 87 makes `RunService` the de facto god node of the run pipeline — every surface (CLI,
dashboard, MCP server) goes through it.

### `graphify path "build()" "run_in_sandbox"`

```
Shortest path (3 hops):
  build() --calls [EXTRACTED]--> DrydockError <--inherits [EXTRACTED]-- SandboxError <--calls [EXTRACTED]-- run_in_sandbox()
```

### `graphify affected "drydock_models_harnessreport" --depth 2`

```
Affected nodes for HarnessReport
Relations: calls, references, imports, imports_from, re_exports, inherits, extends, implements, uses, mixes_in, embeds
Depth: 2
- bench.py [imports] drydock/bench.py:L1
- RunOutcome [uses] drydock/bench.py:L80
- AdversarialOutcome [uses] drydock/bench.py:L121
- CheckId [uses] drydock/bench.py:L130
- BenchResult [uses] drydock/bench.py:L140
- HarnessReport [uses] drydock/bench.py:L149
- Path [uses] drydock/bench.py:L160
- SandboxKind [uses] drydock/bench.py:L160
- RunService [uses] drydock/bench.py:L160
- RunStore [uses] drydock/bench.py:L177
- Echo [uses] drydock/bench.py:L192
- AdversarialCase [uses] drydock/bench.py:L226
- Counter [uses] drydock/bench.py:L370
- Any [uses] drydock/bench.py:L374
- PipelineArtifact [uses] drydock/bench.py:L401
- app.py [imports] drydock/dashboard/app.py:L1
- RunStoreLike [uses] drydock/dashboard/app.py:L36
  ... (547 lines total)
```

`HarnessReport` is a frozen contract (`drydock/models.py`) shared by the harness, bench, dashboard,
MCP, and graph modules, so `--depth 2` pulls in essentially every symbol declared in each importing
file, not just the direct dependents. For a contract this central, `--depth 1` or a narrower
`graphify query` is the more useful first look; `affected --depth 2` is best reserved for smaller,
less-central symbols.

## What the graph got wrong

Two rough edges worth knowing about:

- **Name collisions resolve silently.** `RunService` exists in both `drydock/bench.py` and
  `drydock/graph/service.py`; `graphify explain "RunService"` (and `graphify path` matches, which
  print an explicit "target match was ambiguous" warning) pick one without asking. When a symbol
  name is reused, query by the graph's internal node id (visible in `graphify-out/graph.json` or an
  earlier `explain`/`affected` result) rather than the bare name.
- **`path` prefers shared exception types over the real call chain.** The path from the CLI's
  `build()` command to `run_in_sandbox()` in the harness sandbox runner routes through the
  `DrydockError`/`SandboxError` hierarchy (both raise/catch it) rather than through
  `RunService` → `harness/runner.py` → `harness/sandbox.py`, which is how the code actually calls
  into the sandbox. Treat a `path` result as *a* relationship, not necessarily the call graph you
  expect — cross-check with `explain` on the intermediate nodes when the path looks surprising.

## Counts and build time

- 1734 nodes, 5782 edges, 80 communities (`graphify-out/GRAPH_REPORT.md`, tree-sitter AST only, no
  LLM/API cost)
- Incremental `graphify update .` on this repo: ~7 seconds

## What is excluded

`.graphifyignore` excludes: `.venv/`, `graphify-out/`, `corpus/` (synthetic client fixtures),
`runs/` (per-run artifacts), `deploy/` (approved-artifact output), `data/` (the runtime database),
`tests/fixtures/`, and `uv.lock`. This keeps the graph about the shipped `drydock/` package and its
tests, not generated data or vendored lock content.

## Hooks (local opt-in, not committed)

`graphify install --project` (already run once for this repo) also offers PreToolUse hooks that
intercept `Read`/`Grep`/`Glob` calls and remind the agent to query the graph first. Those hooks are
per-machine, not part of this repo's `.claude/settings.json` — regenerate them locally with
`graphify install --project --platform claude` if you want them; they are intentionally excluded
from version control here.

## Shipyard integration

Implementers query the graph (`graphify query`/`explain`) before opening files listed in a task
pack. Verifiers run `graphify affected "<symbol>" --depth 2` on every symbol a diff touches and
flag anything outside the pack's declared scope as a finding.
