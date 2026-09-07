"""The single validation gate. `make check` and CI both run exactly this.

Steps (all must pass):
  1. ruff check + ruff format --check
  2. mypy drydock, on the host platform and again targeting linux (CI runs Linux)
  3. pytest with coverage >= 80%
  4. drydock bench  (offline, seeded)  -> metrics/headline.json must not drift
  5. metrics/render.py --check         -> README results card must not drift
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

STEPS: list[tuple[str, list[str]]] = [
    ("ruff check", ["uv", "run", "ruff", "check", "."]),
    ("ruff format", ["uv", "run", "ruff", "format", "--check", "."]),
    ("mypy", ["uv", "run", "mypy", "drydock"]),
    ("mypy (linux target)", ["uv", "run", "mypy", "drydock", "--platform", "linux"]),
    (
        "pytest",
        [
            "uv",
            "run",
            "pytest",
            "--cov=drydock",
            "--cov-report=term-missing",
            "--cov-fail-under=80",
        ],
    ),
    ("bench", ["uv", "run", "drydock", "bench"]),
    ("bench drift", ["git", "diff", "--exit-code", "--", "metrics/headline.json"]),
    ("card drift", ["uv", "run", "python", "metrics/render.py", "--check"]),
]


def main() -> int:
    for name, cmd in STEPS:
        print(f"\n=== {name}: {' '.join(cmd)}", flush=True)
        result = subprocess.run(cmd, cwd=ROOT)
        if result.returncode != 0:
            print(f"\nFAILED at step '{name}' (exit {result.returncode})")
            return result.returncode
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
