# T-011 — Integration, review, ship report, GitHub

**Wave:** 4 · **Depends on:** all · **Status:** todo

## Goal
Whole-repo gate green locally and in CI on GitHub; independent code and security review
findings addressed; ship report written; repository public and interview-ready.

## Steps
1. `uv run python scripts/check.py` green end to end (orchestrator).
2. Reviewer agents (parallel): code-reviewer over `drydock/`, security-reviewer over `drydock/harness`, `drydock/mcp`, `drydock/providers/backends.py`, `drydock/graph/nodes.py` (publish path). Address CRITICAL/HIGH; log MEDIUM in ship report "Known issues".
3. `docs/ship-report.md`: gate evidence (command + tail), coverage %, test count, bench KPIs, review findings and dispositions, environment/secrets matrix, observability confirmation (events.jsonl fields, LangSmith toggle), rollback (delete `deploy/<client>`, run stays in store), known issues, pending rows.
4. `STATE.md` → Phase 7 shipped; task log complete.
5. Create public GitHub repo `roshanrana/drydock`, push `main`, confirm the `check` workflow passes; add repo description and topics (langgraph, mcp, airflow, agents, fintech, human-in-the-loop).

## Handoff notes
