"""Synchronous MCP toolbox for graph nodes (docs/design/03-lld.md section 6.2).

A background thread owns an asyncio loop and a persistent :class:`mcp.client.Client`
session, so synchronous LangGraph nodes and providers can invoke MCP tools with a plain
function call. The same class fronts an in-memory :class:`MCPServer` (tests, default graph)
or a stdio subprocess described by :class:`StdioServerParameters` (production).

Failure modes are deliberately split: a tool that reports an error yields the returned
``{"error": ...}`` dict (the Planner can reason about it), while transport and session
failures raise :class:`RuntimeError`.
"""

from __future__ import annotations

import asyncio
import json
import threading
from types import TracebackType
from typing import Any, Self

from mcp.client import Client
from mcp.client.stdio import StdioServerParameters
from mcp.server.mcpserver import MCPServer
from mcp.types import CallToolResult

DEFAULT_TIMEOUT_S = 60.0
THREAD_NAME = "drydock-mcp-toolbox"

ServerSpec = MCPServer[Any] | StdioServerParameters


class McpToolBox:
    """Implements the ``ToolBox`` protocol (LLD section 5) over a live MCP session.

    ``calls`` records every tool name whose round-trip completed, in order; the Planner
    copies it into ``IngestionPlan.tool_calls`` as evidence.
    """

    def __init__(self, server: ServerSpec, *, timeout: float = DEFAULT_TIMEOUT_S) -> None:
        self.calls: list[str] = []
        self._timeout = timeout
        self._loop = asyncio.new_event_loop()
        self._client: Client | None = None
        self._stop: asyncio.Event | None = None
        self._ready = threading.Event()
        self._session_error: Exception | None = None
        self._closed = False
        self._thread = threading.Thread(
            target=self._thread_main, args=(server,), name=THREAD_NAME, daemon=True
        )
        self._thread.start()
        if not self._ready.wait(timeout):
            self.close()
            raise RuntimeError(f"MCP session did not start within {timeout:g}s")
        if self._session_error is not None:
            self.close()
            raise RuntimeError(
                f"MCP session failed to start: {self._session_error}"
            ) from self._session_error

    # ------------------------------------------------------------------ calls

    def call(self, name: str, /, **arguments: Any) -> dict[str, Any]:
        """Invoke tool ``name`` synchronously and return its dict payload.

        ``name`` is positional-only so tools that themselves take a ``name`` argument
        (``peek_sample``, ``profile_sample``) can be called as
        ``tools.call("peek_sample", client=..., name=...)``.
        """
        client = self._client
        if self._closed or client is None:
            raise RuntimeError(self._unavailable_reason())
        future = asyncio.run_coroutine_threadsafe(client.call_tool(name, arguments), self._loop)
        try:
            result = future.result(self._timeout)
        except Exception as exc:
            future.cancel()
            raise RuntimeError(f"MCP call {name!r} failed: {exc}") from exc
        self.calls.append(name)
        return _payload(result)

    def _unavailable_reason(self) -> str:
        if self._closed:
            return "McpToolBox is closed"
        if self._session_error is not None:
            return f"MCP session ended: {self._session_error}"
        return "MCP session is not open"

    # -------------------------------------------------------------- lifecycle

    def close(self) -> None:
        """Shut the session and its loop down. Safe to call repeatedly."""
        if self._closed:
            return
        self._closed = True
        if self._thread.is_alive() and not self._loop.is_closed():
            try:
                self._loop.call_soon_threadsafe(self._request_stop)
            except RuntimeError:  # loop closed between the check and the call
                pass
        self._thread.join(self._timeout)

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    # --------------------------------------------------------- loop thread

    def _thread_main(self, server: ServerSpec) -> None:
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._session(server))
        finally:
            self._loop.run_until_complete(self._loop.shutdown_asyncgens())
            self._loop.close()

    async def _session(self, server: ServerSpec) -> None:
        """Hold one Client session open until ``close`` asks the loop to stop."""
        self._stop = asyncio.Event()
        try:
            async with Client(server) as client:
                self._client = client
                self._ready.set()
                await self._stop.wait()
        except Exception as exc:
            self._session_error = exc
        finally:
            self._client = None
            self._ready.set()

    def _request_stop(self) -> None:
        if self._stop is not None:
            self._stop.set()


# --------------------------------------------------------------------------- #
# Result decoding                                                              #
# --------------------------------------------------------------------------- #


def _payload(result: CallToolResult) -> dict[str, Any]:
    """Prefer ``structured_content``; fall back to the first text item parsed as JSON."""
    if isinstance(result.structured_content, dict):
        return result.structured_content
    text = _first_text(result)
    if result.is_error:
        return {"error": text or "tool call failed"}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {"error": f"non-JSON tool response: {text[:200]!r}"}
    return parsed if isinstance(parsed, dict) else {"result": parsed}


def _first_text(result: CallToolResult) -> str:
    for item in result.content:
        text = getattr(item, "text", None)
        if isinstance(text, str):
            return text
    return ""
