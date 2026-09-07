"""Graph, service and events against the real corpus with the fake provider (LLD section 7).

Facts these tests rest on (from the Wave 1 integration smoke): acme-treasury passes on
iteration 1; blue-harbour-fx, kestrel-payments, northwind-custody and orion-prime fail
iteration 1 and pass iteration 2; meridian-legacy fails H3 on every iteration (the manifest
pins 15 rows, the sample has 14) so it escalates after 3.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from drydock import corpus
from drydock.errors import CorpusError, DrydockError, InvalidTransition, ProviderError, RunNotFound
from drydock.events import USAGE_NODE, EventWriter, read_events
from drydock.graph import state as st
from drydock.graph.build import build_graph
from drydock.graph.nodes import APPROVAL_FILE, Deps, RunPaths, _parse_decision
from drydock.graph.service import EVENTS_FILE, RunService, _InertToolBox, run_config
from drydock.graph.store import ARTIFACT_FILES, RunStore
from drydock.mcp.sources_server import build_server
from drydock.mcp.toolbox import McpToolBox
from drydock.models import (
    CheckId,
    CheckResult,
    FeedSpec,
    GraphState,
    HarnessReport,
    IngestionPlan,
    RunRecord,
    RunStatus,
)
from drydock.paths import CORPUS_DIR
from drydock.providers import load_provider

ACME = "acme-treasury"
NORTHWIND = "northwind-custody"
MERIDIAN = "meridian-legacy"
EVIDENCE = ("list_samples", "peek_sample", "profile_sample")


def latest_state(service: RunService, run_id: str) -> dict[str, Any]:
    history = service.history(run_id)
    return service.state_at(run_id, history[-1]["step"])


# --------------------------------------------------------------------------- #
# Scenarios through the service                                                #
# --------------------------------------------------------------------------- #


def test_acme_reaches_awaiting_approval_in_one_iteration(
    service: RunService, runs_dir: Path
) -> None:
    record = service.start_run(ACME, "fake", seed=42)

    assert record.status is RunStatus.AWAITING_APPROVAL
    assert record.iterations == 1
    assert record.final_passed is True
    assert record.artifact_dir == f"runs/{record.run_id}"
    state = latest_state(service, record.run_id)
    assert tuple(state["plan"]["tool_calls"]) == EVIDENCE
    assert state["report"]["passed"] is True
    assert (runs_dir / record.run_id / "iter-1" / "pipeline.py").is_file()
    assert (runs_dir / record.run_id / "iter-1" / "report.json").is_file()


def test_approve_publishes_deploy_files_and_valid_approval_json(
    service: RunService, deploy_dir: Path
) -> None:
    started = service.start_run(ACME, "fake", seed=1)
    record = service.decide(started.run_id, "approve", "ana", "ship it")

    assert record.status is RunStatus.APPROVED
    assert record.approved_by == "ana"
    assert record.decision_note == "ship it"
    target = deploy_dir / ACME
    assert sorted(p.name for p in target.iterdir()) == sorted([*ARTIFACT_FILES, APPROVAL_FILE])
    approval = json.loads((target / APPROVAL_FILE).read_text(encoding="utf-8"))
    assert approval["run_id"] == started.run_id
    assert approval["approver"] == "ana"
    assert approval["note"] == "ship it"
    assert approval["iteration"] == 1
    assert approval["approved_at"]
    for name in ARTIFACT_FILES:
        digest = hashlib.sha256((target / name).read_bytes()).hexdigest()
        assert approval["sha256"][name] == digest
    assert latest_state(service, started.run_id)["status"] == "approved"


def test_reject_records_decision_and_publishes_nothing(
    service: RunService, deploy_dir: Path
) -> None:
    started = service.start_run(ACME, "fake", seed=2)
    record = service.decide(started.run_id, "reject", "bob", "not today")

    assert record.status is RunStatus.REJECTED
    assert record.approved_by == "bob"
    assert record.decision_note == "not today"
    assert not deploy_dir.exists() or not any(deploy_dir.iterdir())
    state = latest_state(service, started.run_id)
    assert state["decision"] == "reject"
    assert state["status"] == "rejected"


def test_northwind_heals_in_exactly_two_iterations(service: RunService) -> None:
    record = service.start_run(NORTHWIND, "fake", seed=42)

    assert record.status is RunStatus.AWAITING_APPROVAL
    assert record.iterations == 2
    summaries = service.store.list_iterations(record.run_id)
    assert [s["passed"] for s in summaries] == [False, True]
    assert len(summaries[0]["errors"]) >= 1
    assert summaries[0]["errors"][0]["check"] == CheckId.RUNTIME.value
    state = latest_state(service, record.run_id)
    assert [r["passed"] for r in state["history"]] == [False, True]
    assert state["artifact"]["iteration"] == 2
    assert service.store.diff(record.run_id, 2, "pipeline.py") != ""


def test_meridian_escalates_after_exactly_three_iterations(
    service: RunService, deploy_dir: Path
) -> None:
    record = service.start_run(MERIDIAN, "fake", seed=42)

    assert record.status is RunStatus.ESCALATED
    assert record.iterations == 3
    assert record.final_passed is False
    summaries = service.store.list_iterations(record.run_id)
    assert [s["passed"] for s in summaries] == [False, False, False]
    assert all(e["check"] == CheckId.COMPLETENESS.value for e in summaries[-1]["errors"])
    state = latest_state(service, record.run_id)
    assert state["status"] == "escalated"
    assert state["error"]
    assert not deploy_dir.exists()
    with pytest.raises(InvalidTransition):
        service.decide(record.run_id, "approve", "ana")


@pytest.mark.parametrize("client", corpus.list_clients())
def test_every_corpus_scenario_ends_as_its_manifest_declares(
    service: RunService, client: str
) -> None:
    outcome = corpus.load_manifest(client).scenario.expected_outcome
    record = service.start_run(client, "fake", seed=7)
    expected = {
        "pass": (RunStatus.AWAITING_APPROVAL, 1),
        "heal": (RunStatus.AWAITING_APPROVAL, 2),
        "escalate": (RunStatus.ESCALATED, 3),
    }[outcome]
    assert (record.status, record.iterations) == expected


def test_max_iterations_one_escalates_a_heal_scenario(service: RunService) -> None:
    record = service.start_run(NORTHWIND, "fake", seed=3, max_iterations=1)
    assert record.status is RunStatus.ESCALATED
    assert record.iterations == 1


# --------------------------------------------------------------------------- #
# Cross-process resume, history, state_at                                      #
# --------------------------------------------------------------------------- #


def test_second_service_on_same_db_can_decide_a_run_started_by_the_first(
    tmp_db: Path, runs_dir: Path, deploy_dir: Path
) -> None:
    with RunStore(tmp_db, runs_dir) as store_a:
        with RunService(store=store_a, db_path=tmp_db, deploy_dir=deploy_dir) as first:
            started = first.start_run(ACME, "fake", seed=11)
    assert started.status is RunStatus.AWAITING_APPROVAL

    with RunStore(tmp_db, runs_dir) as store_b:
        with RunService(store=store_b, db_path=tmp_db, deploy_dir=deploy_dir) as second:
            record = second.decide(started.run_id, "approve", "ops")
            assert record.status is RunStatus.APPROVED
            assert second.history(started.run_id)[-1]["status"] == "approved"
    assert (deploy_dir / ACME / "pipeline.py").is_file()


def test_history_has_six_or_more_snapshots_in_step_order(service: RunService) -> None:
    record = service.start_run(ACME, "fake", seed=5)
    history = service.history(record.run_id)

    assert len(history) >= 6
    steps = [h["step"] for h in history]
    assert steps == sorted(steps)
    nodes = [h["node"] for h in history]
    assert nodes[-4:] == [st.LOAD_SPEC, st.PLAN, st.GENERATE, st.EVALUATE]
    assert history[-1]["next"] == [st.AWAIT_APPROVAL]
    assert history[-1]["status"] == "evaluating"
    assert history[-1]["iteration"] == 1
    for entry in history:
        assert entry["checkpoint_id"]
        assert entry["created_at"]


def test_state_at_returns_graph_state_dump(service: RunService) -> None:
    record = service.start_run(ACME, "fake", seed=6)
    history = service.history(record.run_id)
    plan_step = next(h["step"] for h in history if h["node"] == st.PLAN)

    state = service.state_at(record.run_id, plan_step)
    assert GraphState.model_validate(state).run_id == record.run_id
    assert state["plan"]["client"] == ACME
    assert state["artifact"] is None
    assert service.state_at(record.run_id, -1) == {}
    with pytest.raises(DrydockError, match="no checkpoint at step 99"):
        service.state_at(record.run_id, 99)


def test_inspection_toolbox_never_calls_tools() -> None:
    toolbox = _InertToolBox()
    assert toolbox.calls == []
    with pytest.raises(RuntimeError, match="inspection graph"):
        toolbox.call("list_samples", client=ACME)


def test_history_and_state_at_unknown_run_raise(service: RunService) -> None:
    with pytest.raises(RunNotFound):
        service.history("ghost")
    with pytest.raises(RunNotFound):
        service.state_at("ghost", 0)


# --------------------------------------------------------------------------- #
# Validation and failure paths                                                 #
# --------------------------------------------------------------------------- #


def test_start_run_unknown_client_raises_corpus_error(service: RunService) -> None:
    with pytest.raises(CorpusError):
        service.start_run("nobody", "fake")
    assert service.list_runs() == []


def test_start_run_rejects_zero_iterations(service: RunService) -> None:
    with pytest.raises(DrydockError, match="max_iterations"):
        service.start_run(ACME, "fake", max_iterations=0)


def test_decide_validates_status_decision_and_approver(service: RunService) -> None:
    with pytest.raises(RunNotFound):
        service.decide("ghost", "approve", "ana")
    started = service.start_run(ACME, "fake", seed=8)
    with pytest.raises(DrydockError, match="decision"):
        service.decide(started.run_id, "maybe", "ana")  # type: ignore[arg-type]
    with pytest.raises(DrydockError, match="approver"):
        service.decide(started.run_id, "approve", "")
    approved = service.decide(started.run_id, "approve", "ana")
    with pytest.raises(InvalidTransition, match="approved"):
        service.decide(approved.run_id, "reject", "ana", "too late")


def test_provider_failure_marks_run_failed_and_logs_event(
    service: RunService, runs_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Broken:
        name = "fake"

        def plan(self, spec: FeedSpec, tools: Any) -> IngestionPlan:
            raise ProviderError("planner exploded")

        def generate(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover
            raise AssertionError("never reached")

    monkeypatch.setattr("drydock.graph.service.load_provider", lambda *a, **k: Broken())
    with pytest.raises(ProviderError, match="exploded"):
        service.start_run(ACME, "fake", seed=9)
    record = service.list_runs()[0]
    assert record.status is RunStatus.FAILED
    events = read_events(runs_dir / record.run_id / EVENTS_FILE)
    assert events[-1]["node"] == "failed"
    assert "exploded" in events[-1]["error"]


def test_get_run_and_list_runs_delegate_to_store(service: RunService) -> None:
    record = service.start_run(ACME, "fake", seed=10)
    assert service.get_run(record.run_id) == service.store.get(record.run_id)
    assert [r.run_id for r in service.list_runs()] == [record.run_id]


# --------------------------------------------------------------------------- #
# Run ids and routing                                                          #
# --------------------------------------------------------------------------- #


def test_seeded_run_ids_are_deterministic_and_unseeded_are_not() -> None:
    assert st.new_run_id(ACME, 42) == st.new_run_id(ACME, 42)
    assert st.new_run_id(ACME, 42) != st.new_run_id(ACME, 43)
    assert st.new_run_id(ACME, 42).startswith(f"{ACME}-{st.SEEDED_TIMESTAMP}-")
    assert len(st.new_run_id(ACME, 42).rsplit("-", 1)[1]) == 6
    first, second = st.new_run_id(ACME), st.new_run_id(ACME)
    assert first != second
    assert st.SEEDED_TIMESTAMP not in first


def _report(passed: bool) -> HarnessReport:
    checks = tuple(CheckResult(check=c, passed=passed) for c in CheckId)
    return HarnessReport(iteration=1, passed=passed, checks=checks)


def test_route_after_evaluate_follows_lld_table() -> None:
    base = st.initial_state("r", ACME, "fake", max_iterations=3)
    assert st.route_after_evaluate(base.model_copy(update={"report": _report(True)})) == "approve"
    failed = base.model_copy(update={"report": _report(False), "iteration": 1})
    assert st.route_after_evaluate(failed) == "repair"
    exhausted = base.model_copy(update={"report": _report(False), "iteration": 3})
    assert st.route_after_evaluate(exhausted) == "escalate"
    assert st.route_after_evaluate(base) == "repair"


def test_route_after_decision_and_summaries() -> None:
    base = st.initial_state("r", ACME, "fake")
    assert st.route_after_decision(base.model_copy(update={"decision": "approve"})) == "approve"
    assert st.route_after_decision(base) == "reject"
    assert st.report_summary(None)["passed"] is None
    payload = st.approval_payload(base.model_copy(update={"report": _report(True)}))
    assert payload["run_id"] == "r"
    assert payload["summary"]["checks"][CheckId.RUNTIME.value] is True


def test_parse_decision_validates_payload() -> None:
    state = st.initial_state("r", ACME, "fake")
    assert _parse_decision({"decision": "approve", "approver": "a"}, state) == (
        "approve",
        "a",
        "",
    )
    with pytest.raises(DrydockError, match="mapping"):
        _parse_decision("approve", state)
    with pytest.raises(DrydockError, match="decision"):
        _parse_decision({"decision": "later", "approver": "a"}, state)
    with pytest.raises(DrydockError, match="approver"):
        _parse_decision({"decision": "approve"}, state)


# --------------------------------------------------------------------------- #
# Events                                                                       #
# --------------------------------------------------------------------------- #


def test_events_log_every_node_and_usage(
    service: RunService, runs_dir: Path, tmp_path: Path
) -> None:
    record = service.start_run(ACME, "fake", seed=12)
    events = read_events(runs_dir / record.run_id / EVENTS_FILE)
    nodes = [e["node"] for e in events]
    assert nodes == [st.LOAD_SPEC, st.PLAN, st.GENERATE, st.EVALUATE, st.AWAIT_APPROVAL]
    assert all(set(e) >= {"ts", "node", "run_id", "iteration"} for e in events)
    assert events[1]["tool_calls"] == list(EVIDENCE)

    writer = EventWriter(tmp_path / "nested" / "events.jsonl")
    writer.on_usage({"prompt_tokens": 10, "completion_tokens": 5, "model": "m", "latency_ms": 7})
    written = read_events(writer.path)
    assert written[0]["node"] == USAGE_NODE
    assert written[0]["prompt_tokens"] == 10
    assert read_events(tmp_path / "missing.jsonl") == []
    assert (tmp_path / "nested" / "events.jsonl").read_bytes().count(b"\r\n") == 0


def test_event_writer_renders_non_json_values_with_str(tmp_path: Path) -> None:
    writer = EventWriter(tmp_path / "e.jsonl")
    record = writer.emit("x", path=tmp_path)
    assert record["path"] == tmp_path
    assert read_events(writer.path)[0]["path"] == str(tmp_path)


# --------------------------------------------------------------------------- #
# The graph itself: a real interrupt, resumed with Command(resume=...)         #
# --------------------------------------------------------------------------- #


@pytest.fixture
def direct_graph(store: RunStore, deploy_dir: Path, tmp_path: Path) -> Iterator[tuple[Any, Deps]]:
    events = EventWriter(tmp_path / "events.jsonl")
    provider = load_provider("fake", fault_plan={ACME: None})
    with McpToolBox(build_server(CORPUS_DIR)) as toolbox:
        deps = Deps(
            provider=provider,
            toolbox=toolbox,
            store=store,
            events=events,
            sandbox="subprocess",
            paths=RunPaths(corpus_root=CORPUS_DIR, runs_dir=store.runs_dir, deploy_dir=deploy_dir),
        )
        yield build_graph(deps, InMemorySaver()), deps


def test_await_approval_is_a_real_interrupt(direct_graph: tuple[Any, Deps]) -> None:
    graph, deps = direct_graph
    run_id = st.new_run_id(ACME, 99)
    deps.store.create(
        RunRecord(run_id=run_id, client=ACME, provider="fake", status=RunStatus.PLANNING)
    )
    config = run_config(run_id)

    graph.invoke(st.initial_state(run_id, ACME, "fake", seed=99).model_dump(), config=config)
    snapshot = graph.get_state(config)
    assert snapshot.next == (st.AWAIT_APPROVAL,)
    interrupts = snapshot.tasks[0].interrupts
    assert len(interrupts) == 1
    payload = interrupts[0].value
    assert payload["run_id"] == run_id
    assert payload["client"] == ACME
    assert payload["iteration"] == 1
    assert payload["summary"]["passed"] is True
    assert deps.store.get(run_id).status is RunStatus.AWAITING_APPROVAL

    resumed = graph.invoke(
        Command(resume={"decision": "approve", "approver": "qa", "note": ""}), config=config
    )
    assert resumed["status"] is RunStatus.APPROVED
    assert graph.get_state(config).next == ()
    assert deps.store.get(run_id).status is RunStatus.APPROVED


def test_invalid_resume_payload_fails_loudly(direct_graph: tuple[Any, Deps]) -> None:
    graph, deps = direct_graph
    run_id = st.new_run_id(ACME, 98)
    deps.store.create(
        RunRecord(run_id=run_id, client=ACME, provider="fake", status=RunStatus.PLANNING)
    )
    config = run_config(run_id)
    graph.invoke(st.initial_state(run_id, ACME, "fake", seed=98).model_dump(), config=config)

    # LangGraph persists the resume value before the node runs, so a payload that fails
    # validation inside the node leaves the thread unrecoverable; RunService.decide validates
    # *before* resuming and this node-level check is only a last line of defence.
    with pytest.raises(DrydockError, match="decision must be one of"):
        graph.invoke(Command(resume={"decision": "shrug", "approver": "qa"}), config=config)
    assert deps.store.get(run_id).status is RunStatus.AWAITING_APPROVAL
    assert graph.get_state(config).tasks[0].error is not None
