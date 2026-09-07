"""FastAPI application for the DRYDOCK review dashboard (LLD section 9).

The app is a thin JSON facade over the ``RunService`` / ``RunStore`` contract from LLD
sections 7.2 and 7.3. It owns no state of its own: every route delegates to the injected
service and serialises the frozen Pydantic contracts with ``model_dump(mode="json")``.

Error mapping (LLD section 8): ``RunNotFound`` -> 404, ``InvalidTransition`` -> 409.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, Literal, Protocol

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from drydock.errors import InvalidTransition, RunNotFound
from drydock.models import HarnessReport, PipelineArtifact, RunRecord

FileName = Literal["pipeline.py", "dag.py", "mapping.yaml"]
Decision = Literal["approve", "reject"]

STATIC_DIR = Path(__file__).parent / "static"
INDEX_HTML = STATIC_DIR / "index.html"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787


# --------------------------------------------------------------------------- #
# Contract the dashboard codes against (structural, so tests can stub it)      #
# --------------------------------------------------------------------------- #


class RunStoreLike(Protocol):
    """Subset of ``RunStore`` (LLD section 7.2) the dashboard reads."""

    def list_iterations(self, run_id: str) -> list[dict[str, Any]]: ...

    def load_iteration(
        self, run_id: str, iteration: int
    ) -> tuple[PipelineArtifact, HarnessReport | None]: ...

    def diff(self, run_id: str, iteration: int, file: FileName) -> str: ...


class RunServiceLike(Protocol):
    """Subset of ``RunService`` (LLD section 7.3) the dashboard calls."""

    @property
    def store(self) -> RunStoreLike: ...

    def get_run(self, run_id: str) -> RunRecord: ...

    def list_runs(self, limit: int = 50) -> list[RunRecord]: ...

    def decide(
        self, run_id: str, decision: Decision, approver: str, note: str = ""
    ) -> RunRecord: ...

    def history(self, run_id: str) -> list[dict[str, Any]]: ...

    def state_at(self, run_id: str, step: int) -> dict[str, Any]: ...


# --------------------------------------------------------------------------- #
# Request bodies                                                               #
# --------------------------------------------------------------------------- #


class DecisionRequest(BaseModel):
    """Body of ``POST /api/runs/{run_id}/decision``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision: Decision
    approver: str = Field(min_length=1, max_length=200)
    note: str = Field(default="", max_length=4000)


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #


_ROWS = TypeAdapter(list[dict[str, Any]])


def _dump(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(mode="json")


def _dump_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """JSON-mode dump for dict rows that may nest contracts (``Finding``) or datetimes."""
    dumped: list[dict[str, Any]] = _ROWS.dump_python(rows, mode="json")
    return dumped


def _read_index() -> str:
    return INDEX_HTML.read_text(encoding="utf-8")


def _known_iterations(service: RunServiceLike, run_id: str) -> list[dict[str, Any]]:
    """Return the iteration summaries for a run, raising ``RunNotFound`` for unknown ids.

    ``get_run`` is called first so a missing run surfaces as 404 regardless of how the
    store reacts to an unknown id.
    """
    service.get_run(run_id)
    return service.store.list_iterations(run_id)


def _require_iteration(service: RunServiceLike, run_id: str, iteration: int) -> None:
    known = {int(row["iteration"]) for row in _known_iterations(service, run_id)}
    if iteration not in known:
        raise HTTPException(status_code=404, detail=f"run {run_id!r} has no iteration {iteration}")


# --------------------------------------------------------------------------- #
# Application factory                                                          #
# --------------------------------------------------------------------------- #


def create_app(service: RunServiceLike) -> FastAPI:
    """Build the dashboard application bound to ``service``."""
    app = FastAPI(title="DRYDOCK dashboard", version="0.1.0", docs_url="/api/docs")

    @app.exception_handler(RunNotFound)
    async def _not_found(_: Request, exc: RunNotFound) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(InvalidTransition)
    async def _conflict(_: Request, exc: InvalidTransition) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def index() -> HTMLResponse:
        return HTMLResponse(_read_index())

    @app.get("/api/runs")
    async def list_runs(
        limit: Annotated[int, Query(ge=1, le=500)] = 50,
    ) -> list[dict[str, Any]]:
        return [_dump(record) for record in service.list_runs(limit=limit)]

    @app.get("/api/runs/{run_id}")
    async def get_run(run_id: str) -> dict[str, Any]:
        record = service.get_run(run_id)
        iterations = service.store.list_iterations(run_id)
        return {"run": _dump(record), "iterations": _dump_rows(iterations)}

    @app.get("/api/runs/{run_id}/iterations/{iteration}")
    async def get_iteration(run_id: str, iteration: int) -> dict[str, Any]:
        _require_iteration(service, run_id, iteration)
        artifact, report = service.store.load_iteration(run_id, iteration)
        return {
            "artifact": _dump(artifact),
            "report": _dump(report) if report is not None else None,
        }

    @app.get("/api/runs/{run_id}/diff/{iteration}")
    async def get_diff(
        run_id: str,
        iteration: int,
        file: Annotated[FileName, Query()] = "pipeline.py",
    ) -> dict[str, Any]:
        _require_iteration(service, run_id, iteration)
        return {
            "run_id": run_id,
            "iteration": iteration,
            "file": file,
            "diff": service.store.diff(run_id, iteration, file),
        }

    @app.get("/api/runs/{run_id}/history")
    async def get_history(run_id: str) -> list[dict[str, Any]]:
        service.get_run(run_id)
        return _dump_rows(service.history(run_id))

    @app.post("/api/runs/{run_id}/decision")
    async def post_decision(run_id: str, body: DecisionRequest) -> dict[str, Any]:
        record = service.decide(run_id, body.decision, body.approver, note=body.note)
        return _dump(record)

    return app


def serve(service: RunServiceLike, *, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
    """Run the dashboard under uvicorn. ``drydock serve`` (LLD section 7.4) calls this."""
    import uvicorn

    uvicorn.run(create_app(service), host=host, port=port)
