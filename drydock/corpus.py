"""Corpus loader, reference transform and manifest tooling (docs/design/03-lld.md section 2).

The corpus is the ground truth every other DRYDOCK component is measured against:

* ``corpus/<client>/spec.md``       prose plus exactly one fenced ``yaml feed-contract`` block
* ``corpus/<client>/samples/*``     hand-written sample files, 10-20 rows each
* ``corpus/<client>/manifest.json`` sha256/bytes/row/amount pins produced by this module
* ``corpus/_adversarial/<name>/``   deliberately broken artifacts the harness must reject

``reference_transform`` is the corpus author's oracle. It is used to *build* manifests and is
never called by the harness at run time, so a generated pipeline cannot pass by calling it.

Run ``python -m drydock.corpus --verify`` to check every pin, or ``--rebuild-manifests`` after
editing a sample.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from collections.abc import Iterable, Mapping, Sequence
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal

import yaml

from drydock.errors import CorpusError, DrydockError
from drydock.models import (
    CANONICAL_COLUMNS,
    CheckId,
    ColumnSpec,
    FeedSpec,
    Frozen,
    PipelineArtifact,
    SampleProfile,
    SourceFormat,
)
from drydock.paths import CORPUS_DIR

SPEC_NAME = "spec.md"
MANIFEST_NAME = "manifest.json"
SAMPLES_DIRNAME = "samples"
ADVERSARIAL_DIRNAME = "_adversarial"
EXPECT_NAME = "expect.json"
ADVERSARIAL_GENERATOR = "adversarial"

_FEED_CONTRACT_RE = re.compile(
    r"```yaml[ \t]+feed-contract[ \t]*\r?\n(.*?)\r?\n[ \t]*```", re.DOTALL
)
_SLICE_RE = re.compile(r"^(\d+):(\d+)$")
_TWO_DP = Decimal("0.01")

DEFECT_IDS: tuple[str, ...] = (
    "date_format_swapped",
    "trailer_not_skipped",
    "wrong_slice",
    "amount_sign_dropped",
    "thousands_separator_kept",
    "dag_missing_dependency",
)
"""Frozen defect identifiers a scenario may inject (LLD section 2.2)."""


# --------------------------------------------------------------------------- #
# Models                                                                       #
# --------------------------------------------------------------------------- #


class Scenario(Frozen):
    """Why a client exists in the corpus and what the graph is expected to do with it."""

    injected_defect: str | None
    expected_outcome: Literal["pass", "heal", "escalate"]
    notes: str = ""


class Manifest(Frozen):
    """Contents of ``corpus/<client>/manifest.json``."""

    client: str
    samples: tuple[SampleProfile, ...]
    scenario: Scenario


class AdversarialCase(Frozen):
    """A hand-written, almost-right artifact and the harness checks that must reject it."""

    name: str
    against_client: str
    artifact: PipelineArtifact
    must_fail: tuple[CheckId, ...]


SCENARIOS: Mapping[str, Scenario] = {
    "acme-treasury": Scenario(
        injected_defect=None,
        expected_outcome="pass",
        notes="Clean daily cash feed with quoted thousands separators; the baseline every "
        "provider must pass first time.",
    ),
    "northwind-custody": Scenario(
        injected_defect="date_format_swapped",
        expected_outcome="heal",
        notes="Day-first settlement dates and a DR/CR column; a pipeline that assumes "
        "%m/%d/%Y fails H4 drift and must heal.",
    ),
    "blue-harbour-fx": Scenario(
        injected_defect="trailer_not_skipped",
        expected_outcome="heal",
        notes="Pipe-delimited with a TRAILER|n control row; ingesting the trailer breaks "
        "H2 schema and H3 completeness.",
    ),
    "orion-prime": Scenario(
        injected_defect="wrong_slice",
        expected_outcome="heal",
        notes="Fixed-width mainframe extract; an off-by-one slice corrupts amounts and "
        "currencies until healed.",
    ),
    "kestrel-payments": Scenario(
        injected_defect="amount_sign_dropped",
        expected_outcome="heal",
        notes="JSON lines with unsigned amounts and a direction field; ignoring DEBIT "
        "flips the amount sum.",
    ),
    "meridian-legacy": Scenario(
        injected_defect=None,
        expected_outcome="escalate",
        notes="Spec claims 15 rows but the sample has 14 by design; no pipeline can satisfy "
        "the spec, so the run must escalate to a human.",
    ),
}
"""Scenario per client, exactly as LLD section 2.3."""


# --------------------------------------------------------------------------- #
# Paths and discovery                                                          #
# --------------------------------------------------------------------------- #


def _client_dir(client: str, root: Path) -> Path:
    path = root / client
    if not path.is_dir():
        raise CorpusError(f"unknown client {client!r}: {path} is not a directory")
    return path


def list_clients(root: Path = CORPUS_DIR) -> list[str]:
    """Client directory names (those holding a ``spec.md``), sorted."""
    if not root.is_dir():
        raise CorpusError(f"corpus root {root} is not a directory")
    return sorted(p.name for p in root.iterdir() if p.is_dir() and (p / SPEC_NAME).is_file())


def samples_dir(client: str, root: Path = CORPUS_DIR) -> Path:
    return _client_dir(client, root) / SAMPLES_DIRNAME


def list_samples(client: str, root: Path = CORPUS_DIR) -> list[Path]:
    """Sample files for a client, sorted by name."""
    directory = samples_dir(client, root)
    if not directory.is_dir():
        raise CorpusError(f"{client}: samples directory {directory} is missing")
    return sorted(p for p in directory.iterdir() if p.is_file())


# --------------------------------------------------------------------------- #
# Spec                                                                         #
# --------------------------------------------------------------------------- #


def extract_feed_contract(markdown: str) -> str:
    """Return the body of the single ``yaml feed-contract`` block in a spec document."""
    blocks = _FEED_CONTRACT_RE.findall(markdown)
    if len(blocks) != 1:
        raise CorpusError(f"expected exactly one yaml feed-contract block, found {len(blocks)}")
    return str(blocks[0])


def _validate_spec(spec: FeedSpec, client: str) -> FeedSpec:
    if spec.client != client:
        raise CorpusError(f"{client}: feed-contract client is {spec.client!r}")
    for col in spec.columns:
        if col.target is not None and col.target not in CANONICAL_COLUMNS:
            raise CorpusError(f"{client}: {col.source!r} targets unknown column {col.target!r}")
        if col.dtype == "date" and col.date_format is None:
            raise CorpusError(f"{client}: date column {col.source!r} has no date_format")
        if col.sign_column is not None and col.negative_marker is None:
            raise CorpusError(f"{client}: {col.source!r} has sign_column but no negative_marker")
        if spec.format is SourceFormat.FIXED_WIDTH:
            _parse_slice(col.source)
    return spec


def load_spec(client: str, root: Path = CORPUS_DIR) -> FeedSpec:
    """Parse ``corpus/<client>/spec.md`` into a validated ``FeedSpec``."""
    path = _client_dir(client, root) / SPEC_NAME
    if not path.is_file():
        raise CorpusError(f"{client}: {path} is missing")
    try:
        data = yaml.safe_load(extract_feed_contract(path.read_text(encoding="utf-8")))
    except yaml.YAMLError as exc:
        raise CorpusError(f"{client}: feed-contract is not valid yaml: {exc}") from exc
    if not isinstance(data, dict):
        raise CorpusError(f"{client}: feed-contract must be a yaml mapping")
    try:
        spec = FeedSpec.model_validate(data)
    except ValueError as exc:
        raise CorpusError(f"{client}: feed-contract does not satisfy FeedSpec: {exc}") from exc
    return _validate_spec(spec, client)


# --------------------------------------------------------------------------- #
# Reference transform                                                          #
# --------------------------------------------------------------------------- #


def _parse_slice(source: str) -> tuple[int, int]:
    match = _SLICE_RE.match(source)
    if match is None:
        raise CorpusError(f"fixed-width source {source!r} is not a 'start:end' slice")
    start, end = int(match.group(1)), int(match.group(2))
    if end <= start:
        raise CorpusError(f"fixed-width slice {source!r} is empty or reversed")
    return start, end


def _body_lines(spec: FeedSpec, path: Path) -> tuple[list[str], list[str]]:
    """Split a sample into (header lines, data lines) honouring blank-line and trailer rules."""
    if not path.is_file():
        raise CorpusError(f"sample {path} is missing")
    lines = path.read_text(encoding=spec.encoding).splitlines()
    if spec.skip_blank_lines:
        lines = [line for line in lines if line.strip()]
    if len(lines) < spec.header_rows + spec.trailer_rows:
        raise CorpusError(f"{path.name}: fewer lines than header_rows + trailer_rows")
    header = lines[: spec.header_rows]
    end = len(lines) - spec.trailer_rows
    return header, lines[spec.header_rows : end]


def _records_csv(spec: FeedSpec, header: list[str], body: list[str]) -> list[dict[str, str]]:
    if not header:
        raise CorpusError("csv feeds need header_rows >= 1 to resolve source column names")
    names = next(csv.reader([header[-1]], delimiter=spec.delimiter))
    records: list[dict[str, str]] = []
    for offset, fields in enumerate(csv.reader(body, delimiter=spec.delimiter)):
        if len(fields) != len(names):
            raise CorpusError(
                f"data row {offset + 1}: expected {len(names)} fields, got {len(fields)}"
            )
        records.append(dict(zip(names, fields, strict=True)))
    return records


def _records_fixed_width(spec: FeedSpec, body: list[str]) -> list[dict[str, str]]:
    slices = {col.source: _parse_slice(col.source) for col in spec.columns}
    return [{src: line[start:end] for src, (start, end) in slices.items()} for line in body]


def _stringify(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _records_jsonl(body: list[str]) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for offset, line in enumerate(body):
        try:
            obj = json.loads(line, parse_float=Decimal)
        except json.JSONDecodeError as exc:
            raise CorpusError(f"data row {offset + 1}: invalid json: {exc.msg}") from exc
        if not isinstance(obj, dict):
            raise CorpusError(f"data row {offset + 1}: json line is not an object")
        records.append({str(k): _stringify(v) for k, v in obj.items()})
    return records


def _raw_records(spec: FeedSpec, path: Path) -> list[dict[str, str]]:
    header, body = _body_lines(spec, path)
    if spec.format is SourceFormat.CSV:
        return _records_csv(spec, header, body)
    if spec.format is SourceFormat.FIXED_WIDTH:
        return _records_fixed_width(spec, body)
    return _records_jsonl(body)


def _to_iso_date(value: str, col: ColumnSpec) -> str:
    from datetime import datetime

    if col.date_format is None:
        raise CorpusError(f"date column {col.source!r} has no date_format")
    return datetime.strptime(value, col.date_format).date().isoformat()


def _to_amount(value: str, col: ColumnSpec, record: Mapping[str, str]) -> str:
    cleaned = value.replace(",", "").replace(" ", "")
    if cleaned == "":
        raise CorpusError(f"decimal column {col.source!r} is empty")
    amount = Decimal(cleaned)
    if col.sign_column is not None:
        marker = record.get(col.sign_column)
        if marker is None:
            raise CorpusError(f"sign column {col.sign_column!r} is missing from the record")
        amount = -abs(amount) if marker.strip() == col.negative_marker else abs(amount)
    quantized = amount.quantize(_TWO_DP, rounding=ROUND_HALF_UP)
    if quantized == 0:
        quantized = Decimal("0.00")
    return f"{quantized:.2f}"


def _convert(col: ColumnSpec, record: Mapping[str, str]) -> str:
    raw = record.get(col.source)
    if raw is None:
        raise CorpusError(f"source column {col.source!r} is missing from the record")
    value = raw.strip()
    if value == "" and col.default is not None:
        value = col.default
    if col.dtype == "date":
        return _to_iso_date(value, col)
    if col.dtype == "decimal":
        return _to_amount(value, col, record)
    if col.dtype == "int":
        return str(int(value))
    return value


def _canonical_row(spec: FeedSpec, record: Mapping[str, str]) -> dict[str, str]:
    mapped = {col.target: _convert(col, record) for col in spec.columns if col.target}
    if "currency" in mapped:
        mapped["currency"] = mapped["currency"].upper()
    return {name: mapped.get(name, "") for name in CANONICAL_COLUMNS}


def reference_transform(spec: FeedSpec, path: Path) -> list[dict[str, str]]:
    """Spec-driven oracle: parse ``path`` and emit canonical rows (LLD section 3 rules).

    Handles header/trailer skipping, csv/fixed-width/jsonl parsing, strptime date reformatting
    to ISO-8601, thousands-separator stripping, 2 dp quantisation and DR/CR sign columns.
    """
    rows: list[dict[str, str]] = []
    for index, record in enumerate(_raw_records(spec, path)):
        try:
            rows.append(_canonical_row(spec, record))
        except (ValueError, InvalidOperation) as exc:
            raise CorpusError(f"{path.name} data row {index + 1}: {exc}") from exc
        except CorpusError as exc:
            raise CorpusError(f"{path.name} data row {index + 1}: {exc}") from exc
    return rows


# --------------------------------------------------------------------------- #
# Profiling and manifests                                                      #
# --------------------------------------------------------------------------- #


def profile_rows(rows: Sequence[Mapping[str, str]]) -> dict[str, Any]:
    """Row count, exact signed amount sum, per-column null rate and distinct count."""
    count = len(rows)
    total = sum((Decimal(row["amount"]) for row in rows), Decimal("0"))
    null_rate = {
        name: (sum(1 for row in rows if row.get(name, "") == "") / count if count else 0.0)
        for name in CANONICAL_COLUMNS
    }
    distinct = {name: len({row.get(name, "") for row in rows}) for name in CANONICAL_COLUMNS}
    return {
        "rows": count,
        "amount_sum": f"{total.quantize(_TWO_DP):.2f}",
        "null_rate": null_rate,
        "distinct": distinct,
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def profile_sample(spec: FeedSpec, path: Path) -> SampleProfile:
    """Pin one sample file: hash, size and the profile of its reference transform."""
    profile = profile_rows(reference_transform(spec, path))
    return SampleProfile(
        name=path.name,
        sha256=_sha256(path),
        bytes=path.stat().st_size,
        expected_rows=_expected_rows(spec, profile["rows"]),
        amount_sum=profile["amount_sum"],
        null_rate=profile["null_rate"],
        distinct=profile["distinct"],
    )


def _expected_rows(spec: FeedSpec, observed: int) -> int:
    """The pin is the client's asserted row count when the contract states one.

    When the contract and the sample disagree (the ``escalate`` scenario) the manifest keeps
    the client's number: a correct pipeline cannot invent the missing row, so the harness
    fails H3 every iteration and the loop must hand the contradiction to a human.
    """
    return observed if spec.expected_row_count is None else spec.expected_row_count


def _manifest_path(client: str, root: Path) -> Path:
    return _client_dir(client, root) / MANIFEST_NAME


def load_manifest(client: str, root: Path = CORPUS_DIR) -> Manifest:
    path = _manifest_path(client, root)
    if not path.is_file():
        raise CorpusError(f"{client}: {path} is missing; run --rebuild-manifests")
    try:
        return Manifest.model_validate_json(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise CorpusError(f"{client}: manifest is invalid: {exc}") from exc


def _scenario_for(client: str, root: Path) -> Scenario:
    """Existing manifest scenario wins, then the LLD table, then a plain pass."""
    if _manifest_path(client, root).is_file():
        return load_manifest(client, root).scenario
    return SCENARIOS.get(client, Scenario(injected_defect=None, expected_outcome="pass"))


def build_manifest(
    client: str, root: Path = CORPUS_DIR, scenario: Scenario | None = None
) -> Manifest:
    """Compute a fresh manifest for ``client`` without writing it."""
    spec = load_spec(client, root)
    samples = tuple(profile_sample(spec, path) for path in list_samples(client, root))
    if not samples:
        raise CorpusError(f"{client}: no sample files found")
    return Manifest(
        client=client,
        samples=samples,
        scenario=scenario if scenario is not None else _scenario_for(client, root),
    )


def write_manifest(manifest: Manifest, root: Path = CORPUS_DIR) -> Path:
    path = _manifest_path(manifest.client, root)
    payload = json.dumps(manifest.model_dump(mode="json"), indent=2) + "\n"
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(payload)
    return path


def rebuild_manifests(root: Path = CORPUS_DIR) -> list[Path]:
    """Regenerate every client's manifest.json; returns the paths written."""
    return [write_manifest(build_manifest(client, root), root) for client in list_clients(root)]


def _sample_problems(spec: FeedSpec, directory: Path, pinned: SampleProfile) -> list[str]:
    path = directory / pinned.name
    if not path.is_file():
        return [f"{pinned.name}: pinned in manifest but missing on disk"]
    problems: list[str] = []
    actual_sha = _sha256(path)
    if actual_sha != pinned.sha256:
        problems.append(f"{pinned.name}: sha256 {actual_sha} != pinned {pinned.sha256}")
    size = path.stat().st_size
    if size != pinned.bytes:
        problems.append(f"{pinned.name}: {size} bytes != pinned {pinned.bytes}")
    profile = profile_rows(reference_transform(spec, path))
    expected = _expected_rows(spec, profile["rows"])
    if expected != pinned.expected_rows:
        problems.append(f"{pinned.name}: {expected} rows != pinned {pinned.expected_rows}")
    if profile["amount_sum"] != pinned.amount_sum:
        problems.append(
            f"{pinned.name}: amount_sum {profile['amount_sum']} != pinned {pinned.amount_sum}"
        )
    return problems


def verify_manifest(client: str, root: Path = CORPUS_DIR) -> None:
    """Raise ``CorpusError`` if any sample pin (sha256, bytes, rows, sum) is stale."""
    spec = load_spec(client, root)
    manifest = load_manifest(client, root)
    directory = samples_dir(client, root)
    problems: list[str] = []
    if manifest.client != client:
        problems.append(f"manifest client {manifest.client!r} != {client!r}")
    for pinned in manifest.samples:
        problems.extend(_sample_problems(spec, directory, pinned))
    pinned_names = {sample.name for sample in manifest.samples}
    for path in list_samples(client, root):
        if path.name not in pinned_names:
            problems.append(f"{path.name}: on disk but not pinned in manifest")
    if problems:
        raise CorpusError(f"{client}: " + "; ".join(problems))


def verify_all(root: Path = CORPUS_DIR) -> None:
    """Verify every client manifest and that every adversarial case loads."""
    clients = list_clients(root)
    if not clients:
        raise CorpusError(f"no clients found under {root}")
    failures = []
    for client in clients:
        try:
            verify_manifest(client, root)
        except CorpusError as exc:
            failures.append(str(exc))
    if failures:
        raise CorpusError("\n".join(failures))
    list_adversarial(root)


# --------------------------------------------------------------------------- #
# Adversarial set                                                              #
# --------------------------------------------------------------------------- #


def _read_required(directory: Path, name: str) -> str:
    path = directory / name
    if not path.is_file():
        raise CorpusError(f"adversarial case {directory.name!r}: {name} is missing")
    return path.read_text(encoding="utf-8")


def _load_adversarial(directory: Path, clients: Iterable[str]) -> AdversarialCase:
    try:
        expect = json.loads(_read_required(directory, EXPECT_NAME))
    except json.JSONDecodeError as exc:
        raise CorpusError(f"adversarial case {directory.name!r}: expect.json: {exc.msg}") from exc
    against = expect.get("against_client")
    if against not in set(clients):
        raise CorpusError(
            f"adversarial case {directory.name!r}: unknown against_client {against!r}"
        )
    try:
        must_fail = tuple(CheckId(check) for check in expect.get("must_fail", []))
    except ValueError as exc:
        raise CorpusError(f"adversarial case {directory.name!r}: bad must_fail: {exc}") from exc
    if not must_fail:
        raise CorpusError(f"adversarial case {directory.name!r}: must_fail is empty")
    artifact = PipelineArtifact(
        pipeline_py=_read_required(directory, "pipeline.py"),
        dag_py=_read_required(directory, "dag.py"),
        mapping_yaml=_read_required(directory, "mapping.yaml"),
        iteration=1,
        generator=ADVERSARIAL_GENERATOR,
        notes=str(expect.get("notes", "")),
    )
    return AdversarialCase(
        name=directory.name, against_client=against, artifact=artifact, must_fail=must_fail
    )


def list_adversarial(root: Path = CORPUS_DIR) -> list[AdversarialCase]:
    """Load every ``corpus/_adversarial/<name>/`` case, sorted by name."""
    directory = root / ADVERSARIAL_DIRNAME
    if not directory.is_dir():
        raise CorpusError(f"adversarial directory {directory} is missing")
    clients = list_clients(root)
    return [
        _load_adversarial(case_dir, clients)
        for case_dir in sorted(directory.iterdir())
        if case_dir.is_dir()
    ]


# --------------------------------------------------------------------------- #
# CLI                                                                          #
# --------------------------------------------------------------------------- #


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m drydock.corpus", description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--verify", action="store_true", help="check every manifest pin")
    group.add_argument(
        "--rebuild-manifests", action="store_true", help="regenerate every manifest.json"
    )
    parser.add_argument("--root", type=Path, default=CORPUS_DIR, help="corpus directory")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for ``python -m drydock.corpus``; returns the process exit code."""
    args = _build_parser().parse_args(argv)
    try:
        if args.rebuild_manifests:
            for path in rebuild_manifests(args.root):
                print(f"wrote {path}")
        verify_all(args.root)
        clients = list_clients(args.root)
        cases = list_adversarial(args.root)
        print(f"corpus ok: {len(clients)} clients, {len(cases)} adversarial cases")
    except DrydockError as exc:
        print(f"corpus error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
