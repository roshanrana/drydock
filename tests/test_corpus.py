"""Corpus loader, reference transform, manifests, adversarial set and CLI (T-001)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from drydock import corpus, errors, paths
from drydock.corpus import (
    DEFECT_IDS,
    SCENARIOS,
    AdversarialCase,
    Manifest,
    Scenario,
    build_manifest,
    extract_feed_contract,
    list_adversarial,
    list_clients,
    list_samples,
    load_manifest,
    load_spec,
    profile_rows,
    rebuild_manifests,
    reference_transform,
    verify_all,
    verify_manifest,
    write_manifest,
)
from drydock.errors import CorpusError
from drydock.models import CANONICAL_COLUMNS, CheckId, SourceFormat

CLIENTS = [
    "acme-treasury",
    "blue-harbour-fx",
    "kestrel-payments",
    "meridian-legacy",
    "northwind-custody",
    "orion-prime",
]
FORMATS = {
    "acme-treasury": SourceFormat.CSV,
    "northwind-custody": SourceFormat.CSV,
    "blue-harbour-fx": SourceFormat.CSV,
    "orion-prime": SourceFormat.FIXED_WIDTH,
    "kestrel-payments": SourceFormat.JSON_LINES,
    "meridian-legacy": SourceFormat.CSV,
}
ADVERSARIAL = {
    "dag_missing_dependency": (CheckId.DAG_CONTRACT,),
    "drops_last_row": (CheckId.COMPLETENESS,),
    "sleeps_past_budget": (CheckId.LATENCY,),
    "slow_network_import": (CheckId.RUNTIME,),
    "wrong_amount_format": (CheckId.SCHEMA,),
}
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
AMOUNT_RE = re.compile(r"^-?\d+\.\d{2}$")
CCY_RE = re.compile(r"^[A-Z]{3}$")

BASIC_SPEC = """\
client: {client}
feed_name: cash
format: {format}
delimiter: "{delimiter}"
header_rows: {header_rows}
trailer_rows: {trailer_rows}
skip_blank_lines: {skip_blank_lines}
columns:
{columns}
"""
CSV_COLUMNS = """\
  - {source: "Ref", target: trade_id, dtype: str}
  - {source: "Acct", target: account_id, dtype: str}
  - {source: "Date", target: value_date, dtype: date, date_format: "%d/%m/%Y"}
  - {source: "Amt", target: amount, dtype: decimal, sign_column: "DrCr", negative_marker: "DR"}
  - {source: "DrCr", target: null, dtype: str}
  - {source: "Ccy", target: currency, dtype: str}
  - {source: "Cpty", target: counterparty, dtype: str}
  - {source: "Desc", target: description, dtype: str}
"""
CSV_HEADER = "Ref,Acct,Date,Amt,DrCr,Ccy,Cpty,Desc"
CSV_ROWS = [
    'T1,A1,28/08/2026,"1,250.00",DR,gbp,Halvorsen Maritime AS,Freight',
    "T2,A1,01/09/2026,300.5,CR,GBP,Pinecrest Logistics Ltd,Invoice",
    "T3,A2,02/09/2026,0.00,DR,EUR,Quillon Pharma BV,Nil",
]


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    return path


def _spec_doc(yaml_body: str, blocks: int = 1) -> str:
    fence = f"```yaml feed-contract\n{yaml_body}```\n"
    return "# Feed\n\nDelivered daily.\n\nQuirks abound.\n\n" + fence * blocks


def _csv_spec(client: str = "demo", **overrides: object) -> str:
    values: dict[str, object] = {
        "client": client,
        "format": "csv",
        "delimiter": ",",
        "header_rows": 1,
        "trailer_rows": 0,
        "skip_blank_lines": "true",
        "columns": CSV_COLUMNS,
    }
    values.update(overrides)
    return BASIC_SPEC.format(**values)


def make_client(
    root: Path,
    client: str = "demo",
    spec_yaml: str | None = None,
    samples: dict[str, str] | None = None,
    blocks: int = 1,
) -> Path:
    """Create ``root/<client>`` with a spec and sample files; returns the client dir."""
    client_dir = root / client
    _write(client_dir / "spec.md", _spec_doc(spec_yaml or _csv_spec(client), blocks))
    files = samples if samples is not None else {"cash.csv": _csv_text(CSV_ROWS)}
    for name, text in files.items():
        _write(client_dir / "samples" / name, text)
    return client_dir


def _csv_text(rows: list[str], header: str = CSV_HEADER, trailer: str | None = None) -> str:
    lines = [header, *rows] + ([trailer] if trailer else [])
    return "\n".join(lines) + "\n"


def make_adversarial(root: Path, name: str = "case", **expect: object) -> Path:
    case = root / corpus.ADVERSARIAL_DIRNAME / name
    payload: dict[str, object] = {"against_client": "demo", "must_fail": ["H3_completeness"]}
    payload.update(expect)
    _write(case / "pipeline.py", "def extract(path):\n    return []\n")
    _write(case / "dag.py", "dag_id = 'demo__cash'\n")
    _write(case / "mapping.yaml", "client: demo\n")
    _write(case / "expect.json", json.dumps(payload))
    return case


@pytest.fixture
def mini_root(tmp_path: Path) -> Path:
    make_client(tmp_path)
    make_adversarial(tmp_path)
    return tmp_path


# --------------------------------------------------------------------------- #
# Committed corpus                                                             #
# --------------------------------------------------------------------------- #


def test_list_clients_matches_lld_table() -> None:
    assert list_clients() == CLIENTS


@pytest.mark.parametrize("client", CLIENTS)
def test_load_spec_parses_each_client(client: str) -> None:
    spec = load_spec(client)
    assert spec.client == client
    assert spec.format is FORMATS[client]
    targets = [c.target for c in spec.columns if c.target]
    assert sorted(targets) == sorted(CANONICAL_COLUMNS)


@pytest.mark.parametrize("client", CLIENTS)
def test_spec_has_one_contract_block_and_prose(client: str) -> None:
    text = (paths.CORPUS_DIR / client / "spec.md").read_text(encoding="utf-8")
    assert text.count("```yaml feed-contract") == 1
    prose = text.split("```yaml feed-contract")[0]
    paragraphs = [p for p in prose.split("\n\n") if p.strip() and not p.startswith("#")]
    assert 2 <= len(paragraphs) <= 4


@pytest.mark.parametrize("client", CLIENTS)
def test_reference_rows_are_canonical_and_bounded(client: str) -> None:
    spec = load_spec(client)
    for sample in list_samples(client):
        rows = reference_transform(spec, sample)
        assert 10 <= len(rows) <= 20
        for row in rows:
            assert tuple(row) == CANONICAL_COLUMNS
            assert DATE_RE.match(row["value_date"])
            assert AMOUNT_RE.match(row["amount"])
            assert CCY_RE.match(row["currency"])
            assert row["trade_id"] and row["counterparty"]


@pytest.mark.parametrize("client", CLIENTS)
def test_manifest_scenarios_match_lld(client: str) -> None:
    manifest = load_manifest(client)
    assert manifest.client == client
    assert manifest.scenario == SCENARIOS[client]
    defect = manifest.scenario.injected_defect
    assert defect is None or defect in DEFECT_IDS
    assert all(len(s.sha256) == 64 and s.bytes > 0 for s in manifest.samples)


def test_verify_all_passes_on_committed_corpus() -> None:
    verify_all()


def test_meridian_spec_disagrees_with_sample_by_design() -> None:
    assert load_spec("meridian-legacy").expected_row_count == 15
    manifest = load_manifest("meridian-legacy")
    # The pin is the client's asserted count; the sample really has 14 rows, so a correct
    # pipeline fails H3 on every iteration and the loop must escalate.
    assert manifest.samples[0].expected_rows == 15
    assert (
        len(
            corpus.reference_transform(
                load_spec("meridian-legacy"), list_samples("meridian-legacy")[0]
            )
        )
        == 14
    )
    assert manifest.scenario.expected_outcome == "escalate"


def test_acme_thousands_separators_are_stripped() -> None:
    rows = reference_transform(load_spec("acme-treasury"), _sample("acme-treasury"))
    assert rows[0]["amount"] == "1250.00"
    assert rows[8]["amount"] == "-1000000.00"
    assert rows[3]["description"] == "SaaS subscription Q3"  # trailing space stripped
    assert load_manifest("acme-treasury").samples[0].amount_sum == "-823639.24"


def test_northwind_day_first_dates_and_drcr_sign() -> None:
    rows = reference_transform(load_spec("northwind-custody"), _sample("northwind-custody"))
    assert len(rows) == 15
    assert rows[0]["value_date"] == "2026-08-28"
    assert rows[0]["amount"] == "152000.00"
    assert rows[1]["amount"] == "-98450.50"


def test_blue_harbour_trailer_and_pipe_delimiter() -> None:
    rows = reference_transform(load_spec("blue-harbour-fx"), _sample("blue-harbour-fx"))
    assert len(rows) == 14
    assert rows[-1]["trade_id"] == "BHF-2026-09-0457-B"
    assert rows[8]["amount"] == "-150000000.00"  # JPY leg without decimals
    assert rows[0]["value_date"] == "2026-09-01"
    assert "TRAILER" not in {row["trade_id"] for row in rows}


def test_orion_fixed_width_slices() -> None:
    rows = reference_transform(load_spec("orion-prime"), _sample("orion-prime"))
    assert len(rows) == 13
    assert rows[0]["trade_id"] == "ORN0115201"
    assert rows[0]["amount"] == "-1250000.00"
    assert rows[0]["currency"] == "USD"
    assert rows[0]["counterparty"] == "Ironbridge Commodities SA"
    assert rows[11]["amount"] == "0.00"


def test_kestrel_jsonl_sign_and_timestamp() -> None:
    rows = reference_transform(load_spec("kestrel-payments"), _sample("kestrel-payments"))
    assert len(rows) == 16
    assert rows[0]["amount"] == "-12500.00"
    assert rows[0]["value_date"] == "2026-09-01"
    assert rows[3]["amount"] == "3150.50"  # JSON number 3150.5 quantised


def _sample(client: str) -> Path:
    return list_samples(client)[0]


def test_list_adversarial_returns_five_cases() -> None:
    cases = list_adversarial()
    assert [c.name for c in cases] == sorted(ADVERSARIAL)
    for case in cases:
        assert isinstance(case, AdversarialCase)
        assert case.against_client == "acme-treasury"
        assert case.must_fail == ADVERSARIAL[case.name]
        assert case.artifact.generator == corpus.ADVERSARIAL_GENERATOR
        assert case.artifact.iteration == 1
        compile(case.artifact.pipeline_py, f"{case.name}/pipeline.py", "exec")
        compile(case.artifact.dag_py, f"{case.name}/dag.py", "exec")
        assert "acme-treasury__daily_cash" in case.artifact.dag_py


def test_slow_network_import_imports_socket_and_sleeps_six_seconds() -> None:
    case = next(c for c in list_adversarial() if c.name == "slow_network_import")
    assert "import socket" in case.artifact.pipeline_py
    assert "SLEEP_SECONDS = 6" in case.artifact.pipeline_py
    assert "time.sleep(SLEEP_SECONDS)" in case.artifact.pipeline_py


def test_dag_missing_dependency_has_no_load_edge() -> None:
    case = next(c for c in list_adversarial() if c.name == "dag_missing_dependency")
    assert "transform >> load" not in case.artifact.dag_py
    assert "extract >> transform" in case.artifact.dag_py


# --------------------------------------------------------------------------- #
# paths / errors                                                               #
# --------------------------------------------------------------------------- #


def test_paths_are_anchored_at_repo_root() -> None:
    assert (paths.ROOT / "pyproject.toml").is_file()
    assert paths.CORPUS_DIR == paths.ROOT / "corpus"
    assert paths.RUNS_DIR == paths.ROOT / "runs"
    assert paths.DEPLOY_DIR == paths.ROOT / "deploy"
    assert paths.DB_PATH.parent == paths.DATA_DIR == paths.ROOT / "data"


def test_error_taxonomy_hierarchy() -> None:
    assert issubclass(errors.CorpusError, errors.DrydockError)
    assert issubclass(errors.SandboxTimeout, errors.SandboxError)
    assert issubclass(errors.SandboxError, errors.DrydockError)
    for cls in (errors.ProviderError, errors.RunNotFound, errors.InvalidTransition):
        assert issubclass(cls, errors.DrydockError)


# --------------------------------------------------------------------------- #
# Spec parsing                                                                 #
# --------------------------------------------------------------------------- #


def test_extract_feed_contract_requires_exactly_one_block() -> None:
    with pytest.raises(CorpusError, match="found 0"):
        extract_feed_contract("# no block\n")
    with pytest.raises(CorpusError, match="found 2"):
        extract_feed_contract(_spec_doc("client: x\n", blocks=2))
    assert extract_feed_contract(_spec_doc("client: x\n")) == "client: x"


def test_load_spec_accepts_crlf_documents(tmp_path: Path) -> None:
    make_client(tmp_path)
    spec_path = tmp_path / "demo" / "spec.md"
    spec_path.write_bytes(spec_path.read_bytes().replace(b"\n", b"\r\n"))
    assert load_spec("demo", tmp_path).client == "demo"


@pytest.mark.parametrize(
    ("yaml_body", "message"),
    [
        ("client: [unclosed\n", "not valid yaml"),
        ("- just\n- a list\n", "must be a yaml mapping"),
        (_csv_spec() + "unknown_field: 1\n", "does not satisfy FeedSpec"),
        (_csv_spec(client="other"), "client is 'other'"),
        (_csv_spec(columns='  - {source: "Ref", target: nope}\n'), "unknown column"),
        (
            _csv_spec(columns='  - {source: "D", target: value_date, dtype: date}\n'),
            "no date_format",
        ),
        (
            _csv_spec(
                columns='  - {source: "A", target: amount, dtype: decimal, sign_column: "S"}\n'
            ),
            "no negative_marker",
        ),
        (
            _csv_spec(format="fixed_width", columns='  - {source: "abc", target: trade_id}\n'),
            "slice",
        ),
        (
            _csv_spec(format="fixed_width", columns='  - {source: "5:5", target: trade_id}\n'),
            "empty",
        ),
    ],
)
def test_load_spec_rejects_bad_contracts(tmp_path: Path, yaml_body: str, message: str) -> None:
    make_client(tmp_path, spec_yaml=yaml_body)
    with pytest.raises(CorpusError, match=message):
        load_spec("demo", tmp_path)


def test_load_spec_missing_client_or_file(tmp_path: Path) -> None:
    with pytest.raises(CorpusError, match="unknown client"):
        load_spec("ghost", tmp_path)
    (tmp_path / "empty").mkdir()
    with pytest.raises(CorpusError, match="is missing"):
        load_spec("empty", tmp_path)


def test_discovery_errors(tmp_path: Path) -> None:
    with pytest.raises(CorpusError, match="not a directory"):
        list_clients(tmp_path / "nowhere")
    (tmp_path / "no-samples").mkdir()
    _write(tmp_path / "no-samples" / "spec.md", _spec_doc(_csv_spec("no-samples")))
    assert list_clients(tmp_path) == ["no-samples"]
    with pytest.raises(CorpusError, match="samples directory"):
        list_samples("no-samples", tmp_path)


# --------------------------------------------------------------------------- #
# Reference transform on synthetic feeds                                       #
# --------------------------------------------------------------------------- #


def test_csv_transform_applies_every_rule(tmp_path: Path) -> None:
    make_client(tmp_path)
    rows = reference_transform(load_spec("demo", tmp_path), tmp_path / "demo/samples/cash.csv")
    assert [r["amount"] for r in rows] == ["-1250.00", "300.50", "0.00"]
    assert [r["value_date"] for r in rows] == ["2026-08-28", "2026-09-01", "2026-09-02"]
    assert rows[0]["currency"] == "GBP"  # upper-cased
    assert "DrCr" not in rows[0]
    assert tuple(rows[0]) == CANONICAL_COLUMNS


def test_transform_defaults_int_and_unmapped_columns(tmp_path: Path) -> None:
    columns = (
        '  - {source: "Ref", target: trade_id, dtype: int}\n'
        '  - {source: "Amt", target: amount, dtype: decimal}\n'
        '  - {source: "Ccy", target: currency, dtype: str, default: "USD"}\n'
    )
    make_client(
        tmp_path,
        spec_yaml=_csv_spec(columns=columns),
        samples={"s.csv": "Ref,Amt,Ccy\n007,1.005,\n8,-0.004,eur\n"},
    )
    rows = reference_transform(load_spec("demo", tmp_path), tmp_path / "demo/samples/s.csv")
    assert rows[0] == {
        "trade_id": "7",
        "account_id": "",
        "value_date": "",
        "amount": "1.01",
        "currency": "USD",
        "counterparty": "",
        "description": "",
    }
    assert rows[1]["amount"] == "0.00"  # -0.004 rounds to negative zero, normalised
    assert rows[1]["currency"] == "EUR"


def test_fixed_width_and_trailer_and_blank_lines(tmp_path: Path) -> None:
    columns = (
        '  - {source: "0:4", target: trade_id}\n'
        '  - {source: "4:14", target: amount, dtype: decimal}\n'
        '  - {source: "14:17", target: currency}\n'
    )
    body = "ID  AMOUNT    CCY\nT001   1200.50GBP\n\nT002    -80.00usd\nEND 2\n"
    make_client(
        tmp_path,
        spec_yaml=_csv_spec(format="fixed_width", trailer_rows=1, columns=columns),
        samples={"fw.txt": body},
    )
    rows = reference_transform(load_spec("demo", tmp_path), tmp_path / "demo/samples/fw.txt")
    assert [(r["trade_id"], r["amount"], r["currency"]) for r in rows] == [
        ("T001", "1200.50", "GBP"),
        ("T002", "-80.00", "USD"),
    ]


def test_blank_lines_kept_when_skip_disabled(tmp_path: Path) -> None:
    make_client(
        tmp_path,
        spec_yaml=_csv_spec(skip_blank_lines="false"),
        samples={"cash.csv": _csv_text([CSV_ROWS[0], "", CSV_ROWS[1]])},
    )
    with pytest.raises(CorpusError, match="expected 8 fields, got 0"):
        reference_transform(load_spec("demo", tmp_path), tmp_path / "demo/samples/cash.csv")


def test_jsonl_transform_and_errors(tmp_path: Path) -> None:
    columns = (
        '  - {source: "id", target: trade_id}\n'
        '  - {source: "amt", target: amount, dtype: decimal, '
        'sign_column: "dir", negative_marker: "DEBIT"}\n'
        '  - {source: "dir", target: null}\n'
        '  - {source: "flag", target: description}\n'
    )
    good = (
        '{"id": 1, "amt": 10.5, "dir": "DEBIT", "flag": true}\n'
        '{"id": 2, "amt": "3", "dir": "CREDIT", "flag": null}\n'
    )
    make_client(
        tmp_path,
        spec_yaml=_csv_spec(format="jsonl", header_rows=0, columns=columns),
        samples={"ok.jsonl": good, "bad.jsonl": "{not json}\n", "list.jsonl": "[1, 2]\n"},
    )
    spec = load_spec("demo", tmp_path)
    rows = reference_transform(spec, tmp_path / "demo/samples/ok.jsonl")
    assert [(r["trade_id"], r["amount"], r["description"]) for r in rows] == [
        ("1", "-10.50", "true"),
        ("2", "3.00", ""),
    ]
    with pytest.raises(CorpusError, match="invalid json"):
        reference_transform(spec, tmp_path / "demo/samples/bad.jsonl")
    with pytest.raises(CorpusError, match="not an object"):
        reference_transform(spec, tmp_path / "demo/samples/list.jsonl")


@pytest.mark.parametrize(
    ("row", "message"),
    [
        ("T1,A1,2026-08-28,1.00,DR,GBP,C,D", "data row 1"),  # wrong date format -> ValueError
        ("T1,A1,28/08/2026,abc,DR,GBP,C,D", "data row 1"),  # InvalidOperation
        ("T1,A1,28/08/2026,,DR,GBP,C,D", "is empty"),
        ("T1,A1,28/08/2026,1.00,DR,GBP,C", "expected 8 fields, got 7"),
    ],
)
def test_transform_reports_row_level_errors(tmp_path: Path, row: str, message: str) -> None:
    make_client(tmp_path, samples={"cash.csv": _csv_text([row])})
    with pytest.raises(CorpusError, match=message):
        reference_transform(load_spec("demo", tmp_path), tmp_path / "demo/samples/cash.csv")


def test_transform_missing_source_and_sign_columns(tmp_path: Path) -> None:
    header_without_sign = "Ref,Acct,Date,Amt,Ccy,Cpty,Desc"
    make_client(
        tmp_path,
        samples={"cash.csv": _csv_text(["T1,A1,28/08/2026,1.00,GBP,C,D"], header_without_sign)},
    )
    with pytest.raises(CorpusError, match="sign column 'DrCr' is missing"):
        reference_transform(load_spec("demo", tmp_path), tmp_path / "demo/samples/cash.csv")
    _write(tmp_path / "demo/samples/cash.csv", "Other\nx\n")
    with pytest.raises(CorpusError, match="source column 'Ref' is missing"):
        reference_transform(load_spec("demo", tmp_path), tmp_path / "demo/samples/cash.csv")


def test_transform_structural_errors(tmp_path: Path) -> None:
    make_client(tmp_path, samples={"short.csv": "\n"})
    spec = load_spec("demo", tmp_path)
    with pytest.raises(CorpusError, match="fewer lines"):
        reference_transform(spec, tmp_path / "demo/samples/short.csv")
    with pytest.raises(CorpusError, match="is missing"):
        reference_transform(spec, tmp_path / "demo/samples/nope.csv")
    make_client(tmp_path, client="nohdr", spec_yaml=_csv_spec("nohdr", header_rows=0))
    with pytest.raises(CorpusError, match="header_rows >= 1"):
        reference_transform(load_spec("nohdr", tmp_path), tmp_path / "nohdr/samples/cash.csv")


# --------------------------------------------------------------------------- #
# Profiling and manifests                                                      #
# --------------------------------------------------------------------------- #


def test_profile_rows_empty() -> None:
    profile = profile_rows([])
    assert profile["rows"] == 0
    assert profile["amount_sum"] == "0.00"
    assert profile["null_rate"]["amount"] == 0.0
    assert profile["distinct"]["currency"] == 0


def test_profile_rows_sums_exactly_and_counts_nulls() -> None:
    base = dict.fromkeys(CANONICAL_COLUMNS, "")
    rows = [
        {**base, "amount": "0.10", "currency": "GBP", "counterparty": "A"},
        {**base, "amount": "0.20", "currency": "GBP", "counterparty": ""},
        {**base, "amount": "-0.30", "currency": "USD", "counterparty": "B"},
        {**base, "amount": "1000000.01", "currency": "USD", "counterparty": ""},
    ]
    profile = profile_rows(rows)
    assert profile == {
        "rows": 4,
        "amount_sum": "1000000.01",
        "null_rate": {**dict.fromkeys(CANONICAL_COLUMNS, 1.0), "amount": 0.0, "currency": 0.0}
        | {"counterparty": 0.5},
        "distinct": {**dict.fromkeys(CANONICAL_COLUMNS, 1), "amount": 4, "currency": 2}
        | {"counterparty": 3},
    }


def test_rebuild_then_verify_roundtrip(mini_root: Path) -> None:
    written = rebuild_manifests(mini_root)
    assert written == [mini_root / "demo" / "manifest.json"]
    assert b"\r\n" not in written[0].read_bytes()
    manifest = load_manifest("demo", mini_root)
    assert isinstance(manifest, Manifest)
    assert manifest.samples[0].expected_rows == 3
    assert manifest.samples[0].amount_sum == "-949.50"
    assert manifest.scenario == Scenario(injected_defect=None, expected_outcome="pass")
    verify_manifest("demo", mini_root)
    verify_all(mini_root)


def test_rebuild_preserves_existing_scenario_and_explicit_override(mini_root: Path) -> None:
    custom = Scenario(injected_defect="wrong_slice", expected_outcome="heal", notes="keep me")
    write_manifest(build_manifest("demo", mini_root, scenario=custom), mini_root)
    rebuild_manifests(mini_root)
    assert load_manifest("demo", mini_root).scenario == custom


def test_build_manifest_uses_lld_scenario_for_known_client(tmp_path: Path) -> None:
    make_client(tmp_path, client="orion-prime", spec_yaml=_csv_spec("orion-prime"))
    assert build_manifest("orion-prime", tmp_path).scenario == SCENARIOS["orion-prime"]


def test_build_manifest_requires_samples(tmp_path: Path) -> None:
    make_client(tmp_path, samples={})
    (tmp_path / "demo" / "samples").mkdir(exist_ok=True)
    with pytest.raises(CorpusError, match="no sample files"):
        build_manifest("demo", tmp_path)


def test_load_manifest_missing_or_invalid(mini_root: Path) -> None:
    with pytest.raises(CorpusError, match="rebuild-manifests"):
        load_manifest("demo", mini_root)
    _write(mini_root / "demo" / "manifest.json", '{"client": "demo"}')
    with pytest.raises(CorpusError, match="manifest is invalid"):
        load_manifest("demo", mini_root)


def test_verify_detects_every_kind_of_drift(mini_root: Path) -> None:
    rebuild_manifests(mini_root)
    sample = mini_root / "demo" / "samples" / "cash.csv"
    original = sample.read_text(encoding="utf-8")

    _write(sample, original.replace("300.5", "300.6"))  # same bytes, new hash and sum
    with pytest.raises(CorpusError) as excinfo:
        verify_manifest("demo", mini_root)
    assert "sha256" in str(excinfo.value) and "amount_sum" in str(excinfo.value)

    _write(sample, original + CSV_ROWS[0] + "\n")  # more bytes and rows
    with pytest.raises(CorpusError, match="bytes"):
        verify_manifest("demo", mini_root)
    assert "rows != pinned" in _verify_error(mini_root)

    _write(sample, original)
    _write(mini_root / "demo" / "samples" / "extra.csv", original)
    assert "extra.csv: on disk but not pinned" in _verify_error(mini_root)
    (mini_root / "demo" / "samples" / "extra.csv").unlink()
    sample.unlink()
    assert "missing on disk" in _verify_error(mini_root)


def _verify_error(root: Path) -> str:
    with pytest.raises(CorpusError) as excinfo:
        verify_manifest("demo", root)
    return str(excinfo.value)


def test_verify_manifest_client_mismatch(mini_root: Path) -> None:
    manifest = build_manifest("demo", mini_root)
    tampered = manifest.model_copy(update={"client": "other"}).model_dump_json(indent=2)
    _write(mini_root / "demo" / "manifest.json", tampered)
    assert "manifest client 'other'" in _verify_error(mini_root)


def test_verify_all_aggregates_and_requires_clients(tmp_path: Path, mini_root: Path) -> None:
    with pytest.raises(CorpusError, match="no clients"):
        verify_all(_empty_root(tmp_path))
    make_client(mini_root, client="second")
    with pytest.raises(CorpusError) as excinfo:
        verify_all(mini_root)
    assert "demo:" in str(excinfo.value) and "second:" in str(excinfo.value)


def _empty_root(tmp_path: Path) -> Path:
    root = tmp_path / "empty-root"
    root.mkdir()
    return root


# --------------------------------------------------------------------------- #
# Adversarial loading                                                          #
# --------------------------------------------------------------------------- #


def test_list_adversarial_synthetic(mini_root: Path) -> None:
    (case,) = list_adversarial(mini_root)
    assert case.name == "case"
    assert case.must_fail == (CheckId.COMPLETENESS,)
    assert case.artifact.mapping_yaml == "client: demo\n"


@pytest.mark.parametrize(
    ("expect", "message"),
    [
        ({"against_client": "ghost"}, "unknown against_client"),
        ({"must_fail": ["H9_nope"]}, "bad must_fail"),
        ({"must_fail": []}, "must_fail is empty"),
    ],
)
def test_list_adversarial_rejects_bad_expectations(
    tmp_path: Path, expect: dict[str, object], message: str
) -> None:
    make_client(tmp_path)
    make_adversarial(tmp_path, **expect)
    with pytest.raises(CorpusError, match=message):
        list_adversarial(tmp_path)


def test_list_adversarial_missing_files(tmp_path: Path) -> None:
    make_client(tmp_path)
    with pytest.raises(CorpusError, match="adversarial directory"):
        list_adversarial(tmp_path)
    case = make_adversarial(tmp_path)
    (case / "pipeline.py").unlink()
    with pytest.raises(CorpusError, match="pipeline.py is missing"):
        list_adversarial(tmp_path)
    _write(case / "pipeline.py", "")
    _write(case / "expect.json", "{oops")
    with pytest.raises(CorpusError, match="expect.json"):
        list_adversarial(tmp_path)


# --------------------------------------------------------------------------- #
# CLI                                                                          #
# --------------------------------------------------------------------------- #


def test_main_rebuild_and_verify(mini_root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert corpus.main(["--rebuild-manifests", "--root", str(mini_root)]) == 0
    out = capsys.readouterr().out
    assert "wrote" in out and "corpus ok: 1 clients, 1 adversarial cases" in out
    assert corpus.main(["--verify", "--root", str(mini_root)]) == 0


def test_main_reports_corpus_errors_with_exit_2(
    mini_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert corpus.main(["--verify", "--root", str(mini_root)]) == 2
    assert "corpus error: demo:" in capsys.readouterr().err


def test_main_requires_an_action() -> None:
    with pytest.raises(SystemExit):
        corpus.main([])


def test_main_verify_on_committed_corpus(capsys: pytest.CaptureFixture[str]) -> None:
    assert corpus.main(["--verify"]) == 0
    assert "6 clients, 5 adversarial cases" in capsys.readouterr().out
