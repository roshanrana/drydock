"""Dashboard API and trace viewer (docs/design/03-lld.md section 9, T-006).

``create_app(service)`` builds a FastAPI application over any object satisfying the
``RunServiceLike`` protocol (the real ``drydock.graph.service.RunService`` or a stub).
"""

from __future__ import annotations

from drydock.dashboard.app import (
    DecisionRequest,
    FileName,
    RunServiceLike,
    RunStoreLike,
    create_app,
    serve,
)

__all__ = [
    "DecisionRequest",
    "FileName",
    "RunServiceLike",
    "RunStoreLike",
    "create_app",
    "serve",
]
