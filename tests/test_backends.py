"""ChatBackend adapters, tested with httpx.MockTransport and fake SDK clients. No network."""

from __future__ import annotations

import json
import sys
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from drydock.providers import ProviderError
from drydock.providers.backends import (
    AnthropicBackend,
    BedrockBackend,
    ChatResult,
    OpenAICompatBackend,
    ScriptedBackend,
)

# --------------------------------------------------------------------------- #
# OpenAI-compatible                                                            #
# --------------------------------------------------------------------------- #


def make_openai_backend(
    handler: Any, api_key: str | None = "sk-test", model: str = "qwen2.5-coder:7b"
) -> OpenAICompatBackend:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return OpenAICompatBackend("http://localhost:11434/v1/", model, api_key, client=client)


def test_openai_compat_posts_chat_completion() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("Authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"role": "assistant", "content": '{"ok": true}'}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 3},
            },
        )

    result = make_openai_backend(handler).complete("sys", "usr", temperature=0.2, max_tokens=99)

    assert seen["url"] == "http://localhost:11434/v1/chat/completions"
    assert seen["auth"] == "Bearer sk-test"
    assert seen["body"]["model"] == "qwen2.5-coder:7b"
    assert seen["body"]["messages"] == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "usr"},
    ]
    assert seen["body"]["temperature"] == 0.2 and seen["body"]["max_tokens"] == 99
    assert result == ChatResult(
        text='{"ok": true}', prompt_tokens=12, completion_tokens=3, latency_ms=result.latency_ms
    )


def test_openai_compat_without_api_key_sends_no_auth_header() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "Authorization" not in request.headers
        return httpx.Response(200, json={"choices": [{"message": {"content": "hi"}}]})

    result = make_openai_backend(handler, api_key=None).complete("s", "u")

    assert result.text == "hi" and result.prompt_tokens == 0


def test_openai_compat_http_error_becomes_provider_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    with pytest.raises(ProviderError, match="500"):
        make_openai_backend(handler).complete("s", "u")


def test_openai_compat_transport_error_becomes_provider_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(ProviderError, match="refused"):
        make_openai_backend(handler).complete("s", "u")


def test_openai_compat_non_json_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>not json</html>")

    with pytest.raises(ProviderError, match="not JSON"):
        make_openai_backend(handler).complete("s", "u")


@pytest.mark.parametrize(
    "body",
    [{"choices": []}, {"error": "x"}, {"choices": [{"message": {"content": None}}]}],
    ids=["no-choice", "no-choices", "non-text"],
)
def test_openai_compat_unexpected_shape(body: dict[str, Any]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    with pytest.raises(ProviderError):
        make_openai_backend(handler).complete("s", "u")


def test_openai_compat_default_client_is_created() -> None:
    backend = OpenAICompatBackend("http://localhost:8000/v1", "m", timeout=5)
    assert backend.base_url == "http://localhost:8000/v1"
    assert isinstance(backend._client, httpx.Client)


# --------------------------------------------------------------------------- #
# Bedrock                                                                      #
# --------------------------------------------------------------------------- #


class FakeBedrockClient:
    def __init__(self, response: dict[str, Any] | None = None, error: Exception | None = None):
        self.response = response
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def converse(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response


def test_bedrock_converse_request_and_parse() -> None:
    client = FakeBedrockClient(
        {
            "output": {"message": {"role": "assistant", "content": [{"text": "{"}, {"text": "}"}]}},
            "usage": {"inputTokens": 40, "outputTokens": 2},
            "metrics": {"latencyMs": 321},
        }
    )
    backend = BedrockBackend("anthropic.claude-opus-5", "us-east-1", client=client)

    result = backend.complete("sys", "usr", max_tokens=77)

    call = client.calls[0]
    assert call["modelId"] == "anthropic.claude-opus-5"
    assert call["system"] == [{"text": "sys"}]
    assert call["messages"] == [{"role": "user", "content": [{"text": "usr"}]}]
    assert call["inferenceConfig"] == {"maxTokens": 77}
    assert result == ChatResult(text="{}", prompt_tokens=40, completion_tokens=2, latency_ms=321)


def test_bedrock_client_error_becomes_provider_error() -> None:
    backend = BedrockBackend(
        "m", "eu-west-1", client=FakeBedrockClient(error=RuntimeError("denied"))
    )
    with pytest.raises(ProviderError, match="denied"):
        backend.complete("s", "u")


def test_bedrock_unexpected_shape() -> None:
    backend = BedrockBackend("m", "eu-west-1", client=FakeBedrockClient({"output": {}}))
    with pytest.raises(ProviderError, match="unexpected converse shape"):
        backend.complete("s", "u")


def test_bedrock_missing_boto3(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "boto3", None)
    with pytest.raises(ProviderError, match=r"install drydock\[bedrock\]"):
        BedrockBackend("m", "us-east-1").complete("s", "u")


def test_bedrock_lazy_client_uses_boto3(monkeypatch: pytest.MonkeyPatch) -> None:
    created: dict[str, Any] = {}
    fake_client = FakeBedrockClient({"output": {"message": {"content": [{"text": "ok"}]}}})

    def fake_boto_client(service: str, region_name: str) -> FakeBedrockClient:
        created["service"], created["region"] = service, region_name
        return fake_client

    monkeypatch.setitem(sys.modules, "boto3", SimpleNamespace(client=fake_boto_client))
    result = BedrockBackend("m", "ap-southeast-2").complete("s", "u")

    assert created == {"service": "bedrock-runtime", "region": "ap-southeast-2"}
    assert result.text == "ok" and result.latency_ms >= 0


# --------------------------------------------------------------------------- #
# Anthropic                                                                    #
# --------------------------------------------------------------------------- #


class FakeMessages:
    def __init__(self, message: Any = None, error: Exception | None = None) -> None:
        self.message = message
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.message


def fake_anthropic_message(text: str) -> SimpleNamespace:
    return SimpleNamespace(
        content=[
            SimpleNamespace(type="thinking", thinking="..."),
            SimpleNamespace(type="text", text=text),
        ],
        usage=SimpleNamespace(input_tokens=15, output_tokens=4),
    )


def test_anthropic_messages_create_and_parse() -> None:
    messages = FakeMessages(fake_anthropic_message('{"a": 1}'))
    backend = AnthropicBackend("claude-opus-5", "k", client=SimpleNamespace(messages=messages))

    result = backend.complete("sys", "usr", temperature=0.7, max_tokens=55)

    call = messages.calls[0]
    assert call["model"] == "claude-opus-5"
    assert call["system"] == "sys"
    assert call["messages"] == [{"role": "user", "content": "usr"}]
    assert call["max_tokens"] == 55
    assert "temperature" not in call, "current Claude models reject sampling parameters"
    assert result.text == '{"a": 1}'
    assert (result.prompt_tokens, result.completion_tokens) == (15, 4)


def test_anthropic_api_error_becomes_provider_error() -> None:
    client = SimpleNamespace(messages=FakeMessages(error=RuntimeError("rate limited")))
    with pytest.raises(ProviderError, match="rate limited"):
        AnthropicBackend("m", client=client).complete("s", "u")


def test_anthropic_unexpected_shape() -> None:
    client = SimpleNamespace(messages=FakeMessages(message=object()))
    with pytest.raises(ProviderError, match="unexpected message shape"):
        AnthropicBackend("m", client=client).complete("s", "u")


def test_anthropic_missing_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "anthropic", None)
    with pytest.raises(ProviderError, match=r"install drydock\[anthropic\]"):
        AnthropicBackend("m", "k").complete("s", "u")


def test_anthropic_lazy_client_construction(monkeypatch: pytest.MonkeyPatch) -> None:
    created: dict[str, Any] = {}
    messages = FakeMessages(fake_anthropic_message("ok"))

    def fake_anthropic(**kwargs: Any) -> SimpleNamespace:
        created.update(kwargs)
        return SimpleNamespace(messages=messages)

    monkeypatch.setitem(sys.modules, "anthropic", SimpleNamespace(Anthropic=fake_anthropic))
    result = AnthropicBackend("m", "key-from-env").complete("s", "u")

    assert created == {"api_key": "key-from-env"}
    assert result.text == "ok"


# --------------------------------------------------------------------------- #
# Scripted                                                                     #
# --------------------------------------------------------------------------- #


def test_scripted_backend_replays_and_records() -> None:
    backend = ScriptedBackend(["one", "two"])

    first = backend.complete("s1", "u1")
    second = backend.complete("s2", "u2")

    assert (first.text, second.text) == ("one", "two")
    assert backend.requests == [("s1", "u1"), ("s2", "u2")]
    assert first.prompt_tokens >= 0 and first.completion_tokens >= 0
    with pytest.raises(ProviderError, match="no reply left"):
        backend.complete("s3", "u3")
