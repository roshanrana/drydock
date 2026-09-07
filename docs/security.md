# DRYDOCK harness sandbox — threat model and hardening (T-012)

DRYDOCK executes **model-generated** `pipeline.py` / `dag.py` to judge it. That code is
untrusted. A security review on 2026-09-07 demonstrated live escapes against
`drydock.harness.evaluate`; this document records the threat model, the three-layer defence
that closes them, the payload outcomes before and after the fix, and the residual limits.

## Threat model

- **Adversary:** the code generator (a remote LLM, or a prompt-injected one). It fully
  controls the text of `pipeline.py` and `dag.py`.
- **Assets:** the orchestrator host's filesystem and network, the developer's secrets, and
  the integrity of the harness verdict (a leaked file must not become "evidence" that is
  then forwarded to a remote model in a repair prompt).
- **Trust boundary:** generated code never runs in the orchestrator process. It is written
  to a scratch directory and executed by `runner.py` in a separate, isolated interpreter
  (`python -I -X utf8`) or a docker container.
- **Non-goals:** this is defence in depth for a CI/quality harness, not a multi-tenant
  hostile-code platform. A determined kernel-level exploit of the OS or docker is out of
  scope; the design assumes the interpreter and container runtime are sound.

## Three layers (each independently tested)

1. **Static AST guard — `drydock/harness/guard.py`.** Runs *before* execution. Import
   allowlist, plus rejection of the attribute/name hops that reach a real capability through
   an allowed module, plus a forbidden-call list (open-for-write, `os`/`pathlib` mutators,
   `exec`/`eval`/`__import__`/`getattr`, `system`/`popen`/`exec*`/`spawn*`). Any finding
   means the code is never executed. Tests: `test_guard_blocks_payload_before_execution`.
2. **Runtime jail — `drydock/harness/runner.py`.** Installed in the child *before* importing
   the pipeline. `open`/`io.open` are confined to **reads inside the work directory** (write
   modes and reads outside are `PermissionError`); dangerous `os` capabilities are replaced
   with a raiser; a denylist of modules is poisoned (`import` raises `ImportError`) and a
   `sys.meta_path` finder refuses them for late imports. The runner keeps private references
   to what it needs and writes its outputs through the real `open` to an explicit output
   directory. Tests: `test_*_outside_workdir_is_blocked`, `test_pathlib_replace_is_disabled`.
3. **Process containment — `drydock/harness/sandbox.py`.** The child starts in its own
   process group / session, so a timeout kills the **whole tree** (`taskkill /T /F` on
   Windows, `killpg(SIGKILL)` on POSIX). POSIX resource limits cap address space, file size
   and process count. A Windows Job Object caps committed memory (512 MiB) and kills the tree
   on close (best effort). The docker kind mounts the work dir **read-only** and a separate
   writable `/out`, with `--cap-drop ALL --security-opt no-new-privileges --pids-limit 64
   --memory 512m --network none --read-only --tmpfs /tmp`. Tests:
   `test_sleeping_child_tree_is_killed_on_timeout`, `test_memory_bomb_is_contained_*`,
   `test_docker_read_only_mount_blocks_writes`.

## Payload table — before vs after

| # | Payload | Before | After | Layer that stops it |
|---|---------|--------|-------|---------------------|
| C1 | `import os.path as osp; osp.os.system(...)` | **executed** | blocked | 1 guard — `forbidden_import 'os.path'` (os.path removed from allowlist) |
| C1 | `import typing; typing.sys.modules["os"].system(...)` | **executed** | blocked | 1 guard — `forbidden_call 'system'` / attr `sys`,`modules` |
| C1 | `import json; json.codecs.sys.modules` (and `re.functools.sys`, `decimal.sys`) | **executed** | blocked | 1 guard — `forbidden_call 'modules'` (attribute hop) |
| C1 | `().__class__.__bases__[0].__subclasses__()` | **executed** | blocked | 1 guard — `forbidden_call '__subclasses__'` (dunder walk) |
| C2 | `Path(<abs outside workdir>).read_text()` | **leaked file into H2 evidence** | blocked, marker absent from report | 2 jail — `PermissionError: read outside workdir` |
| C2 | `open(<abs outside workdir>).read()` | **leaked** | blocked, marker absent | 2 jail — `PermissionError: read outside workdir` |
| — | `open("x","w")`, `Path("x").write_text("y")`, `Path("x").mkdir()`, `Path(sample).unlink()` | wrote/deleted | blocked | 1 guard — `forbidden_call` |
| — | `Path(sample).replace(...)` (name shared with `str.replace`) | renamed | blocked | 2 jail — `os.replace` disabled (`PermissionError`) |
| — | `__import__("os")`, `importlib.import_module("os")`, `getattr(__builtins__,"__import__")`, `exec("import os")` | imported/exec'd | blocked | 1 guard — `forbidden_call` |
| H2 | Docker bind-mount was read-write, no limits | writable `/work`, no caps | `/work` read-only, writable `/out`, caps dropped, pids/memory capped, no network | 3 containment |
| H3 | Timeout killed only the direct child | child tree survived | tree killed (`taskkill /T` / `killpg`) | 3 containment |
| H4 | No memory cap on Windows | unbounded | Windows Job Object 512 MiB (best effort) + wall-clock backstop | 3 containment |
| — | Memory bomb `[bytearray(10**8) for _ in range(100)]` | OOM risk / hang | POSIX `MemoryError` via `RLIMIT_AS`; Windows capped or timed out, always returns within timeout + margin | 3 containment |

## Residual limits (known, accepted)

- **Windows Job Object is best effort.** If any `ctypes` call fails, the per-process memory
  cap is not enforced; a warning is appended to `SandboxResult.stderr` and the wall-clock
  timeout becomes the only backstop. A memory bomb then ends as a *timeout*, not a
  `MemoryError`. The harness never crashes on a Job Object failure. On the platforms tested
  the Job Object is created successfully.
- **The guard is name-based.** Layer 1 rejects a fixed denylist of attribute and call names
  plus every attribute starting with `_`. A novel capability reachable purely through
  allowed *public* attribute names could evade it; that is exactly why layers 2 and 3 exist
  and are tested independently. `str.replace` and `pathlib.Path.replace` share a name, so
  `replace` is intentionally **not** blocked statically (it would break legitimate
  transforms); `Path.replace` is closed at layer 2 because `os.replace` is disabled.
- **`approval.json` is an audit trail, not a signature (M1).** Its SHA-256 hashes record
  what was approved and by whom; they are **not** tamper-evident and must not be described as
  a cryptographic signature. Anyone who can write `deploy/<client>/` can rewrite both the
  artifact and its recorded hash.
- **Docker read-only mount is a backstop.** In the layered design an in-container write is
  already refused by the guard and the in-process jail; the read-only mount is the final
  line and is verified structurally (`test_docker_argv_matches_lld`) and, when a docker
  daemon is present, end-to-end (`test_docker_read_only_mount_blocks_writes`).
