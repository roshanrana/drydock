"""Minimal Airflow stand-in used only inside the harness sandbox.

Records DAG structure (``dag_id``, ``schedule``, task ids and ``>>`` edges) without
scheduling or executing anything. Pure stdlib: it is copied into the scratch directory
and imported by ``runner.py`` under ``python -I``; the orchestrator never imports it.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

_REGISTRY: list[DAG] = []
_CONTEXT: list[DAG] = []


class DAG:
    """Recorder for one DAG declaration. Supports ``with DAG(...) as dag:`` and ``dag=``."""

    def __init__(
        self,
        dag_id: str,
        *,
        schedule: Any = None,
        schedule_interval: Any = None,
        **_ignored: Any,
    ) -> None:
        self.dag_id = dag_id
        self.schedule: Any = schedule if schedule is not None else schedule_interval
        self.task_ids: list[str] = []
        self.edges: list[tuple[str, str]] = []
        _REGISTRY.append(self)

    def __enter__(self) -> DAG:
        _CONTEXT.append(self)
        return self

    def __exit__(self, *_exc: object) -> None:
        _CONTEXT.pop()

    def add_task(self, task_id: str) -> None:
        if task_id not in self.task_ids:
            self.task_ids.append(task_id)

    def add_edge(self, upstream: str, downstream: str) -> None:
        edge = (upstream, downstream)
        if edge not in self.edges:
            self.edges.append(edge)

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready structure consumed by the harness (LLD section 4)."""
        schedule = self.schedule
        if schedule is not None and not isinstance(schedule, str):
            schedule = repr(schedule)
        return {
            "dag_id": self.dag_id,
            "schedule": schedule,
            "tasks": list(self.task_ids),
            "edges": [list(edge) for edge in self.edges],
        }


class BaseOperator:
    """Common recorder for operators; implements the ``>>`` / ``<<`` dependency syntax."""

    def __init__(self, *, task_id: str, dag: DAG | None = None, **_ignored: Any) -> None:
        owner = dag if dag is not None else current_dag()
        if owner is None:
            raise RuntimeError(f"task {task_id!r} was created outside a DAG context")
        self.task_id = task_id
        self.dag = owner
        owner.add_task(task_id)

    def set_downstream(self, other: BaseOperator | Sequence[BaseOperator]) -> None:
        for downstream in _as_list(other):
            self.dag.add_edge(self.task_id, downstream.task_id)

    def set_upstream(self, other: BaseOperator | Sequence[BaseOperator]) -> None:
        for upstream in _as_list(other):
            self.dag.add_edge(upstream.task_id, self.task_id)

    def __rshift__(
        self, other: BaseOperator | Sequence[BaseOperator]
    ) -> BaseOperator | Sequence[BaseOperator]:
        self.set_downstream(other)
        return other

    def __lshift__(
        self, other: BaseOperator | Sequence[BaseOperator]
    ) -> BaseOperator | Sequence[BaseOperator]:
        self.set_upstream(other)
        return other

    def __rrshift__(self, other: Sequence[BaseOperator]) -> BaseOperator:
        # ``[a, b] >> self``
        self.set_upstream(other)
        return self

    def __rlshift__(self, other: Sequence[BaseOperator]) -> BaseOperator:
        # ``[a, b] << self``
        self.set_downstream(other)
        return self


def _as_list(other: BaseOperator | Sequence[BaseOperator]) -> list[BaseOperator]:
    if isinstance(other, BaseOperator):
        return [other]
    return list(other)


def current_dag() -> DAG | None:
    return _CONTEXT[-1] if _CONTEXT else None


def registered_dags() -> list[DAG]:
    return list(_REGISTRY)


__all__ = ["DAG", "BaseOperator", "current_dag", "registered_dags"]
