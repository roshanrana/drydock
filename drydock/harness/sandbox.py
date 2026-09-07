"""Process isolation for generated code (LLD section 4, layer 3).

The sandbox never imports generated code; it only spawns ``runner.py`` in a scratch
directory. Windows and Linux are both supported.

Containment applied here (around the in-process jail of ``runner.py``):

* the child is started in its own process group / session, so a timeout kills the **whole**
  tree (``taskkill /T`` on Windows, ``killpg(SIGKILL)`` on POSIX), not just the direct child;
* POSIX resource limits (address space, file size, process count) via ``preexec_fn``;
* a Windows Job Object caps committed memory and kills the tree when the job handle closes
  (best effort — any ctypes failure is recorded in ``stderr`` and never crashes the harness);
* the docker kind mounts the work directory **read-only** and a separate writable output
  directory, drops all capabilities, and caps pids / memory with no network.
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
MEMORY_LIMIT_BYTES = 1024 * 1024 * 1024  # POSIX RLIMIT_AS
FILE_SIZE_LIMIT_BYTES = 64 * 1024 * 1024  # POSIX RLIMIT_FSIZE
PROCESS_LIMIT = 64  # POSIX RLIMIT_NPROC
CONTAINMENT_MEMORY_BYTES = 512 * 1024 * 1024  # Windows Job Object + docker --memory
DOCKER_MEMORY = "512m"
DOCKER_PIDS_LIMIT = "64"
DOCKER_OUTDIR = "/out"
DOCKER_KILL_TIMEOUT_S = 10.0
TREE_KILL_TIMEOUT_S = 10.0
INTERPRETER_FLAGS: tuple[str, ...] = ("-I", "-X", "utf8")
JAIL_ENV_VAR = "DRYDOCK_JAIL"


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


def _child_env() -> dict[str, str]:
    return {**sandbox_env(), JAIL_ENV_VAR: "1"}


def _docker_user_args() -> list[str]:
    """Run the container as the host user on POSIX.

    With every capability dropped, root inside the container has no ``CAP_DAC_OVERRIDE``
    and cannot write into a bind-mounted directory owned by the host user; matching the
    uid/gid makes ``/out`` writable and ``/work`` readable without granting anything back.
    Docker Desktop on Windows mediates bind mounts itself, so no flag is needed there.
    """
    if sys.platform == "win32":
        return []
    return ["--user", f"{os.getuid()}:{os.getgid()}"]


def docker_argv(workdir: Path, outdir: Path, argv: list[str], *, name: str) -> list[str]:
    """Locked-down ``docker run``: read-only work mount, writable /out, no caps, no network."""
    return [
        "docker",
        "run",
        "--rm",
        "--name",
        name,
        *_docker_user_args(),
        "--network",
        "none",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--pids-limit",
        DOCKER_PIDS_LIMIT,
        "--memory",
        DOCKER_MEMORY,
        "--read-only",
        "--tmpfs",
        "/tmp",
        "-e",
        "PYTHONIOENCODING=utf-8",
        "-e",
        f"{JAIL_ENV_VAR}=1",
        "-v",
        f"{workdir.resolve()}:/work:ro",
        "-v",
        f"{outdir.resolve()}:{DOCKER_OUTDIR}",
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
    try:
        resource.setrlimit(resource.RLIMIT_NPROC, (PROCESS_LIMIT, PROCESS_LIMIT))
    except (ValueError, OSError):
        pass  # RLIMIT_NPROC is per-user; never fail the run because it could not be tightened


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


def _kill_tree(proc: subprocess.Popen[bytes]) -> None:
    """Kill the child and every process it spawned (process group / job tree)."""
    if proc.poll() is not None:
        return
    if sys.platform == "win32":
        try:
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                capture_output=True,
                timeout=TREE_KILL_TIMEOUT_S,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            proc.kill()
        return
    try:
        os.killpg(os.getpgid(proc.pid), 9)
    except (OSError, ProcessLookupError):
        proc.kill()


class _WinJob:
    """A Windows Job Object that caps committed memory and kills its tree on close."""

    _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
    _LIMIT_PROCESS_MEMORY = 0x00000100
    _LIMIT_KILL_ON_JOB_CLOSE = 0x00002000

    def __init__(self, handle: int) -> None:
        self._handle = handle

    @classmethod
    def create(cls, proc: subprocess.Popen[bytes]) -> tuple[_WinJob | None, str]:
        """Assign ``proc`` to a memory-capped job. Returns (job or None, warning text)."""
        if sys.platform != "win32":
            return None, "drydock sandbox: Windows Job Object not applicable on this platform"
        try:
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

            class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):  # noqa: N801
                _fields_ = [
                    ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
                    ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
                    ("LimitFlags", wintypes.DWORD),
                    ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t),
                    ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.POINTER(wintypes.ULONG)),
                    ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD),
                ]

            class _IO_COUNTERS(ctypes.Structure):  # noqa: N801
                _fields_ = [
                    (n, ctypes.c_ulonglong)
                    for n in (
                        "ReadOperationCount",
                        "WriteOperationCount",
                        "OtherOperationCount",
                        "ReadTransferCount",
                        "WriteTransferCount",
                        "OtherTransferCount",
                    )
                ]

            class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):  # noqa: N801
                _fields_ = [
                    ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
                    ("IoInfo", _IO_COUNTERS),
                    ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t),
                ]

            kernel32.CreateJobObjectW.restype = wintypes.HANDLE
            job = kernel32.CreateJobObjectW(None, None)
            if not job:
                raise OSError(ctypes.get_last_error(), "CreateJobObjectW failed")
            info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
            info.BasicLimitInformation.LimitFlags = (
                cls._LIMIT_PROCESS_MEMORY | cls._LIMIT_KILL_ON_JOB_CLOSE
            )
            info.ProcessMemoryLimit = ctypes.c_size_t(CONTAINMENT_MEMORY_BYTES)
            if not kernel32.SetInformationJobObject(
                job,
                cls._JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                ctypes.byref(info),
                ctypes.sizeof(info),
            ):
                err = ctypes.get_last_error()
                kernel32.CloseHandle(job)
                raise OSError(err, "SetInformationJobObject failed")
            if not kernel32.AssignProcessToJobObject(job, int(proc._handle)):  # type: ignore[attr-defined]
                err = ctypes.get_last_error()
                kernel32.CloseHandle(job)
                raise OSError(err, "AssignProcessToJobObject failed")
            return cls(int(job)), ""
        except Exception as exc:  # noqa: BLE001 - job objects are best effort
            return None, f"drydock sandbox: Windows Job Object unavailable ({exc})"

    def close(self) -> None:
        if sys.platform != "win32":
            return
        try:
            import ctypes

            ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle(self._handle)
        except Exception:  # noqa: BLE001 - closing is best effort
            return


def _build_command(
    workdir: Path, outdir: Path, argv: list[str], kind: SandboxKind
) -> tuple[list[str], str]:
    if kind == "docker":
        if shutil.which("docker") is None:
            raise SandboxError("docker binary not found on PATH")
        name = f"drydock-{uuid.uuid4().hex[:12]}"
        return docker_argv(workdir, outdir, argv, name=name), name
    return list(argv), ""


def _popen(command: list[str], workdir: Path, kind: SandboxKind) -> subprocess.Popen[bytes]:
    """Start the child in its own group/session so a timeout can kill the whole tree."""
    contained = kind == "subprocess"
    on_windows = sys.platform == "win32"
    creationflags = 0
    if contained and sys.platform == "win32":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
    start_new_session = contained and not on_windows
    preexec = _apply_posix_limits if contained and os.name == "posix" else None
    try:
        return subprocess.Popen(
            command,
            cwd=workdir,
            env=_child_env(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=creationflags,
            start_new_session=start_new_session,
            preexec_fn=preexec,
        )
    except OSError as exc:
        raise SandboxError(f"could not start sandbox process: {exc}") from exc


def run_in_sandbox(
    workdir: Path,
    argv: list[str],
    *,
    timeout_s: float,
    kind: SandboxKind = "subprocess",
    outdir: Path | None = None,
) -> SandboxResult:
    """Run ``argv`` with cwd ``workdir`` under containment and a wall-clock cap."""
    if not workdir.is_dir():
        raise SandboxError(f"sandbox workdir does not exist: {workdir}")
    out = outdir if outdir is not None else workdir
    command, container = _build_command(workdir, out, argv, kind)
    started = time.perf_counter()
    proc = _popen(command, workdir, kind)
    job: _WinJob | None = None
    warning = ""
    if kind == "subprocess" and sys.platform == "win32":
        job, warning = _WinJob.create(proc)
    try:
        try:
            stdout_b, stderr_b = proc.communicate(timeout=timeout_s)
            timed_out = False
            exit_code = proc.returncode
        except subprocess.TimeoutExpired:
            _kill_tree(proc)
            if container:
                _kill_container(container)
            stdout_b, stderr_b = proc.communicate()
            timed_out = True
            exit_code = TIMEOUT_EXIT_CODE
    finally:
        if job is not None:
            job.close()
    stderr = _decode(stderr_b)
    if warning:
        stderr = f"{stderr}\n{warning}" if stderr else warning
    return SandboxResult(
        exit_code=exit_code,
        stdout=_decode(stdout_b),
        stderr=stderr,
        wall_ms=int((time.perf_counter() - started) * 1000),
        timed_out=timed_out,
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
