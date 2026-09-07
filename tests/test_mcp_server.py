"""Tests for the DRYDOCK MCP server (T-007).

The server is exercised over the in-memory ``Client`` against a stub service that has the
same shape as LLD section 7.3. Nothing here imports ``drydock.graph`` directly; the stdio
smoke test spawns the real module and is skipped until T-005 lands.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from collections.abc import Coroutine
from pathlib import Path
from typing import Any, Literal

import pytest
from mcp.client import Client
from mcp.client.stdio import StdioServerParameters
from mcp.server.mcpserver import MCPServer

from drydock.errors import InvalidTransition, RunNotFound
from drydock.mcp import server as server_module
from drydock.mcp.server import TOOL_NAMES, build_server
from drydock.mcp.toolbox import McpToolBox
from drydock.models import (
    CheckId,
    CheckResult,
    Finding,
    HarnessReport,
    PipelineArtifact,
    RunRecord,
    RunStatus,
    Severity,
)

CLIENT = "acme-treasury"


def run(coro: Coroutine[Any, Any, Any]) -> Any:
    return asyncio.run(coro)


async def call(server: MCPServer[Any], tool: str, /, **args: Any) -> dict[str, Any]:
    async with Client(server) as client:
        result = await client.call_tool(tool, args)
    assert result.is_error is False, result.content
    assert isinstance(result.structured_content, dict)
    return result.structured_content


def _graph_available() -> bool:
    try:
        return importlib.util.find_spec("drydock.graph.service") is not None
    except ModuleNotFoundError:
        return False


# --------------------------------------------------------------------------- #
# Stub service (LLD section 7.3 shape, in memory)                              #
# --------------------------------------------------------------------------- #

FINDING = Finding(
    check=CheckId.SCHEMA,
    severity=Severity.ERROR,
    message="missing column currency",
    evidence={"columns": ["trade_id"]},
)


def _artifact(iteration: int) -> PipelineArtifact:
    return PipelineArtifact(
        pipeline_py=f"# iteration {iteration}\n",
        dag_py="from airflow import DAG\n",
        mapping_yaml="fields: []\n",
        iteration=iteration,
        generator="fake",
    )


def _report(iteration: int, passed: bool) -> HarnessReport:
    findings = () if passed else (FINDING,)
    return HarnessReport(
        iteration=iteration,
        passed=passed,
        checks=(CheckResult(check=CheckId.SCHEMA, passed=passed, findings=findings),),
        rows_emitted=6 if passed else 0,
        wall_ms=12,
    )


class StubStore:
    def __init__(self) -> None:
        self.iterations: dict[str, list[tuple[PipelineArtifact, HarnessReport | None]]] = {}

    def add(self, run_id: str, artifact: PipelineArtifact, report: HarnessReport | None) -> None:
        self.iterations.setdefault(run_id, []).append((artifact, report))

    def list_iterations(self, run_id: str) -> list[dict[str, Any]]:
        return [
            {
                "iteration": artifact.iteration,
                "passed": report.passed if report else None,
                "errors": list(report.errors) if report else [],
                "wall_ms": report.wall_ms if report else 0,
            }
            for artifact, report in self.iterations.get(run_id, [])
        ]

    def load_iteration(
        self, run_id: str, iteration: int
    ) -> tuple[PipelineArtifact, HarnessReport | None]:
        for artifact, report in self.iterations.get(run_id, []):
            if artifact.iteration == iteration:
                return artifact, report
        raise RunNotFound(f"{run_id} has no iteration {iteration}")


class StubService:
    """Deterministic ``RunService`` stand-in: every build heals on iteration 2."""

    def __init__(self) -> None:
        self.store = StubStore()
        self.runs: dict[str, RunRecord] = {}
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def start_run(
        self, client: str, provider: str = "fake", *, seed: int = 0, max_iterations: int = 3
    ) -> RunRecord:
        self.calls.append(("start_run", (client, provider), {"max_iterations": max_iterations}))
        run_id = f"{client}-00000000000000-{len(self.runs):06x}"
        record = RunRecord(
            run_id=run_id,
            client=client,
            provider=provider,
            status=RunStatus.AWAITING_APPROVAL,
            iterations=2,
            max_iterations=max_iterations,
            artifact_dir=f"runs/{run_id}",
        )
        self.runs[run_id] = record
        self.store.add(run_id, _artifact(1), _report(1, passed=False))
        self.store.add(run_id, _artifact(2), _report(2, passed=True))
        return record

    def decide(
        self,
        run_id: str,
        decision: Literal["approve", "reject"],
        approver: str,
        note: str = "",
    ) -> RunRecord:
        self.calls.append(("decide", (run_id, decision, approver, note), {}))
        record = self.get_run(run_id)
        if record.status is not RunStatus.AWAITING_APPROVAL:
            raise InvalidTransition(f"{run_id} is {record.status}, not awaiting_approval")
        status = RunStatus.APPROVED if decision == "approve" else RunStatus.REJECTED
        updated = record.model_copy(
            update={
                "status": status,
                "approved_by": approver,
                "decision_note": note or None,
                "final_passed": decision == "approve",
            }
        )
        self.runs[run_id] = updated
        return updated

    def get_run(self, run_id: str) -> RunRecord:
        try:
            return self.runs[run_id]
        except KeyError:
            raise RunNotFound(f"no run {run_id!r}") from None

    def list_runs(self, limit: int = 50) -> list[RunRecord]:
        self.calls.append(("list_runs", (limit,), {}))
        return list(reversed(list(self.runs.values())))[:limit]

    def history(self, run_id: str) -> list[dict[str, Any]]:
        self.get_run(run_id)
        return [
            {
                "step": step,
                "node": node,
                "status": status,
                "iteration": iteration,
                "checkpoint_id": f"ckpt-{step}",
                "created_at": "2026-09-07T00:00:00+00:00",
            }
            for step, (node, status, iteration) in enumerate(
                [
                    ("load_spec", "planning", 0),
                    ("plan", "planning", 0),
                    ("evaluate", "evaluating", 2),
                ]
            )
        ]


# --------------------------------------------------------------------------- #
# Fixtures                                                                     #
# --------------------------------------------------------------------------- #


@pytest.fixture
def service() -> StubService:
    return StubService()


@pytest.fixture
def server(service: StubService) -> MCPServer[Any]:
    return build_server(service)


@pytest.fixture
def awaiting(service: StubService) -> RunRecord:
    return service.start_run(CLIENT)


# --------------------------------------------------------------------------- #
# Server shape                                                                 #
# --------------------------------------------------------------------------- #


def test_build_server_name_and_seven_tools(server: MCPServer[Any]) -> None:
    assert server.name == "drydock"

    async def listed() -> dict[str, str]:
        async with Client(server) as client:
            tools = await client.list_tools()
        return {tool.name: tool.description or "" for tool in tools.tools}

    tools = run(listed())
    assert set(tools) == set(TOOL_NAMES) and len(tools) == 7
    assert all(len(description) > 40 for description in tools.values()), tools
    assert "never approves" in tools["approve_run"]


# --------------------------------------------------------------------------- #
# build_pipeline / list_runs                                                   #
# --------------------------------------------------------------------------- #


def test_build_pipeline_returns_run_dict(server: MCPServer[Any], service: StubService) -> None:
    result = run(call(server, "build_pipeline", client=CLIENT))

    record = RunRecord.model_validate(result)
    assert record.client == CLIENT
    assert record.provider == "fake"
    assert record.status is RunStatus.AWAITING_APPROVAL
    assert isinstance(result["created_at"], str)
    assert service.calls == [("start_run", (CLIENT, "fake"), {"max_iterations": 3})]


def test_build_pipeline_forwards_provider_and_max_iterations(
    server: MCPServer[Any], service: StubService
) -> None:
    result = run(call(server, "build_pipeline", client=CLIENT, provider="ollama", max_iterations=5))
    assert (result["provider"], result["max_iterations"]) == ("ollama", 5)
    assert service.calls[-1] == ("start_run", (CLIENT, "ollama"), {"max_iterations": 5})


def test_build_pipeline_rejects_non_positive_max_iterations(server: MCPServer[Any]) -> None:
    result = run(call(server, "build_pipeline", client=CLIENT, max_iterations=0))
    assert set(result) == {"error"} and "max_iterations" in result["error"]


def test_list_runs_empty_then_newest_first(server: MCPServer[Any], service: StubService) -> None:
    assert run(call(server, "list_runs")) == {"runs": []}
    first = service.start_run(CLIENT)
    second = service.start_run("other-bank")

    result = run(call(server, "list_runs", limit=5))
    assert [r["run_id"] for r in result["runs"]] == [second.run_id, first.run_id]
    assert service.calls[-1] == ("list_runs", (5,), {})


def test_list_runs_rejects_non_positive_limit(server: MCPServer[Any]) -> None:
    result = run(call(server, "list_runs", limit=0))
    assert set(result) == {"error"} and "limit" in result["error"]


# --------------------------------------------------------------------------- #
# get_run / get_iteration / get_history                                        #
# --------------------------------------------------------------------------- #


def test_get_run_includes_iterations_with_serialised_findings(
    server: MCPServer[Any], awaiting: RunRecord
) -> None:
    result = run(call(server, "get_run", run_id=awaiting.run_id))

    assert RunRecord.model_validate(result["run"]) == awaiting
    assert [i["iteration"] for i in result["iterations"]] == [1, 2]
    failed, healed = result["iterations"]
    assert failed["passed"] is False and failed["wall_ms"] == 12
    assert failed["errors"] == [FINDING.model_dump(mode="json")]
    assert healed["passed"] is True and healed["errors"] == []


def test_get_run_unknown_returns_run_not_found_error(server: MCPServer[Any]) -> None:
    result = run(call(server, "get_run", run_id="ghost"))
    assert set(result) == {"error"}
    assert result["error"].startswith("RunNotFound:") and "ghost" in result["error"]


def test_get_iteration_returns_artifact_and_report(
    server: MCPServer[Any], awaiting: RunRecord
) -> None:
    result = run(call(server, "get_iteration", run_id=awaiting.run_id, iteration=1))

    assert PipelineArtifact.model_validate(result["artifact"]) == _artifact(1)
    assert HarnessReport.model_validate(result["report"]) == _report(1, passed=False)


def test_get_iteration_without_report_returns_null_report(
    server: MCPServer[Any], service: StubService, awaiting: RunRecord
) -> None:
    service.store.add(awaiting.run_id, _artifact(3), None)
    result = run(call(server, "get_iteration", run_id=awaiting.run_id, iteration=3))
    assert result["artifact"]["iteration"] == 3
    assert result["report"] is None


def test_get_iteration_unknown_returns_error(server: MCPServer[Any], awaiting: RunRecord) -> None:
    result = run(call(server, "get_iteration", run_id=awaiting.run_id, iteration=9))
    assert set(result) == {"error"} and "iteration 9" in result["error"]


def test_get_history_returns_checkpoints(server: MCPServer[Any], awaiting: RunRecord) -> None:
    result = run(call(server, "get_history", run_id=awaiting.run_id))
    assert result["run_id"] == awaiting.run_id
    assert [h["node"] for h in result["history"]] == ["load_spec", "plan", "evaluate"]
    assert result["history"][-1]["checkpoint_id"] == "ckpt-2"


def test_get_history_unknown_returns_error(server: MCPServer[Any]) -> None:
    assert "RunNotFound" in run(call(server, "get_history", run_id="ghost"))["error"]


# --------------------------------------------------------------------------- #
# approve_run / reject_run (the human gate)                                    #
# --------------------------------------------------------------------------- #


def test_approve_run_with_named_approver_transitions(
    server: MCPServer[Any], service: StubService, awaiting: RunRecord
) -> None:
    result = run(
        call(server, "approve_run", run_id=awaiting.run_id, approver="  roshan ", note="LGTM")
    )

    record = RunRecord.model_validate(result)
    assert record.status is RunStatus.APPROVED
    assert record.approved_by == "roshan"
    assert record.decision_note == "LGTM"
    assert service.calls[-1] == ("decide", (awaiting.run_id, "approve", "roshan", "LGTM"), {})


def test_approve_run_note_is_optional(server: MCPServer[Any], awaiting: RunRecord) -> None:
    result = run(call(server, "approve_run", run_id=awaiting.run_id, approver="roshan"))
    assert result["status"] == "approved" and result["decision_note"] is None


@pytest.mark.parametrize("approver", ["", "   ", "\t\n"])
def test_approve_run_requires_non_empty_approver(
    server: MCPServer[Any], service: StubService, awaiting: RunRecord, approver: str
) -> None:
    result = run(call(server, "approve_run", run_id=awaiting.run_id, approver=approver))

    assert set(result) == {"error"} and "approver is required" in result["error"]
    assert service.get_run(awaiting.run_id).status is RunStatus.AWAITING_APPROVAL
    assert not any(name == "decide" for name, _, _ in service.calls)


def test_approve_run_on_non_awaiting_run_returns_invalid_transition(
    server: MCPServer[Any], service: StubService, awaiting: RunRecord
) -> None:
    service.decide(awaiting.run_id, "reject", "qa", "nope")

    result = run(call(server, "approve_run", run_id=awaiting.run_id, approver="roshan"))
    assert set(result) == {"error"}
    assert result["error"].startswith("InvalidTransition:")
    assert service.get_run(awaiting.run_id).status is RunStatus.REJECTED


def test_approve_run_unknown_run_returns_error(server: MCPServer[Any]) -> None:
    result = run(call(server, "approve_run", run_id="ghost", approver="roshan"))
    assert result["error"].startswith("RunNotFound:")


def test_reject_run_with_approver_and_note_transitions(
    server: MCPServer[Any], service: StubService, awaiting: RunRecord
) -> None:
    result = run(
        call(server, "reject_run", run_id=awaiting.run_id, approver="qa", note=" bad mapping ")
    )

    record = RunRecord.model_validate(result)
    assert record.status is RunStatus.REJECTED
    assert record.approved_by == "qa"
    assert record.decision_note == "bad mapping"
    assert record.final_passed is False


@pytest.mark.parametrize("note", ["", "   "])
def test_reject_run_requires_non_empty_note(
    server: MCPServer[Any], service: StubService, awaiting: RunRecord, note: str
) -> None:
    result = run(call(server, "reject_run", run_id=awaiting.run_id, approver="qa", note=note))

    assert set(result) == {"error"} and "note is required" in result["error"]
    assert service.get_run(awaiting.run_id).status is RunStatus.AWAITING_APPROVAL


def test_reject_run_requires_non_empty_approver(
    server: MCPServer[Any], service: StubService, awaiting: RunRecord
) -> None:
    result = run(call(server, "reject_run", run_id=awaiting.run_id, approver="", note="why"))
    assert "approver is required" in result["error"]
    assert service.get_run(awaiting.run_id).status is RunStatus.AWAITING_APPROVAL


def test_reject_run_on_approved_run_returns_invalid_transition(
    server: MCPServer[Any], service: StubService, awaiting: RunRecord
) -> None:
    service.decide(awaiting.run_id, "approve", "roshan")
    result = run(call(server, "reject_run", run_id=awaiting.run_id, approver="qa", note="late"))
    assert result["error"].startswith("InvalidTransition:")


def test_server_never_decides_without_a_tool_call(
    server: MCPServer[Any], service: StubService
) -> None:
    run(call(server, "build_pipeline", client=CLIENT))
    run(call(server, "list_runs"))
    for run_id in service.runs:
        run(call(server, "get_run", run_id=run_id))
        run(call(server, "get_iteration", run_id=run_id, iteration=2))
        run(call(server, "get_history", run_id=run_id))

    assert all(r.status is RunStatus.AWAITING_APPROVAL for r in service.runs.values())
    assert not any(name == "decide" for name, _, _ in service.calls)


# --------------------------------------------------------------------------- #
# Toolbox and unexpected errors                                                #
# --------------------------------------------------------------------------- #


def test_toolbox_round_trip_against_drydock_server(server: MCPServer[Any]) -> None:
    with McpToolBox(server) as tools:
        built = tools.call("build_pipeline", client=CLIENT)
        approved = tools.call("approve_run", run_id=built["run_id"], approver="roshan")
        unknown = tools.call("no_such_tool")

    assert approved["status"] == "approved"
    assert set(unknown) == {"error"}
    assert tools.calls == ["build_pipeline", "approve_run", "no_such_tool"]


def test_unexpected_exception_becomes_error_dict(service: StubService) -> None:
    def boom(limit: int = 50) -> list[RunRecord]:
        raise KeyError("db locked")

    service.list_runs = boom  # type: ignore[method-assign]
    result = run(call(build_server(service), "list_runs"))
    assert result == {"error": "KeyError: 'db locked'"}


def test_jsonable_handles_nested_models_tuples_and_scalars() -> None:
    value = {"a": (FINDING,), "b": [1, {"c": _artifact(1)}], 3: None}
    dumped = server_module._jsonable(value)
    assert dumped["a"] == [FINDING.model_dump(mode="json")]
    assert dumped["b"][1]["c"]["iteration"] == 1
    assert dumped["3"] is None


# --------------------------------------------------------------------------- #
# main() and stdio transport                                                   #
# --------------------------------------------------------------------------- #


def _install_fake_graph(monkeypatch: pytest.MonkeyPatch, seen: dict[str, Any]) -> None:
    """Register fake ``drydock.graph`` modules so main() is testable before T-005 lands."""

    class FakeStore:
        def __init__(self, db_path: Path, runs_dir: Path) -> None:
            seen["store"] = (db_path, runs_dir)
            seen["store_obj"] = self

    class FakeService:
        def __init__(self, *, store: FakeStore, db_path: Path) -> None:
            seen["service"] = (store, db_path)

    graph = types.ModuleType("drydock.graph")
    service_mod = types.ModuleType("drydock.graph.service")
    store_mod = types.ModuleType("drydock.graph.store")
    service_mod.RunService = FakeService  # type: ignore[attr-defined]
    store_mod.RunStore = FakeStore  # type: ignore[attr-defined]
    for name, module in [
        ("drydock.graph", graph),
        ("drydock.graph.service", service_mod),
        ("drydock.graph.store", store_mod),
    ]:
        monkeypatch.setitem(sys.modules, name, module)


def test_main_reads_env_paths_builds_service_and_runs_stdio(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: dict[str, Any] = {}
    _install_fake_graph(monkeypatch, seen)

    class FakeServer:
        def run(self, transport: str) -> None:
            seen["transport"] = transport

    def fake_build(service: Any) -> FakeServer:
        seen["built_with"] = service
        return FakeServer()

    monkeypatch.setattr(server_module, "build_server", fake_build)
    db_path = tmp_path / "state" / "drydock.db"
    runs_dir = tmp_path / "artifacts"
    monkeypatch.setenv(server_module.ENV_DB_PATH, str(db_path))
    monkeypatch.setenv(server_module.ENV_RUNS_DIR, str(runs_dir))

    server_module.main()

    assert seen["store"] == (db_path, runs_dir)
    assert seen["service"] == (seen["store_obj"], db_path)
    assert type(seen["built_with"]).__name__ == "FakeService"
    assert seen["transport"] == "stdio"
    assert db_path.parent.is_dir() and runs_dir.is_dir()


def test_main_defaults_to_drydock_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seen: dict[str, Any] = {}
    _install_fake_graph(monkeypatch, seen)
    idle_server = types.SimpleNamespace(run=lambda transport: None)
    monkeypatch.setattr(server_module, "build_server", lambda service: idle_server)
    monkeypatch.delenv(server_module.ENV_DB_PATH, raising=False)
    monkeypatch.delenv(server_module.ENV_RUNS_DIR, raising=False)
    monkeypatch.setattr(server_module, "DB_PATH", tmp_path / "data" / "drydock.db")
    monkeypatch.setattr(server_module, "RUNS_DIR", tmp_path / "runs")

    server_module.main()

    assert seen["store"] == (tmp_path / "data" / "drydock.db", tmp_path / "runs")


@pytest.mark.slow
@pytest.mark.skipif(
    not _graph_available(),
    reason="drydock.graph (T-005) not present yet; main() needs the real RunService",
)
def test_stdio_smoke_spawns_module_and_lists_runs(tmp_path: Path) -> None:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "drydock.mcp.server"],
        env={
            server_module.ENV_DB_PATH: str(tmp_path / "data" / "drydock.db"),
            server_module.ENV_RUNS_DIR: str(tmp_path / "runs"),
        },
    )
    with McpToolBox(params) as tools:
        assert tools.call("list_runs") == {"runs": []}
        missing = tools.call("get_run", run_id="ghost")
    assert missing["error"].startswith("RunNotFound")
    assert tools.calls == ["list_runs", "get_run"]
