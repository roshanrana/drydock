"""Sandbox escape suite (T-012): every reviewed payload, run through ``evaluate()``.

Each test asserts three things: the run does **not** pass, the side effect did **not**
happen (no file created, no external content leaked into any finding evidence), and the
report names the layer that stopped it — a static guard finding (``forbidden_import`` /
``forbidden_call``) or a runtime ``PermissionError`` / ``ImportError`` in the H1 evidence.

The three layers under test:
* layer 1 - static AST guard (``drydock.harness.guard``): blocks before execution;
* layer 2 - runtime jail (``drydock.harness.runner``): jailed ``open``, disabled ``os``
  capabilities, poisoned imports; surfaces as a ``PermissionError`` / ``ImportError``;
* layer 3 - process containment (``drydock.harness.sandbox``): process-tree kill on timeout
  and a memory cap.

Timeouts are short (1-5 s). Nothing here needs docker; the docker read-only mount is
covered by ``tests/test_harness.py::test_docker_read_only_mount_blocks_writes``.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

from drydock.harness import evaluate, runner
from drydock.models import CheckId, HarnessReport, PipelineArtifact
from tests.fixtures.manifest_stub import SAMPLE, make_manifest, make_spec

FIXTURES = SAMPLE.parent
GOOD_PIPELINE = (FIXTURES / "good_pipeline.py").read_text(encoding="utf-8")
GOOD_DAG = (FIXTURES / "good_dag.py").read_text(encoding="utf-8")
FAST_TIMEOUT_S = 5.0


def _artifact(pipeline_src: str) -> PipelineArtifact:
    return PipelineArtifact(
        pipeline_py=pipeline_src,
        dag_py=GOOD_DAG,
        mapping_yaml="client: acme\nfeed: ledger\nformat: csv\nfields: []\n",
        iteration=1,
        generator="escape-test",
    )


def _judge(
    pipeline_src: str,
    *,
    workdir: Path | None = None,
    timeout_s: float = FAST_TIMEOUT_S,
    samples: list[Path] | None = None,
) -> HarnessReport:
    return evaluate(
        _artifact(pipeline_src),
        make_spec(),
        make_manifest(*(samples or [SAMPLE])),
        samples or [SAMPLE],
        iteration=1,
        timeout_s=timeout_s,
        workdir=workdir,
    )


def _h1(report: HarnessReport) -> object:
    return next(c for c in report.checks if c.check == CheckId.RUNTIME)


def _guard_values(report: HarnessReport) -> set[str]:
    """Every forbidden_import / forbidden_call value the static guard reported for H1."""
    values: set[str] = set()
    for finding in _h1(report).findings:  # type: ignore[attr-defined]
        for key in ("forbidden_import", "forbidden_call"):
            value = finding.evidence.get(key)
            if isinstance(value, str):
                values.add(value)
    return values


def _h1_stderr(report: HarnessReport) -> str:
    return "\n".join(
        str(f.evidence.get("stderr_tail", ""))
        for f in _h1(report).findings  # type: ignore[attr-defined]
    )


# --------------------------------------------------------------------------- #
# Layer 1: static guard blocks before anything executes                        #
# --------------------------------------------------------------------------- #

GUARD_PAYLOADS = [
    pytest.param(
        'import os.path as osp\nosp.os.system("echo PWNED > pwn.txt")\n', id="os.path-hop"
    ),
    pytest.param('import typing\ntyping.sys.modules["os"].system("x")\n', id="typing.sys-hop"),
    pytest.param("import json\njson.codecs.sys.modules\n", id="json.codecs-hop"),
    pytest.param("import re\nre.functools.sys.modules\n", id="re.functools-hop"),
    pytest.param("import decimal\ndecimal.sys.modules['os'].system('x')\n", id="decimal.sys-hop"),
    pytest.param('from pathlib import Path\nPath("x.txt").write_text("y")\n', id="write_text"),
    pytest.param('open("x.txt", "w")\n', id="open-w"),
    pytest.param('from pathlib import Path\nPath("x").mkdir()\n', id="mkdir"),
    pytest.param('from pathlib import Path\nPath("acme_ledger.csv").unlink()\n', id="unlink"),
    pytest.param('__import__("os")\n', id="dunder-import"),
    pytest.param('import importlib\nimportlib.import_module("os")\n', id="importlib"),
    pytest.param('getattr(__builtins__, "__import__")("os")\n', id="getattr-builtins"),
    pytest.param('exec("import os")\n', id="exec"),
    pytest.param("().__class__.__bases__[0].__subclasses__()\n", id="subclasses-walk"),
]


@pytest.mark.parametrize("payload", GUARD_PAYLOADS)
def test_guard_blocks_payload_before_execution(payload: str, tmp_path: Path) -> None:
    report = _judge(payload + GOOD_PIPELINE, workdir=tmp_path)

    assert not report.passed
    # A guard finding names the layer: forbidden_import or forbidden_call.
    assert _guard_values(report), "expected a static guard finding"
    # Blocked before execution => the scratch dir was never staged, no file was written.
    assert list(tmp_path.iterdir()) == []


# --------------------------------------------------------------------------- #
# Layer 2: runtime jail stops reads/writes that slip past the static guard     #
# --------------------------------------------------------------------------- #


def test_pathlib_read_outside_workdir_is_blocked_and_not_leaked(tmp_path: Path) -> None:
    secret = tmp_path / "secret.txt"
    marker = f"LEAK_{uuid.uuid4().hex}"
    secret.write_text(marker, encoding="utf-8")
    wd = tmp_path / "wd"
    payload = f'from pathlib import Path\n_x = Path(r"{secret}").read_text()\n'

    report = _judge(payload + GOOD_PIPELINE, workdir=wd, timeout_s=FAST_TIMEOUT_S)

    assert not report.passed
    assert marker not in report.model_dump_json(), "external file content leaked into the report"
    assert "PermissionError" in _h1_stderr(report)
    assert "read outside workdir" in _h1_stderr(report)


def test_builtin_open_read_outside_workdir_is_blocked(tmp_path: Path) -> None:
    secret = tmp_path / "secret.txt"
    marker = f"LEAK_{uuid.uuid4().hex}"
    secret.write_text(marker, encoding="utf-8")
    wd = tmp_path / "wd"
    payload = f'_x = open(r"{secret}").read()\n'

    report = _judge(payload + GOOD_PIPELINE, workdir=wd, timeout_s=FAST_TIMEOUT_S)

    assert not report.passed
    assert marker not in report.model_dump_json()
    assert "PermissionError" in _h1_stderr(report)


def test_pathlib_replace_is_disabled_at_runtime(tmp_path: Path) -> None:
    # str.replace collides with Path.replace, so the guard cannot block the name; the runtime
    # jail disables os.replace (which Path.replace calls) instead.
    victim = tmp_path / "wd" / "victim.txt"
    payload = 'from pathlib import Path\nPath("acme_ledger.csv").replace("victim.txt")\n'
    report = _judge(payload + GOOD_PIPELINE, workdir=tmp_path / "wd", timeout_s=FAST_TIMEOUT_S)

    assert not report.passed
    assert not victim.exists()
    assert "PermissionError" in _h1_stderr(report) or "disabled" in _h1_stderr(report)


# --------------------------------------------------------------------------- #
# Layer 3: process containment - tree kill on timeout, memory cap              #
# --------------------------------------------------------------------------- #


def _command_lines() -> str | None:
    """Best-effort snapshot of every running process command line, or None if unavailable."""
    try:
        if sys.platform == "win32":
            out = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "Get-CimInstance Win32_Process | ForEach-Object { $_.CommandLine }",
                ],
                capture_output=True,
                timeout=20,
                check=False,
            )
        else:
            out = subprocess.run(
                ["ps", "-eo", "args"], capture_output=True, timeout=20, check=False
            )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout.decode("utf-8", errors="replace")


def test_sleeping_child_tree_is_killed_on_timeout(tmp_path: Path) -> None:
    # A unique sample name makes the sandbox child identifiable in the process list.
    token = f"escape_{uuid.uuid4().hex}"
    sample = tmp_path / f"{token}.csv"
    shutil.copy(SAMPLE, sample)
    payload = "import time\ntime.sleep(60)\n" + GOOD_PIPELINE

    started = time.perf_counter()
    report = _judge(payload, workdir=tmp_path / "wd", timeout_s=1.0, samples=[sample])
    elapsed = time.perf_counter() - started

    assert not report.passed
    assert _h1(report).findings[0].evidence["timed_out"] is True  # type: ignore[attr-defined]
    assert elapsed < 30.0, "evaluate blocked on the sleeping child instead of killing the tree"
    # Give the OS a moment to reap, then assert no survivor carries our unique sample name.
    time.sleep(1.0)
    lines = _command_lines()
    if lines is not None:
        assert token not in lines, "a sandbox child survived the timeout kill"


def test_memory_bomb_is_contained_within_the_timeout(tmp_path: Path) -> None:
    payload = "_bomb = [bytearray(10**8) for _ in range(100)]\n" + GOOD_PIPELINE

    started = time.perf_counter()
    report = _judge(payload, workdir=tmp_path / "wd", timeout_s=5.0)
    elapsed = time.perf_counter() - started

    assert not report.passed
    assert failing_is_runtime(report)
    assert elapsed < 10.0, "harness did not return within timeout + 5 s"
    if sys.platform != "win32":
        # POSIX RLIMIT_AS turns the bomb into a MemoryError, not a timeout.
        assert "MemoryError" in _h1_stderr(report)
        assert _h1(report).findings[0].evidence["timed_out"] is False  # type: ignore[attr-defined]


def failing_is_runtime(report: HarnessReport) -> bool:
    return {f.check for f in report.errors} == {CheckId.RUNTIME}


# --------------------------------------------------------------------------- #
# Runtime jail internals (pure helpers - exercised here in-process, safely)     #
# --------------------------------------------------------------------------- #


def test_jailed_open_allows_reads_inside_workdir(tmp_path: Path) -> None:
    workdir = tmp_path.resolve()
    inside = workdir / "data.csv"
    inside.write_text("ok", encoding="utf-8")
    opener = runner._jailed_open(workdir)

    with opener(str(inside), "r", encoding="utf-8") as handle:
        assert handle.read() == "ok"


def test_jailed_open_rejects_write_modes(tmp_path: Path) -> None:
    opener = runner._jailed_open(tmp_path.resolve())
    for mode in ("w", "a", "x", "r+", "rb+"):
        with pytest.raises(PermissionError, match="write mode"):
            opener(str(tmp_path / "x"), mode)


def test_jailed_open_rejects_reads_outside_workdir(tmp_path: Path) -> None:
    workdir = tmp_path / "wd"
    workdir.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("secret", encoding="utf-8")
    opener = runner._jailed_open(workdir.resolve())

    with pytest.raises(PermissionError, match="read outside workdir"):
        opener(str(outside))


def test_jailed_open_rejects_raw_file_descriptor(tmp_path: Path) -> None:
    opener = runner._jailed_open(tmp_path.resolve())
    with pytest.raises(PermissionError, match="file descriptor"):
        opener(0)


def test_disabled_capability_raises() -> None:
    disabled = runner._disabled("os.system")
    with pytest.raises(PermissionError, match="os.system is disabled"):
        disabled("echo hi")


def test_deny_finder_blocks_denylisted_roots_only() -> None:
    finder = runner._DenyFinder(["socket", "subprocess"])
    assert finder.find_spec("csv") is None
    assert finder.find_spec("json.decoder") is None
    with pytest.raises(ImportError, match="socket"):
        finder.find_spec("socket")
    with pytest.raises(ImportError, match="subprocess"):
        finder.find_spec("subprocess.run")
