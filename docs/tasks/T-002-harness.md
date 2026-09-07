# T-002 — Harness: sandbox, six checks, Airflow shim

**Wave:** 1 · **Depends on:** T-000 · **Status:** in_progress

## Goal
The deterministic judge. Runs a generated pipeline in a sandbox against sample files and
returns a `HarnessReport` with per-check findings. It must be impossible for generated code
to pass by cheating (no oracle access, no network, no writes).

## Read first
- `drydock/models.py` (PipelineArtifact, HarnessReport, CheckResult, Finding, CheckId, Severity, SampleProfile, FeedSpec, CANONICAL_COLUMNS)
- `docs/design/03-lld.md` §3 (contract), §4 (harness procedure and check table), §8 (errors: SandboxError, SandboxTimeout — define them locally in `drydock/harness/sandbox.py` if `drydock/errors.py` does not exist yet, then re-export; T-001 owns `errors.py`, coordinate via handoff note)

## Scope (only these files)
- `drydock/harness/__init__.py`, `sandbox.py`, `runner.py`, `checks.py`
- `drydock/harness/airflow_shim/airflow/__init__.py`, `airflow_shim/airflow/operators/__init__.py`, `airflow_shim/airflow/operators/python.py`
- `tests/test_harness.py`, `tests/fixtures/pipelines/**` (your own minimal spec + sample + good/bad pipelines; do NOT depend on `corpus/`, it is being written concurrently)
- `tests/fixtures/manifest_stub.py` if you need a helper to build a `Manifest`-like object: the LLD `Manifest` type lives in `drydock/corpus.py` (T-001). Until it lands, `evaluate` should accept any object with `.samples: Sequence[SampleProfile]`; type it as a small `Protocol` named `ManifestLike` inside `drydock/harness/__init__.py`.

## Acceptance criteria
1. `evaluate(...)` signature exactly as LLD §4; returns `HarnessReport` with six `CheckResult`s in CheckId order, `passed = all(no ERROR findings)`.
2. `runner.py` is stdlib only, runs with `python -I`, imports `pipeline.py` via importlib, writes `out.json` rows and `dag_out.json` structure; the shim records `dag_id`, `schedule`, task ids, and `>>` edges.
3. Static guard: AST allowlist per LLD §4; `import socket`, `import requests`, `open(x, "w")`, `subprocess` → H1 error with `evidence.forbidden_import` / `forbidden_call`, and the code is **not executed**.
4. Each check has a fixture that fails exactly that check and nothing else (H2: wrong amount format `1250` not `1250.00`; H3: drop last row; H4: sign flipped on one row so sum differs; H5: `time.sleep(6)` with budget 5000 ms — use a smaller budget in the test, e.g. 200 ms with a 0.3 s sleep, so tests stay fast; H6: missing `transform >> load` edge).
5. Timeout → H1 error with `evidence.timed_out = true`; `SandboxResult.timed_out`.
6. Docker kind implemented per LLD §4; test skipped when `shutil.which("docker")` is None.
7. Works on Windows and Linux (no `resource` without guard; `sys.executable` for the interpreter; env limited to `PATH`, `SYSTEMROOT` on Windows, `PYTHONIOENCODING=utf-8`).
8. `ruff`, `ruff format --check`, `mypy drydock/harness`, `pytest tests/test_harness.py` green; harness coverage ≥ 85 % excluding the shim.

## Validation
```
uv run ruff check drydock/harness tests/test_harness.py && uv run ruff format --check drydock/harness tests
uv run mypy drydock/harness
uv run pytest tests/test_harness.py -q --cov=drydock.harness --cov-report=term-missing
```

## Handoff notes (≤10 lines)
