"""Sources MCP server: the only door through which the Planner sees client feeds.

Every tool returns a JSON-serialisable dict and never raises across the MCP boundary;
failures come back as ``{"error": "..."}``. ``peek_sample`` enforces the data perimeter
(NFR-5): at most ``MAX_PEEK_ROWS`` raw lines per call. Caller-supplied ``client`` and
``name`` arguments must match ``SAFE_NAME`` and resolve to a direct child of the corpus root
(or of the client's samples directory), so path traversal is rejected before any file is read.

Run standalone with ``python -m drydock.mcp.sources_server`` (stdio transport). The corpus
root is taken from the ``DRYDOCK_CORPUS_ROOT`` environment variable when set.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol, cast

import yaml
from mcp.server.mcpserver import MCPServer
from pydantic import BaseModel, ConfigDict

from drydock.models import FeedSpec, SampleProfile

SERVER_NAME = "drydock-sources"
CORPUS_DIR = Path(__file__).resolve().parents[2] / "corpus"
ENV_CORPUS_ROOT = "DRYDOCK_CORPUS_ROOT"
MAX_PEEK_ROWS = 5
SAFE_NAME = re.compile(r"^[A-Za-z0-9._-]+$")

_INSTRUCTIONS = (
    "Read-only view of DRYDOCK client feed specifications and pinned sample profiles. "
    f"peek_sample never returns more than {MAX_PEEK_ROWS} raw lines."
)


# --------------------------------------------------------------------------- #
# Corpus access (real drydock.corpus when present, private fallback otherwise)  #
# --------------------------------------------------------------------------- #


class _ManifestLike(Protocol):
    @property
    def samples(self) -> tuple[SampleProfile, ...]: ...


class _CorpusApi(Protocol):
    """Subset of the LLD section 2.4 ``corpus.py`` API this server relies on."""

    def list_clients(self, root: Path) -> list[str]: ...
    def load_spec(self, client: str, root: Path) -> FeedSpec: ...
    def load_manifest(self, client: str, root: Path) -> _ManifestLike: ...
    def samples_dir(self, client: str, root: Path) -> Path: ...
    def list_samples(self, client: str, root: Path) -> list[Path]: ...


_CONTRACT_BLOCK = re.compile(r"```yaml[ \t]+feed-contract[ \t]*\r?\n(.*?)\r?\n```", re.DOTALL)


class _FallbackManifest(BaseModel):
    """Just enough of ``corpus.Manifest`` to serve ``profile_sample``."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    client: str
    samples: tuple[SampleProfile, ...]


class _FallbackCorpus:
    """Private stand-in for ``drydock.corpus`` used until T-001 lands.

    T-005: delete this class (and the ImportError branch in ``_corpus_api``) once
    ``drydock/corpus.py`` exists; the tools only need the five functions of ``_CorpusApi``.
    """

    @staticmethod
    def list_clients(root: Path) -> list[str]:
        return sorted(p.name for p in root.iterdir() if (p / "spec.md").is_file())

    @staticmethod
    def load_spec(client: str, root: Path) -> FeedSpec:
        text = (root / client / "spec.md").read_text(encoding="utf-8")
        match = _CONTRACT_BLOCK.search(text)
        if match is None:
            raise ValueError(f"spec.md for {client!r} has no fenced yaml feed-contract block")
        return FeedSpec.model_validate(yaml.safe_load(match.group(1)))

    @staticmethod
    def load_manifest(client: str, root: Path) -> _FallbackManifest:
        raw = json.loads((root / client / "manifest.json").read_text(encoding="utf-8"))
        return _FallbackManifest.model_validate(raw)

    @staticmethod
    def samples_dir(client: str, root: Path) -> Path:
        return root / client / "samples"

    @staticmethod
    def list_samples(client: str, root: Path) -> list[Path]:
        folder = root / client / "samples"
        if not folder.is_dir():
            return []
        return sorted(p for p in folder.iterdir() if p.is_file())


def _corpus_api() -> _CorpusApi:
    """Import ``drydock.corpus`` lazily so this module loads before T-001 is merged."""
    try:
        module = importlib.import_module("drydock.corpus")
    except ImportError:
        return _FallbackCorpus()
    return cast(_CorpusApi, module)


# --------------------------------------------------------------------------- #
# Path safety                                                                  #
# --------------------------------------------------------------------------- #


def _safe_child(parent: Path, name: str, kind: str) -> Path:
    """Return ``parent/name`` iff ``name`` is a plain identifier resolving directly under it."""
    if not SAFE_NAME.fullmatch(name):
        raise ValueError(f"invalid {kind} name: {name!r}")
    base = parent.resolve()
    candidate = (base / name).resolve()
    if candidate.parent != base:
        raise ValueError(f"invalid {kind} name: {name!r}")
    return candidate


def _client_dir(root: Path, client: str) -> Path:
    path = _safe_child(root, client, "client")
    if not path.is_dir():
        raise ValueError(f"unknown client: {client!r}")
    return path


def _sample_path(api: _CorpusApi, root: Path, client: str, name: str) -> Path:
    _client_dir(root, client)
    path = _safe_child(api.samples_dir(client, root), name, "sample")
    if not path.is_file():
        raise ValueError(f"unknown sample: {name!r}")
    return path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


# --------------------------------------------------------------------------- #
# Tool bodies (raise freely; ``_guard`` converts to {"error": ...})            #
# --------------------------------------------------------------------------- #


def _list_clients(root: Path) -> dict[str, Any]:
    return {"clients": list(_corpus_api().list_clients(root))}


def _read_spec(root: Path, client: str) -> dict[str, Any]:
    markdown = (_client_dir(root, client) / "spec.md").read_text(encoding="utf-8")
    contract = _corpus_api().load_spec(client, root).model_dump(mode="json")
    return {"client": client, "markdown": markdown, "contract": contract}


def _list_samples(root: Path, client: str) -> dict[str, Any]:
    _client_dir(root, client)
    paths = _corpus_api().list_samples(client, root)
    return {
        "samples": [
            {"name": p.name, "bytes": p.stat().st_size, "sha256": _sha256(p)} for p in paths
        ]
    }


def _peek_sample(root: Path, client: str, name: str, rows: int) -> dict[str, Any]:
    path = _sample_path(_corpus_api(), root, client, name)
    limit = max(1, min(rows, MAX_PEEK_ROWS))
    lines: list[str] = []
    with path.open(encoding="utf-8", errors="replace", newline="") as fh:
        for line in fh:
            lines.append(line.rstrip("\r\n"))
            if len(lines) >= limit:
                break
    return {"name": name, "lines": lines}


def _profile_sample(root: Path, client: str, name: str) -> dict[str, Any]:
    _client_dir(root, client)
    api = _corpus_api()
    _safe_child(api.samples_dir(client, root), name, "sample")
    for profile in api.load_manifest(client, root).samples:
        if profile.name == name:
            return profile.model_dump(mode="json")
    raise ValueError(f"unknown sample: {name!r}")


def _guard(fn: Callable[..., dict[str, Any]], *args: Any) -> dict[str, Any]:
    """Run a tool body; any exception becomes an error dict instead of crossing the wire."""
    try:
        return fn(*args)
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


# --------------------------------------------------------------------------- #
# Server                                                                       #
# --------------------------------------------------------------------------- #


def build_server(corpus_root: Path = CORPUS_DIR) -> MCPServer[Any]:
    """Build the ``drydock-sources`` server serving the corpus under ``corpus_root``."""
    root = Path(corpus_root)
    server: MCPServer[Any] = MCPServer(SERVER_NAME, instructions=_INSTRUCTIONS)

    @server.tool()
    def list_clients() -> dict[str, Any]:
        """List the client identifiers available in the corpus."""
        return _guard(_list_clients, root)

    @server.tool()
    def read_spec(client: str) -> dict[str, Any]:
        """Return a client's spec.md markdown and its parsed feed contract."""
        return _guard(_read_spec, root, client)

    @server.tool()
    def list_samples(client: str) -> dict[str, Any]:
        """List a client's sample files with their byte size and sha256."""
        return _guard(_list_samples, root, client)

    @server.tool()
    def peek_sample(client: str, name: str, rows: int = MAX_PEEK_ROWS) -> dict[str, Any]:
        """Return the first raw lines of a sample; rows is clamped to 1..5 (data perimeter)."""
        return _guard(_peek_sample, root, client, name, rows)

    @server.tool()
    def profile_sample(client: str, name: str) -> dict[str, Any]:
        """Return the pinned SampleProfile for a sample from manifest.json (never recomputed)."""
        return _guard(_profile_sample, root, client, name)

    return server


def main() -> None:
    """Entry point for ``python -m drydock.mcp.sources_server``: serve the corpus over stdio."""
    root = Path(os.environ.get(ENV_CORPUS_ROOT) or CORPUS_DIR)
    build_server(root).run("stdio")


if __name__ == "__main__":  # pragma: no cover
    main()
