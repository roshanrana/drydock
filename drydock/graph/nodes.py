"""Graph node functions (docs/design/03-lld.md section 7.1).

Every node receives the current ``GraphState`` and returns a ``dict`` partial that LangGraph
merges into a new state. Dependencies arrive through the frozen ``Deps`` dataclass so the
same node code runs with the fake provider in tests and a live LLM in production. Each node
writes one event, persists what it produced via the store and moves the run status.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from langgraph.types import interrupt

from drydock import corpus
from drydock.errors import DrydockError
from drydock.events import EventWriter
from drydock.graph import state as st
from drydock.graph.store import RunStore, artifact_files, write_text
from drydock.harness import evaluate
from drydock.models import GraphState, RunStatus, utcnow
from drydock.providers import Provider, ToolBox

SandboxKind = Literal["subprocess", "docker"]
APPROVAL_FILE = "approval.json"
SANDBOX_DIRNAME = "sandbox"


@dataclass(frozen=True)
class RunPaths:
    """Filesystem roots a run reads from and writes to."""

    corpus_root: Path
    runs_dir: Path
    deploy_dir: Path


@dataclass(frozen=True)
class Deps:
    """Everything a node needs that is not in the state."""

    provider: Provider
    toolbox: ToolBox
    store: RunStore
    events: EventWriter
    sandbox: SandboxKind
    paths: RunPaths


def _require(value: Any, what: str, state: GraphState) -> Any:
    if value is None:
        raise DrydockError(f"run {state.run_id}: {what} is missing from the graph state")
    return value


class Nodes:
    """Node functions bound to one ``Deps``; ``build_graph`` registers them by name."""

    def __init__(self, deps: Deps) -> None:
        self.deps = deps

    # ------------------------------------------------------------------ helpers

    def _event(self, node: str, state: GraphState, **fields: Any) -> None:
        self.deps.events.emit(node, run_id=state.run_id, iteration=state.iteration, **fields)

    def _status(self, state: GraphState, status: RunStatus, **fields: Any) -> None:
        self.deps.store.update(state.run_id, status=status, **fields)

    # ------------------------------------------------------------------ nodes

    def load_spec(self, state: GraphState) -> dict[str, Any]:
        spec = corpus.load_spec(state.client, self.deps.paths.corpus_root)
        self._event(st.LOAD_SPEC, state, feed=spec.feed_name, format=spec.format.value)
        return {"spec": spec, "status": RunStatus.PLANNING}

    def plan(self, state: GraphState) -> dict[str, Any]:
        spec = _require(state.spec, "spec", state)
        plan = self.deps.provider.plan(spec, self.deps.toolbox)
        self._status(state, RunStatus.GENERATING)
        self._event(
            st.PLAN,
            state,
            tool_calls=list(plan.tool_calls),
            columns=len(plan.column_map),
            validations=len(plan.validations),
        )
        return {"plan": plan, "status": RunStatus.GENERATING}

    def generate(self, state: GraphState) -> dict[str, Any]:
        plan = _require(state.plan, "plan", state)
        spec = _require(state.spec, "spec", state)
        iteration = state.iteration + 1
        artifact = self.deps.provider.generate(
            plan,
            spec,
            iteration=iteration,
            seed=state.seed,
            previous=state.artifact,
            report=state.report,
        )
        self._status(state, RunStatus.EVALUATING, iterations=iteration)
        self.deps.events.emit(
            st.GENERATE,
            run_id=state.run_id,
            iteration=iteration,
            generator=artifact.generator,
            notes=artifact.notes,
            pipeline_bytes=len(artifact.pipeline_py),
        )
        return {"artifact": artifact, "iteration": iteration, "status": RunStatus.EVALUATING}

    def evaluate(self, state: GraphState) -> dict[str, Any]:
        artifact = _require(state.artifact, "artifact", state)
        spec = _require(state.spec, "spec", state)
        root = self.deps.paths.corpus_root
        manifest = corpus.load_manifest(state.client, root)
        samples = corpus.list_samples(state.client, root)
        workdir = self.deps.store.iteration_dir(state.run_id, state.iteration) / SANDBOX_DIRNAME
        report = evaluate(
            artifact,
            spec,
            manifest,
            samples,
            iteration=state.iteration,
            sandbox=self.deps.sandbox,
            workdir=workdir,
        )
        self.deps.store.save_iteration(state.run_id, artifact, report)
        self._event(st.EVALUATE, state, **st.report_summary(report))
        return {"report": report, "history": [*state.history, report]}

    def await_approval(self, state: GraphState) -> dict[str, Any]:
        """Human gate: a real LangGraph interrupt, resumed with ``Command(resume=...)``."""
        if self.deps.store.get(state.run_id).status != RunStatus.AWAITING_APPROVAL:
            self._status(state, RunStatus.AWAITING_APPROVAL, final_passed=True)
            self._event(st.AWAIT_APPROVAL, state, phase="requested")
        answer = interrupt(st.approval_payload(state))
        decision, approver, note = _parse_decision(answer, state)
        self.deps.store.update(state.run_id, approved_by=approver, decision_note=note)
        self._event(st.AWAIT_APPROVAL, state, phase="decided", decision=decision, approver=approver)
        return {"decision": decision, "decision_note": note}

    def publish(self, state: GraphState) -> dict[str, Any]:
        artifact = _require(state.artifact, "artifact", state)
        record = self.deps.store.get(state.run_id)
        target = self.deps.paths.deploy_dir / state.client
        files = artifact_files(artifact)
        for name, text in files.items():
            write_text(target / name, text)
        approval = {
            "run_id": state.run_id,
            "client": state.client,
            "approver": record.approved_by,
            "note": record.decision_note or "",
            "approved_at": utcnow().isoformat(),
            "iteration": artifact.iteration,
            "sha256": {name: _sha256(text) for name, text in files.items()},
        }
        write_text(target / APPROVAL_FILE, json.dumps(approval, indent=2) + "\n")
        self._status(state, RunStatus.APPROVED, final_passed=True)
        self._event(st.PUBLISH, state, deploy_dir=str(target), files=sorted(files))
        return {"status": RunStatus.APPROVED}

    def record_rejection(self, state: GraphState) -> dict[str, Any]:
        self._status(state, RunStatus.REJECTED)
        self._event(st.RECORD_REJECTION, state, note=state.decision_note or "")
        return {"status": RunStatus.REJECTED}

    def escalate(self, state: GraphState) -> dict[str, Any]:
        errors = [] if state.report is None else [f.message for f in state.report.errors]
        self._status(state, RunStatus.ESCALATED, final_passed=False)
        self._event(st.ESCALATE, state, errors=errors, max_iterations=state.max_iterations)
        return {"status": RunStatus.ESCALATED, "error": "; ".join(errors) or None}


def _parse_decision(answer: Any, state: GraphState) -> tuple[st.Decision, str, str]:
    """Validate the resume payload ``{"decision", "approver", "note"}``."""
    if not isinstance(answer, dict):
        raise DrydockError(f"run {state.run_id}: approval payload must be a mapping")
    decision = answer.get("decision")
    if decision not in st.DECISIONS:
        raise DrydockError(f"run {state.run_id}: decision must be one of {st.DECISIONS}")
    approver = str(answer.get("approver") or "")
    if not approver:
        raise DrydockError(f"run {state.run_id}: an approver is required")
    return decision, approver, str(answer.get("note") or "")


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


__all__ = ["APPROVAL_FILE", "Deps", "Nodes", "RunPaths", "SandboxKind"]
