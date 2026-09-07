"""CLI via ``typer.testing.CliRunner`` against a temporary tree (LLD section 7.4)."""

from __future__ import annotations

import importlib
import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from drydock import cli, corpus
from drydock.cli import app, render_table
from drydock.errors import DrydockError
from drydock.paths import CORPUS_DIR

ACME = "acme-treasury"


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    return {
        "DRYDOCK_DB": str(tmp_path / "data" / "drydock.db"),
        "DRYDOCK_RUNS_DIR": str(tmp_path / "runs"),
        "DRYDOCK_DEPLOY_DIR": str(tmp_path / "deploy"),
        "DRYDOCK_CORPUS_ROOT": str(CORPUS_DIR),
    }


@pytest.fixture
def acme_run(runner: CliRunner, env: dict[str, str]) -> Iterator[str]:
    result = runner.invoke(app, ["build", ACME, "--provider", "fake", "--seed", "21"], env=env)
    assert result.exit_code == 0, result.output
    yield result.output.splitlines()[-1].split()[0]


def test_build_prints_run_table_with_awaiting_approval(acme_run: str, env: dict[str, str]) -> None:
    assert acme_run.startswith(f"{ACME}-00000000000000-")
    assert Path(env["DRYDOCK_RUNS_DIR"], acme_run, "iter-1", "pipeline.py").is_file()


def test_build_json_prints_record(runner: CliRunner, env: dict[str, str]) -> None:
    result = runner.invoke(app, ["build", ACME, "--seed", "22", "--json"], env=env)
    assert result.exit_code == 0, result.output
    record = json.loads(result.output)
    assert record["status"] == "awaiting_approval"
    assert record["iterations"] == 1


def test_build_unknown_client_exits_2(runner: CliRunner, env: dict[str, str]) -> None:
    result = runner.invoke(app, ["build", "nobody"], env=env)
    assert result.exit_code == 2
    assert "error:" in result.output


def test_build_rejects_bad_sandbox(runner: CliRunner, env: dict[str, str]) -> None:
    result = runner.invoke(app, ["build", ACME, "--sandbox", "cloud"], env=env)
    assert result.exit_code == 2
    assert "--sandbox" in result.output


def test_runs_table_and_json(runner: CliRunner, env: dict[str, str], acme_run: str) -> None:
    table = runner.invoke(app, ["runs"], env=env)
    assert table.exit_code == 0
    assert acme_run in table.output
    assert "awaiting_approval" in table.output

    as_json = runner.invoke(app, ["runs", "--json", "--limit", "5"], env=env)
    assert as_json.exit_code == 0
    payload = json.loads(as_json.output)
    assert [r["run_id"] for r in payload] == [acme_run]


def test_show_text_and_json(runner: CliRunner, env: dict[str, str], acme_run: str) -> None:
    text = runner.invoke(app, ["show", acme_run], env=env)
    assert text.exit_code == 0, text.output
    assert "final_passed: True" in text.output
    assert "iteration  passed" in text.output

    as_json = runner.invoke(app, ["show", acme_run, "--json"], env=env)
    payload = json.loads(as_json.output)
    assert payload["run"]["run_id"] == acme_run
    assert payload["iterations"][0]["passed"] is True


def test_show_unknown_run_exits_2(runner: CliRunner, env: dict[str, str]) -> None:
    result = runner.invoke(app, ["show", "ghost"], env=env)
    assert result.exit_code == 2
    assert "no run with id" in result.output


def test_approve_publishes_and_second_approve_exits_2(
    runner: CliRunner, env: dict[str, str], acme_run: str
) -> None:
    result = runner.invoke(app, ["approve", acme_run, "--approver", "ana", "--note", "ok"], env=env)
    assert result.exit_code == 0, result.output
    assert "approved" in result.output
    deploy = Path(env["DRYDOCK_DEPLOY_DIR"], ACME)
    assert (deploy / "approval.json").is_file()
    approval = json.loads((deploy / "approval.json").read_text(encoding="utf-8"))
    assert approval["approver"] == "ana"

    again = runner.invoke(app, ["approve", acme_run], env=env)
    assert again.exit_code == 2
    assert "only awaiting_approval" in again.output


def test_reject_requires_note_and_publishes_nothing(
    runner: CliRunner, env: dict[str, str], acme_run: str
) -> None:
    missing = runner.invoke(app, ["reject", acme_run], env=env)
    assert missing.exit_code != 0

    result = runner.invoke(app, ["reject", acme_run, "--note", "nope"], env=env)
    assert result.exit_code == 0, result.output
    assert "rejected" in result.output
    assert not Path(env["DRYDOCK_DEPLOY_DIR"]).exists()


def test_replay_lists_history_and_dumps_state(
    runner: CliRunner, env: dict[str, str], acme_run: str
) -> None:
    history = runner.invoke(app, ["replay", acme_run], env=env)
    assert history.exit_code == 0, history.output
    lines = [line for line in history.output.splitlines() if line.strip()]
    assert lines[0].split()[:3] == ["step", "node", "status"]
    assert len(lines) >= 8
    assert "evaluate" in history.output

    state = runner.invoke(app, ["replay", acme_run, "--step", "4"], env=env)
    assert state.exit_code == 0, state.output
    payload = json.loads(state.output)
    assert payload["run_id"] == acme_run
    assert payload["report"]["passed"] is True

    bad = runner.invoke(app, ["replay", acme_run, "--step", "77"], env=env)
    assert bad.exit_code == 2


def test_global_options_override_env(runner: CliRunner, tmp_path: Path) -> None:
    args = [
        "--db",
        str(tmp_path / "x.db"),
        "--runs-dir",
        str(tmp_path / "r"),
        "--deploy-dir",
        str(tmp_path / "d"),
        "runs",
        "--json",
    ]
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == []
    assert (tmp_path / "x.db").is_file()


def test_corpus_verify_and_rebuild(
    runner: CliRunner, env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = runner.invoke(app, ["corpus", "verify"], env=env)
    assert result.exit_code == 0, result.output
    assert result.output.startswith("corpus ok: 6 clients")

    bad = runner.invoke(app, ["--corpus-root", str(tmp_path / "empty"), "corpus", "verify"])
    assert bad.exit_code == 2

    called: list[Path] = []

    def fake_rebuild(root: Path) -> list[Path]:
        called.append(root)
        return [root / "acme-treasury" / "manifest.json"]

    monkeypatch.setattr(corpus, "rebuild_manifests", fake_rebuild)
    rebuilt = runner.invoke(app, ["corpus", "rebuild-manifests"], env=env)
    assert rebuilt.exit_code == 0, rebuilt.output
    assert "wrote" in rebuilt.output
    assert called == [CORPUS_DIR]


@pytest.mark.parametrize(
    ("command", "module", "task"),
    [
        (["serve"], "drydock.dashboard.app", "T-006"),
        (["mcp"], "drydock.mcp.server", "T-007"),
        (["bench"], "drydock.bench", "T-009"),
    ],
)
def test_later_task_commands_explain_when_module_is_absent(
    runner: CliRunner,
    env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    command: list[str],
    module: str,
    task: str,
) -> None:
    def missing(name: str) -> object:
        raise ImportError(f"No module named {name!r}")

    monkeypatch.setattr(importlib, "import_module", missing)
    result = runner.invoke(app, command, env=env)
    assert result.exit_code == 2
    assert module in result.output
    assert task in result.output


def test_guarded_maps_drydock_error_to_exit_2() -> None:
    @cli.guarded
    def boom() -> None:
        raise DrydockError("bad thing")

    import typer

    with pytest.raises(typer.Exit) as excinfo:
        boom()
    assert excinfo.value.exit_code == 2


def test_render_table_fits_columns() -> None:
    text = render_table(("a", "bb"), [["xxx", "y"]])
    assert text.splitlines() == ["a    bb", "---  --", "xxx  y"]
