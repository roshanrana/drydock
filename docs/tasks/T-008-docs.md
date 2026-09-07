# T-008 — Documentation: README body, serving guide, runbook

**Wave:** 2 · **Depends on:** T-000 (design docs) · **Status:** done

## Goal
An interviewer reads the README and understands the problem, the architecture, the
guarantees and how to run it in five minutes. `docs/serving.md` shows the local-versus-cloud
model story with a data-perimeter table. `docs/runbook.md` is what an operator would use.

## Read first
- `docs/design/01-requirements.md`, `02-hld.md`, `03-lld.md` §3, §4, §5, §6, §7.4, §10; `decisions.md`
- Sibling READMEs for house style (open and read fully): `C:\Code-Central\LedgerLens\README.md`, `C:\Code-Central\harbormaster\README.md`, `C:\Code-Central\roshanrana\README.md`. Match their register: plain, measured, no marketing adjectives, "measured, not claimed".
- `metrics/render.py` docstring: the README must keep the `<!-- metrics:start -->`/`<!-- metrics:end -->` markers exactly where they are (the block between them is generated; do not hand-write inside it).

## Scope (only these files)
- `README.md` (everything outside the metrics markers), `docs/serving.md`, `docs/runbook.md`, `corpus/README.md` (only if T-001 has not written it; otherwise leave it)

## Acceptance criteria
1. README sections, in order: title + one-line thesis (keep the existing two paragraphs, tighten if needed); "At a glance" table (problem / what it does / stack / validation) in the sibling style; the metrics block (untouched markers); "How it works" with an ASCII graph diagram (from HLD §2) and a numbered walk-through of the five critical flows (HLD §5); "What the harness checks" table H1–H6; "Guarantees" (bounded loop, human gate cannot be disabled, sandbox, data perimeter, deterministic bench); "Run it" (`uv sync`, `uv run drydock build acme-treasury`, `approve`, `serve`, `mcp`, `bench`, `python scripts/check.py`; note Windows has no make); "Local or cloud models" (short, link to docs/serving.md); "Repository map"; "Relationship to sibling repos" (Harbormaster consumes the mapping.yaml; LedgerLens downstream; one sentence each); "Honest limits" (synthetic corpus, fake provider drives the bench, live-model rows pending, Airflow stub); License.
2. `docs/serving.md`: provider matrix (fake / Ollama / vLLM / Bedrock / Anthropic) with config file, env var names, how to start each (Ollama pull command, vLLM docker one-liner with OpenAI-compatible server, Bedrock IAM note), a **data perimeter table** listing exactly what leaves the process per provider (spec yaml, column profiles, ≤5 peeked rows, previous artifact, harness findings; never full sample files, never deploy/ contents), LangSmith tracing toggle (`LANGCHAIN_TRACING_V2`, `LANGCHAIN_API_KEY`, `LANGCHAIN_PROJECT=drydock`) with a note that trace links are added to the ship report only once a recorded run exists, and token-usage recording in `runs/<id>/events.jsonl`.
3. `docs/runbook.md`: start/approve/reject/replay procedures, where state lives (`data/drydock.db`, `runs/`, `deploy/`), how to reset, how to run with Docker sandbox, how to run the Airflow profile (`docker compose --profile airflow up`, dags folder mounted from `deploy/`), troubleshooting (timeout, forbidden import, escalated run), and the bounded-loop invariants an operator can rely on.
4. No claims of measured numbers anywhere outside the generated metrics block. Where a number is not yet observed, say "pending" explicitly.
5. All internal links resolve to files that exist or are scheduled (docs/mcp.md from T-007, docs/ship-report.md from T-011 — mark those two as "written at ship").
6. Markdown renders cleanly; lines ≤ 120 chars; no emoji.

## Validation
```
uv run python metrics/render.py --check   # may report stale until T-009 writes headline.json; must NOT error on missing markers
grep -c "metrics:start" README.md          # exactly 1
```

## Handoff notes (≤10 lines)
- Written: README.md (body outside the metrics markers; markers and empty block untouched),
  docs/serving.md, docs/runbook.md. corpus/README.md left to T-001. No code touched. LF endings.
- `uv run python metrics/render.py --check` (exit 1): FileNotFoundError: [Errno 2] No such file or directory: 'C:\\Code-Central\\drydock\\metrics\\headline.json'
  metrics/headline.json does not exist until T-009 runs the bench; not a marker error.
  Marker check done directly: render.splice(README) -> splice ok.
- `grep -c "metrics:start" README.md` -> 1
- Links to docs/mcp.md (T-007), docs/ship-report.md (T-011) marked 'written at ship';
  deploy/README.md and docker-compose.yml referenced as written with T-010.
- No measured numbers outside the generated block; live-provider, Docker and Airflow rows say pending.
- All lines <= 120 chars, no emoji, ASCII only.
