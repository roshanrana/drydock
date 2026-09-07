"""Shared fixtures: temp database, runs dir, deploy dir, store and service (T-005).

Everything runs offline against the real corpus and the fake provider. SQLite connections
are closed in teardown so Windows can delete ``tmp_path``.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from drydock.graph.service import RunService
from drydock.graph.store import RunStore
from drydock.paths import CORPUS_DIR


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    return tmp_path / "data" / "drydock.db"


@pytest.fixture
def runs_dir(tmp_path: Path) -> Path:
    return tmp_path / "runs"


@pytest.fixture
def deploy_dir(tmp_path: Path) -> Path:
    return tmp_path / "deploy"


@pytest.fixture
def store(tmp_db: Path, runs_dir: Path) -> Iterator[RunStore]:
    with RunStore(tmp_db, runs_dir) as store:
        yield store


@pytest.fixture
def service(store: RunStore, tmp_db: Path, deploy_dir: Path) -> Iterator[RunService]:
    with RunService(
        store=store, db_path=tmp_db, corpus_root=CORPUS_DIR, deploy_dir=deploy_dir
    ) as service:
        yield service
