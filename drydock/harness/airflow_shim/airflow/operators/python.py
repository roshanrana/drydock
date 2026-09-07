"""``PythonOperator`` recorder: stores the callable, never invokes it."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from .. import DAG, BaseOperator


class PythonOperator(BaseOperator):
    def __init__(
        self,
        *,
        task_id: str,
        python_callable: Callable[..., Any],
        op_args: Sequence[Any] | None = None,
        op_kwargs: Mapping[str, Any] | None = None,
        dag: DAG | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(task_id=task_id, dag=dag, **kwargs)
        self.python_callable = python_callable
        self.op_args: tuple[Any, ...] = tuple(op_args or ())
        self.op_kwargs: dict[str, Any] = dict(op_kwargs or {})


__all__ = ["PythonOperator"]
