"""``drydock bench`` replays the corpus offline into a byte-stable headline (T-009).

The bench takes about fifteen seconds (the ``sleeps_past_budget`` adversarial case sleeps
six seconds per sample), so it runs once per module, twice in total to prove determinism.
Marked ``slow`` but never skipped: this is the number the README shows.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from drydock import bench, paths
from drydock.errors import DrydockError
from drydock.graph.store import RunStore
from drydock.models import CheckId, PipelineArtifact, RunRecord, RunStatus
from metrics import render

pytestmark = pytest.mark.slow

CARD = json.loads((paths.ROOT / "metrics" / "card.json").read_text(encoding="utf-8"))
DEV_DIRS = (paths.DATA_DIR, paths.RUNS_DIR, paths.DEPLOY_DIR)


def _listing(directory: Path) -> tuple[str, ...]:
    return tuple(sorted(p.name for p in directory.iterdir())) if directory.is_dir() else ()


@dataclass(frozen=True)
class TwoRuns:
    first: Path
    second: Path
    kept_workdir: Path
    removed_workdir: Path
    dev_before: tuple[tuple[str, ...], ...]
    dev_after: tuple[tuple[str, ...], ...]
    echo_lines: tuple[str, ...]

    @property
    def headline(self) -> dict[str, object]:
        payload: dict[str, object] = json.loads(self.first.read_text(encoding="utf-8"))
        return payload


@pytest.fixture(scope="module")
def two_runs(tmp_path_factory: pytest.TempPathFactory) -> Iterator[TwoRuns]:
    root = tmp_path_factory.mktemp("bench")
    dev_before = tuple(_listing(d) for d in DEV_DIRS)
    kept, removed = root / "work-keep", root / "work-drop"
    lines: list[str] = []
    bench.main(out=root / "one" / "headline.json", keep=True, workdir=kept, echo=lines.append)
    bench.main(out=root / "two" / "headline.json", workdir=removed, echo=lines.append)
    yield TwoRuns(
        first=root / "one" / "headline.json",
        second=root / "two" / "headline.json",
        kept_workdir=kept,
        removed_workdir=removed,
        dev_before=dev_before,
        dev_after=tuple(_listing(d) for d in DEV_DIRS),
        echo_lines=tuple(lines),
    )


def test_two_runs_write_identical_bytes(two_runs: TwoRuns) -> None:
    first = two_runs.first.read_bytes()
    assert first == two_runs.second.read_bytes()
    assert b"\r" not in first
    assert first.endswith(b"}\n")


def test_kpis_follow_card_order_with_declared_outcomes(two_runs: TwoRuns) -> None:
    kpis = two_runs.headline["kpis"]
    assert isinstance(kpis, dict)
    assert list(kpis) == CARD["kpi_order"] == list(bench.KPI_ORDER)
    assert kpis["scenarios"]["value"] == "6 / 6"
    assert kpis["adversarial_rejected"]["value"] == "5 / 5"
    assert kpis["healed_rate"]["value"] == "4 / 4"
    assert kpis["first_pass_rate"]["value"] == "1 / 6"
    assert kpis["mean_iterations"]["value"] == "2.00"
    assert int(kpis["checkpoints"]["value"]) >= 6 * 6
    for tile in kpis.values():
        assert tile["note"], "every KPI says how it was measured"


def test_headline_satisfies_render_schema(two_runs: TwoRuns) -> None:
    render.validate(two_runs.headline, CARD["kpi_order"])


def test_bars_count_error_findings_per_check(two_runs: TwoRuns) -> None:
    bars = two_runs.headline["bars"]
    assert isinstance(bars, dict)
    rows = bars["rows"]
    assert [row["label"] for row in rows] == [c.value.replace("_", " ") for c in CheckId]
    total = sum(row["value"] for row in rows)
    assert total > 0
    assert all(row["max"] == total for row in rows)
    assert all(row["value"] >= 1 for row in rows), "each adversarial case trips its check"


def test_facts_report_evidence_and_explicit_pending_rows(two_runs: TwoRuns) -> None:
    facts = two_runs.headline["facts"]
    assert isinstance(facts, dict)
    rows = {row["label"]: row for row in facts["rows"]}
    assert rows["Escalations"]["value"].startswith("1 of 6: meridian-legacy, spec contradicts")
    assert rows["Artifacts published"]["value"].startswith("5 clients under deploy/")
    assert rows["MCP tool calls made"]["value"].startswith("18 over an in-memory MCP session")
    assert rows["Sandbox kind"]["value"].startswith("subprocess")
    assert rows["Sandbox kind"]["status"] == "ok"
    for label in ("Live provider accuracy", "Docker sandbox", "Airflow real import"):
        assert rows[label]["status"] == "pending"


def test_headline_carries_no_environment_facts(two_runs: TwoRuns) -> None:
    text = two_runs.first.read_text(encoding="utf-8")
    assert str(two_runs.kept_workdir) not in text
    assert str(paths.ROOT) not in text
    assert "wall_ms" not in text
    assert '"ts"' not in text
    assert "20" + "26" not in text, "no dates"


def test_bench_uses_a_temporary_tree_and_honours_keep(two_runs: TwoRuns) -> None:
    assert two_runs.dev_after == two_runs.dev_before, "developer data/, runs/, deploy/ untouched"
    assert not two_runs.removed_workdir.exists()
    kept = two_runs.kept_workdir
    assert (kept / "data" / "drydock.db").is_file()
    assert len(list((kept / "runs").iterdir())) == 6
    assert sorted(p.name for p in (kept / "deploy").iterdir()) == [
        "acme-treasury",
        "blue-harbour-fx",
        "kestrel-payments",
        "northwind-custody",
        "orion-prime",
    ]
    # slow_network_import is rejected by the static AST guard, so it never gets a scratch dir.
    assert sorted(p.name for p in (kept / bench.ADVERSARIAL_DIRNAME).iterdir()) == [
        "dag_missing_dependency",
        "drops_last_row",
        "sleeps_past_budget",
        "wrong_amount_format",
    ]


def test_written_file_is_the_canonical_dump(two_runs: TwoRuns) -> None:
    payload = json.loads(two_runs.first.read_text(encoding="utf-8"))
    assert bench.dump_headline(payload) == two_runs.first.read_text(encoding="utf-8")


def test_bench_echoes_one_line_per_run_and_case_plus_a_summary(two_runs: TwoRuns) -> None:
    lines = two_runs.echo_lines
    assert sum(1 for line in lines if line.startswith("bench: seed=42")) == 2
    assert sum(1 for line in lines if "observed=" in line) == 12
    assert sum(1 for line in lines if " rejected " in line) == 10
    assert lines[-1].endswith("scenarios 6 / 6, adversarial 5 / 5, checkpoints 59")
    assert any(line.startswith("bench: kept working tree at") for line in lines)


def test_headline_rejects_kpi_order_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    result = bench.BenchResult(runs=(), adversarial=(), published=(), max_iterations=3)
    monkeypatch.setattr(bench, "KPI_ORDER", ("checkpoints",))
    with pytest.raises(RuntimeError, match="kpi order"):
        bench.headline(result)


def test_headline_handles_an_empty_result() -> None:
    payload = bench.headline(
        bench.BenchResult(runs=(), adversarial=(), published=(), max_iterations=3)
    )
    assert payload["kpis"]["scenarios"]["value"] == "0 / 0"
    assert payload["kpis"]["mean_iterations"]["value"] == "0.00"
    assert all(row["max"] == 0 for row in payload["bars"]["rows"])
    render.validate(payload, CARD["kpi_order"])


def _outcome(status: RunStatus, iterations: int) -> bench.RunOutcome:
    artifact = PipelineArtifact(
        pipeline_py="", dag_py="", mapping_yaml="", iteration=1, generator="x"
    )
    return bench.RunOutcome(
        client="acme-treasury",
        run_id="acme-treasury-00000000000000-000000",
        expected="pass",
        injected_defect=None,
        status=status,
        iterations=iterations,
        checkpoints=0,
        tool_calls=(),
        reports=(),
        final_artifact=artifact,
    )


@pytest.mark.parametrize(
    ("status", "iterations", "observed"),
    [
        (RunStatus.APPROVED, 1, "pass"),
        (RunStatus.APPROVED, 2, "heal"),
        (RunStatus.ESCALATED, 3, "escalate"),
        (RunStatus.FAILED, 1, "failed"),
        (RunStatus.REJECTED, 2, "rejected"),
    ],
)
def test_observed_outcome_follows_final_status(
    status: RunStatus, iterations: int, observed: str
) -> None:
    outcome = _outcome(status, iterations)
    assert outcome.observed == observed
    assert outcome.matched is (observed == "pass")
    assert outcome.first_pass is False, "no reports means no first pass"


def test_published_clients_is_empty_without_a_deploy_dir(tmp_path: Path) -> None:
    assert bench._published_clients(tmp_path / "missing") == ()


def test_load_reports_refuses_an_iteration_without_a_report(store: RunStore) -> None:
    run_id = "acme-treasury-00000000000000-abcdef"
    store.create(
        RunRecord(run_id=run_id, client="acme-treasury", provider="fake", status=RunStatus.PLANNING)
    )
    artifact = PipelineArtifact(
        pipeline_py="", dag_py="", mapping_yaml="", iteration=1, generator="fake"
    )
    store.save_iteration(run_id, artifact, None)
    with pytest.raises(DrydockError, match="has no report"):
        bench._load_reports(store, run_id, 1)
