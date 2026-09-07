# STATE — DRYDOCK

**Phase:** 7 — shipped. `uv run python scripts/check.py` green: 505 tests, 98 % coverage, bench and card drift clean.
**Gate command:** `uv run python scripts/check.py` (or `make check`)
**Updated:** 2026-09-07

## Now / next

- Now: shipped to GitHub (`roshanrana/drydock`); CI runs the same gate.
- Next (backlog, none load-bearing): record a live-provider run (Ollama) and publish it as a recorded figure; Docker-sandbox and real-Airflow bench rows; HMAC-signed approvals; add DRYDOCK to the profile README.

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
| T-009 | done | bench: 6/6 scenarios, 5/5 adversarial, 59 checkpoints; card rendered |
| T-010 | done | Airflow compose profile validated, deploy/README |
| T-011 | done | reviews dispositioned, pip-audit clean, ship report, GitHub |
| T-012 | done | three-layer sandbox; 25 escape tests; docs/security.md |

## Deviations

- ADR-000: design gates self-approved under the owner's autonomy instruction.
- ADR-007: four Wave 1 integration defects fixed by the orchestrator (tool kwarg, escalate pin, wrong_slice, adversarial split).

## Blockers

- none
