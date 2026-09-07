"""DRYDOCK MCP server: DRYDOCK exposing itself as a tool (docs/design/03-lld.md section 6.3).

Any MCP client (Claude Desktop, Cursor, a script) can start a build, inspect a run's
iterations and findings, and approve or reject it. Every tool returns a JSON-serialisable
dict and never raises across the MCP boundary: ``RunNotFound``, ``InvalidTransition`` and
any other ``DrydockError`` come back as ``{"error": "..."}``.

The human gate is preserved end to end. The server never auto-approves: ``approve_run``
requires a named ``approver`` and ``reject_run`` requires both an ``approver`` and a
``note``, and the underlying service refuses either decision unless the run is
``awaiting_approval``.

Run standalone with ``python -m drydock.mcp.server`` (stdio transport) or ``drydock mcp``.
``DRYDOCK_DB_PATH`` and ``DRYDOCK_RUNS_DIR`` override the default store locations.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal, Protocol

from mcp.server.mcpserver import MCPServer
from pydantic import BaseModel

from drydock.models import HarnessReport, PipelineArtifact, RunRecord
from drydock.paths import DB_PATH, RUNS_DIR

SERVER_NAME = "drydock"
ENV_DB_PATH = "DRYDOCK_DB_PATH"
ENV_RUNS_DIR = "DRYDOCK_RUNS_DIR"
DEFAULT_LIST_LIMIT = 20
DEFAULT_MAX_ITERATIONS = 3
TOOL_NAMES: tuple[str, ...] = (
    "build_pipeline",
    "list_runs",
    "get_run",
    "get_iteration",
    "get_history",
    "approve_run",
    "reject_run",
)

_INSTRUCTIONS = (
    "Control plane for DRYDOCK, the agentic pipeline generation and validation harness. "
    "build_pipeline starts a build for a client feed; the graph plans, generates and "
    "evaluates the pipeline (self-healing up to max_iterations) and then pauses at "
    "status 'awaiting_approval'. Nothing is published until a named human calls "
    "approve_run; this server never approves on its own. Use get_run and get_iteration to "
    "inspect harness findings (checks H1-H6) before deciding. Every tool returns a JSON "
    'object; failures are reported as {"error": "..."} rather than raised.'
)

Decision = Literal["approve", "reject"]


# --------------------------------------------------------------------------- #
# Service contract (structural subset of LLD section 7.3)                      #
# --------------------------------------------------------------------------- #


class RunStoreLike(Protocol):
    """The two ``RunStore`` methods the server reads iterations through."""

    def list_iterations(self, run_id: str) -> list[dict[str, Any]]: ...

    def load_iteration(
        self, run_id: str, iteration: int
    ) -> tuple[PipelineArtifact, HarnessReport | None]: ...


class RunServiceLike(Protocol):
    """Subset of ``drydock.graph.service.RunService`` this server depends on."""

    @property
    def store(self) -> RunStoreLike: ...

    def start_run(
        self, client: str, provider: str = "fake", *, seed: int = 0, max_iterations: int = 3
    ) -> RunRecord: ...

    def decide(
        self, run_id: str, decision: Decision, approver: str, note: str = ""
    ) -> RunRecord: ...

    def get_run(self, run_id: str) -> RunRecord: ...

    def list_runs(self, limit: int = 50) -> list[RunRecord]: ...

    def history(self, run_id: str) -> list[dict[str, Any]]: ...


# --------------------------------------------------------------------------- #
# Serialisation and guarding                                                   #
# --------------------------------------------------------------------------- #


def _jsonable(value: Any) -> Any:
    """Recursively dump Pydantic models so store dicts (which embed Findings) serialise."""
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in value]
    return value


def _record(record: RunRecord) -> dict[str, Any]:
    dumped: dict[str, Any] = record.model_dump(mode="json")
    return dumped


def _require(value: str, field: str) -> str:
    """Return ``value`` stripped, or raise if it is blank; decisions need a named human."""
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field} is required and must not be empty")
    return cleaned


def _guard(fn: Callable[..., dict[str, Any]], *args: Any) -> dict[str, Any]:
    """Run a tool body; any exception becomes an error dict instead of crossing the wire.

    ``DrydockError`` subclasses (``RunNotFound``, ``InvalidTransition``, ...) are the
    expected failures; anything else is still reported the same way so a client never
    sees a bare ``Error executing tool`` with the detail lost to the server's stderr.
    """
    try:
        return fn(*args)
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


# --------------------------------------------------------------------------- #
# Tool bodies (raise freely; ``_guard`` converts to {"error": ...})            #
# --------------------------------------------------------------------------- #


def _build_pipeline(
    service: RunServiceLike, client: str, provider: str, max_iterations: int
) -> dict[str, Any]:
    if max_iterations < 1:
        raise ValueError("max_iterations must be at least 1")
    return _record(service.start_run(client, provider, max_iterations=max_iterations))


def _list_runs(service: RunServiceLike, limit: int) -> dict[str, Any]:
    if limit < 1:
        raise ValueError("limit must be at least 1")
    return {"runs": [_record(r) for r in service.list_runs(limit)]}


def _get_run(service: RunServiceLike, run_id: str) -> dict[str, Any]:
    record = service.get_run(run_id)
    iterations = service.store.list_iterations(run_id)
    return {"run": _record(record), "iterations": _jsonable(iterations)}


def _get_iteration(service: RunServiceLike, run_id: str, iteration: int) -> dict[str, Any]:
    artifact, report = service.store.load_iteration(run_id, iteration)
    return {
        "artifact": artifact.model_dump(mode="json"),
        "report": None if report is None else report.model_dump(mode="json"),
    }


def _get_history(service: RunServiceLike, run_id: str) -> dict[str, Any]:
    service.get_run(run_id)  # RunNotFound before touching checkpoints
    return {"run_id": run_id, "history": _jsonable(service.history(run_id))}


def _approve_run(service: RunServiceLike, run_id: str, approver: str, note: str) -> dict[str, Any]:
    who = _require(approver, "approver")
    return _record(service.decide(run_id, "approve", who, note or ""))


def _reject_run(service: RunServiceLike, run_id: str, approver: str, note: str) -> dict[str, Any]:
    who = _require(approver, "approver")
    why = _require(note, "note")
    return _record(service.decide(run_id, "reject", who, why))


# --------------------------------------------------------------------------- #
# Server                                                                       #
# --------------------------------------------------------------------------- #


def build_server(service: RunServiceLike) -> MCPServer[Any]:
    """Build the ``drydock`` server exposing ``service`` through the seven LLD 6.3 tools."""
    server: MCPServer[Any] = MCPServer(SERVER_NAME, instructions=_INSTRUCTIONS)

    @server.tool()
    def build_pipeline(
        client: str, provider: str = "fake", max_iterations: int = DEFAULT_MAX_ITERATIONS
    ) -> dict[str, Any]:
        """Start a DRYDOCK build for a client feed and return the resulting run record.

        The graph reads the client's spec, plans, generates pipeline.py/dag.py/mapping.yaml,
        evaluates them in a sandbox and self-heals up to max_iterations times. The call
        blocks until the run pauses at 'awaiting_approval' (harness passed), ends
        'escalated' (still failing after max_iterations) or 'failed'. provider is a name
        from configs/providers (default 'fake', offline). Use the returned run_id with
        get_run, get_iteration, approve_run or reject_run.
        """
        return _guard(_build_pipeline, service, client, provider, max_iterations)

    @server.tool()
    def list_runs(limit: int = DEFAULT_LIST_LIMIT) -> dict[str, Any]:
        """List the most recent runs (newest first) as {"runs": [RunRecord, ...]}.

        Each record carries run_id, client, provider, status (planning, generating,
        evaluating, awaiting_approval, approved, rejected, escalated, failed), iterations,
        max_iterations, timestamps and any approval decision.
        """
        return _guard(_list_runs, service, limit)

    @server.tool()
    def get_run(run_id: str) -> dict[str, Any]:
        """Return one run's record plus a summary of every iteration.

        Result: {"run": RunRecord, "iterations": [{"iteration", "passed", "errors": [...],
        "wall_ms"}]}. Each error is a harness Finding (check H1-H6, severity, message,
        evidence). Unknown run_id returns {"error": "RunNotFound: ..."}.
        """
        return _guard(_get_run, service, run_id)

    @server.tool()
    def get_iteration(run_id: str, iteration: int) -> dict[str, Any]:
        """Return the generated files and harness report for one iteration (1-based).

        Result: {"artifact": {pipeline_py, dag_py, mapping_yaml, iteration, generator,
        notes}, "report": {passed, checks: [...], rows_emitted, wall_ms, sandbox} or null
        when the iteration was never evaluated}. Read this before approving a run.
        """
        return _guard(_get_iteration, service, run_id, iteration)

    @server.tool()
    def get_history(run_id: str) -> dict[str, Any]:
        """Return the LangGraph checkpoint history of a run, oldest step first.

        Result: {"run_id", "history": [{"step", "node", "status", "iteration",
        "checkpoint_id", "created_at"}]}. Useful to see which node ran when and where a
        run paused or escalated.
        """
        return _guard(_get_history, service, run_id)

    @server.tool()
    def approve_run(run_id: str, approver: str, note: str = "") -> dict[str, Any]:
        """Approve a run that is awaiting_approval and publish its pipeline to deploy/.

        approver must be the non-empty name of the human taking responsibility; the
        server never approves on its own. Returns the updated RunRecord (status
        'approved', approved_by set). Runs in any other status return
        {"error": "InvalidTransition: ..."}.
        """
        return _guard(_approve_run, service, run_id, approver, note)

    @server.tool()
    def reject_run(run_id: str, approver: str, note: str) -> dict[str, Any]:
        """Reject a run that is awaiting_approval; nothing is published.

        Both approver (who decided) and note (why) are required and must be non-empty.
        Returns the updated RunRecord (status 'rejected', decision_note set). Runs in any
        other status return {"error": "InvalidTransition: ..."}.
        """
        return _guard(_reject_run, service, run_id, approver, note)

    return server


# --------------------------------------------------------------------------- #
# Entry point                                                                  #
# --------------------------------------------------------------------------- #


def _build_service(db_path: Path, runs_dir: Path) -> RunServiceLike:
    """Construct the real ``RunService``; imported lazily so this module loads before T-005."""
    from drydock.graph.service import RunService
    from drydock.graph.store import RunStore

    db_path.parent.mkdir(parents=True, exist_ok=True)
    runs_dir.mkdir(parents=True, exist_ok=True)
    store = RunStore(db_path, runs_dir)
    service: RunServiceLike = RunService(store=store, db_path=db_path)
    return service


def main() -> None:
    """Entry point for ``python -m drydock.mcp.server`` and ``drydock mcp``: serve over stdio."""
    db_path = Path(os.environ.get(ENV_DB_PATH) or DB_PATH)
    runs_dir = Path(os.environ.get(ENV_RUNS_DIR) or RUNS_DIR)
    build_server(_build_service(db_path, runs_dir)).run("stdio")


if __name__ == "__main__":  # pragma: no cover
    main()
