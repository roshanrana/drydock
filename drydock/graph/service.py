"""RunService: the facade every surface uses (docs/design/03-lld.md section 7.3).

CLI, dashboard and the DRYDOCK MCP server all go through this class. It owns the LangGraph
SQLite checkpointer (same database file as the ``RunStore``, different tables), builds the
provider and the in-memory sources toolbox per run, and turns graph checkpoints into the
``history`` / ``state_at`` views. A second instance on the same database can resume a run
started by the first, which is what makes approvals survive process restarts.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Literal, Self

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command, StateSnapshot

from drydock import corpus
from drydock.errors import DrydockError, InvalidTransition
from drydock.events import EventWriter
from drydock.graph import state as st
from drydock.graph.build import build_graph
from drydock.graph.nodes import Deps, RunPaths, SandboxKind
from drydock.graph.store import RunStore
from drydock.mcp.sources_server import build_server
from drydock.mcp.toolbox import McpToolBox
from drydock.models import (
    CheckId,
    CheckResult,
    ColumnSpec,
    FeedSpec,
    Finding,
    GraphState,
    HarnessReport,
    IngestionPlan,
    PipelineArtifact,
    RunRecord,
    RunStatus,
    Severity,
    SourceFormat,
)
from drydock.paths import CORPUS_DIR, DB_PATH, DEPLOY_DIR
from drydock.providers import Provider, load_provider

EVENTS_FILE = "events.jsonl"
FAILED_NODE = "failed"
INSPECTION_PROVIDER = "fake"
START_NODE = "__start__"

Graph = CompiledStateGraph[GraphState, Any, Any, Any]

CHECKPOINT_TYPES: tuple[type, ...] = (
    SourceFormat,
    ColumnSpec,
    FeedSpec,
    IngestionPlan,
    PipelineArtifact,
    CheckId,
    Severity,
    Finding,
    CheckResult,
    HarnessReport,
    RunStatus,
    GraphState,
)
"""Contract types LangGraph may deserialise from checkpoints (msgpack allowlist)."""


def checkpoint_serializer() -> JsonPlusSerializer:
    """Serde that accepts exactly the frozen contract types, silencing the allowlist warning."""
    return JsonPlusSerializer(allowed_msgpack_modules=CHECKPOINT_TYPES)


def run_config(run_id: str) -> RunnableConfig:
    """LangGraph config for a run: ``thread_id`` is the run id."""
    return RunnableConfig(configurable={"thread_id": run_id})


class _InertToolBox:
    """ToolBox stand-in for graphs that only read checkpoints and never execute a node."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def call(self, name: str, /, **arguments: Any) -> dict[str, Any]:
        raise RuntimeError(f"inspection graph cannot call MCP tool {name!r}")


class RunService:
    """Start, decide, inspect and replay runs; safe to hold for the life of a process."""

    def __init__(
        self,
        *,
        store: RunStore,
        db_path: Path = DB_PATH,
        corpus_root: Path = CORPUS_DIR,
        deploy_dir: Path = DEPLOY_DIR,
        sandbox: SandboxKind = "subprocess",
    ) -> None:
        self.store = store
        self.db_path = db_path
        self.corpus_root = corpus_root
        self.deploy_dir = deploy_dir
        self.sandbox: SandboxKind = sandbox
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._checkpointer = SqliteSaver(self._conn, serde=checkpoint_serializer())
        self._checkpointer.setup()

    # ------------------------------------------------------------------ lifecycle

    def close(self) -> None:
        """Close the checkpointer connection (the store is closed by its owner)."""
        self._conn.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # ------------------------------------------------------------------ public API

    def start_run(
        self, client: str, provider: str = "fake", *, seed: int = 0, max_iterations: int = 3
    ) -> RunRecord:
        """Create the record, run the graph until the approval interrupt or END."""
        if max_iterations < 1:
            raise DrydockError("max_iterations must be at least 1")
        fault_plan = self._fault_plan(client)
        run_id = st.new_run_id(client, seed)
        record = RunRecord(
            run_id=run_id,
            client=client,
            provider=provider,
            status=RunStatus.PLANNING,
            max_iterations=max_iterations,
            artifact_dir=f"runs/{run_id}",
        )
        self.store.create(record)
        initial = st.initial_state(
            run_id, client, provider, seed=seed, max_iterations=max_iterations
        )
        self._invoke(record, fault_plan, initial.model_dump())
        return self.store.get(run_id)

    def decide(
        self,
        run_id: str,
        decision: Literal["approve", "reject"],
        approver: str,
        note: str = "",
    ) -> RunRecord:
        """Resume the interrupted graph with the human decision."""
        record = self.store.get(run_id)
        if record.status != RunStatus.AWAITING_APPROVAL:
            raise InvalidTransition(
                f"run {run_id} is {record.status.value}; only awaiting_approval runs can be decided"
            )
        if decision not in st.DECISIONS:
            raise DrydockError(f"decision must be one of {st.DECISIONS}, got {decision!r}")
        if not approver:
            raise DrydockError("an approver name is required")
        resume = {"decision": decision, "approver": approver, "note": note}
        self._invoke(record, self._fault_plan(record.client), Command(resume=resume))
        return self.store.get(run_id)

    def get_run(self, run_id: str) -> RunRecord:
        return self.store.get(run_id)

    def list_runs(self, limit: int = 50) -> list[RunRecord]:
        return self.store.list(limit)

    def history(self, run_id: str) -> list[dict[str, Any]]:
        """Checkpoints oldest first: step, node, status, iteration, checkpoint_id, created_at."""
        snapshots = self._snapshots(run_id)
        entries = []
        for index, snapshot in enumerate(snapshots):
            parent = snapshots[index + 1] if index + 1 < len(snapshots) else None
            entries.append(_history_entry(snapshot, parent))
        entries.reverse()
        return entries

    def state_at(self, run_id: str, step: int) -> dict[str, Any]:
        """``GraphState`` dump at the checkpoint whose ``metadata["step"] == step``."""
        for snapshot in self._snapshots(run_id):
            if snapshot.metadata is not None and snapshot.metadata.get("step") == step:
                return _dump_values(snapshot.values)
        raise DrydockError(f"run {run_id} has no checkpoint at step {step}")

    # ------------------------------------------------------------------ internals

    def _paths(self) -> RunPaths:
        return RunPaths(
            corpus_root=self.corpus_root, runs_dir=self.store.runs_dir, deploy_dir=self.deploy_dir
        )

    def _events(self, run_id: str) -> EventWriter:
        return EventWriter(self.store.runs_dir / run_id / EVENTS_FILE)

    def _fault_plan(self, client: str) -> dict[str, str | None]:
        manifest = corpus.load_manifest(client, self.corpus_root)
        return {client: manifest.scenario.injected_defect}

    @contextmanager
    def _graph(self, record: RunRecord, fault_plan: dict[str, str | None]) -> Iterator[Graph]:
        events = self._events(record.run_id)
        provider = load_provider(record.provider, fault_plan=fault_plan, on_usage=events.on_usage)
        with McpToolBox(build_server(self.corpus_root)) as toolbox:
            deps = Deps(
                provider=provider,
                toolbox=toolbox,
                store=self.store,
                events=events,
                sandbox=self.sandbox,
                paths=self._paths(),
            )
            yield build_graph(deps, self._checkpointer)

    def _inspection_graph(self, run_id: str) -> Graph:
        provider: Provider = load_provider(INSPECTION_PROVIDER)
        deps = Deps(
            provider=provider,
            toolbox=_InertToolBox(),
            store=self.store,
            events=self._events(run_id),
            sandbox=self.sandbox,
            paths=self._paths(),
        )
        return build_graph(deps, self._checkpointer)

    def _invoke(self, record: RunRecord, fault_plan: dict[str, str | None], payload: Any) -> None:
        config = run_config(record.run_id)
        try:
            with self._graph(record, fault_plan) as graph:
                graph.invoke(payload, config=config)
        except Exception as exc:
            self.store.update(record.run_id, status=RunStatus.FAILED)
            self._events(record.run_id).emit(
                FAILED_NODE, run_id=record.run_id, error=str(exc), kind=type(exc).__name__
            )
            raise

    def _snapshots(self, run_id: str) -> list[StateSnapshot]:
        self.store.get(run_id)
        graph = self._inspection_graph(run_id)
        return list(graph.get_state_history(run_config(run_id)))


def _history_entry(snapshot: StateSnapshot, parent: StateSnapshot | None) -> dict[str, Any]:
    values = snapshot.values if isinstance(snapshot.values, dict) else {}
    metadata = snapshot.metadata or {}
    node = parent.next[0] if parent is not None and parent.next else START_NODE
    status = values.get("status")
    return {
        "step": metadata.get("step"),
        "node": node,
        "status": status.value if isinstance(status, RunStatus) else status,
        "iteration": values.get("iteration", 0),
        "checkpoint_id": snapshot.config["configurable"]["checkpoint_id"],
        "created_at": snapshot.created_at,
        "next": list(snapshot.next),
    }


def _dump_values(values: Any) -> dict[str, Any]:
    """Snapshot values are dicts; the input checkpoint (step -1) has none and dumps as ``{}``."""
    if isinstance(values, dict) and "run_id" in values:
        return GraphState.model_validate(values).model_dump(mode="json")
    return {}


__all__ = ["CHECKPOINT_TYPES", "EVENTS_FILE", "RunService", "checkpoint_serializer", "run_config"]
