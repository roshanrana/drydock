# T-003 — Providers: fake, templates, LLM, backends, configs

**Wave:** 1 · **Depends on:** T-000 · **Status:** in_progress

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
