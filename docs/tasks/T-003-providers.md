# T-003 — Providers: fake, templates, LLM, backends, configs

**Wave:** 1 · **Depends on:** T-000 · **Status:** done

## Goal
One `Provider` protocol, two implementations. `FakeProvider` is deterministic, offline,
template-driven with scenario-declared fault injection and repair. `LLMProvider` runs the
same prompts against any `ChatBackend` (Ollama/vLLM via OpenAI-compatible HTTP, Bedrock,
Anthropic) with structured JSON output and validation.

## Read first
- `drydock/models.py` (FeedSpec, ColumnSpec, IngestionPlan, PipelineArtifact, HarnessReport, Finding, CANONICAL_COLUMNS, SourceFormat)
- `docs/design/03-lld.md` §3 (what generated code must look like), §5 (provider/backend contracts, config yaml), §2.2 (defect ids)

## Scope (only these files)
- `drydock/providers/__init__.py`, `fake.py`, `templates.py`, `llm.py`, `backends.py`, `prompts.py`
- `configs/providers/{fake,ollama,vllm,bedrock,anthropic}.yaml`
- `tests/test_providers.py`, `tests/test_backends.py`, `tests/test_templates.py`
- If `drydock/errors.py` does not exist yet (T-001 owns it), define `ProviderError` in `drydock/providers/__init__.py` and note it in Handoff so T-001/T-005 can consolidate.

## Acceptance criteria
1. `templates.render_pipeline(plan)` emits stdlib-only Python implementing LLD §3 exactly for all three `SourceFormat`s: header/trailer skipping, delimiter, encoding, thousands separators stripped, `Decimal` quantized to 2 dp, date reformat via `date_format`, sign column with `negative_marker`, fixed-width slices `"a:b"`, jsonl keys, dropped columns (`target=None`), `default` values. Output keys exactly `CANONICAL_COLUMNS` in order. **Test it by exec-ing the rendered module in-process on small inline samples** for each format and asserting rows.
2. `render_dag(plan)` emits a DAG that imports only what §3 allows, with `dag_id`, `schedule`, three `PythonOperator`s and `extract >> transform >> load`. `render_mapping(plan)` emits yaml per §3.
3. `templates.inject_defect(pipeline_py, dag_py, defect_id)` implements all six defect ids from LLD §2.2 as targeted string/AST edits that produce *plausible* buggy code (e.g. swap `%d/%m/%Y` for `%m/%d/%Y`; skip trailer_rows=0; shift a slice by one; ignore sign column; keep the comma in amounts; delete `transform >> load`). Unknown id → `ProviderError`.
4. `FakeProvider(fault_plan).plan()` calls `tools.call` for `list_samples`, `peek_sample`, `profile_sample` (in that order) and records them in `IngestionPlan.tool_calls`; `parse_options` and `column_map` per §5. `generate()` applies the defect on iteration 1 only; on iteration ≥ 2 with a report emits clean code and `notes` mentioning the failed check id.
5. `LLMProvider`: prompts in `prompts.py`; parses JSON with or without code fences; validates with Pydantic; retries once on `ValidationError`/`JSONDecodeError` appending the error to the user prompt; raises `ProviderError` after that. Unit-tested with a scripted `ChatBackend` (returns canned strings), including the retry path. `on_usage` callback fires per call.
6. Backends: `OpenAICompatBackend(base_url, model, api_key)` posting to `/chat/completions` with `httpx.Client` injectable for tests (use `httpx.MockTransport`); `BedrockBackend(model_id, region)` using `boto3` `converse` behind a lazy import, tested with a fake client object; `AnthropicBackend(model)` behind lazy import, tested with a fake client. Missing optional dependency → `ProviderError("install drydock[bedrock]")`.
7. `load_provider(name, fault_plan=...)` reads `configs/providers/<name>.yaml`; `fake` needs no env; others resolve `api_key_env` and raise `ProviderError` naming the variable when absent. Yaml never contains secrets.
8. `ruff`, `ruff format --check`, `mypy drydock/providers`, tests green; providers coverage ≥ 85 %.

## Validation
```
uv run ruff check drydock/providers tests && uv run ruff format --check drydock/providers tests
uv run mypy drydock/providers
uv run pytest tests/test_providers.py tests/test_backends.py tests/test_templates.py -q --cov=drydock.providers --cov-report=term-missing
```

## Handoff notes (≤10 lines)
1. Validation 2026-09-07: `ruff check` + `ruff format --check` -> "All checks passed! / 14 files already formatted"; `mypy drydock/providers` -> "Success: no issues found in 6 source files"; pytest -> `96 passed`, coverage `TOTAL 495 stmts, 7 miss, 99%` (fake.py 100%, others 97-99%).
2. `ProviderError` lives in `drydock/providers/__init__.py` because `drydock/errors.py` does not exist yet; T-001/T-005 should re-export or alias it from `drydock.errors` rather than define a second class.
3. T-005 wiring: `load_provider(name, fault_plan=..., on_usage=cb)`; build `fault_plan` as `{client: manifest["scenario"]["injected_defect"]}` from every `corpus/<client>/manifest.json` (`null` -> no defect). `FakeProvider(fault_plan)` also works directly: defect is applied on iteration 1 only, iteration >= 2 renders clean code with `notes` naming `report.errors[0].check`.
4. `on_usage` is an optional kwarg on both `load_provider` and `LLMProvider(...)`; it fires once per backend call (retries included) with `{"prompt_tokens","completion_tokens","model","latency_ms"}` (`llm.UsageRecord`). `FakeProvider` never fires it.
5. Planner evidence calls (both providers): `tools.call("list_samples", client=)`, then `tools.call("peek_sample", client=, sample=<first name>)`, `tools.call("profile_sample", client=, sample=)`. The kwarg is `sample`, not `name`, because `ToolBox.call(name, **kw)` reserves `name`; T-004's tools should accept `sample`, or T-005's toolbox should map it.
6. Generated `dag.py` uses `with DAG(dag_id=, schedule=, start_date=datetime(2026, 1, 1), catchup=False) as dag:` plus `op_kwargs={"path": ...}`; the harness airflow shim must accept these kwargs and support the context manager.
7. Backends: Anthropic and Bedrock adapters deliberately omit `temperature` (current Claude models reject sampling params); only OpenAI-compat sends it. `ollama.yaml` sets `api_key_env: null` (no env var); vllm needs `VLLM_API_KEY`, anthropic `ANTHROPIC_API_KEY`, bedrock uses the AWS credential chain. `load_provider` builds SDK clients lazily, so loading anthropic/bedrock never imports the SDK.
8. `inject_defect` raises `ProviderError(... not applicable)` when the plan has nothing to break (e.g. `wrong_slice` on CSV, `trailer_not_skipped` with `trailer_rows=0`); corpus fault plans must match their specs or the run fails loudly instead of passing by accident.
