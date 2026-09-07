"""Provider layer: who plans and who writes the pipeline code (LLD section 5).

Two implementations share one ``Provider`` protocol:

* :class:`drydock.providers.fake.FakeProvider` - deterministic, offline, template-driven,
  with scenario-declared fault injection and repair.
* :class:`drydock.providers.llm.LLMProvider` - the same prompts against any ``ChatBackend``
  (Ollama / vLLM over OpenAI-compatible HTTP, Amazon Bedrock, Anthropic).

``load_provider`` reads ``configs/providers/<name>.yaml`` and wires the right one. The yaml
never carries secrets; API keys are resolved from the environment variable named by
``api_key_env``.

``ProviderError`` lives here until ``drydock/errors.py`` (owned by T-001) consolidates the
error taxonomy; import it from this package.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Protocol

import yaml
from pydantic import ValidationError

from drydock.errors import ProviderError
from drydock.models import FeedSpec, Frozen, HarnessReport, IngestionPlan, PipelineArtifact

if TYPE_CHECKING:
    from drydock.providers.backends import ChatBackend
    from drydock.providers.llm import UsageCallback

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_DIR = ROOT / "configs" / "providers"

BackendKind = Literal["fake", "openai_compat", "bedrock", "anthropic"]

DEFAULT_API_KEY_ENV: Mapping[str, str | None] = {
    "fake": None,
    "openai_compat": "OPENAI_API_KEY",
    "bedrock": None,  # boto3 resolves AWS credentials through its own chain
    "anthropic": "ANTHROPIC_API_KEY",
}


# --------------------------------------------------------------------------- #
# Protocols                                                                    #
# --------------------------------------------------------------------------- #


class ToolBox(Protocol):
    """MCP tool facade handed to providers so planning leaves an evidence trail."""

    calls: list[str]

    def call(self, name: str, /, **arguments: Any) -> dict[str, Any]: ...


class Provider(Protocol):
    """Plans an ingestion and generates one PipelineArtifact per iteration."""

    name: str

    def plan(self, spec: FeedSpec, tools: ToolBox) -> IngestionPlan: ...

    def generate(
        self,
        plan: IngestionPlan,
        spec: FeedSpec,
        *,
        iteration: int,
        seed: int,
        previous: PipelineArtifact | None,
        report: HarnessReport | None,
    ) -> PipelineArtifact: ...


# --------------------------------------------------------------------------- #
# Configuration                                                                #
# --------------------------------------------------------------------------- #


class ProviderConfig(Frozen):
    """Validated form of ``configs/providers/<name>.yaml``. No secrets, only their env names."""

    backend: BackendKind
    model: str = ""
    base_url: str | None = None
    api_key_env: str | None = None
    region: str | None = None
    temperature: float = 0.0
    max_tokens: int = 4096
    description: str = ""


def read_provider_config(name: str, config_dir: Path = DEFAULT_CONFIG_DIR) -> ProviderConfig:
    """Load and validate one provider yaml; missing ``api_key_env`` gets the backend default."""
    path = config_dir / f"{name}.yaml"
    if not path.is_file():
        raise ProviderError(f"no provider config for '{name}' at {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ProviderError(f"{path}: expected a mapping at the top level")
    backend = raw.get("backend")
    if "api_key_env" not in raw and isinstance(backend, str):
        raw = {**raw, "api_key_env": DEFAULT_API_KEY_ENV.get(backend)}
    try:
        return ProviderConfig.model_validate(raw)
    except ValidationError as exc:
        raise ProviderError(f"{path}: invalid provider config: {exc}") from exc


def resolve_api_key(config: ProviderConfig, name: str) -> str | None:
    """Read the API key from the environment variable the config names (None = no auth)."""
    if config.api_key_env is None:
        return None
    value = os.environ.get(config.api_key_env, "")
    if not value:
        raise ProviderError(
            f"provider '{name}' needs the environment variable {config.api_key_env} "
            f"(api_key_env in configs/providers/{name}.yaml); it is not set"
        )
    return value


def build_backend(config: ProviderConfig, name: str) -> ChatBackend:
    """Construct the ChatBackend for a non-fake config. Optional SDKs are imported lazily."""
    from drydock.providers.backends import AnthropicBackend, BedrockBackend, OpenAICompatBackend

    if config.backend == "openai_compat":
        if not config.base_url:
            raise ProviderError(f"provider '{name}': openai_compat needs base_url")
        return OpenAICompatBackend(
            base_url=config.base_url, model=config.model, api_key=resolve_api_key(config, name)
        )
    if config.backend == "bedrock":
        if not config.region:
            raise ProviderError(f"provider '{name}': bedrock needs region")
        return BedrockBackend(model_id=config.model, region=config.region)
    if config.backend == "anthropic":
        return AnthropicBackend(model=config.model, api_key=resolve_api_key(config, name))
    raise ProviderError(f"provider '{name}': backend '{config.backend}' has no chat adapter")


def load_provider(
    name: str,
    *,
    fault_plan: Mapping[str, str | None] | None = None,
    config_dir: Path = DEFAULT_CONFIG_DIR,
    on_usage: UsageCallback | None = None,
) -> Provider:
    """Build the provider named by ``configs/providers/<name>.yaml``.

    ``fault_plan`` (client -> defect id) only affects the fake provider. ``on_usage`` is an
    optional callback the LLM provider fires with token counts after every backend call.
    """
    from drydock.providers.fake import FakeProvider
    from drydock.providers.llm import LLMProvider

    config = read_provider_config(name, config_dir)
    if config.backend == "fake":
        return FakeProvider(fault_plan)
    backend = build_backend(config, name)
    return LLMProvider(
        backend,
        name,
        on_usage=on_usage,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
    )


__all__ = [
    "DEFAULT_CONFIG_DIR",
    "ROOT",
    "Provider",
    "ProviderConfig",
    "ProviderError",
    "ToolBox",
    "build_backend",
    "load_provider",
    "read_provider_config",
    "resolve_api_key",
]
