# T-012 — Sandbox hardening after security review

**Wave:** 4 · **Depends on:** T-002, T-005 · **Status:** done

## Why
The security review (2026-09-07) demonstrated with live payloads against `drydock.harness.evaluate`:

- **C1** The AST guard allowlists *imports* and blocklists *call names*, so an attribute hop reaches the
  real `os` module: `import os.path as osp; osp.os.system("...")` passed the guard and executed. Any
  allowed stdlib module exposes such hops (`typing.sys.modules`, `pathlib.ntpath.os`, `re.functools`...).
- **C2** Read access is unrestricted: `Path(r"C:\Windows\win.ini").read_text()` ran, and the content
  came back as H2 "offending rows" evidence, which the repair prompt would forward to a remote LLM.
- **H2** Docker mode bind-mounts the workdir read-write and sets no cap/pids/memory limits.
- **H3** Timeout kills only the direct child; no process-group / job kill on either OS.
- **H4** No memory cap on Windows (POSIX `resource` only).
- **M1** `approval.json` hashes are an audit trail, not a signature; docs must not call it tamper-evident.

## Design (implement all; these become LLD §4 text)

Defense in depth, three layers, each independently tested:

1. **Static guard (checks.py)** — keep the import allowlist, and add:
   - Deny any `ast.Attribute` whose `attr` is in `FORBIDDEN_ATTRS = {"os","sys","posix","nt","ntpath","posixpath","subprocess","builtins","importlib","modules","_os","_sys","__builtins__","__loader__","__spec__","__dict__","__class__","__subclasses__","__bases__","__mro__","__globals__","__code__","__closure__","__self__","__func__","__import__"}` or that starts with `_`.
   - Deny `ast.Name` identifiers `__builtins__`, `__import__`, `__loader__`, `__spec__`.
   - Extend `FORBIDDEN_CALLS` with pathlib/os mutators: `unlink, rename, replace, rmdir, mkdir, touch, chmod, symlink_to, hardlink_to, link_to, remove, removedirs, makedirs, system, popen, startfile, spawn*, exec*, fork, kill`.
   - Remove `os.path` from `PIPELINE_ALLOWED_MODULES` (templates do not use it; verify with grep and adjust the LLD list). Keep `pathlib` (jailed at runtime, layer 2).
   - Run the same scan over `dag.py` (already done) and over any `Subscript` of `sys.modules` form.
2. **Runtime jail (runner.py, stdlib only, applied *before* importing the pipeline)**:
   - Jailed `open`: replace `builtins.open` and `io.open` with a wrapper that resolves the path, requires it to be inside the workdir (`Path(p).resolve().is_relative_to(WORKDIR)`), and rejects any mode containing `w`, `a`, `x`, `+`. `pathlib.Path.open/read_text/read_bytes` route through `io.open` on 3.12, so they inherit the jail; verify and add a direct guard on `Path.open` if not.
   - Strip capabilities from `os` in-process: set `os.system, os.popen, os.execv*, os.execl*, os.spawn*, os.fork, os.forkpty, os.kill, os.remove, os.unlink, os.rename, os.replace, os.rmdir, os.mkdir, os.makedirs, os.removedirs, os.chmod, os.chown, os.startfile, os.open, os.fdopen, os.link, os.symlink, os.truncate, os.putenv, os.unsetenv` (those that exist) to a function that raises `PermissionError("drydock sandbox: <name> is disabled")`.
   - Poison imports: set `sys.modules[name] = None` for `subprocess, socket, ssl, http, urllib, ftplib, smtplib, telnetlib, xmlrpc, multiprocessing, ctypes, importlib, shutil, tempfile, glob, sqlite3, pickle, shelve, marshal, code, codeop, pty, signal, resource, webbrowser, asyncio, threading, concurrent, _thread` (importing any of them then raises `ImportError`). Do this *after* the runner itself has finished using what it needs (it needs `json`, `importlib`, `pathlib`; import them first, keep references, then poison).
   - Install a `sys.meta_path` finder at position 0 that refuses to import anything not in the allowlist (belt and braces against `__import__` reaching a not-yet-loaded module).
   - Then import `pipeline.py`, run extract/transform, write outputs via the *original* `open` kept as a local reference to an explicitly allowed output directory.
3. **Process containment (sandbox.py)**:
   - Launch with `subprocess.Popen`; on Windows `creationflags=CREATE_NEW_PROCESS_GROUP` and on timeout `taskkill /T /F /PID <pid>`; on POSIX `start_new_session=True` and on timeout `os.killpg(pgid, SIGKILL)`. Then `communicate()` to reap. Record `timed_out=True`.
   - Docker kind: mount the workdir **read-only** (`-v <workdir>:/work:ro`) and a separate writable output dir (`-v <outdir>:/out`); pass output paths under `/out`; add `--cap-drop ALL --security-opt no-new-privileges --pids-limit 64 --memory 512m --network none --read-only --tmpfs /tmp`. Keep the subprocess kind writing outputs to the same separate `outdir` so the runner protocol is identical: `runner.py <pipeline.py> <sample> <dag.py> <outdir>` writes `<outdir>/out.json` and `<outdir>/dag_out.json`.
   - Windows memory cap: implement a Job Object via `ctypes` (`CreateJobObjectW`, `SetInformationJobObject` with `JOBOBJECT_EXTENDED_LIMIT_INFORMATION` setting `JOB_OBJECT_LIMIT_PROCESS_MEMORY` = 512 MiB and `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`, `AssignProcessToJobObject`) guarded by `sys.platform == "win32"`; if any ctypes call fails, log a warning into the `SandboxResult.stderr` and continue (never crash the harness). Keep POSIX `RLIMIT_AS`/`RLIMIT_FSIZE`/`RLIMIT_NPROC`.

## Scope (only these files)
- `drydock/harness/checks.py`, `drydock/harness/runner.py`, `drydock/harness/sandbox.py`, `drydock/harness/__init__.py`
- `tests/test_harness.py`, `tests/test_sandbox_escapes.py` (new), `tests/fixtures/pipelines/**`
- `docs/security.md` (new: threat model, the three layers, the payload table below with outcomes after the fix, known residual limits)
- `docs/design/03-lld.md` §4 only (update the guard/runner/sandbox description to match)

## Acceptance criteria
1. `tests/test_sandbox_escapes.py` runs every payload below through `evaluate()` with the fixtures in `tests/fixtures/manifest_stub.py` and asserts: the run does **not** pass, the side effect did **not** happen (no file created, no content leaked into any finding evidence), and the report names the layer that stopped it (guard finding vs runtime `PermissionError`/`ImportError` in H1 evidence):
   - `import os.path as osp; osp.os.system("echo PWNED > pwn.txt")`
   - `import typing; typing.sys.modules["os"].system(...)`
   - `from pathlib import Path; Path(<absolute path outside workdir>).read_text()` (use a file the test creates in `tmp_path` outside the workdir; assert its marker string appears nowhere in `report.model_dump_json()`)
   - `open(<abs path outside workdir>).read()`
   - `Path("x.txt").write_text("y")`, `open("x.txt","w")`, `Path("x").mkdir()`, `Path(sample).unlink()`
   - `__import__("os")`, `importlib.import_module("os")`, `getattr(__builtins__, "__import__")`, `exec("import os")`
   - `import json; json.codecs.sys.modules` style hop (any hop the agent can find; add at least two novel ones)
   - a pipeline that spawns a child that sleeps (via any reachable means, or a fixture that uses `time.sleep(60)` in `extract` with a 1 s timeout) → whole tree gone after `evaluate` returns (check no process with the workdir in its command line survives; on Windows use `tasklist`/`wmic`/psutil-free approach via `subprocess` in the test).
   - a memory-bomb (`[bytearray(10**8) for _ in range(100)]`) with a 5 s timeout → H1 error, and on POSIX the failure is a `MemoryError` not a timeout; on Windows either MemoryError (job object worked) or timeout, but the test asserts the harness returned within timeout + 5 s.
2. All previously passing harness tests still pass; the good fixture and every corpus client's *clean* generated pipeline still pass all six checks (`tests/test_harness.py` gets one parametrized test that renders `templates.render_pipeline` for each of the six clients through `FakeProvider(...).generate(... iteration=2 ...)` and evaluates it: all pass). The five adversarial cases still fail their declared checks.
3. Docker test (skipped without docker) verifies the read-only mount: a pipeline that tries `open("/work/x","w")` fails inside the container and the harness records it.
4. `docs/security.md` written; LLD §4 updated; `ruff`, `ruff format --check`, `mypy --strict`, full `pytest` green; harness coverage ≥ 85 %.
5. Nothing in `metrics/headline.json` changes as a result (bench numbers are behavioural, not timing); if `drydock bench` output changes, stop and report why.

## Validation
```
uv run ruff check drydock/harness tests && uv run ruff format --check drydock/harness tests
uv run mypy drydock
uv run pytest -q
uv run pytest tests/test_sandbox_escapes.py -q -v
```

## Handoff notes (≤10 lines)

- Status: done. `ruff check`, `ruff format --check`, `mypy drydock` (34 files) clean; `pytest` 505 passed; harness coverage 93% (≥85%).
- Layer 1 guard split into `guard.py` (re-exported by `checks.py`); `os.path` removed from allowlist (templates never use it); `replace` intentionally NOT blocked statically (collides with `str.replace`) — closed at layer 2 via disabled `os.replace`.
- Runner protocol changed to `runner.py pipeline.py <sample> dag.py <outdir>`; mirrored in sandbox/__init__; jail gated on `DRYDOCK_JAIL=1` env so in-process `runner.main()` unit tests are not mutated.
- Payloads closed: 14 via guard, 3 via runtime jail (read-outside/write/`Path.replace`), containment via tree-kill + memory cap + docker `:ro` mount. Escapes in `tests/test_sandbox_escapes.py` (25 tests).
- meridian-legacy is escalate-by-design (spec claims 15 rows, sample has 14); its clean pipeline fails ONLY H3 completeness — the parametrized corpus test asserts that explicitly, not `passed`.
- Residual risks (docs/security.md): Windows Job Object is best-effort (ctypes failure → warning in stderr, wall-clock timeout is the backstop, bomb ends as timeout not MemoryError); guard is name-based (why layers 2/3 exist); `approval.json` is an audit trail, not a signature (M1) — README/runbook already avoid "tamper-evident".
- Orchestrator note: nothing in `metrics/headline.json` changes (6 scenarios + 5 adversarial verdicts preserved; `test_bench.py`/`test_corpus.py` green). No README wording change required.
