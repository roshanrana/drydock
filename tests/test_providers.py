"""FakeProvider, LLMProvider (scripted backend) and load_provider. No network, no corpus."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from drydock.models import (
    CheckId,
    CheckResult,
    ColumnSpec,
    FeedSpec,
    Finding,
    HarnessReport,
    IngestionPlan,
    PipelineArtifact,
    Severity,
    SourceFormat,
)
from drydock.providers import (
    DEFAULT_CONFIG_DIR,
    ProviderError,
    load_provider,
    read_provider_config,
)
from drydock.providers.backends import (
    AnthropicBackend,
    BedrockBackend,
    OpenAICompatBackend,
    ScriptedBackend,
)
from drydock.providers.fake import FakeProvider, collect_evidence, first_sample_name, repair_note
from drydock.providers.llm import LLMProvider, UsageRecord, parse_json_object, strip_fences

SPEC = FeedSpec(
    client="acme-treasury",
    feed_name="daily_cash",
    format=SourceFormat.CSV,
    delimiter="|",
    header_rows=1,
    trailer_rows=1,
    columns=(
        ColumnSpec(source="TradeRef", target="trade_id"),
        ColumnSpec(source="Account", target="account_id"),
        ColumnSpec(source="ValueDate", target="value_date", dtype="date", date_format="%d/%m/%Y"),
        ColumnSpec(
            source="Amount",
            target="amount",
            dtype="decimal",
            sign_column="DrCr",
            negative_marker="DR",
        ),
        ColumnSpec(source="DrCr", target=None),
        ColumnSpec(source="Ccy", target="currency"),
        ColumnSpec(source="Cpty", target="counterparty"),
        ColumnSpec(source="Narrative", target="description"),
    ),
    expected_row_count=12,
    quirks=("Amounts carry thousands separators.",),
)

FAILED_REPORT = HarnessReport(
    iteration=1,
    passed=False,
    checks=(
        CheckResult(check=CheckId.RUNTIME, passed=True),
        CheckResult(
            check=CheckId.COMPLETENESS,
            passed=False,
            findings=(
                Finding(
                    check=CheckId.COMPLETENESS,
                    severity=Severity.ERROR,
                    message="expected 12 rows, got 13",
                ),
            ),
        ),
    ),
    rows_emitted=13,
)


class FakeToolBox:
    """In-memory ToolBox that records calls and returns canned MCP-style results."""

    def __init__(self, samples: Any = None) -> None:
        self.calls: list[str] = []
        self.arguments: list[dict[str, Any]] = []
        self._samples = (
            samples
            if samples is not None
            else {"samples": [{"name": "daily_cash_2026-09-01.csv", "bytes": 1234}]}
        )

    def call(self, name: str, /, **arguments: Any) -> dict[str, Any]:
        self.calls.append(name)
        self.arguments.append(arguments)
        if name == "list_samples":
            return self._samples
        if name == "peek_sample":
            return {"lines": ["TradeRef|Account|ValueDate", "T1|A|03/09/2026"]}
        if name == "profile_sample":
            return {"expected_rows": 12, "amount_sum": "-1523.40"}
        raise AssertionError(f"unexpected tool {name}")


# --------------------------------------------------------------------------- #
# FakeProvider                                                                 #
# --------------------------------------------------------------------------- #


def test_fake_plan_records_tool_calls_in_order() -> None:
    tools = FakeToolBox()

    plan = FakeProvider().plan(SPEC, tools)

    assert tools.calls == ["list_samples", "peek_sample", "profile_sample"]
    assert plan.tool_calls == ("list_samples", "peek_sample", "profile_sample")
    assert tools.arguments[0] == {"client": "acme-treasury"}
    assert tools.arguments[1] == {"client": "acme-treasury", "name": "daily_cash_2026-09-01.csv"}
    assert tools.arguments[2] == tools.arguments[1]


def test_fake_plan_maps_spec_deterministically() -> None:
    plan_a = FakeProvider().plan(SPEC, FakeToolBox())
    plan_b = FakeProvider().plan(SPEC, FakeToolBox())

    assert plan_a == plan_b
    assert plan_a.client == "acme-treasury" and plan_a.format is SourceFormat.CSV
    assert plan_a.parse_options == {
        "delimiter": "|",
        "encoding": "utf-8",
        "header_rows": 1,
        "trailer_rows": 1,
        "skip_blank_lines": True,
    }
    assert plan_a.column_map == SPEC.columns
    assert plan_a.schedule_cron == SPEC.schedule_cron
    assert any("12 rows" in rule for rule in plan_a.validations)
    assert "daily_cash_2026-09-01.csv" in plan_a.rationale


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        ({"samples": ["a.csv", "b.csv"]}, "a.csv"),
        ({"samples": [{"name": "x.txt"}]}, "x.txt"),
        ({"names": ["n.jsonl"]}, "n.jsonl"),
        (["plain.csv"], "plain.csv"),
        ({"samples": []}, None),
        ({}, None),
        ({"samples": [42]}, None),
    ],
)
def test_first_sample_name_handles_shapes(result: Any, expected: str | None) -> None:
    assert first_sample_name(result) == expected


def test_collect_evidence_falls_back_to_feed_name() -> None:
    tools = FakeToolBox(samples={"samples": []})
    evidence = collect_evidence(SPEC, tools)
    assert evidence.sample_name == "daily_cash"
    assert set(evidence.as_prompt_context()) == {
        "sample_name",
        "list_samples",
        "peek_sample",
        "profile_sample",
    }


def test_fake_generate_clean_when_no_fault() -> None:
    provider = FakeProvider()
    plan = provider.plan(SPEC, FakeToolBox())

    artifact = provider.generate(plan, SPEC, iteration=1, seed=7, previous=None, report=None)

    assert artifact.generator == "fake" and artifact.iteration == 1
    assert "TRAILER_ROWS = 1" in artifact.pipeline_py
    assert "extract >> transform >> load" in artifact.dag_py
    assert "seed=7" in artifact.notes


def test_fake_generate_injects_defect_on_iteration_one_only() -> None:
    provider = FakeProvider({"acme-treasury": "trailer_not_skipped", "other": None})
    plan = provider.plan(SPEC, FakeToolBox())

    first = provider.generate(plan, SPEC, iteration=1, seed=0, previous=None, report=None)
    second = provider.generate(
        plan, SPEC, iteration=2, seed=0, previous=first, report=FAILED_REPORT
    )

    assert "TRAILER_ROWS = 0" in first.pipeline_py
    assert "trailer_not_skipped" not in first.notes, "the defect is never advertised"
    assert "TRAILER_ROWS = 1" in second.pipeline_py
    assert "H3_completeness" in second.notes and "expected 12 rows" in second.notes
    assert second.iteration == 2


def test_fake_generate_other_client_unaffected_by_fault_plan() -> None:
    provider = FakeProvider({"someone-else": "dag_missing_dependency"})
    plan = provider.plan(SPEC, FakeToolBox())
    artifact = provider.generate(plan, SPEC, iteration=1, seed=0, previous=None, report=None)
    assert "extract >> transform >> load" in artifact.dag_py


def test_fake_generate_dag_defect() -> None:
    provider = FakeProvider({"acme-treasury": "dag_missing_dependency"})
    plan = provider.plan(SPEC, FakeToolBox())
    artifact = provider.generate(plan, SPEC, iteration=1, seed=0, previous=None, report=None)
    assert "extract >> transform\n" in artifact.dag_py
    assert "transform >> load" not in artifact.dag_py


def test_fake_generate_unknown_defect_raises() -> None:
    provider = FakeProvider({"acme-treasury": "nonsense"})
    plan = provider.plan(SPEC, FakeToolBox())
    with pytest.raises(ProviderError, match="unknown defect"):
        provider.generate(plan, SPEC, iteration=1, seed=0, previous=None, report=None)


def test_repair_note_variants() -> None:
    passed = HarnessReport(iteration=1, passed=True, checks=())
    assert "no harness report" in repair_note(None)
    assert "no failing checks" in repair_note(passed)
    assert repair_note(FAILED_REPORT).startswith("Repair after H3_completeness")


# --------------------------------------------------------------------------- #
# LLMProvider                                                                  #
# --------------------------------------------------------------------------- #


def plan_json() -> str:
    plan = FakeProvider().plan(SPEC, FakeToolBox())
    data = plan.model_dump(mode="json")
    data["rationale"] = "model decided"
    data["tool_calls"] = []
    data["client"] = "wrong-client"
    return json.dumps(data)


def files_json(notes: str = "first cut", fenced: bool = False) -> str:
    body = json.dumps(
        {
            "pipeline_py": "```python\ndef extract(path):\n    return []\n```",
            "dag_py": "from airflow import DAG\n",
            "mapping_yaml": "client: acme-treasury\n",
            "notes": notes,
        }
    )
    return f"```json\n{body}\n```" if fenced else body


def test_llm_plan_validates_and_pins_facts() -> None:
    backend = ScriptedBackend([plan_json()], model="scripted-1")
    usage: list[UsageRecord] = []
    provider = LLMProvider(backend, "ollama", on_usage=usage.append)
    tools = FakeToolBox()

    plan = provider.plan(SPEC, tools)

    assert isinstance(plan, IngestionPlan)
    assert tools.calls == ["list_samples", "peek_sample", "profile_sample"]
    assert plan.tool_calls == ("list_samples", "peek_sample", "profile_sample")
    assert plan.client == "acme-treasury", "spec facts override the model"
    assert plan.rationale == "model decided"
    system, user = backend.requests[0]
    assert "IngestionPlan" in system and "daily_cash_2026-09-01.csv" in user
    assert '"expected_row_count": 12' in user
    assert usage == [
        {
            "prompt_tokens": backend.requests and (len(system) + len(user)) // 4,
            "completion_tokens": len(plan_json()) // 4,
            "model": "scripted-1",
            "latency_ms": 1,
        }
    ]


def test_llm_generate_strips_fences_and_builds_artifact() -> None:
    backend = ScriptedBackend([files_json(fenced=True)])
    provider = LLMProvider(backend, "vllm")
    plan = FakeProvider().plan(SPEC, FakeToolBox())

    artifact = provider.generate(plan, SPEC, iteration=1, seed=3, previous=None, report=None)

    assert isinstance(artifact, PipelineArtifact)
    assert artifact.pipeline_py == "def extract(path):\n    return []"
    assert artifact.dag_py == "from airflow import DAG"
    assert artifact.generator == "vllm" and artifact.iteration == 1
    assert artifact.notes == "first cut"
    system, user = backend.requests[0]
    assert "pipeline_py" in system and "Worked example" in user
    assert "Previous attempt" not in user


def test_llm_generate_repair_prompt_includes_previous_and_errors() -> None:
    backend = ScriptedBackend([files_json(notes="")])
    provider = LLMProvider(backend, "vllm")
    plan = FakeProvider().plan(SPEC, FakeToolBox())
    previous = PipelineArtifact(
        pipeline_py="BROKEN = True", dag_py="", mapping_yaml="", iteration=1, generator="vllm"
    )

    artifact = provider.generate(
        plan, SPEC, iteration=2, seed=3, previous=previous, report=FAILED_REPORT
    )

    _, user = backend.requests[0]
    assert "BROKEN = True" in user
    assert "H3_completeness" in user and "expected 12 rows, got 13" in user
    assert artifact.notes.startswith("Generated by scripted"), "empty notes get a default"


def test_llm_retries_once_on_invalid_json_then_succeeds() -> None:
    backend = ScriptedBackend(["not json at all", files_json()])
    usage: list[UsageRecord] = []
    provider = LLMProvider(backend, "ollama", on_usage=usage.append)
    plan = FakeProvider().plan(SPEC, FakeToolBox())

    artifact = provider.generate(plan, SPEC, iteration=1, seed=0, previous=None, report=None)

    assert artifact.notes == "first cut"
    assert len(backend.requests) == 2 and len(usage) == 2
    retry_user = backend.requests[1][1]
    assert "previous reply was rejected" in retry_user
    assert "not json at all" in retry_user
    assert "Expecting value" in retry_user or "no JSON object" in retry_user


def test_llm_retries_on_validation_error_with_details() -> None:
    backend = ScriptedBackend(['{"pipeline_py": "x"}', files_json()])
    provider = LLMProvider(backend, "ollama")
    plan = FakeProvider().plan(SPEC, FakeToolBox())

    provider.generate(plan, SPEC, iteration=1, seed=0, previous=None, report=None)

    assert "dag_py" in backend.requests[1][1], "pydantic error names the missing field"


def test_llm_raises_provider_error_after_two_failures() -> None:
    backend = ScriptedBackend(["{}", "[]"])
    provider = LLMProvider(backend, "ollama")

    with pytest.raises(ProviderError, match="plan reply failed validation after 2 attempts"):
        provider.plan(SPEC, FakeToolBox())
    assert len(backend.requests) == 2


def test_llm_backend_errors_propagate() -> None:
    provider = LLMProvider(ScriptedBackend([]), "ollama")
    with pytest.raises(ProviderError, match="no reply left"):
        provider.plan(SPEC, FakeToolBox())


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('{"a": 1}', {"a": 1}),
        ('```json\n{"a": 1}\n```', {"a": 1}),
        ('```\n{"a": 1}\n```', {"a": 1}),
        ('Sure! Here it is:\n{"a": {"b": 2}}\nHope that helps.', {"a": {"b": 2}}),
    ],
)
def test_parse_json_object_variants(text: str, expected: dict[str, Any]) -> None:
    assert parse_json_object(text) == expected


@pytest.mark.parametrize("text", ["", "no braces here", "[1, 2]", "{broken"])
def test_parse_json_object_rejects_non_objects(text: str) -> None:
    with pytest.raises(json.JSONDecodeError):
        parse_json_object(text)


def test_strip_fences_leaves_plain_text() -> None:
    assert strip_fences("  plain\n") == "plain"
    assert strip_fences("```py\nx = 1\n```") == "x = 1"


# --------------------------------------------------------------------------- #
# load_provider                                                                #
# --------------------------------------------------------------------------- #


def test_config_dir_has_five_providers() -> None:
    names = sorted(path.stem for path in DEFAULT_CONFIG_DIR.glob("*.yaml"))
    assert names == ["anthropic", "bedrock", "fake", "ollama", "vllm"]
    for path in DEFAULT_CONFIG_DIR.glob("*.yaml"):
        text = path.read_text(encoding="utf-8").lower()
        assert "sk-" not in text and "api_key:" not in text, f"{path.name} must not hold secrets"


def test_load_fake_provider_needs_no_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    provider = load_provider("fake", fault_plan={"acme-treasury": "wrong_slice"})
    assert isinstance(provider, FakeProvider)
    assert provider.defect_for("acme-treasury") == "wrong_slice"


def test_load_ollama_points_at_local_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    provider = load_provider("ollama")
    assert isinstance(provider, LLMProvider)
    assert isinstance(provider.backend, OpenAICompatBackend)
    assert provider.backend.base_url == "http://localhost:11434/v1"
    assert provider.backend.model == "qwen2.5-coder:7b"
    assert provider.backend._api_key is None


def test_load_vllm_requires_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VLLM_API_KEY", raising=False)
    with pytest.raises(ProviderError, match="VLLM_API_KEY"):
        load_provider("vllm")

    monkeypatch.setenv("VLLM_API_KEY", "dummy-local")
    provider = load_provider("vllm")
    assert isinstance(provider, LLMProvider)
    assert isinstance(provider.backend, OpenAICompatBackend)
    assert provider.backend.base_url == "http://localhost:8000/v1"
    assert provider.backend._api_key == "dummy-local"


def test_load_anthropic_and_bedrock_are_lazy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ProviderError, match="ANTHROPIC_API_KEY"):
        load_provider("anthropic")

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    def record(usage: UsageRecord) -> None:
        return None

    anthropic_provider = load_provider("anthropic", on_usage=record)
    bedrock_provider = load_provider("bedrock")

    assert isinstance(anthropic_provider, LLMProvider)
    assert isinstance(anthropic_provider.backend, AnthropicBackend)
    assert anthropic_provider.backend.model == "claude-opus-5"
    assert anthropic_provider.on_usage is record
    assert isinstance(bedrock_provider, LLMProvider)
    assert isinstance(bedrock_provider.backend, BedrockBackend)
    assert bedrock_provider.backend.region == "us-east-1"
    assert bedrock_provider.name == "bedrock"


def test_load_unknown_provider() -> None:
    with pytest.raises(ProviderError, match="no provider config for 'nope'"):
        load_provider("nope")


def write_yaml(tmp_path: Path, name: str, text: str) -> Path:
    (tmp_path / f"{name}.yaml").write_text(text, encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("backend: teleport\n", "invalid provider config"),
        ("- just\n- a list\n", "expected a mapping"),
        ("backend: openai_compat\nmodel: m\napi_key_env: null\n", "needs base_url"),
        ("backend: bedrock\nmodel: m\n", "needs region"),
        ("backend: fake\nbogus_key: 1\n", "invalid provider config"),
    ],
)
def test_load_provider_config_errors(tmp_path: Path, text: str, message: str) -> None:
    config_dir = write_yaml(tmp_path, "custom", text)
    with pytest.raises(ProviderError, match=message):
        load_provider("custom", config_dir=config_dir)


def test_read_provider_config_defaults_api_key_env(tmp_path: Path) -> None:
    config_dir = write_yaml(tmp_path, "c", "backend: openai_compat\nmodel: m\nbase_url: http://x\n")
    config = read_provider_config("c", config_dir)
    assert config.api_key_env == "OPENAI_API_KEY"
    assert config.temperature == 0.0 and config.max_tokens == 4096


def test_load_provider_passes_tuning_to_llm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MY_KEY", "abc")
    config_dir = write_yaml(
        tmp_path,
        "tuned",
        "backend: openai_compat\nmodel: m\nbase_url: http://x/v1\n"
        "api_key_env: MY_KEY\ntemperature: 0.3\nmax_tokens: 512\n",
    )
    provider = load_provider("tuned", config_dir=config_dir)
    assert isinstance(provider, LLMProvider)
    assert provider.temperature == 0.3 and provider.max_tokens == 512
    assert provider.name == "tuned"
