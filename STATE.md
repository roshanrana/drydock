# STATE — DRYDOCK

**Phase:** 5 → 6 (implementation complete except bench; validation and hardening)
**Gate command:** `uv run python scripts/check.py` (or `make check`)
**Updated:** 2026-09-07

## Now / next

- Now: T-009 bench + code/security review running in parallel. Repo gate steps 1-3 green: 455 tests, 99 % coverage.
- Next: T-011 ship report, CI on GitHub.

## Task log

| Task | Status | Notes |
|---|---|---|
| T-000 | done | scaffold, models.py, check.py, CI, Makefile, card.json |
| T-001 | done | corpus: 6 clients, 5 adversarial, 80 tests |
| T-002 | done | harness: 6 checks, sandbox, shim, 74 tests |
| T-003 | done | providers: fake/templates/LLM/backends, 96 tests |
| T-004 | done | MCP sources server + toolbox, 81 tests |
| T-005 | done | graph/store/service/CLI, 66 tests, real interrupt gate |
| T-006 | done | dashboard API + trace viewer, 25 tests |
| T-007 | done | DRYDOCK MCP server, 7 tools, docs/mcp.md |
| T-008 | done | README body, serving.md, runbook.md |
| T-009 | in_progress | |
| T-010 | done | Airflow compose profile validated, deploy/README |
| T-011 | in_progress | reviewers running |

## Deviations

- ADR-000: design gates self-approved under the owner's autonomy instruction.
- ADR-007: four Wave 1 integration defects fixed by the orchestrator (tool kwarg, escalate pin, wrong_slice, adversarial split).

## Blockers

- none
