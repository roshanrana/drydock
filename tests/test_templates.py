"""Templates: rendered pipeline/dag/mapping are executed in-process on inline samples."""

from __future__ import annotations

import ast
import decimal
import json
import subprocess
import sys
import types
from pathlib import Path
from typing import Any

import pytest
import yaml

from drydock.models import CANONICAL_COLUMNS, ColumnSpec, IngestionPlan, SourceFormat
from drydock.providers import ProviderError
from drydock.providers import templates as tpl

PIPELINE_ALLOWLIST = {
    "csv",
    "json",
    "decimal",
    "datetime",
    "re",
    "io",
    "os.path",
    "pathlib",
    "typing",
    "dataclasses",
    "collections",
    "itertools",
    "functools",
    "math",
    "string",
}
DAG_ALLOWLIST = {"airflow", "airflow.operators.python", "datetime", "pipeline"}

# --------------------------------------------------------------------------- #
# Plans and samples                                                            #
# --------------------------------------------------------------------------- #

CSV_PLAN = IngestionPlan(
    client="acme-treasury",
    feed_name="daily_cash",
    format=SourceFormat.CSV,
    parse_options={"delimiter": ",", "encoding": "utf-8", "header_rows": 1, "trailer_rows": 1},
    column_map=(
        ColumnSpec(source="TradeRef", target="trade_id"),
        ColumnSpec(source="Account", target="account_id"),
        ColumnSpec(source="ValueDate", target="value_date", dtype="date", date_format="%d/%m/%Y"),
        ColumnSpec(
            source="Amount",
            target="amount",
            dtype="decimal",
            sign_column="DrCr",
            negative_marker="DR",
        ),
        ColumnSpec(source="DrCr", target=None),
        ColumnSpec(source="Ccy", target="currency", default="USD"),
        ColumnSpec(source="Cpty", target="counterparty"),
        ColumnSpec(source="Narrative", target="description"),
    ),
    schedule_cron="0 6 * * 1-5",
)

CSV_SAMPLE = (
    "TradeRef,Account,ValueDate,Amount,DrCr,Ccy,Cpty,Narrative\n"
    'T1,ACC-1,03/09/2026,"1,234.50",DR,usd,Alpha Ltd,Fee\n'
    "T2,ACC-2,04/09/2026,99.999,CR,,Beta,Interest\n"
    "\n"
    "TOTAL,2,,1334.50,,,,\n"
)

FW_PLAN = IngestionPlan(
    client="north-bank",
    feed_name="positions",
    format=SourceFormat.FIXED_WIDTH,
    parse_options={"header_rows": 0, "trailer_rows": 0, "encoding": "latin-1"},
    column_map=(
        ColumnSpec(source="0:6", target="trade_id"),
        ColumnSpec(source="6:14", target="account_id"),
        ColumnSpec(source="14:22", target="value_date", dtype="date", date_format="%Y%m%d"),
        ColumnSpec(
            source="22:34",
            target="amount",
            dtype="decimal",
            sign_column="34:36",
            negative_marker="DR",
        ),
        ColumnSpec(source="34:36", target=None),
        ColumnSpec(source="36:39", target="currency"),
        ColumnSpec(source="39:51", target="counterparty"),
        ColumnSpec(source="51:70", target="description"),
    ),
    schedule_cron="30 7 * * *",
)


def fw_line(
    ref: str, acct: str, date: str, amount: str, drcr: str, ccy: str, cp: str, d: str
) -> str:
    return (
        ref.ljust(6)
        + acct.ljust(8)
        + date.ljust(8)
        + amount.rjust(12)
        + drcr.ljust(2)
        + ccy.ljust(3)
        + cp.ljust(12)
        + d.ljust(19)
    )


FW_SAMPLE = (
    fw_line("T00001", "ACC00001", "20260903", "1,234.50", "DR", "EUR", "Alpha Ltd", "Fee")
    + "\n"
    + fw_line("T00002", "ACC00002", "20260904", "0.10", "CR", "GBP", "Beta", "Interest")
    + "\n"
)

JSONL_PLAN = IngestionPlan(
    client="delta-fund",
    feed_name="ledger",
    format=SourceFormat.JSON_LINES,
    parse_options={"header_rows": 0},
    column_map=(
        ColumnSpec(source="ref", target="trade_id"),
        ColumnSpec(source="acct", target="account_id"),
        ColumnSpec(source="date", target="value_date", dtype="date"),
        ColumnSpec(source="amt", target="amount", dtype="decimal"),
        ColumnSpec(source="ccy", target="currency"),
        ColumnSpec(source="cpty", target="counterparty"),
        ColumnSpec(source="memo", target="description"),
        ColumnSpec(source="internal_flag", target=None),
    ),
    schedule_cron="0 1 * * *",
)

JSONL_SAMPLE = (
    json.dumps(
        {
            "ref": "J1",
            "acct": "A1",
            "date": "2026-09-03",
            "amt": -1234.5,
            "ccy": "chf",
            "cpty": "Gamma",
            "memo": None,
            "internal_flag": True,
        }
    )
    + "\n"
    + json.dumps(
        {
            "ref": "J2",
            "acct": "A2",
            "date": "2026-09-04",
            "amt": "(12.00)",
            "ccy": "CHF",
            "cpty": "Delta",
            "memo": "Refund",
            "internal_flag": False,
        }
    )
    + "\n"
)


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #


def load_module(source: str, name: str = "pipeline") -> types.ModuleType:
    module = types.ModuleType(name)
    # dont_inherit: the generated module must not inherit this file's __future__ flags.
    exec(compile(source, f"{name}.py", "exec", dont_inherit=True), module.__dict__)
    return module


def imported_modules(source: str) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def run_pipeline(plan: IngestionPlan, sample: str, tmp_path: Path, encoding: str = "utf-8"):
    source = tpl.render_pipeline(plan)
    module = load_module(source)
    path = tmp_path / "sample.dat"
    path.write_text(sample, encoding=encoding, newline="\n")
    return module, module.transform(module.extract(str(path)))


class FakeOperator:
    def __init__(self, task_id: str, python_callable: Any, **kwargs: Any) -> None:
        self.task_id = task_id
        self.python_callable = python_callable
        self.kwargs = kwargs
        FakeDag.current.tasks.append(self)

    def __rshift__(self, other: FakeOperator) -> FakeOperator:
        FakeDag.current.edges.append((self.task_id, other.task_id))
        return other


class FakeDag:
    current: FakeDag

    def __init__(self, dag_id: str, schedule: str, **kwargs: Any) -> None:
        self.dag_id = dag_id
        self.schedule = schedule
        self.kwargs = kwargs
        self.tasks: list[FakeOperator] = []
        self.edges: list[tuple[str, str]] = []
        FakeDag.current = self

    def __enter__(self) -> FakeDag:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def run_dag(monkeypatch: pytest.MonkeyPatch, dag_py: str, pipeline_py: str) -> FakeDag:
    airflow = types.ModuleType("airflow")
    airflow.DAG = FakeDag  # type: ignore[attr-defined]
    operators = types.ModuleType("airflow.operators")
    python_mod = types.ModuleType("airflow.operators.python")
    python_mod.PythonOperator = FakeOperator  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "airflow", airflow)
    monkeypatch.setitem(sys.modules, "airflow.operators", operators)
    monkeypatch.setitem(sys.modules, "airflow.operators.python", python_mod)
    monkeypatch.setitem(sys.modules, "pipeline", load_module(pipeline_py))
    load_module(dag_py, "dag")
    return FakeDag.current


# --------------------------------------------------------------------------- #
# render_pipeline                                                              #
# --------------------------------------------------------------------------- #


def test_csv_pipeline_maps_rows_to_canonical_schema(tmp_path: Path) -> None:
    _, rows = run_pipeline(CSV_PLAN, CSV_SAMPLE, tmp_path)

    assert len(rows) == 2, "header, blank line and trailer must be skipped"
    assert all(tuple(row) == CANONICAL_COLUMNS for row in rows)
    assert rows[0] == {
        "trade_id": "T1",
        "account_id": "ACC-1",
        "value_date": "2026-09-03",
        "amount": "-1234.50",
        "currency": "USD",
        "counterparty": "Alpha Ltd",
        "description": "Fee",
    }
    assert rows[1]["amount"] == "100.00", "ROUND_HALF_UP to two decimals"
    assert rows[1]["currency"] == "USD", "default applies when the source value is empty"


def test_csv_pipeline_honours_delimiter_and_encoding(tmp_path: Path) -> None:
    plan = CSV_PLAN.model_copy(
        update={"parse_options": {"delimiter": ";", "encoding": "latin-1", "trailer_rows": 0}}
    )
    sample = (
        "TradeRef;Account;ValueDate;Amount;DrCr;Ccy;Cpty;Narrative\n"
        "T1;A;01/02/2026;5;CR;EUR;Caf\xe9;x\n"
    )
    _, rows = run_pipeline(plan, sample, tmp_path, encoding="latin-1")

    assert rows == [
        {
            "trade_id": "T1",
            "account_id": "A",
            "value_date": "2026-02-01",
            "amount": "5.00",
            "currency": "EUR",
            "counterparty": "Caf\xe9",
            "description": "x",
        }
    ]


def test_fixed_width_pipeline_slices_and_signs(tmp_path: Path) -> None:
    _, rows = run_pipeline(FW_PLAN, FW_SAMPLE, tmp_path, encoding="latin-1")

    assert [row["trade_id"] for row in rows] == ["T00001", "T00002"]
    assert rows[0]["value_date"] == "2026-09-03"
    assert rows[0]["amount"] == "-1234.50"
    assert rows[1]["amount"] == "0.10"
    assert rows[0]["currency"] == "EUR"
    assert rows[1]["description"] == "Interest"
    assert all(tuple(row) == CANONICAL_COLUMNS for row in rows)


def test_jsonl_pipeline_coerces_values_and_drops_columns(tmp_path: Path) -> None:
    _, rows = run_pipeline(JSONL_PLAN, JSONL_SAMPLE, tmp_path)

    assert len(rows) == 2
    assert rows[0]["amount"] == "-1234.50"
    assert rows[0]["currency"] == "CHF"
    assert rows[0]["description"] == "", "JSON null becomes empty string"
    assert rows[1]["amount"] == "-12.00", "accounting-style parentheses are negative"
    assert rows[1]["value_date"] == "2026-09-04"
    assert "internal_flag" not in rows[0]
    assert all(tuple(row) == CANONICAL_COLUMNS for row in rows)


def test_csv_without_header_uses_positional_source_names(tmp_path: Path) -> None:
    plan = CSV_PLAN.model_copy(update={"parse_options": {"header_rows": 0, "trailer_rows": 0}})
    _, rows = run_pipeline(plan, "T9,A9,05/09/2026,7.5,CR,GBP,Zed,note\n", tmp_path)

    assert rows[0]["trade_id"] == "T9"
    assert rows[0]["amount"] == "7.50"


def test_int_dtype_and_short_records(tmp_path: Path) -> None:
    plan = CSV_PLAN.model_copy(
        update={
            "parse_options": {"trailer_rows": 0},
            "column_map": (
                ColumnSpec(source="TradeRef", target="trade_id", dtype="int"),
                ColumnSpec(source="Amount", target="amount", dtype="decimal"),
            ),
        }
    )
    _, rows = run_pipeline(plan, "TradeRef,Amount\n0042,-0.001\n7\n", tmp_path)

    assert rows[0]["trade_id"] == "42"
    assert rows[0]["amount"] == "0.00", "-0.00 is normalised"
    assert rows[1] == {**dict.fromkeys(CANONICAL_COLUMNS, ""), "trade_id": "7", "amount": "0.00"}


@pytest.mark.parametrize("plan", [CSV_PLAN, FW_PLAN, JSONL_PLAN], ids=["csv", "fw", "jsonl"])
def test_pipeline_uses_only_allowlisted_imports(plan: IngestionPlan) -> None:
    source = tpl.render_pipeline(plan)

    assert imported_modules(source) <= PIPELINE_ALLOWLIST
    assert "open(" in source and ".write(" not in source


@pytest.mark.parametrize("plan", [CSV_PLAN, FW_PLAN, JSONL_PLAN], ids=["csv", "fw", "jsonl"])
def test_rendered_code_passes_ruff(plan: IngestionPlan, tmp_path: Path) -> None:
    (tmp_path / "pipeline.py").write_text(tpl.render_pipeline(plan), encoding="utf-8")
    (tmp_path / "dag.py").write_text(tpl.render_dag(plan), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--isolated",
            "--select",
            "E,F,W,B",
            "--line-length",
            "100",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
    )
    if "No module named ruff" in result.stderr:
        pytest.skip("ruff is not importable in this interpreter")
    assert result.returncode == 0, result.stdout + result.stderr


def test_invalid_parse_options_raise_provider_error() -> None:
    plan = CSV_PLAN.model_copy(update={"parse_options": {"header_rows": "many"}})
    with pytest.raises(ProviderError, match="parse_options"):
        tpl.render_pipeline(plan)


# --------------------------------------------------------------------------- #
# render_dag / render_mapping                                                  #
# --------------------------------------------------------------------------- #


def test_dag_declares_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    dag_py = tpl.render_dag(CSV_PLAN)

    assert imported_modules(dag_py) <= DAG_ALLOWLIST
    assert 'dag_id="acme-treasury__daily_cash"' in dag_py
    assert 'schedule="0 6 * * 1-5"' in dag_py
    dag = run_dag(monkeypatch, dag_py, tpl.render_pipeline(CSV_PLAN))
    assert dag.dag_id == "acme-treasury__daily_cash"
    assert dag.schedule == "0 6 * * 1-5"
    assert [task.task_id for task in dag.tasks] == ["extract", "transform", "load"]
    assert dag.edges == [("extract", "transform"), ("transform", "load")]
    assert dag.tasks[0].kwargs["op_kwargs"]["path"].endswith("{{ ds }}.csv")


def test_dag_requires_three_task_ids() -> None:
    plan = CSV_PLAN.model_copy(update={"task_ids": ("extract", "load")})
    with pytest.raises(ProviderError, match="three tasks"):
        tpl.render_dag(plan)


def test_mapping_yaml_shape() -> None:
    document = yaml.safe_load(tpl.render_mapping(CSV_PLAN))

    assert document["client"] == "acme-treasury"
    assert document["feed"] == "daily_cash"
    assert document["format"] == "csv"
    fields = {field["source"]: field for field in document["fields"]}
    assert set(fields) == {column.source for column in CSV_PLAN.column_map}
    assert fields["DrCr"]["target"] is None
    assert fields["TradeRef"].keys() == {"source", "target", "dtype"}
    assert "%d/%m/%Y" in fields["ValueDate"]["transform"]
    assert "DrCr" in fields["Amount"]["transform"]
    assert "upper()" in fields["Ccy"]["transform"] and "USD" in fields["Ccy"]["transform"]


def test_render_all_returns_three_documents() -> None:
    pipeline_py, dag_py, mapping_yaml = tpl.render_all(JSONL_PLAN)
    assert "def extract" in pipeline_py and "PythonOperator" in dag_py
    assert yaml.safe_load(mapping_yaml)["format"] == "jsonl"


# --------------------------------------------------------------------------- #
# inject_defect                                                                #
# --------------------------------------------------------------------------- #


def inject_and_run(plan: IngestionPlan, sample: str, defect: str, tmp_path: Path, encoding="utf-8"):
    pipeline_py, dag_py = tpl.inject_defect(tpl.render_pipeline(plan), tpl.render_dag(plan), defect)
    module = load_module(pipeline_py)
    path = tmp_path / "sample.dat"
    path.write_text(sample, encoding=encoding, newline="\n")
    return module.transform(module.extract(str(path)))


def test_defect_date_format_swapped(tmp_path: Path) -> None:
    rows = inject_and_run(CSV_PLAN, CSV_SAMPLE, "date_format_swapped", tmp_path)
    assert rows[0]["value_date"] == "2026-03-09", "day and month read the American way"


def test_defect_trailer_not_skipped(tmp_path: Path) -> None:
    rows = inject_and_run(CSV_PLAN, CSV_SAMPLE, "trailer_not_skipped", tmp_path)
    assert len(rows) == 3 and rows[2]["trade_id"] == "TOTAL"


def test_defect_wrong_slice(tmp_path: Path) -> None:
    rows = inject_and_run(FW_PLAN, FW_SAMPLE, "wrong_slice", tmp_path, encoding="latin-1")
    assert rows[0]["currency"] == "REU", "currency slice shifted one character left"


def test_defect_amount_sign_dropped(tmp_path: Path) -> None:
    rows = inject_and_run(CSV_PLAN, CSV_SAMPLE, "amount_sign_dropped", tmp_path)
    assert rows[0]["amount"] == "1234.50", "DR row is no longer negative"


def test_defect_thousands_separator_kept(tmp_path: Path) -> None:
    with pytest.raises(decimal.InvalidOperation):
        inject_and_run(CSV_PLAN, CSV_SAMPLE, "thousands_separator_kept", tmp_path)


def test_defect_dag_missing_dependency(monkeypatch: pytest.MonkeyPatch) -> None:
    pipeline_py, dag_py = tpl.inject_defect(
        tpl.render_pipeline(CSV_PLAN), tpl.render_dag(CSV_PLAN), "dag_missing_dependency"
    )
    assert pipeline_py == tpl.render_pipeline(CSV_PLAN)
    dag = run_dag(monkeypatch, dag_py, pipeline_py)
    assert dag.edges == [("extract", "transform")]


def test_injected_code_still_looks_plausible() -> None:
    pipeline_py = tpl.render_pipeline(CSV_PLAN)
    for defect in tpl.DEFECT_IDS - {"dag_missing_dependency", "wrong_slice"}:
        edited, _ = (
            tpl.inject_defect(pipeline_py, "", defect)
            if defect != "dag_missing_dependency"
            else (
                pipeline_py,
                "",
            )
        )
        ast.parse(edited)
        assert defect not in edited, "the defect id must not be advertised in the code"


def test_inject_defect_unknown_id() -> None:
    with pytest.raises(ProviderError, match="unknown defect id"):
        tpl.inject_defect("x", "y", "bogus")


@pytest.mark.parametrize(
    ("plan", "defect"),
    [
        (CSV_PLAN, "wrong_slice"),
        (JSONL_PLAN, "trailer_not_skipped"),
        (JSONL_PLAN, "amount_sign_dropped"),
        (JSONL_PLAN, "date_format_swapped"),
    ],
)
def test_inject_defect_not_applicable(plan: IngestionPlan, defect: str) -> None:
    with pytest.raises(ProviderError, match="not applicable"):
        tpl.inject_defect(tpl.render_pipeline(plan), tpl.render_dag(plan), defect)


def test_inject_defect_dag_not_applicable() -> None:
    with pytest.raises(ProviderError, match="not applicable"):
        tpl.inject_defect("", "extract >> transform\n", "dag_missing_dependency")


def test_inject_defect_thousands_marker_missing() -> None:
    with pytest.raises(ProviderError, match="not applicable"):
        tpl.inject_defect("def f():\n    return 1\n", "", "thousands_separator_kept")
