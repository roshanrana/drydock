"""Tests for the dashboard API (T-006) against an in-memory stub of the LLD section 7.3 service.

Nothing here imports ``drydock.graph``; the stub implements exactly the ``RunService`` /
``RunStore`` surface the dashboard codes against (see ``RunServiceLike``).
"""

from __future__ import annotations

import difflib
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import pytest
from fastapi.testclient import TestClient

from drydock.dashboard import DecisionRequest, RunServiceLike, create_app, serve
from drydock.dashboard import app as app_module
from drydock.errors import InvalidTransition, RunNotFound
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

FileName = Literal["pipeline.py", "dag.py", "mapping.yaml"]

AWAITING = "acme-treasury-20260907000000-aaaaaa"
APPROVED = "globex-20260907000000-bbbbbb"
PLANNING = "initech-20260907000000-cccccc"
T0 = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)


# --------------------------------------------------------------------------- #
# Stub service                                                                 #
# --------------------------------------------------------------------------- #


def _artifact(iteration: int, body: str) -> PipelineArtifact:
    return PipelineArtifact(
        pipeline_py=f"def extract(path):\n    return {body}\n",
        dag_py="from airflow import DAG\n",
        mapping_yaml=f"iteration: {iteration}\n",
        iteration=iteration,
        generator="fake",
    )


def _report(iteration: int, *, passed: bool) -> HarnessReport:
    schema_findings = (
        ()
        if passed
        else (
            Finding(
                check=CheckId.SCHEMA,
                severity=Severity.ERROR,
                message="missing column 'currency'",
                evidence={"missing": ["currency"]},
            ),
        )
    )
    checks = tuple(
        CheckResult(
            check=cid,
            passed=passed or cid != CheckId.SCHEMA,
            duration_ms=3,
            findings=schema_findings if cid == CheckId.SCHEMA else (),
        )
        for cid in CheckId
    )
    return HarnessReport(iteration=iteration, passed=passed, checks=checks, rows_emitted=42)


class StubStore:
    """In-memory ``RunStore`` (LLD section 7.2) restricted to the read methods."""

    def __init__(self) -> None:
        self.iterations: dict[str, dict[int, tuple[PipelineArtifact, HarnessReport | None]]] = {}

    def add(self, run_id: str, artifact: PipelineArtifact, report: HarnessReport | None) -> None:
        self.iterations.setdefault(run_id, {})[artifact.iteration] = (artifact, report)

    def list_iterations(self, run_id: str) -> list[dict[str, Any]]:
        rows = self.iterations.get(run_id, {})
        return [
            {
                "iteration": n,
                "passed": report.passed if report else None,
                "errors": list(report.errors) if report else [],
                "wall_ms": report.wall_ms if report else 0,
            }
            for n, (_, report) in sorted(rows.items())
        ]

    def load_iteration(
        self, run_id: str, iteration: int
    ) -> tuple[PipelineArtifact, HarnessReport | None]:
        return self.iterations[run_id][iteration]

    def diff(self, run_id: str, iteration: int, file: FileName) -> str:
        if iteration <= 1:
            return ""
        attr = file.replace(".", "_")
        before = getattr(self.iterations[run_id][iteration - 1][0], attr)
        after = getattr(self.iterations[run_id][iteration][0], attr)
        return "".join(
            difflib.unified_diff(
                before.splitlines(keepends=True),
                after.splitlines(keepends=True),
                fromfile=f"iter-{iteration - 1}/{file}",
                tofile=f"iter-{iteration}/{file}",
            )
        )


class StubService:
    """In-memory ``RunService`` (LLD section 7.3)."""

    def __init__(self) -> None:
        self.store = StubStore()
        self.runs: dict[str, RunRecord] = {}
        self.decisions: list[tuple[str, str, str, str]] = []

    def get_run(self, run_id: str) -> RunRecord:
        try:
            return self.runs[run_id]
        except KeyError:
            raise RunNotFound(f"no run {run_id!r}") from None

    def list_runs(self, limit: int = 50) -> list[RunRecord]:
        return sorted(self.runs.values(), key=lambda r: r.created_at, reverse=True)[:limit]

    def decide(
        self, run_id: str, decision: Literal["approve", "reject"], approver: str, note: str = ""
    ) -> RunRecord:
        record = self.get_run(run_id)
        if record.status is not RunStatus.AWAITING_APPROVAL:
            raise InvalidTransition(f"run {run_id!r} is {record.status}, not awaiting_approval")
        self.decisions.append((run_id, decision, approver, note))
        status = RunStatus.APPROVED if decision == "approve" else RunStatus.REJECTED
        updated = record.model_copy(
            update={"status": status, "approved_by": approver, "decision_note": note}
        )
        self.runs = {**self.runs, run_id: updated}
        return updated

    def history(self, run_id: str) -> list[dict[str, Any]]:
        record = self.get_run(run_id)
        nodes = ["load_spec", "plan", "generate", "evaluate"]
        return [
            {
                "step": i,
                "node": node,
                "status": record.status.value,
                "iteration": min(i, record.iterations),
                "checkpoint_id": f"1ef{i:04d}-{run_id[-6:]}",
                "created_at": T0,
            }
            for i, node in enumerate(nodes)
        ]

    def state_at(self, run_id: str, step: int) -> dict[str, Any]:
        record = self.get_run(run_id)
        return {"run_id": run_id, "step": step, "status": record.status.value}


def _seed(service: StubService) -> None:
    service.runs[AWAITING] = RunRecord(
        run_id=AWAITING,
        client="acme-treasury",
        provider="fake",
        status=RunStatus.AWAITING_APPROVAL,
        iterations=2,
        created_at=T0,
        updated_at=T0,
    )
    service.store.add(AWAITING, _artifact(1, "[]"), _report(1, passed=False))
    service.store.add(AWAITING, _artifact(2, "list(rows)"), _report(2, passed=True))

    service.runs[APPROVED] = RunRecord(
        run_id=APPROVED,
        client="globex",
        provider="fake",
        status=RunStatus.APPROVED,
        iterations=1,
        approved_by="reviewer",
        decision_note="lgtm",
        final_passed=True,
        created_at=datetime(2026, 9, 6, tzinfo=UTC),
        updated_at=T0,
    )
    service.store.add(APPROVED, _artifact(1, "[]"), _report(1, passed=True))

    service.runs[PLANNING] = RunRecord(
        run_id=PLANNING,
        client="initech",
        provider="fake",
        status=RunStatus.PLANNING,
        created_at=datetime(2026, 9, 5, tzinfo=UTC),
        updated_at=T0,
    )
    # An iteration whose report has not been written yet (evaluate still running).
    service.store.add(PLANNING, _artifact(1, "[]"), None)


@pytest.fixture
def service() -> StubService:
    svc = StubService()
    _seed(svc)
    return svc


@pytest.fixture
def client(service: StubService) -> TestClient:
    typed: RunServiceLike = service  # the stub must satisfy the protocol under mypy
    return TestClient(create_app(typed))


# --------------------------------------------------------------------------- #
# Runs                                                                         #
# --------------------------------------------------------------------------- #


def test_list_runs_returns_json_dumps_newest_first(client: TestClient) -> None:
    res = client.get("/api/runs")

    assert res.status_code == 200
    body = res.json()
    assert [r["run_id"] for r in body] == [AWAITING, APPROVED, PLANNING]
    assert body[0]["status"] == "awaiting_approval"
    assert body[0]["created_at"] == "2026-09-07T12:00:00Z"


def test_list_runs_honours_limit(client: TestClient) -> None:
    assert len(client.get("/api/runs", params={"limit": 1}).json()) == 1
    assert client.get("/api/runs", params={"limit": 0}).status_code == 422


def test_get_run_returns_record_and_iterations(client: TestClient) -> None:
    res = client.get(f"/api/runs/{AWAITING}")

    assert res.status_code == 200
    body = res.json()
    assert body["run"]["run_id"] == AWAITING
    assert body["run"]["iterations"] == 2
    iters = body["iterations"]
    assert [i["iteration"] for i in iters] == [1, 2]
    assert iters[0]["passed"] is False and iters[1]["passed"] is True
    assert iters[0]["errors"][0]["check"] == "H2_schema"
    assert iters[0]["errors"][0]["severity"] == "error"


def test_get_unknown_run_is_404(client: TestClient) -> None:
    res = client.get("/api/runs/nope")

    assert res.status_code == 404
    assert "nope" in res.json()["detail"]


# --------------------------------------------------------------------------- #
# Iterations and diff                                                          #
# --------------------------------------------------------------------------- #


def test_get_iteration_returns_artifact_and_report(client: TestClient) -> None:
    res = client.get(f"/api/runs/{AWAITING}/iterations/1")

    assert res.status_code == 200
    body = res.json()
    assert body["artifact"]["iteration"] == 1
    assert body["artifact"]["pipeline_py"].startswith("def extract")
    report = body["report"]
    assert report["passed"] is False
    assert len(report["checks"]) == 6
    failed = [c for c in report["checks"] if not c["passed"]]
    assert [c["check"] for c in failed] == ["H2_schema"]
    assert failed[0]["findings"][0]["evidence"] == {"missing": ["currency"]}


def test_get_iteration_without_report_serialises_null(client: TestClient) -> None:
    body = client.get(f"/api/runs/{PLANNING}/iterations/1").json()

    assert body["artifact"]["iteration"] == 1
    assert body["report"] is None


def test_get_iteration_unknown_run_or_iteration_is_404(client: TestClient) -> None:
    assert client.get("/api/runs/nope/iterations/1").status_code == 404
    res = client.get(f"/api/runs/{AWAITING}/iterations/9")
    assert res.status_code == 404
    assert "iteration 9" in res.json()["detail"]


def test_diff_returns_unified_diff_for_requested_file(client: TestClient) -> None:
    res = client.get(f"/api/runs/{AWAITING}/diff/2", params={"file": "pipeline.py"})

    assert res.status_code == 200
    body = res.json()
    assert body == {
        "run_id": AWAITING,
        "iteration": 2,
        "file": "pipeline.py",
        "diff": body["diff"],
    }
    assert "-    return []" in body["diff"]
    assert "+    return list(rows)" in body["diff"]


def test_diff_defaults_to_pipeline_and_is_empty_for_first_iteration(client: TestClient) -> None:
    body = client.get(f"/api/runs/{AWAITING}/diff/1").json()

    assert body["file"] == "pipeline.py"
    assert body["diff"] == ""


def test_diff_rejects_unknown_file_and_unknown_iteration(client: TestClient) -> None:
    assert client.get(f"/api/runs/{AWAITING}/diff/2", params={"file": "x.py"}).status_code == 422
    assert client.get(f"/api/runs/{AWAITING}/diff/5").status_code == 404
    assert client.get("/api/runs/nope/diff/1").status_code == 404


# --------------------------------------------------------------------------- #
# History                                                                      #
# --------------------------------------------------------------------------- #


def test_history_returns_checkpoint_rows(client: TestClient) -> None:
    res = client.get(f"/api/runs/{AWAITING}/history")

    assert res.status_code == 200
    rows = res.json()
    assert [r["node"] for r in rows] == ["load_spec", "plan", "generate", "evaluate"]
    assert set(rows[0]) == {"step", "node", "status", "iteration", "checkpoint_id", "created_at"}
    assert rows[0]["created_at"] == "2026-09-07T12:00:00Z"


def test_history_unknown_run_is_404(client: TestClient) -> None:
    assert client.get("/api/runs/nope/history").status_code == 404


# --------------------------------------------------------------------------- #
# Decision                                                                     #
# --------------------------------------------------------------------------- #


def test_decision_approve_updates_run(client: TestClient, service: StubService) -> None:
    res = client.post(
        f"/api/runs/{AWAITING}/decision",
        json={"decision": "approve", "approver": "roshan", "note": "ship it"},
    )

    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "approved"
    assert body["approved_by"] == "roshan"
    assert body["decision_note"] == "ship it"
    assert service.decisions == [(AWAITING, "approve", "roshan", "ship it")]
    assert client.get(f"/api/runs/{AWAITING}").json()["run"]["status"] == "approved"


def test_decision_reject_with_default_note(client: TestClient, service: StubService) -> None:
    res = client.post(
        f"/api/runs/{AWAITING}/decision", json={"decision": "reject", "approver": "qa"}
    )

    assert res.status_code == 200
    assert res.json()["status"] == "rejected"
    assert service.decisions == [(AWAITING, "reject", "qa", "")]


def test_decision_on_wrong_status_is_409(client: TestClient) -> None:
    res = client.post(
        f"/api/runs/{APPROVED}/decision", json={"decision": "approve", "approver": "x"}
    )

    assert res.status_code == 409
    assert "awaiting_approval" in res.json()["detail"]


def test_decision_unknown_run_is_404(client: TestClient) -> None:
    res = client.post("/api/runs/nope/decision", json={"decision": "approve", "approver": "x"})

    assert res.status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        {"decision": "maybe", "approver": "x"},
        {"decision": "approve", "approver": ""},
        {"decision": "approve"},
        {"decision": "approve", "approver": "x", "extra": 1},
    ],
)
def test_decision_invalid_body_is_422(client: TestClient, body: dict[str, Any]) -> None:
    assert client.post(f"/api/runs/{AWAITING}/decision", json=body).status_code == 422


def test_decision_request_model_is_frozen() -> None:
    req = DecisionRequest(decision="approve", approver="a")

    assert req.note == ""
    with pytest.raises(Exception):  # noqa: B017 - pydantic raises ValidationError for frozen
        req.approver = "b"  # type: ignore[misc]


# --------------------------------------------------------------------------- #
# Static UI                                                                    #
# --------------------------------------------------------------------------- #


def test_index_serves_html_with_brand(client: TestClient) -> None:
    res = client.get("/")

    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/html")
    assert "DRYDOCK" in res.text
    assert "<script" in res.text and "fetch(" in res.text


def test_index_is_self_contained() -> None:
    html = Path(app_module.INDEX_HTML).read_text(encoding="utf-8")

    assert "http://" not in html and "https://" not in html
    assert not re.search(r"<link\s", html), "no external stylesheets"
    assert not re.search(r"<script[^>]*\ssrc=", html), "no external scripts"
    assert "@import" not in html and "@font-face" not in html
    assert "innerHTML" not in html, "server text must be inserted via textContent"


def test_index_uses_results_card_palette() -> None:
    html = Path(app_module.INDEX_HTML).read_text(encoding="utf-8")

    for colour in ("#0f172a", "#1e293b", "#e2e8f0", "#2dd4bf", "#fbbf24", "#f87171"):
        assert colour in html
    for feature in ("awaiting_approval", "diff vs previous", "Checkpoints", "5000"):
        assert feature in html


# --------------------------------------------------------------------------- #
# serve() hook                                                                 #
# --------------------------------------------------------------------------- #


def test_serve_runs_uvicorn_on_loopback(
    service: StubService, monkeypatch: pytest.MonkeyPatch
) -> None:
    import uvicorn

    calls: list[dict[str, Any]] = []

    def fake_run(app: Any, **kwargs: Any) -> None:
        calls.append({"app": app, **kwargs})

    monkeypatch.setattr(uvicorn, "run", fake_run)

    serve(service, port=8787)

    assert len(calls) == 1
    assert calls[0]["host"] == "127.0.0.1" and calls[0]["port"] == 8787
    assert calls[0]["app"].title == "DRYDOCK dashboard"
