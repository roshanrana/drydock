"""Tests for the sources MCP server and the sync McpToolBox (T-004).

The corpus is built in a fixture under ``tmp_path``; nothing here depends on the real
``corpus/`` directory, which T-001 is authoring concurrently.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from collections.abc import Coroutine
from pathlib import Path
from typing import Any

import pytest
from mcp.client import Client
from mcp.client.stdio import StdioServerParameters
from mcp.server.mcpserver import MCPServer
from mcp.types import CallToolResult, TextContent

from drydock.mcp import McpToolBox, build_server, sources_server
from drydock.mcp.toolbox import _payload
from drydock.models import FeedSpec, SampleProfile

CLIENT = "acme-treasury"
SAMPLE = "daily_cash_2026-09-01.csv"
TOOL_NAMES = {"list_clients", "read_spec", "list_samples", "peek_sample", "profile_sample"}

SPEC_MD = """# ACME Treasury — daily cash feed

Prose the planner may read. Amounts arrive with thousands separators.

```yaml feed-contract
client: acme-treasury
feed_name: daily_cash
format: csv
delimiter: ","
header_rows: 1
trailer_rows: 0
schedule_cron: "0 6 * * 1-5"
expected_row_count: 6
columns:
  - {source: "TradeRef", target: trade_id, dtype: str}
  - {source: "Acct", target: account_id, dtype: str}
  - {source: "ValueDate", target: value_date, dtype: date, date_format: "%Y-%m-%d"}
  - {source: "Amount", target: amount, dtype: decimal}
  - {source: "Ccy", target: currency, dtype: str}
  - {source: "Cpty", target: counterparty, dtype: str}
  - {source: "Narrative", target: description, dtype: str}
quirks:
  - "Amounts arrive with thousands separators."
```

Trailing prose after the block.
"""

CSV_LINES = (
    "TradeRef,Acct,ValueDate,Amount,Ccy,Cpty,Narrative",
    "T1,A1,2026-09-01,1000.00,USD,Alpha,Coupon",
    "T2,A1,2026-09-01,-250.50,USD,Beta,Fee",
    "T3,A2,2026-09-01,75.25,EUR,Gamma,Settlement",
    "T4,A2,2026-09-01,-1200.00,EUR,Delta,Redemption",
    "T5,A3,2026-09-01,10.10,USD,Epsilon,Interest",
    "T6,A3,2026-09-01,-1158.25,USD,Zeta,Transfer",
)

BAD_NAMES = ["../x", "..", ".", "../../spec.md", "samples/../spec.md", "..\\x", "", "a b"]


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")


def run(coro: Coroutine[Any, Any, Any]) -> Any:
    return asyncio.run(coro)


async def call(server: MCPServer[Any], tool: str, /, **args: Any) -> dict[str, Any]:
    async with Client(server) as client:
        result = await client.call_tool(tool, args)
    assert result.is_error is False, result.content
    assert isinstance(result.structured_content, dict)
    return result.structured_content


# --------------------------------------------------------------------------- #
# Fixtures                                                                     #
# --------------------------------------------------------------------------- #


@pytest.fixture
def corpus_root(tmp_path: Path) -> Path:
    client_dir = tmp_path / CLIENT
    samples = client_dir / "samples"
    samples.mkdir(parents=True)
    _write(client_dir / "spec.md", SPEC_MD)
    sample = samples / SAMPLE
    _write(sample, "\n".join(CSV_LINES) + "\n")
    data = sample.read_bytes()
    profile = SampleProfile(
        name=SAMPLE,
        sha256=hashlib.sha256(data).hexdigest(),
        bytes=len(data),
        expected_rows=6,
        amount_sum="-1523.40",
        null_rate={"counterparty": 0.0},
        distinct={"currency": 2},
    )
    manifest = {
        "client": CLIENT,
        "samples": [profile.model_dump()],
        "scenario": {"injected_defect": None, "expected_outcome": "pass", "notes": "fixture"},
    }
    _write(client_dir / "manifest.json", json.dumps(manifest, indent=2))
    return tmp_path


@pytest.fixture
def server(corpus_root: Path) -> MCPServer[Any]:
    return build_server(corpus_root)


@pytest.fixture
def manifest_profile(corpus_root: Path) -> dict[str, Any]:
    raw = json.loads((corpus_root / CLIENT / "manifest.json").read_text(encoding="utf-8"))
    sample: dict[str, Any] = raw["samples"][0]
    return sample


# --------------------------------------------------------------------------- #
# Server shape                                                                 #
# --------------------------------------------------------------------------- #


def test_build_server_name_and_five_tools(server: MCPServer[Any]) -> None:
    assert server.name == "drydock-sources"

    async def names() -> set[str]:
        async with Client(server) as client:
            listed = await client.list_tools()
        return {tool.name for tool in listed.tools}

    assert run(names()) == TOOL_NAMES


def test_list_clients(server: MCPServer[Any]) -> None:
    assert run(call(server, "list_clients")) == {"clients": [CLIENT]}


# --------------------------------------------------------------------------- #
# read_spec                                                                    #
# --------------------------------------------------------------------------- #


def test_read_spec_returns_markdown_and_contract(server: MCPServer[Any]) -> None:
    result = run(call(server, "read_spec", client=CLIENT))

    assert result["client"] == CLIENT
    assert result["markdown"] == SPEC_MD
    spec = FeedSpec.model_validate(result["contract"])
    assert spec.feed_name == "daily_cash"
    assert spec.format == "csv"
    assert len(spec.columns) == 7
    assert spec.quirks == ("Amounts arrive with thousands separators.",)


def test_read_spec_unknown_client_returns_error(server: MCPServer[Any]) -> None:
    result = run(call(server, "read_spec", client="nobody"))
    assert set(result) == {"error"}
    assert "unknown client" in result["error"]


def test_read_spec_without_contract_block_returns_error(corpus_root: Path) -> None:
    broken = corpus_root / "broken-client"
    broken.mkdir()
    _write(broken / "spec.md", "# No contract here\n")
    server = build_server(corpus_root)

    result = run(call(server, "read_spec", client="broken-client"))
    assert set(result) == {"error"}
    assert run(call(server, "list_clients")) == {"clients": [CLIENT, "broken-client"]}


# --------------------------------------------------------------------------- #
# list_samples                                                                 #
# --------------------------------------------------------------------------- #


def test_list_samples_reports_name_bytes_sha256(
    server: MCPServer[Any], manifest_profile: dict[str, Any]
) -> None:
    result = run(call(server, "list_samples", client=CLIENT))
    assert result == {
        "samples": [
            {
                "name": SAMPLE,
                "bytes": manifest_profile["bytes"],
                "sha256": manifest_profile["sha256"],
            }
        ]
    }


def test_list_samples_unknown_client_returns_error(server: MCPServer[Any]) -> None:
    assert "unknown client" in run(call(server, "list_samples", client="ghost"))["error"]


# --------------------------------------------------------------------------- #
# peek_sample (data perimeter)                                                 #
# --------------------------------------------------------------------------- #


def test_peek_sample_default_is_five_raw_lines(server: MCPServer[Any]) -> None:
    result = run(call(server, "peek_sample", client=CLIENT, name=SAMPLE))
    assert result == {"name": SAMPLE, "lines": list(CSV_LINES[:5])}


@pytest.mark.parametrize(
    ("rows", "expected"),
    [(-7, 1), (0, 1), (1, 1), (3, 3), (5, 5), (6, 5), (100, 5)],
)
def test_peek_sample_clamps_rows_to_1_to_5(
    server: MCPServer[Any], rows: int, expected: int
) -> None:
    result = run(call(server, "peek_sample", client=CLIENT, name=SAMPLE, rows=rows))
    assert result["lines"] == list(CSV_LINES[:expected])


def test_peek_sample_strips_crlf_and_replaces_undecodable_bytes(corpus_root: Path) -> None:
    path = corpus_root / CLIENT / "samples" / "odd.csv"
    path.write_bytes(b"h1,h2\r\nv1,\xff\r\n")
    server = build_server(corpus_root)

    result = run(call(server, "peek_sample", client=CLIENT, name="odd.csv"))
    assert result["lines"] == ["h1,h2", "v1,�"]


def test_peek_sample_unknown_sample_returns_error(server: MCPServer[Any]) -> None:
    result = run(call(server, "peek_sample", client=CLIENT, name="missing.csv"))
    assert "unknown sample" in result["error"]


@pytest.mark.parametrize("tool", ["peek_sample", "profile_sample"])
@pytest.mark.parametrize("bad", BAD_NAMES)
def test_sample_name_traversal_is_rejected(server: MCPServer[Any], tool: str, bad: str) -> None:
    result = run(call(server, tool, client=CLIENT, name=bad))
    assert set(result) == {"error"}
    assert "invalid sample name" in result["error"]


def test_absolute_sample_name_is_rejected(server: MCPServer[Any], corpus_root: Path) -> None:
    absolute = str(corpus_root / CLIENT / "spec.md")
    result = run(call(server, "peek_sample", client=CLIENT, name=absolute))
    assert "invalid sample name" in result["error"]


@pytest.mark.parametrize("tool", ["read_spec", "list_samples", "peek_sample", "profile_sample"])
@pytest.mark.parametrize("bad", BAD_NAMES)
def test_client_traversal_is_rejected(server: MCPServer[Any], tool: str, bad: str) -> None:
    args: dict[str, Any] = {"client": bad}
    if tool in {"peek_sample", "profile_sample"}:
        args["name"] = SAMPLE
    result = run(call(server, tool, **args))
    assert set(result) == {"error"}
    assert "invalid client name" in result["error"]


# --------------------------------------------------------------------------- #
# profile_sample                                                               #
# --------------------------------------------------------------------------- #


def test_profile_sample_returns_manifest_profile(
    server: MCPServer[Any], manifest_profile: dict[str, Any]
) -> None:
    result = run(call(server, "profile_sample", client=CLIENT, name=SAMPLE))
    assert result == manifest_profile
    assert SampleProfile.model_validate(result).expected_rows == 6


def test_profile_sample_does_not_recompute(corpus_root: Path) -> None:
    manifest_path = corpus_root / CLIENT / "manifest.json"
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    raw["samples"][0].update({"expected_rows": 999, "sha256": "deadbeef", "bytes": 1})
    _write(manifest_path, json.dumps(raw))
    server = build_server(corpus_root)

    result = run(call(server, "profile_sample", client=CLIENT, name=SAMPLE))
    assert (result["expected_rows"], result["sha256"], result["bytes"]) == (999, "deadbeef", 1)


def test_profile_sample_unknown_sample_returns_error(server: MCPServer[Any]) -> None:
    result = run(call(server, "profile_sample", client=CLIENT, name="ghost.csv"))
    assert "unknown sample" in result["error"]


# --------------------------------------------------------------------------- #
# Fallback loader (until drydock.corpus exists; T-005 removes it)              #
# --------------------------------------------------------------------------- #


def test_tools_work_through_fallback_loader_when_corpus_module_is_absent(
    corpus_root: Path, manifest_profile: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_corpus(name: str) -> Any:
        raise ImportError(name)

    monkeypatch.setattr(sources_server.importlib, "import_module", no_corpus)
    assert isinstance(sources_server._corpus_api(), sources_server._FallbackCorpus)
    server = build_server(corpus_root)

    assert run(call(server, "list_clients")) == {"clients": [CLIENT]}
    spec = FeedSpec.model_validate(run(call(server, "read_spec", client=CLIENT))["contract"])
    assert spec.expected_row_count == 6
    assert run(call(server, "list_samples", client=CLIENT))["samples"][0]["name"] == SAMPLE
    peek = run(call(server, "peek_sample", client=CLIENT, name=SAMPLE, rows=2))
    assert peek["lines"] == list(CSV_LINES[:2])
    assert run(call(server, "profile_sample", client=CLIENT, name=SAMPLE)) == manifest_profile


def test_fallback_loader_handles_missing_samples_dir_and_contract(tmp_path: Path) -> None:
    (tmp_path / "bare").mkdir()
    _write(tmp_path / "bare" / "spec.md", "# no block\n")
    fallback = sources_server._FallbackCorpus()

    assert fallback.list_samples("bare", tmp_path) == []
    with pytest.raises(ValueError, match="feed-contract"):
        fallback.load_spec("bare", tmp_path)


# --------------------------------------------------------------------------- #
# McpToolBox (in-memory)                                                       #
# --------------------------------------------------------------------------- #


def test_toolbox_records_calls_in_order(server: MCPServer[Any]) -> None:
    with McpToolBox(server) as tools:
        clients = tools.call("list_clients")
        samples = tools.call("list_samples", client=CLIENT)
        peek = tools.call("peek_sample", client=CLIENT, name=SAMPLE, rows=2)
        profile = tools.call("profile_sample", client=CLIENT, name=SAMPLE)

        assert tools.calls == ["list_clients", "list_samples", "peek_sample", "profile_sample"]
    assert clients == {"clients": [CLIENT]}
    assert samples["samples"][0]["name"] == SAMPLE
    assert peek["lines"] == list(CSV_LINES[:2])
    assert profile["expected_rows"] == 6


def test_toolbox_tool_errors_are_returned_not_raised(server: MCPServer[Any]) -> None:
    with McpToolBox(server) as tools:
        unknown_client = tools.call("read_spec", client="nobody")
        unknown_tool = tools.call("no_such_tool")
        bad_argument = tools.call("peek_sample", client=CLIENT, name=SAMPLE, rows="many")

    assert "unknown client" in unknown_client["error"]
    assert set(unknown_tool) == {"error"} and "no_such_tool" in unknown_tool["error"]
    assert set(bad_argument) == {"error"}
    assert tools.calls == ["read_spec", "no_such_tool", "peek_sample"]


def test_toolbox_close_is_idempotent_and_call_after_close_raises(
    server: MCPServer[Any],
) -> None:
    tools = McpToolBox(server)
    assert tools.call("list_clients") == {"clients": [CLIENT]}

    tools.close()
    tools.close()

    with pytest.raises(RuntimeError, match="closed"):
        tools.call("list_clients")
    assert tools.calls == ["list_clients"]


def test_toolbox_startup_failure_raises_runtime_error() -> None:
    dead = StdioServerParameters(command=sys.executable, args=["-c", "raise SystemExit(3)"])
    with pytest.raises(RuntimeError, match="MCP session"):
        McpToolBox(dead, timeout=20)


def test_toolbox_rejects_session_that_never_opens(
    server: MCPServer[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def hang(self: McpToolBox, _server: Any) -> None:
        await asyncio.sleep(3600)

    monkeypatch.setattr(McpToolBox, "_session", hang)
    with pytest.raises(RuntimeError, match="did not start"):
        McpToolBox(server, timeout=0.2)


# --------------------------------------------------------------------------- #
# Result decoding                                                              #
# --------------------------------------------------------------------------- #


def _text_result(text: str, *, is_error: bool = False) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=text)], is_error=is_error)


def test_payload_prefers_structured_content() -> None:
    result = CallToolResult(content=[], structured_content={"a": 1})
    assert _payload(result) == {"a": 1}


def test_payload_falls_back_to_json_text() -> None:
    assert _payload(_text_result('{"b": [1, 2]}')) == {"b": [1, 2]}
    assert _payload(_text_result("[1, 2]")) == {"result": [1, 2]}


def test_payload_wraps_errors_and_non_json() -> None:
    assert _payload(_text_result("Unknown tool: x", is_error=True)) == {"error": "Unknown tool: x"}
    assert _payload(CallToolResult(content=[], is_error=True)) == {"error": "tool call failed"}
    assert set(_payload(_text_result("not json"))) == {"error"}


# --------------------------------------------------------------------------- #
# main() and stdio transport                                                   #
# --------------------------------------------------------------------------- #


def test_main_reads_env_root_and_runs_stdio(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: dict[str, Any] = {}

    class FakeServer:
        def run(self, transport: str) -> None:
            seen["transport"] = transport

    def fake_build(root: Path) -> FakeServer:
        seen["root"] = root
        return FakeServer()

    monkeypatch.setattr(sources_server, "build_server", fake_build)
    monkeypatch.setenv(sources_server.ENV_CORPUS_ROOT, str(tmp_path))
    sources_server.main()
    assert seen == {"root": tmp_path, "transport": "stdio"}

    monkeypatch.delenv(sources_server.ENV_CORPUS_ROOT)
    sources_server.main()
    assert seen["root"] == sources_server.CORPUS_DIR


@pytest.mark.slow
def test_stdio_smoke_spawns_module_and_lists_clients(corpus_root: Path) -> None:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "drydock.mcp.sources_server"],
        env={sources_server.ENV_CORPUS_ROOT: str(corpus_root)},
    )
    with McpToolBox(params) as tools:
        assert tools.call("list_clients") == {"clients": [CLIENT]}
        peek = tools.call("peek_sample", client=CLIENT, name=SAMPLE, rows=99)
    assert len(peek["lines"]) == 5
    assert tools.calls == ["list_clients", "peek_sample"]
