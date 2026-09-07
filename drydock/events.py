"""Append-only JSONL event log, one file per run (docs/design/03-lld.md section 1).

Every graph node emits one line per significant step and the LLM provider's ``on_usage``
callback lands here as ``{"node": "llm_usage", ...}``. Lines are ``{"ts", "node", ...}``;
values that are not JSON-native are rendered with ``str`` so a bad field never loses the
event. Files are written with ``\\n`` line endings on every platform.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from drydock.models import utcnow

USAGE_NODE = "llm_usage"


class EventWriter:
    """Appends JSON lines to ``path``; the parent directory is created on first emit."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def emit(self, node: str, **fields: Any) -> dict[str, Any]:
        """Append ``{ts, node, **fields}`` as one JSON line and return the record written."""
        record: dict[str, Any] = {"ts": utcnow().isoformat(), "node": node, **fields}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record, default=str, sort_keys=False) + "\n")
        return record

    def on_usage(self, usage: Mapping[str, Any]) -> None:
        """Provider ``on_usage`` callback: records token counts as an ``llm_usage`` event."""
        self.emit(USAGE_NODE, **dict(usage))


def read_events(path: Path) -> list[dict[str, Any]]:
    """Load every event line; a missing file is an empty log, not an error."""
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


__all__ = ["USAGE_NODE", "EventWriter", "read_events"]
