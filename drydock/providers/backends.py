"""Chat backends: one ``complete(system, user)`` call against a hosted or local model.

* ``OpenAICompatBackend`` - Ollama, vLLM or anything speaking ``/v1/chat/completions``.
* ``BedrockBackend`` - Amazon Bedrock ``converse`` through boto3 (optional extra).
* ``AnthropicBackend`` - the Anthropic SDK (optional extra).
* ``ScriptedBackend`` - canned replies for tests and offline demos.

Optional SDKs are imported lazily inside the adapters, so importing this module never
requires them; a missing dependency surfaces as ``ProviderError`` at first use.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from typing import Any, Protocol

import httpx

from drydock.models import Frozen
from drydock.providers import ProviderError

DEFAULT_TIMEOUT_SECONDS = 120.0


class ChatResult(Frozen):
    text: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int


class ChatBackend(Protocol):
    model: str

    def complete(
        self, system: str, user: str, *, temperature: float = 0.0, max_tokens: int = 4096
    ) -> ChatResult: ...


def _elapsed_ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


def _as_int(value: Any) -> int:
    return int(value) if isinstance(value, int | float) else 0


# --------------------------------------------------------------------------- #
# OpenAI-compatible HTTP (Ollama, vLLM, ...)                                   #
# --------------------------------------------------------------------------- #


class OpenAICompatBackend:
    """POST ``{base_url}/chat/completions`` with the OpenAI request shape.

    ``client`` is injectable so tests can pass ``httpx.Client(transport=MockTransport(...))``.
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str | None = None,
        *,
        client: httpx.Client | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._api_key = api_key
        self._client = client if client is not None else httpx.Client(timeout=timeout)

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    def complete(
        self, system: str, user: str, *, temperature: float = 0.0, max_tokens: int = 4096
    ) -> ChatResult:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        url = f"{self.base_url}/chat/completions"
        start = time.perf_counter()
        try:
            response = self._client.post(url, json=payload, headers=self._headers())
            response.raise_for_status()
            body = response.json()
        except httpx.HTTPError as exc:
            raise ProviderError(f"{self.model} @ {url}: {exc}") from exc
        except ValueError as exc:
            raise ProviderError(f"{self.model} @ {url}: response is not JSON") from exc
        return _parse_openai_body(body, self.model, _elapsed_ms(start))


def _parse_openai_body(body: Any, model: str, latency_ms: int) -> ChatResult:
    try:
        text = body["choices"][0]["message"]["content"]
        usage = body.get("usage") or {}
    except (KeyError, IndexError, TypeError) as exc:
        raise ProviderError(f"{model}: unexpected chat completion shape: {exc!r}") from exc
    if not isinstance(text, str):
        raise ProviderError(f"{model}: message content is not text")
    return ChatResult(
        text=text,
        prompt_tokens=_as_int(usage.get("prompt_tokens")),
        completion_tokens=_as_int(usage.get("completion_tokens")),
        latency_ms=latency_ms,
    )


# --------------------------------------------------------------------------- #
# Amazon Bedrock (boto3 converse)                                              #
# --------------------------------------------------------------------------- #


class BedrockBackend:
    """Bedrock ``converse`` API. Credentials come from the usual AWS chain, never from yaml.

    Only ``maxTokens`` is sent in ``inferenceConfig``: current Claude models reject
    sampling parameters such as temperature, and the prompts already ask for JSON only.
    """

    def __init__(self, model_id: str, region: str, *, client: Any | None = None) -> None:
        self.model = model_id
        self.region = region
        self._client = client

    def _bedrock_client(self) -> Any:
        if self._client is None:
            try:
                import boto3
            except ImportError as exc:
                raise ProviderError("BedrockBackend needs boto3: install drydock[bedrock]") from exc
            self._client = boto3.client("bedrock-runtime", region_name=self.region)
        return self._client

    def complete(
        self, system: str, user: str, *, temperature: float = 0.0, max_tokens: int = 4096
    ) -> ChatResult:
        client = self._bedrock_client()
        start = time.perf_counter()
        try:
            response = client.converse(
                modelId=self.model,
                system=[{"text": system}],
                messages=[{"role": "user", "content": [{"text": user}]}],
                inferenceConfig={"maxTokens": max_tokens},
            )
        except ProviderError:
            raise
        except Exception as exc:  # botocore.exceptions.ClientError and friends
            raise ProviderError(f"bedrock {self.model} ({self.region}): {exc}") from exc
        return _parse_converse(response, self.model, _elapsed_ms(start))


def _parse_converse(response: Any, model: str, latency_ms: int) -> ChatResult:
    try:
        blocks = response["output"]["message"]["content"]
        text = "".join(str(block.get("text", "")) for block in blocks)
    except (KeyError, TypeError, AttributeError) as exc:
        raise ProviderError(f"bedrock {model}: unexpected converse shape: {exc!r}") from exc
    usage = response.get("usage") or {}
    metrics = response.get("metrics") or {}
    return ChatResult(
        text=text,
        prompt_tokens=_as_int(usage.get("inputTokens")),
        completion_tokens=_as_int(usage.get("outputTokens")),
        latency_ms=_as_int(metrics.get("latencyMs")) or latency_ms,
    )


# --------------------------------------------------------------------------- #
# Anthropic SDK                                                                #
# --------------------------------------------------------------------------- #


class AnthropicBackend:
    """Anthropic Messages API via the official SDK (``client.messages.create``).

    ``temperature`` is deliberately not forwarded: current Claude models reject sampling
    parameters, and the JSON-only prompts keep replies deterministic enough for retries.
    """

    def __init__(
        self, model: str, api_key: str | None = None, *, client: Any | None = None
    ) -> None:
        self.model = model
        self._api_key = api_key
        self._client = client

    def _anthropic_client(self) -> Any:
        if self._client is None:
            try:
                import anthropic
            except ImportError as exc:
                raise ProviderError(
                    "AnthropicBackend needs the anthropic SDK: install drydock[anthropic]"
                ) from exc
            self._client = anthropic.Anthropic(api_key=self._api_key)
        return self._client

    def complete(
        self, system: str, user: str, *, temperature: float = 0.0, max_tokens: int = 4096
    ) -> ChatResult:
        client = self._anthropic_client()
        start = time.perf_counter()
        try:
            message = client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
        except ProviderError:
            raise
        except Exception as exc:  # anthropic.APIError hierarchy
            raise ProviderError(f"anthropic {self.model}: {exc}") from exc
        return _parse_anthropic_message(message, self.model, _elapsed_ms(start))


def _parse_anthropic_message(message: Any, model: str, latency_ms: int) -> ChatResult:
    try:
        blocks = message.content
        text = "".join(
            str(getattr(block, "text", ""))
            for block in blocks
            if getattr(block, "type", "") == "text"
        )
        usage = message.usage
    except (AttributeError, TypeError) as exc:
        raise ProviderError(f"anthropic {model}: unexpected message shape: {exc!r}") from exc
    return ChatResult(
        text=text,
        prompt_tokens=_as_int(getattr(usage, "input_tokens", 0)),
        completion_tokens=_as_int(getattr(usage, "output_tokens", 0)),
        latency_ms=latency_ms,
    )


# --------------------------------------------------------------------------- #
# Scripted (tests / offline demos)                                             #
# --------------------------------------------------------------------------- #


class ScriptedBackend:
    """Replays canned replies in order and records every request it received."""

    def __init__(self, replies: Sequence[str], *, model: str = "scripted") -> None:
        self.model = model
        self._replies = tuple(replies)
        self._served = 0
        self.requests: list[tuple[str, str]] = []

    def complete(
        self, system: str, user: str, *, temperature: float = 0.0, max_tokens: int = 4096
    ) -> ChatResult:
        if self._served >= len(self._replies):
            raise ProviderError(
                f"ScriptedBackend has no reply left (served {self._served} of {len(self._replies)})"
            )
        text = self._replies[self._served]
        self._served += 1
        self.requests.append((system, user))
        return ChatResult(
            text=text,
            prompt_tokens=(len(system) + len(user)) // 4,
            completion_tokens=len(text) // 4,
            latency_ms=1,
        )
