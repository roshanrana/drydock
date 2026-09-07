"""Offline bench: replay the corpus and write ``metrics/headline.json`` (LLD section 10).

``drydock bench`` runs every client through ``RunService`` with the deterministic fake
provider (seed 42, ``max_iterations=3``), approves each run that reaches the human gate as
``bench``, evaluates the five adversarial artifacts through ``harness.evaluate`` and reduces
the run records, iteration reports and harness reports to the numbers the README shows.

Everything happens in a temporary tree (database, runs, deploy) that is removed afterwards
unless ``keep`` is set, so the developer's ``data/``, ``runs/`` and ``deploy/`` are never
touched. The output is byte-stable: no timestamps, no wall-clock milliseconds, no absolute
paths, and rows the offline harness cannot observe (live provider, Docker, real Airflow) are
always written as *pending*, whatever the host has installed.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from collections import Counter
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import typer

from drydock import corpus
from drydock.errors import DrydockError
from drydock.graph.nodes import APPROVAL_FILE, SandboxKind
from drydock.graph.service import RunService
from drydock.graph.store import ARTIFACT_FILES, RunStore, artifact_files
from drydock.harness import evaluate
from drydock.models import CheckId, HarnessReport, PipelineArtifact, RunStatus
from drydock.paths import CORPUS_DIR

DEFAULT_OUT = Path("metrics") / "headline.json"
BENCH_SEED = 42
BENCH_PROVIDER = "fake"
BENCH_APPROVER = "bench"
BENCH_MAX_ITERATIONS = 3
BENCH_SANDBOX: SandboxKind = "subprocess"
TEMP_PREFIX = "drydock-bench-"
ADVERSARIAL_DIRNAME = "adversarial"

Outcome = Literal["pass", "heal", "escalate"]
Echo = Callable[[str], object]

KPI_ORDER: tuple[str, ...] = (
    "scenarios",
    "first_pass_rate",
    "healed_rate",
    "adversarial_rejected",
    "mean_iterations",
    "checkpoints",
)
"""Must match ``metrics/card.json`` ``kpi_order``; ``metrics/render.py`` enforces it."""

CHECK_ACCENTS: dict[CheckId, str] = {
    CheckId.RUNTIME: "red",
    CheckId.SCHEMA: "amber",
    CheckId.COMPLETENESS: "blue",
    CheckId.DRIFT: "violet",
    CheckId.LATENCY: "amber",
    CheckId.DAG_CONTRACT: "teal",
}

ESCALATION_REASONS: dict[str | None, str] = {None: "spec contradicts sample"}
"""Why an ``escalate`` scenario escalates, keyed by its injected defect (LLD section 2.3)."""
DEFAULT_ESCALATION_REASON = "repair budget exhausted"


# --------------------------------------------------------------------------- #
# Observations                                                                 #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class RunOutcome:
    """Everything the bench reads back about one client run."""

    client: str
    run_id: str
    expected: Outcome
    injected_defect: str | None
    status: RunStatus
    iterations: int
    checkpoints: int
    tool_calls: tuple[str, ...]
    reports: tuple[HarnessReport, ...]
    final_artifact: PipelineArtifact

    @property
    def observed(self) -> str:
        """``pass`` / ``heal`` / ``escalate`` as the manifest scenarios define them."""
        if self.status is RunStatus.APPROVED:
            return "pass" if self.iterations == 1 else "heal"
        if self.status is RunStatus.ESCALATED:
            return "escalate"
        return self.status.value

    @property
    def matched(self) -> bool:
        return self.observed == self.expected

    @property
    def first_pass(self) -> bool:
        return bool(self.reports) and self.reports[0].passed

    @property
    def healed(self) -> bool:
        return self.observed == "heal" and self.iterations <= BENCH_MAX_ITERATIONS

    @property
    def escalation_reason(self) -> str:
        return ESCALATION_REASONS.get(self.injected_defect, DEFAULT_ESCALATION_REASON)


@dataclass(frozen=True)
class AdversarialOutcome:
    """One adversarial artifact judged by the harness."""

    name: str
    against_client: str
    must_fail: tuple[CheckId, ...]
    report: HarnessReport

    @property
    def failed_checks(self) -> frozenset[CheckId]:
        return frozenset(finding.check for finding in self.report.errors)

    @property
    def rejected(self) -> bool:
        """Rejected when the report fails and every declared ``must_fail`` check errored."""
        return not self.report.passed and set(self.must_fail) <= self.failed_checks


@dataclass(frozen=True)
class BenchResult:
    """The raw observations ``headline`` reduces to numbers."""

    runs: tuple[RunOutcome, ...]
    adversarial: tuple[AdversarialOutcome, ...]
    published: tuple[str, ...]
    max_iterations: int

    @property
    def reports(self) -> tuple[HarnessReport, ...]:
        run_reports = [report for run in self.runs for report in run.reports]
        return (*run_reports, *(case.report for case in self.adversarial))


# --------------------------------------------------------------------------- #
# Replay                                                                       #
# --------------------------------------------------------------------------- #


@contextmanager
def _open(workdir: Path, corpus_root: Path, sandbox: SandboxKind) -> Iterator[RunService]:
    db_path = workdir / "data" / "drydock.db"
    store = RunStore(db_path, workdir / "runs")
    service = RunService(
        store=store,
        db_path=db_path,
        corpus_root=corpus_root,
        deploy_dir=workdir / "deploy",
        sandbox=sandbox,
    )
    try:
        yield service
    finally:
        service.close()
        store.close()


def _load_reports(store: RunStore, run_id: str, iterations: int) -> tuple[HarnessReport, ...]:
    reports = []
    for iteration in range(1, iterations + 1):
        _, report = store.load_iteration(run_id, iteration)
        if report is None:
            raise DrydockError(f"run {run_id}: iteration {iteration} has no report")
        reports.append(report)
    return tuple(reports)


def _tool_calls(service: RunService, run_id: str, last_step: int) -> tuple[str, ...]:
    plan = service.state_at(run_id, last_step).get("plan") or {}
    return tuple(str(name) for name in plan.get("tool_calls", ()))


def replay_client(
    service: RunService,
    client: str,
    *,
    seed: int,
    max_iterations: int,
    echo: Echo = typer.echo,
) -> RunOutcome:
    """Start one run, approve it if it reaches the gate, read every observation back."""
    manifest = corpus.load_manifest(client, service.corpus_root)
    record = service.start_run(client, BENCH_PROVIDER, seed=seed, max_iterations=max_iterations)
    if record.status is RunStatus.AWAITING_APPROVAL:
        record = service.decide(record.run_id, "approve", BENCH_APPROVER, note="bench replay")
    history = service.history(record.run_id)
    final_artifact, _ = service.store.load_iteration(record.run_id, record.iterations)
    outcome = RunOutcome(
        client=client,
        run_id=record.run_id,
        expected=manifest.scenario.expected_outcome,
        injected_defect=manifest.scenario.injected_defect,
        status=record.status,
        iterations=record.iterations,
        checkpoints=len(history),
        tool_calls=_tool_calls(service, record.run_id, int(history[-1]["step"])),
        reports=_load_reports(service.store, record.run_id, record.iterations),
        final_artifact=final_artifact,
    )
    echo(
        f"{client:<20} expected={outcome.expected:<8} observed={outcome.observed:<8} "
        f"iterations={outcome.iterations} checkpoints={outcome.checkpoints}"
    )
    return outcome


def replay_adversarial(
    case: corpus.AdversarialCase,
    *,
    corpus_root: Path,
    workdir: Path,
    sandbox: SandboxKind,
    echo: Echo = typer.echo,
) -> AdversarialOutcome:
    """Judge one adversarial artifact against its target client's samples."""
    report = evaluate(
        case.artifact,
        corpus.load_spec(case.against_client, corpus_root),
        corpus.load_manifest(case.against_client, corpus_root),
        corpus.list_samples(case.against_client, corpus_root),
        iteration=1,
        sandbox=sandbox,
        workdir=workdir / ADVERSARIAL_DIRNAME / case.name,
    )
    outcome = AdversarialOutcome(
        name=case.name,
        against_client=case.against_client,
        must_fail=case.must_fail,
        report=report,
    )
    verdict = "rejected" if outcome.rejected else "ACCEPTED"
    failed = ", ".join(sorted(check.value for check in outcome.failed_checks)) or "-"
    echo(f"{case.name:<24} {verdict:<8} failed={failed}")
    return outcome


def _published_clients(deploy_dir: Path) -> tuple[str, ...]:
    if not deploy_dir.is_dir():
        return ()
    return tuple(sorted(p.name for p in deploy_dir.iterdir() if (p / APPROVAL_FILE).is_file()))


def replay(
    workdir: Path,
    *,
    corpus_root: Path = CORPUS_DIR,
    seed: int = BENCH_SEED,
    max_iterations: int = BENCH_MAX_ITERATIONS,
    sandbox: SandboxKind = BENCH_SANDBOX,
    echo: Echo = typer.echo,
) -> BenchResult:
    """Replay every client and adversarial case inside ``workdir``."""
    with _open(workdir, corpus_root, sandbox) as service:
        runs = tuple(
            replay_client(service, client, seed=seed, max_iterations=max_iterations, echo=echo)
            for client in corpus.list_clients(corpus_root)
        )
        published = _published_clients(service.deploy_dir)
    adversarial = tuple(
        replay_adversarial(
            case, corpus_root=corpus_root, workdir=workdir, sandbox=sandbox, echo=echo
        )
        for case in corpus.list_adversarial(corpus_root)
    )
    return BenchResult(
        runs=runs, adversarial=adversarial, published=published, max_iterations=max_iterations
    )


# --------------------------------------------------------------------------- #
# Reduction                                                                    #
# --------------------------------------------------------------------------- #


def _kpi(label: str, value: str, note: str, accent: str) -> dict[str, str]:
    return {"label": label, "value": value, "note": note, "accent": accent}


def _names(items: Sequence[str]) -> str:
    return ", ".join(items) if items else "none"


def _outcome_kpis(result: BenchResult) -> dict[str, dict[str, str]]:
    """scenarios, first_pass_rate and healed_rate: run outcomes against the manifests."""
    runs = result.runs
    matched = [run.client for run in runs if run.matched]
    first_pass = [run.client for run in runs if run.first_pass]
    heal_runs = [run for run in runs if run.expected == "heal"]
    healed = [run.client for run in heal_runs if run.healed]
    budget = result.max_iterations
    return {
        "scenarios": _kpi(
            "Scenarios as declared",
            f"{len(matched)} / {len(runs)}",
            "final run status matched each manifest's expected_outcome: pass = approved at "
            "iteration 1, heal = approved after repair, escalate = escalated at the "
            f"{budget}-iteration budget",
            "teal",
        ),
        "first_pass_rate": _kpi(
            "First-pass rate",
            f"{len(first_pass)} / {len(runs)}",
            f"runs whose iteration-1 harness report passed ({_names(first_pass)}); "
            f"{len(heal_runs)} scenarios inject a defect on purpose",
            "blue",
        ),
        "healed_rate": _kpi(
            "Healed",
            f"{len(healed)} / {len(heal_runs)}",
            f"heal scenarios repaired and approved within {budget} iterations ({_names(healed)})",
            "violet",
        ),
    }


def _loop_kpis(result: BenchResult) -> dict[str, dict[str, str]]:
    """adversarial_rejected, mean_iterations and checkpoints: what the loop cost and caught."""
    runs = result.runs
    rejected = [case.name for case in result.adversarial if case.rejected]
    mean = sum(run.iterations for run in runs) / len(runs) if runs else 0.0
    checkpoints = sum(run.checkpoints for run in runs)
    budget = result.max_iterations
    return {
        "adversarial_rejected": _kpi(
            "Adversarial rejected",
            f"{len(rejected)} / {len(result.adversarial)}",
            "hand-written almost-right artifacts whose harness report failed on every check "
            "their expect.json says must fail",
            "amber",
        ),
        "mean_iterations": _kpi(
            "Mean iterations",
            f"{mean:.2f}",
            f"generate/evaluate iterations per run, {len(runs)} runs, budget {budget}",
            "blue",
        ),
        "checkpoints": _kpi(
            "Checkpoints",
            str(checkpoints),
            f"LangGraph checkpoints across {len(runs)} runs via service.history, counting "
            "every step including each run's step -1 input checkpoint",
            "teal",
        ),
    }


def _kpis(result: BenchResult) -> dict[str, dict[str, str]]:
    return {**_outcome_kpis(result), **_loop_kpis(result)}


def _error_counts(reports: Sequence[HarnessReport]) -> Counter[CheckId]:
    return Counter(finding.check for report in reports for finding in report.errors)


def _bars(result: BenchResult) -> dict[str, Any]:
    counts = _error_counts(result.reports)
    total = sum(counts.values())
    run_reports = sum(len(run.reports) for run in result.runs)
    rows = [
        {
            "label": check.value.replace("_", " "),
            "value": counts[check],
            "max": total,
            "display": f"{counts[check]} of {total} error findings",
            "accent": CHECK_ACCENTS[check],
        }
        for check in CheckId
    ]
    return {
        "title": (
            f"Defects caught by check ({total} error findings across {run_reports} iteration "
            f"reports and {len(result.adversarial)} adversarial reports)"
        ),
        "rows": rows,
    }


def _fact(label: str, value: str, status: str) -> dict[str, str]:
    return {"label": label, "value": value, "status": status}


def _code_lines(artifact: PipelineArtifact) -> int:
    return sum(len(text.splitlines()) for text in artifact_files(artifact).values())


def _observed_facts(result: BenchResult) -> list[dict[str, str]]:
    runs = result.runs
    tool_calls = [name for run in runs for name in run.tool_calls]
    escalated = [run for run in runs if run.observed == "escalate"]
    sandboxes = sorted({report.sandbox for report in result.reports})
    lines = sum(_code_lines(run.final_artifact) for run in runs)
    return [
        _fact(
            "MCP tool calls made",
            f"{len(tool_calls)} over an in-memory MCP session "
            f"({_names(sorted(set(tool_calls)))}), recorded in each IngestionPlan.tool_calls",
            "ok",
        ),
        _fact(
            "Escalations",
            f"{len(escalated)} of {len(runs)}: "
            + (_names([f"{run.client}, {run.escalation_reason}" for run in escalated])),
            "ok",
        ),
        _fact(
            "Artifacts published",
            f"{len(result.published)} clients under deploy/ ({_names(result.published)}), "
            f"each with {', '.join(ARTIFACT_FILES)} and {APPROVAL_FILE}",
            "ok",
        ),
        _fact(
            "Sandbox kind",
            f"{_names(sandboxes)}: python -I in a scratch directory with a minimal "
            f"environment, {len(result.reports)} harness reports",
            "ok",
        ),
        _fact(
            "Generated code lines",
            f"{lines} lines across the final pipeline.py, dag.py and mapping.yaml of "
            f"{len(runs)} runs",
            "ok",
        ),
    ]


def _pending_facts() -> list[dict[str, str]]:
    return [
        _fact(
            "Live provider accuracy",
            "bench runs the deterministic fake provider only; Ollama, vLLM, Bedrock and "
            "Anthropic backends are not scored offline",
            "pending",
        ),
        _fact(
            "Docker sandbox",
            "harness supports sandbox=docker (python:3.12-slim, --network none); the bench "
            "always uses subprocess so its output is identical with or without Docker",
            "pending",
        ),
        _fact(
            "Airflow real import",
            "scripts/airflow_smoke.sh imports deploy/*/dag.py under real Airflow; not run by "
            "the offline bench",
            "pending",
        ),
    ]


def headline(result: BenchResult) -> dict[str, Any]:
    """Reduce a ``BenchResult`` to the ``metrics/headline.json`` document."""
    kpis = _kpis(result)
    if tuple(kpis) != KPI_ORDER:
        raise RuntimeError(f"kpi order {tuple(kpis)} != {KPI_ORDER}")
    return {
        "kpis": kpis,
        "bars": _bars(result),
        "facts": {
            "title": "Replay evidence",
            "rows": [*_observed_facts(result), *_pending_facts()],
        },
    }


def dump_headline(payload: dict[str, Any]) -> str:
    """Canonical JSON text: 2-space indent, ASCII, ``\\n`` line endings, trailing newline."""
    return json.dumps(payload, indent=2, ensure_ascii=True) + "\n"


def write_headline(payload: dict[str, Any], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(dump_headline(payload))


# --------------------------------------------------------------------------- #
# Entry point                                                                  #
# --------------------------------------------------------------------------- #


@contextmanager
def _workdir(explicit: Path | None, keep: bool) -> Iterator[Path]:
    path = explicit if explicit is not None else Path(tempfile.mkdtemp(prefix=TEMP_PREFIX))
    path.mkdir(parents=True, exist_ok=True)
    try:
        yield path
    finally:
        if not keep:
            shutil.rmtree(path, ignore_errors=True)


def main(
    out: Path = DEFAULT_OUT,
    *,
    keep: bool = False,
    corpus_root: Path = CORPUS_DIR,
    seed: int = BENCH_SEED,
    max_iterations: int = BENCH_MAX_ITERATIONS,
    workdir: Path | None = None,
    echo: Echo = typer.echo,
) -> dict[str, Any]:
    """Replay the corpus in a temporary tree and write ``out``; returns the headline."""
    with _workdir(workdir, keep) as root:
        echo(f"bench: seed={seed} provider={BENCH_PROVIDER} max_iterations={max_iterations}")
        result = replay(
            root, corpus_root=corpus_root, seed=seed, max_iterations=max_iterations, echo=echo
        )
        payload = headline(result)
        write_headline(payload, out)
        if keep:
            echo(f"bench: kept working tree at {root}")
    kpis = payload["kpis"]
    echo(
        f"wrote {out}: scenarios {kpis['scenarios']['value']}, adversarial "
        f"{kpis['adversarial_rejected']['value']}, checkpoints {kpis['checkpoints']['value']}"
    )
    return payload


__all__ = [
    "BENCH_APPROVER",
    "BENCH_MAX_ITERATIONS",
    "BENCH_PROVIDER",
    "BENCH_SEED",
    "DEFAULT_OUT",
    "KPI_ORDER",
    "AdversarialOutcome",
    "BenchResult",
    "RunOutcome",
    "dump_headline",
    "headline",
    "main",
    "replay",
    "write_headline",
]
