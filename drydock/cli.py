"""DRYDOCK command line (docs/design/03-lld.md section 7.4). Typer app named ``app``.

Global options (or ``DRYDOCK_*`` environment variables) point every command at a database,
runs directory, deploy directory and corpus root, so tests and the bench can run against a
temporary tree. ``DrydockError`` exits 2 with its message; anything else is a bug and exits
1 with a traceback. ``serve``, ``mcp`` and ``bench`` import their modules lazily because
they land in later tasks (T-006, T-007, T-009).
"""

from __future__ import annotations

import functools
import getpass
import importlib
import json
from collections.abc import Callable, Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

import typer

from drydock import corpus
from drydock.errors import DrydockError
from drydock.graph.service import RunService
from drydock.graph.store import RunStore
from drydock.models import RunRecord
from drydock.paths import CORPUS_DIR, DB_PATH, DEPLOY_DIR, RUNS_DIR

EXIT_USER_ERROR = 2
DEFAULT_PORT = 8787
DEFAULT_BENCH_OUT = Path("metrics") / "headline.json"

app = typer.Typer(
    help="Agentic pipeline generation with a human gate before anything sails.",
    no_args_is_help=True,
    add_completion=False,
)
corpus_app = typer.Typer(help="Corpus maintenance: verify pins or rebuild manifests.")
app.add_typer(corpus_app, name="corpus")


@dataclass(frozen=True)
class Settings:
    """Where this invocation reads and writes."""

    db_path: Path = DB_PATH
    runs_dir: Path = RUNS_DIR
    deploy_dir: Path = DEPLOY_DIR
    corpus_root: Path = CORPUS_DIR


def guarded[F: Callable[..., Any]](fn: F) -> F:
    """Map ``DrydockError`` to exit code 2 with the message on stderr."""

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except DrydockError as exc:
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(EXIT_USER_ERROR) from exc

    return cast(F, wrapper)


def settings_from(ctx: typer.Context) -> Settings:
    obj = ctx.obj if ctx.obj is not None else ctx.find_root().obj
    return obj if isinstance(obj, Settings) else Settings()


@contextmanager
def open_service(
    settings: Settings, sandbox: Literal["subprocess", "docker"] = "subprocess"
) -> Iterator[RunService]:
    """A ``RunService`` (and its store) for one command; both closed on exit."""
    store = RunStore(settings.db_path, settings.runs_dir)
    service = RunService(
        store=store,
        db_path=settings.db_path,
        corpus_root=settings.corpus_root,
        deploy_dir=settings.deploy_dir,
        sandbox=sandbox,
    )
    try:
        yield service
    finally:
        service.close()
        store.close()


def lazy_module(name: str, task: str) -> Any:
    """Import a module that a later task delivers; explain clearly when it is not there yet."""
    try:
        return importlib.import_module(name)
    except ImportError as exc:
        typer.echo(f"{name} is not available yet (it lands in {task}): {exc}", err=True)
        raise typer.Exit(EXIT_USER_ERROR) from exc


# --------------------------------------------------------------------------- #
# Rendering                                                                    #
# --------------------------------------------------------------------------- #

RUN_COLUMNS = ("run_id", "client", "provider", "status", "iterations", "updated_at")


def render_table(headers: Sequence[str], rows: Iterable[Sequence[Any]]) -> str:
    """Plain-text table with left-aligned, width-fitted columns."""
    body = [[str(cell) for cell in row] for row in rows]
    widths = [len(header) for header in headers]
    for row in body:
        widths = [max(width, len(cell)) for width, cell in zip(widths, row, strict=True)]
    fmt = "  ".join(f"{{:<{width}}}" for width in widths)
    lines = [fmt.format(*headers), fmt.format(*("-" * width for width in widths))]
    lines.extend(fmt.format(*row) for row in body)
    return "\n".join(line.rstrip() for line in lines)


def record_row(record: RunRecord) -> list[str]:
    return [
        record.run_id,
        record.client,
        record.provider,
        record.status.value,
        str(record.iterations),
        record.updated_at.strftime("%Y-%m-%d %H:%M:%S"),
    ]


def dump_json(payload: Any) -> str:
    return json.dumps(payload, indent=2, default=str)


def echo_record(record: RunRecord, as_json: bool) -> None:
    if as_json:
        typer.echo(dump_json(record.model_dump(mode="json")))
        return
    typer.echo(render_table(RUN_COLUMNS, [record_row(record)]))


def default_approver() -> str:
    try:
        return getpass.getuser()
    except (OSError, KeyError):  # pragma: no cover - no user database
        return "cli"


# --------------------------------------------------------------------------- #
# Commands                                                                     #
# --------------------------------------------------------------------------- #


@app.callback()
def main(
    ctx: typer.Context,
    db: Path = typer.Option(DB_PATH, "--db", envvar="DRYDOCK_DB", help="SQLite database."),
    runs_dir: Path = typer.Option(
        RUNS_DIR, "--runs-dir", envvar="DRYDOCK_RUNS_DIR", help="Per-run artifact root."
    ),
    deploy_dir: Path = typer.Option(
        DEPLOY_DIR, "--deploy-dir", envvar="DRYDOCK_DEPLOY_DIR", help="Approved pipelines."
    ),
    corpus_root: Path = typer.Option(
        CORPUS_DIR, "--corpus-root", envvar="DRYDOCK_CORPUS_ROOT", help="Client corpus."
    ),
) -> None:
    ctx.obj = Settings(
        db_path=db, runs_dir=runs_dir, deploy_dir=deploy_dir, corpus_root=corpus_root
    )


@app.command()
@guarded
def build(
    ctx: typer.Context,
    client: str = typer.Argument(..., help="Corpus client, e.g. acme-treasury."),
    provider: str = typer.Option("fake", help="Provider config name under configs/providers."),
    seed: int = typer.Option(0, help="Non-zero seeds make the run id deterministic."),
    max_iterations: int = typer.Option(3, min=1, help="Repair budget before escalating."),
    sandbox: str = typer.Option("subprocess", help="Harness sandbox: subprocess or docker."),
    as_json: bool = typer.Option(False, "--json", help="Print the run record as JSON."),
) -> None:
    """Plan, generate and evaluate a pipeline for CLIENT until approval, escalation or END."""
    if sandbox not in ("subprocess", "docker"):
        raise DrydockError("--sandbox must be 'subprocess' or 'docker'")
    kind = cast(Literal["subprocess", "docker"], sandbox)
    with open_service(settings_from(ctx), sandbox=kind) as service:
        record = service.start_run(client, provider, seed=seed, max_iterations=max_iterations)
    echo_record(record, as_json)


@app.command()
@guarded
def runs(
    ctx: typer.Context,
    limit: int = typer.Option(50, min=1, help="Newest N runs."),
    as_json: bool = typer.Option(False, "--json", help="Print JSON instead of a table."),
) -> None:
    """List recent runs."""
    with open_service(settings_from(ctx)) as service:
        records = service.list_runs(limit)
    if as_json:
        typer.echo(dump_json([record.model_dump(mode="json") for record in records]))
        return
    typer.echo(render_table(RUN_COLUMNS, [record_row(record) for record in records]))


@app.command()
@guarded
def show(
    ctx: typer.Context,
    run_id: str = typer.Argument(..., help="Run id from `drydock runs`."),
    as_json: bool = typer.Option(False, "--json", help="Print JSON instead of text."),
) -> None:
    """Show one run: record, iterations and their error findings."""
    with open_service(settings_from(ctx)) as service:
        record = service.get_run(run_id)
        iterations = service.store.list_iterations(run_id)
    if as_json:
        typer.echo(dump_json({"run": record.model_dump(mode="json"), "iterations": iterations}))
        return
    typer.echo(render_table(RUN_COLUMNS, [record_row(record)]))
    typer.echo("")
    for key in ("approved_by", "decision_note", "final_passed", "artifact_dir"):
        typer.echo(f"{key:>14}: {getattr(record, key)}")
    typer.echo("")
    rows = [
        [entry["iteration"], entry["passed"], entry["wall_ms"], _errors_cell(entry["errors"])]
        for entry in iterations
    ]
    typer.echo(render_table(("iteration", "passed", "wall_ms", "errors"), rows))


MAX_SHOWN_ERRORS = 3


def _errors_cell(errors: list[dict[str, Any]]) -> str:
    """First few findings for the table; ``--json`` carries the full list."""
    shown = errors[:MAX_SHOWN_ERRORS]
    text = "; ".join(f"{e['check']}: {e['message']}" for e in shown) or "-"
    if len(errors) > MAX_SHOWN_ERRORS:
        text += f" (+{len(errors) - MAX_SHOWN_ERRORS} more, use --json)"
    return text


@app.command()
@guarded
def approve(
    ctx: typer.Context,
    run_id: str = typer.Argument(...),
    approver: str = typer.Option(default_approver, help="Who is approving."),
    note: str = typer.Option("", help="Free-text note stored with the decision."),
) -> None:
    """Approve an awaiting run: publishes deploy/<client>/ and records the decision."""
    with open_service(settings_from(ctx)) as service:
        record = service.decide(run_id, "approve", approver, note)
    echo_record(record, as_json=False)


@app.command()
@guarded
def reject(
    ctx: typer.Context,
    run_id: str = typer.Argument(...),
    note: str = typer.Option(..., help="Why the run is rejected (required)."),
    approver: str = typer.Option(default_approver, help="Who is rejecting."),
) -> None:
    """Reject an awaiting run: nothing is published."""
    with open_service(settings_from(ctx)) as service:
        record = service.decide(run_id, "reject", approver, note)
    echo_record(record, as_json=False)


@app.command()
@guarded
def replay(
    ctx: typer.Context,
    run_id: str = typer.Argument(...),
    step: int | None = typer.Option(None, help="Dump the graph state at this checkpoint step."),
) -> None:
    """Walk the checkpoint history of a run, or dump the state at one step."""
    with open_service(settings_from(ctx)) as service:
        if step is not None:
            typer.echo(dump_json(service.state_at(run_id, step)))
            return
        history = service.history(run_id)
    rows = [
        [h["step"], h["node"], h["status"], h["iteration"], h["created_at"], h["checkpoint_id"]]
        for h in history
    ]
    headers = ("step", "node", "status", "iteration", "created_at", "checkpoint_id")
    typer.echo(render_table(headers, rows))


@app.command()
@guarded
def serve(
    ctx: typer.Context,
    port: int = typer.Option(DEFAULT_PORT, help="Dashboard port."),
    host: str = typer.Option("127.0.0.1", help="Bind address."),
) -> None:
    """Serve the review dashboard (T-006)."""
    dashboard = lazy_module("drydock.dashboard.app", "T-006")
    uvicorn = lazy_module("uvicorn", "T-006")
    with open_service(settings_from(ctx)) as service:
        uvicorn.run(dashboard.create_app(service), host=host, port=port)


@app.command()
@guarded
def mcp(ctx: typer.Context) -> None:
    """Serve DRYDOCK itself as an MCP server over stdio (T-007)."""
    server = lazy_module("drydock.mcp.server", "T-007")
    server.main()


@app.command()
@guarded
def bench(
    ctx: typer.Context,
    out: Path = typer.Option(DEFAULT_BENCH_OUT, help="Where to write headline.json."),
    keep: bool = typer.Option(False, "--keep", help="Keep the temporary DB, runs and deploy tree."),
) -> None:
    """Run every corpus scenario offline and write the metrics headline (T-009)."""
    module = lazy_module("drydock.bench", "T-009")
    module.main(out=out, keep=keep)


@corpus_app.command("verify")
@guarded
def corpus_verify(ctx: typer.Context) -> None:
    """Check every manifest pin against the sample files."""
    root = settings_from(ctx).corpus_root
    corpus.verify_all(root)
    clients = corpus.list_clients(root)
    cases = corpus.list_adversarial(root)
    typer.echo(f"corpus ok: {len(clients)} clients, {len(cases)} adversarial cases")


@corpus_app.command("rebuild-manifests")
@guarded
def corpus_rebuild_manifests(ctx: typer.Context) -> None:
    """Regenerate every corpus/<client>/manifest.json from the samples."""
    root = settings_from(ctx).corpus_root
    for path in corpus.rebuild_manifests(root):
        typer.echo(f"wrote {path}")
    corpus.verify_all(root)


__all__ = ["Settings", "app", "guarded", "lazy_module", "open_service", "render_table"]
