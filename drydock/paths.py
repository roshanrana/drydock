"""Repository paths, resolved once (docs/design/03-lld.md section 1).

Every module imports paths from here; tests override via ``monkeypatch`` or by passing
explicit ``root`` arguments to the functions that accept one.
"""

from __future__ import annotations

from pathlib import Path

ROOT: Path = Path(__file__).resolve().parent.parent
"""Repository root (the directory containing ``pyproject.toml``)."""

CORPUS_DIR: Path = ROOT / "corpus"
"""Client feed specs, samples and manifests, plus the ``_adversarial`` set."""

RUNS_DIR: Path = ROOT / "runs"
"""Per-run artifacts: ``runs/<run_id>/``."""

DEPLOY_DIR: Path = ROOT / "deploy"
"""Approved pipelines promoted for deployment."""

DATA_DIR: Path = ROOT / "data"
"""Mutable local state (SQLite store, event log)."""

DB_PATH: Path = DATA_DIR / "drydock.db"
"""SQLite database used by the run store and LangGraph checkpointer."""
