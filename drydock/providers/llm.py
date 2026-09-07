"""LLMProvider: the planner/generator prompts against any ChatBackend.

Replies must be JSON; the provider strips code fences, validates with Pydantic, retries once
with the validation error appended to the prompt, and raises ``ProviderError`` after that.
Every backend call reports usage through the optional ``on_usage`` callback, which the graph
wires to the run's events file.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any, TypedDict, TypeVar

from pydantic import BaseModel, ValidationError

from drydock.models import FeedSpec, Frozen, HarnessReport, IngestionPlan, PipelineArtifact
from drydock.providers import ProviderError, ToolBox, prompts, templates
from drydock.providers.backends import ChatBackend, ChatResult
from drydock.providers.fake import collect_evidence

MAX_ATTEMPTS = 2
_FENCE = re.compile(r"^\s*```[a-zA-Z0-9_-]*\s*\n(.*?)\n\s*```\s*$", re.S)

ModelT = TypeVar("ModelT", bound=BaseModel)


class UsageRecord(TypedDict):
    prompt_tokens: int
    completion_tokens: int
    model: str
    latency_ms: int


UsageCallback = Callable[[UsageRecord], None]


class GeneratedFiles(Frozen):
    """Shape of the generator reply before it becomes a PipelineArtifact."""

    pipeline_py: str
    dag_py: str
    mapping_yaml: str
    notes: str = ""


def strip_fences(text: str) -> str:
    """Remove one enclosing markdown code fence (```json ... ```), if present."""
    match = _FENCE.match(text)
    return match.group(1) if match else text.strip()


def parse_json_object(text: str) -> dict[str, Any]:
    """Parse the reply as a JSON object, tolerating fences and surrounding prose."""
    candidate = strip_fences(text)
    if not candidate.startswith("{"):
        start, end = candidate.find("{"), candidate.rfind("}")
        if start == -1 or end <= start:
            raise json.JSONDecodeError("reply contains no JSON object", text, 0)
        candidate = candidate[start : end + 1]
    data = json.loads(candidate)
    if not isinstance(data, dict):
        raise json.JSONDecodeError("reply is not a JSON object", text, 0)
    return data


class LLMProvider:
    """Plans and generates with a chat model; see module docstring for the retry contract."""

    def __init__(
        self,
        backend: ChatBackend,
        name: str,
        *,
        on_usage: UsageCallback | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> None:
        self.backend = backend
        self.name = name
        self.on_usage = on_usage
        self.temperature = temperature
        self.max_tokens = max_tokens

    # -- backend plumbing -------------------------------------------------- #

    def _complete(self, system: str, user: str) -> ChatResult:
        result = self.backend.complete(
            system, user, temperature=self.temperature, max_tokens=self.max_tokens
        )
        if self.on_usage is not None:
            self.on_usage(
                {
                    "prompt_tokens": result.prompt_tokens,
                    "completion_tokens": result.completion_tokens,
                    "model": self.backend.model,
                    "latency_ms": result.latency_ms,
                }
            )
        return result

    def _ask(self, system: str, user: str, model_cls: type[ModelT], what: str) -> ModelT:
        """Ask for JSON validating as ``model_cls``; retry once with the error appended."""
        attempt_user = user
        last_error: Exception | None = None
        for _ in range(MAX_ATTEMPTS):
            result = self._complete(system, attempt_user)
            try:
                return model_cls.model_validate(parse_json_object(result.text))
            except (json.JSONDecodeError, ValidationError) as exc:
                last_error = exc
                attempt_user = prompts.retry_user(user, result.text, str(exc))
        raise ProviderError(
            f"{self.name}: {what} reply failed validation after {MAX_ATTEMPTS} attempts: "
            f"{last_error}"
        ) from last_error

    # -- Provider protocol ------------------------------------------------- #

    def plan(self, spec: FeedSpec, tools: ToolBox) -> IngestionPlan:
        evidence = collect_evidence(spec, tools)
        user = prompts.planner_user(spec, evidence.as_prompt_context())
        proposed = self._ask(prompts.PLANNER_SYSTEM, user, IngestionPlan, "plan")
        # Facts come from the spec and the tool trail; the model only decides the rest.
        return proposed.model_copy(
            update={
                "client": spec.client,
                "feed_name": spec.feed_name,
                "format": spec.format,
                "schedule_cron": spec.schedule_cron,
                "tool_calls": evidence.tool_calls,
            }
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
        example = templates.render_all(plan)
        user = prompts.generator_user(plan, spec, example, previous=previous, report=report)
        files = self._ask(prompts.GENERATOR_SYSTEM, user, GeneratedFiles, "generate")
        return PipelineArtifact(
            pipeline_py=strip_fences(files.pipeline_py),
            dag_py=strip_fences(files.dag_py),
            mapping_yaml=strip_fences(files.mapping_yaml),
            iteration=iteration,
            generator=self.name,
            notes=files.notes or f"Generated by {self.backend.model} (seed={seed}).",
        )
