# Ship report — DRYDOCK 0.1.0

**Date:** 2026-09-07 · **Decision requested:** go / no-go for publishing the repository

## 1. Gate evidence

One command validates everything, locally and in CI (`.github/workflows/check.yml`):

```
uv run python scripts/check.py
=== ruff check        All checks passed!
=== ruff format       already formatted
=== mypy              Success: no issues found
=== pytest            505 passed (TOTAL 2866 statements, 67 missed, 98 % coverage)
=== bench             wrote metrics/headline.json
=== bench drift       (git diff --exit-code) clean
=== card drift        metrics card is current
all checks passed
```

Coverage floor is 80 %; observed 98 % on `drydock/` (airflow shim excluded).

## 2. What the bench observed (fake provider, seed 42, offline)

| KPI | Value | How |
|---|---|---|
| Scenarios as declared | 6 / 6 | final run status matched each manifest's `expected_outcome` |
| First-pass rate | 1 / 6 | acme-treasury passed at iteration 1; four heal scenarios and one escalate did not |
| Healed | 4 / 4 | every heal scenario repaired and approved within the 3-iteration budget |
| Adversarial rejected | 5 / 5 | hand-written almost-right artifacts all failed their declared checks |
| Mean iterations | 2.00 | generate/evaluate iterations per run |
| Checkpoints | 59 | LangGraph checkpoints across the six runs, including each run's input checkpoint |

Defects caught by check across 12 iteration reports and 5 adversarial reports: H1 2, H2 4,
H3 6, H4 25, H5 2, H6 1. Escalations: 1 of 6 (meridian-legacy, spec contradicts sample).
Artifacts published: 5 clients. MCP tool calls made by the planner: 18, over an in-memory
MCP session. Live-provider, Docker-sandbox and real-Airflow rows are **pending** until a
recorded run exists.

## 3. Review findings and dispositions

### Code review (code-reviewer agent) — approve, 0 critical, 0 high

| Severity | Finding | Disposition |
|---|---|---|
| MEDIUM | `drydock show` printed an unbounded errors column | fixed: capped at 3 findings with a `--json` hint |
| LOW | `SandboxTimeout` defined but never raised | documented: timeouts are reported via `SandboxResult.timed_out` |

### Security review (security-reviewer agent) — 3 critical, 4 high, 2 medium before T-012

| ID | Finding | Disposition |
|---|---|---|
| C1 | AST guard bypass via module attribute hop (`os.path` → `os.system`) | closed (T-012): attribute/name denylists in `harness/guard.py`; `os.path` removed from the allowlist; the payload is now a guard finding and never executes |
| C2 | Unrestricted reads outside the workdir; content reached harness evidence and repair prompts | closed (T-012): the runner installs a jailed `open`/`io.open` before importing the pipeline; reads outside the scratch workdir raise `PermissionError`; the marker string appears nowhere in the report |
| C3 | Prompt-injection path from spec prose to generated code | generator prompt now states the boundary; the guard and jail are independent of the model |
| H1 | No filesystem confinement in subprocess mode | mitigated (T-012): runtime jail (jailed open, capability-stripped `os`, poisoned modules, import finder) plus process-group kill; not an OS-level boundary, Docker mode is, see `docs/security.md` |
| H2 | Docker mount read-write, no cap/pids/memory limits | closed (T-012): `/work` mounted read-only, separate writable `/out`, `--cap-drop ALL --pids-limit 64 --memory 512m --read-only --network none` |
| H3 | Timeout killed only the direct child | closed (T-012): `Popen` in a new process group / session; `taskkill /T /F` on Windows, `killpg(SIGKILL)` on POSIX; escape test asserts the tree is gone |
| H4 | No memory cap on Windows | mitigated (T-012): Windows Job Object memory cap (512 MiB) via ctypes, best-effort with the wall-clock timeout as backstop; POSIX keeps `RLIMIT_AS/FSIZE/NPROC` |
| M1 | `approval.json` hashes are not a signature | documented as an audit trail in `deploy/README.md` |
| M2 | Dependency CVE audit not run offline | closed: `pip-audit` over `uv export --all-extras` on 2026-09-07 reported no known vulnerabilities |

Payload-by-payload outcomes after hardening are in `docs/security.md`.

## 4. Environment and secrets matrix

| Setting | Where | Default | Notes |
|---|---|---|---|
| `DRYDOCK_DB`, `DRYDOCK_RUNS_DIR`, `DRYDOCK_DEPLOY_DIR`, `DRYDOCK_CORPUS_ROOT` | CLI global options / env | `data/drydock.db`, `runs/`, `deploy/`, `corpus/` | also honoured by `drydock mcp` via `DRYDOCK_DB_PATH`/`DRYDOCK_RUNS_DIR` |
| `OPENAI_API_KEY` | env | unset | `openai_compat` backend (vLLM); Ollama config sets `api_key_env: null` |
| `VLLM_API_KEY` | env | unset | `configs/providers/vllm.yaml` |
| `ANTHROPIC_API_KEY` | env | unset | `configs/providers/anthropic.yaml` |
| AWS credential chain, `AWS_REGION` | env / profile | unset | `configs/providers/bedrock.yaml` |
| `LANGCHAIN_TRACING_V2`, `LANGCHAIN_API_KEY`, `LANGCHAIN_PROJECT` | env | off | LangSmith tracing; documented in `docs/serving.md` |

No secret is read from yaml or written to disk. The offline gate needs none of them.

## 5. Observability

- `runs/<run_id>/events.jsonl`: one line per node (`ts`, `node`, `iteration`, `ms`, `outcome`) and one `llm_usage` line per real-model call (`prompt_tokens`, `completion_tokens`, `model`, `latency_ms`).
- `runs/<run_id>/iter-N/`: the three artifacts, `report.json`, and the sandbox scratch evidence per sample.
- `drydock replay <run_id>` walks every LangGraph checkpoint; `--step N` dumps the state at that step.
- Dashboard (`drydock serve`) shows all of the above per run.

## 6. Deployment and rollback

DRYDOCK deploys nothing. `publish` writes `deploy/<client>/{pipeline.py,dag.py,mapping.yaml,approval.json}` only after a human approves through CLI, dashboard or MCP. Rollback is deleting `deploy/<client>/`; the run, its iterations and the decision remain in `data/drydock.db` and `runs/`. The optional Airflow profile (`docker compose --profile airflow up`) mounts `deploy/` read-only for one client at a time (`DRYDOCK_CLIENT`).

## 7. Known issues and honest limits

- The bench is driven by the deterministic fake provider. It measures the harness and the loop, not any model's code quality. Live-provider accuracy is pending.
- `subprocess` sandbox mode is the offline default. After T-012 it has a static guard, a runtime jail and process-group kill, but it is not an OS-level isolation boundary; Docker mode adds read-only mounts, dropped capabilities and memory/pid limits. Residual risks are listed in `docs/security.md`.
- Dependency audit (`pip-audit`, 2026-09-07) found no known vulnerabilities; it is not part of the offline gate because it needs the network.
- The Airflow profile runs one published client per invocation because every generated module is named `pipeline`.
- The corpus is synthetic; six clients and five adversarial cases.

## 8. Recommendation

**Go.** The offline gate is green in one command on Windows and (via CI) Linux, every published number is observed by the bench, both reviews are dispositioned, and the residual limits are written down where a reader will find them. Publish `roshanrana/drydock` and add it to the profile README.
