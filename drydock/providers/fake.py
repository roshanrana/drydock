"""FakeProvider: deterministic, offline, template-driven planning and generation.

The corpus scenarios drive it through a ``fault_plan`` (client -> defect id or None): on
iteration 1 the named defect is injected into the rendered code so the harness has
something real to catch; from iteration 2 the clean template is emitted with a repair note
that names the failed check. No randomness, no network, no model.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from drydock.models import FeedSpec, HarnessReport, IngestionPlan, PipelineArtifact
from drydock.providers import ProviderError, ToolBox, templates

EVIDENCE_TOOLS: tuple[str, str, str] = ("list_samples", "peek_sample", "profile_sample")


@dataclass(frozen=True)
class Evidence:
    """What the planner learned from the MCP tools, in call order."""

    sample_name: str
    samples: dict[str, Any]
    peek: dict[str, Any]
    profile: dict[str, Any]
    tool_calls: tuple[str, ...] = EVIDENCE_TOOLS

    def as_prompt_context(self) -> dict[str, Any]:
        return {
            "sample_name": self.sample_name,
            "list_samples": self.samples,
            "peek_sample": self.peek,
            "profile_sample": self.profile,
        }


def first_sample_name(result: Any) -> str | None:
    """Pull the first sample file name out of a ``list_samples`` result, whatever its shape."""
    items: Any = result
    if isinstance(result, dict):
        items = result.get("samples", result.get("names", result.get("files", [])))
    if not isinstance(items, list) or not items:
        return None
    first = items[0]
    if isinstance(first, str):
        return first
    if isinstance(first, dict):
        name = first.get("name", first.get("path"))
        return str(name) if name is not None else None
    return None


def collect_evidence(spec: FeedSpec, tools: ToolBox) -> Evidence:
    """Call list_samples, peek_sample, profile_sample (in that order) for the spec's client."""
    samples = _checked(EVIDENCE_TOOLS[0], tools.call(EVIDENCE_TOOLS[0], client=spec.client))
    name = first_sample_name(samples) or spec.feed_name
    peek = _checked(EVIDENCE_TOOLS[1], tools.call(EVIDENCE_TOOLS[1], client=spec.client, name=name))
    profile = _checked(
        EVIDENCE_TOOLS[2], tools.call(EVIDENCE_TOOLS[2], client=spec.client, name=name)
    )
    return Evidence(sample_name=name, samples=samples, peek=peek, profile=profile)


def _checked(tool: str, result: dict[str, Any]) -> dict[str, Any]:
    """MCP tools report failures as ``{"error": ...}``; planning must not proceed on them."""
    if "error" in result:
        raise ProviderError(f"MCP tool {tool} failed: {result['error']}")
    return result


def parse_options_from_spec(spec: FeedSpec) -> dict[str, Any]:
    return {
        "delimiter": spec.delimiter,
        "encoding": spec.encoding,
        "header_rows": spec.header_rows,
        "trailer_rows": spec.trailer_rows,
        "skip_blank_lines": spec.skip_blank_lines,
    }


def validations_from_spec(spec: FeedSpec) -> tuple[str, ...]:
    """Human-readable rules the generated pipeline must satisfy (mirrors LLD section 3)."""
    rules = [
        "transform() output rows have exactly CANONICAL_COLUMNS as keys, in order",
        "value_date is ISO-8601 (YYYY-MM-DD)",
        r"amount matches ^-?\d+\.\d{2}$ with no thousands separator",
        "currency matches ^[A-Z]{3}$",
    ]
    if spec.expected_row_count is not None:
        rules.append(
            f"the sample yields exactly {spec.expected_row_count} rows after skipping "
            f"{spec.header_rows} header and {spec.trailer_rows} trailer line(s)"
        )
    return tuple(rules)


def repair_note(report: HarnessReport | None) -> str:
    if report is None:
        return "Regenerated clean template (no harness report supplied)."
    errors = report.errors
    if not errors:
        return "Regenerated clean template (previous report had no failing checks)."
    return (
        f"Repair after {errors[0].check.value}: regenerated clean template ({errors[0].message})."
    )


class FakeProvider:
    """Template provider with scenario-declared fault injection."""

    name = "fake"

    def __init__(self, fault_plan: Mapping[str, str | None] | None = None) -> None:
        self._fault_plan: Mapping[str, str | None] = dict(fault_plan or {})

    def defect_for(self, client: str) -> str | None:
        return self._fault_plan.get(client)

    def plan(self, spec: FeedSpec, tools: ToolBox) -> IngestionPlan:
        evidence = collect_evidence(spec, tools)
        return IngestionPlan(
            client=spec.client,
            feed_name=spec.feed_name,
            format=spec.format,
            parse_options=parse_options_from_spec(spec),
            column_map=spec.columns,
            validations=validations_from_spec(spec),
            schedule_cron=spec.schedule_cron,
            rationale=(
                f"Deterministic template plan for a {spec.format.value} feed; "
                f"sample '{evidence.sample_name}' listed, peeked and profiled for evidence."
            ),
            tool_calls=evidence.tool_calls,
        )

    def generate(
        self,
        plan: IngestionPlan,
        spec: FeedSpec,
        *,
        iteration: int,
        seed: int,
        previous: PipelineArtifact | None,
        report: HarnessReport | None,
    ) -> PipelineArtifact:
        pipeline_py, dag_py, mapping_yaml = templates.render_all(plan)
        defect = self.defect_for(plan.client) if iteration == 1 else None
        if defect is not None:
            pipeline_py, dag_py = templates.inject_defect(pipeline_py, dag_py, defect)
        notes = f"Rendered from template (seed={seed})." if iteration == 1 else repair_note(report)
        return PipelineArtifact(
            pipeline_py=pipeline_py,
            dag_py=dag_py,
            mapping_yaml=mapping_yaml,
            iteration=iteration,
            generator=self.name,
            notes=notes,
        )
