"""GraphState helpers and node names (docs/design/03-lld.md section 7.1).

``GraphState`` itself is frozen in ``drydock.models``; this module only adds the vocabulary
the graph, service, CLI and dashboard share: node names, routing labels, run-id minting and
the small summaries handed to the human at the approval gate.
"""

from __future__ import annotations

import hashlib
import secrets
from typing import Any, Final, Literal

from drydock.models import GraphState, HarnessReport, RunStatus, utcnow

# Node names, in graph order. ``build_graph`` and ``RunService.history`` both use them.
LOAD_SPEC: Final = "load_spec"
PLAN: Final = "plan"
GENERATE: Final = "generate"
EVALUATE: Final = "evaluate"
AWAIT_APPROVAL: Final = "await_approval"
PUBLISH: Final = "publish"
RECORD_REJECTION: Final = "record_rejection"
ESCALATE: Final = "escalate"

NODE_NAMES: Final[tuple[str, ...]] = (
    LOAD_SPEC,
    PLAN,
    GENERATE,
    EVALUATE,
    AWAIT_APPROVAL,
    PUBLISH,
    RECORD_REJECTION,
    ESCALATE,
)

Route = Literal["approve", "repair", "escalate"]
Decision = Literal["approve", "reject"]
DECISIONS: Final[tuple[str, ...]] = ("approve", "reject")

SEEDED_TIMESTAMP: Final = "00000000000000"
RUN_ID_HEX_CHARS: Final = 6


def new_run_id(client: str, seed: int = 0) -> str:
    """``<client>-<YYYYmmddHHMMSS>-<6 hex>``; fully deterministic when ``seed != 0``."""
    if seed != 0:
        digest = hashlib.sha256(f"{client}:{seed}".encode()).hexdigest()
        return f"{client}-{SEEDED_TIMESTAMP}-{digest[:RUN_ID_HEX_CHARS]}"
    stamp = utcnow().strftime("%Y%m%d%H%M%S")
    return f"{client}-{stamp}-{secrets.token_hex(RUN_ID_HEX_CHARS // 2)}"


def initial_state(
    run_id: str, client: str, provider: str, *, seed: int = 0, max_iterations: int = 3
) -> GraphState:
    """The state handed to ``compiled.invoke`` when a run starts."""
    return GraphState(
        run_id=run_id,
        client=client,
        provider=provider,
        seed=seed,
        max_iterations=max_iterations,
        status=RunStatus.PLANNING,
    )


def route_after_evaluate(state: GraphState) -> Route:
    """LLD 7.1: passed -> approval gate; failed with budget left -> repair; else escalate."""
    if state.report is not None and state.report.passed:
        return "approve"
    if state.iteration < state.max_iterations:
        return "repair"
    return "escalate"


def route_after_decision(state: GraphState) -> Decision:
    """Send an approved run to ``publish`` and a rejected one to ``record_rejection``."""
    if state.decision == "approve":
        return "approve"
    return "reject"


def report_summary(report: HarnessReport | None) -> dict[str, Any]:
    """Compact, JSON-native view of a report for events and the interrupt payload."""
    if report is None:
        return {"passed": None, "errors": [], "rows_emitted": 0, "wall_ms": 0}
    return {
        "passed": report.passed,
        "rows_emitted": report.rows_emitted,
        "wall_ms": report.wall_ms,
        "checks": {check.check.value: check.passed for check in report.checks},
        "errors": [f"{f.check.value}: {f.message}" for f in report.errors],
    }


def approval_payload(state: GraphState) -> dict[str, Any]:
    """What the human sees at the interrupt: run, client, iteration and a report summary."""
    return {
        "run_id": state.run_id,
        "client": state.client,
        "iteration": state.iteration,
        "summary": report_summary(state.report),
    }


__all__ = [
    "AWAIT_APPROVAL",
    "DECISIONS",
    "ESCALATE",
    "EVALUATE",
    "GENERATE",
    "LOAD_SPEC",
    "NODE_NAMES",
    "PLAN",
    "PUBLISH",
    "RECORD_REJECTION",
    "Decision",
    "Route",
    "approval_payload",
    "initial_state",
    "new_run_id",
    "report_summary",
    "route_after_decision",
    "route_after_evaluate",
]
