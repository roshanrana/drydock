"""Process isolation for generated code: a minimal-environment subprocess or docker.

The sandbox never imports generated code; it only spawns ``runner.py`` in a scratch
directory. Windows and Linux are both supported: POSIX resource limits are applied only
when the ``resource`` module exists, and the interpreter is always ``sys.executable``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Literal

from drydock.errors import SandboxError, SandboxTimeout
from drydock.models import Frozen

SandboxKind = Literal["subprocess", "docker"]

DOCKER_IMAGE = "python:3.12-slim"
TIMEOUT_EXIT_CODE = -1
MEMORY_LIMIT_BYTES = 1024 * 1024 * 1024
FILE_SIZE_LIMIT_BYTES = 64 * 1024 * 1024
DOCKER_KILL_TIMEOUT_S = 10.0
INTERPRETER_FLAGS: tuple[str, ...] = ("-I", "-X", "utf8")


class SandboxResult(Frozen):
    exit_code: int
    stdout: str
    stderr: str
    wall_ms: int
    timed_out: bool


def python_argv(kind: SandboxKind) -> list[str]:
    """Interpreter prefix for ``runner.py`` inside the given sandbox kind."""
    interpreter = sys.executable if kind == "subprocess" else "python"
    return [interpreter, *INTERPRETER_FLAGS]


def sandbox_env() -> dict[str, str]:
    """Minimal environment: PATH, SYSTEMROOT (Windows only) and PYTHONIOENCODING."""
    env = {"PATH": os.environ.get("PATH", ""), "PYTHONIOENCODING": "utf-8"}
    if sys.platform == "win32":
        env["SYSTEMROOT"] = os.environ.get("SYSTEMROOT", r"C:\Windows")
    return env


def docker_argv(workdir: Path, argv: list[str], *, name: str) -> list[str]:
    """``docker run --rm --network none -v <workdir>:/work -w /work python:3.12-slim ...``."""
    return [
        "docker",
        "run",
        "--rm",
        "--name",
        name,
        "--network",
        "none",
        "-e",
        "PYTHONIOENCODING=utf-8",
        "-v",
        f"{workdir.resolve()}:/work",
        "-w",
        "/work",
        DOCKER_IMAGE,
        *argv,
    ]


def _apply_posix_limits() -> None:  # pragma: no cover - POSIX only, runs in the child
    if sys.platform == "win32":
        return  # the resource module does not exist on Windows
    import resource

    resource.setrlimit(resource.RLIMIT_AS, (MEMORY_LIMIT_BYTES, MEMORY_LIMIT_BYTES))
    resource.setrlimit(resource.RLIMIT_FSIZE, (FILE_SIZE_LIMIT_BYTES, FILE_SIZE_LIMIT_BYTES))


def _decode(data: bytes | None) -> str:
    return "" if data is None else data.decode("utf-8", errors="replace")


def _kill_container(name: str) -> None:
    """Best effort: the docker client was killed on timeout, the container may linger."""
    try:
        subprocess.run(
            ["docker", "rm", "-f", name],
            capture_output=True,
            timeout=DOCKER_KILL_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return


def _build_command(workdir: Path, argv: list[str], kind: SandboxKind) -> tuple[list[str], str]:
    if kind == "docker":
        if shutil.which("docker") is None:
            raise SandboxError("docker binary not found on PATH")
        name = f"drydock-{uuid.uuid4().hex[:12]}"
        return docker_argv(workdir, argv, name=name), name
    return list(argv), ""


def run_in_sandbox(
    workdir: Path,
    argv: list[str],
    *,
    timeout_s: float,
    kind: SandboxKind = "subprocess",
) -> SandboxResult:
    """Run ``argv`` with cwd ``workdir`` under a minimal environment and a wall-clock cap."""
    if not workdir.is_dir():
        raise SandboxError(f"sandbox workdir does not exist: {workdir}")
    command, container = _build_command(workdir, argv, kind)
    preexec = _apply_posix_limits if kind == "subprocess" and os.name == "posix" else None
    started = time.perf_counter()
    try:
        proc = subprocess.run(
            command,
            cwd=workdir,
            env=sandbox_env(),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=timeout_s,
            preexec_fn=preexec,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        if container:
            _kill_container(container)
        return SandboxResult(
            exit_code=TIMEOUT_EXIT_CODE,
            stdout=_decode(exc.stdout),
            stderr=_decode(exc.stderr),
            wall_ms=int((time.perf_counter() - started) * 1000),
            timed_out=True,
        )
    except OSError as exc:
        raise SandboxError(f"could not start sandbox process: {exc}") from exc
    return SandboxResult(
        exit_code=proc.returncode,
        stdout=_decode(proc.stdout),
        stderr=_decode(proc.stderr),
        wall_ms=int((time.perf_counter() - started) * 1000),
        timed_out=False,
    )


__all__ = [
    "DOCKER_IMAGE",
    "SandboxError",
    "SandboxKind",
    "SandboxResult",
    "SandboxTimeout",
    "docker_argv",
    "python_argv",
    "run_in_sandbox",
    "sandbox_env",
]
