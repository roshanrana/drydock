# STATE — DRYDOCK

**Phase:** 4 → 5 (guardrails done, implementation waves running)
**Gate command:** `uv run python scripts/check.py` (or `make check`)
**Updated:** 2026-09-07

## Now / next

- Now: Wave 2 (T-005 graph, T-006 dashboard, T-007 MCP server) running in parallel; T-008 done early.
- Next: Wave 3 (T-009 bench, T-010 Airflow profile), then T-011 ship.

## Task log

| Task | Status | Notes |
|---|---|---|
| T-000 | done | scaffold, models.py, check.py, CI, Makefile, card.json |
| T-001 | done | corpus: 6 clients, 5 adversarial, 80 tests |
| T-002 | done | harness: 6 checks, sandbox, shim, 74 tests |
| T-003 | done | providers: fake/templates/LLM/backends, 96 tests |
| T-004 | done | MCP sources server + toolbox, 81 tests |
| T-005 | in_progress | |
| T-006 | in_progress | |
| T-007 | in_progress | |
| T-008 | done | README body, serving.md, runbook.md |
| T-009 | todo | |
| T-010 | todo | |
| T-011 | todo | |

## Deviations

- ADR-000: design gates self-approved under the owner's autonomy instruction.
- ADR-007: four Wave 1 integration defects fixed by the orchestrator (tool kwarg, escalate pin, wrong_slice, adversarial split).

## Blockers

- none
