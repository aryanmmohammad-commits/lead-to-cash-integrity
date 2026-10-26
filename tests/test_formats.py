"""Format equivalence and a complete large-profile smoke run."""

from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from l2c import cli
from l2c.dbt_runner import build_models
from l2c.load import load_files
from l2c.output_data import read_database as _connection
from l2c.report import write_report


def _freeze(value: Any) -> Any:
    return tuple(_freeze(item) for item in value) if isinstance(value, list) else value


def _semantic_snapshot(database: Path) -> dict[str, list[tuple]]:
    snapshot = {}
    with _connection(database) as connection:
        models = connection.execute(
            "SELECT table_schema, table_name FROM information_schema.tables "
            "WHERE table_schema IN ('staging','intermediate','marts') ORDER BY 1,2"
        ).fetchall()
        for schema, table in models:
            columns = connection.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema=? AND table_name=? ORDER BY ordinal_position",
                [schema, table],
            ).fetchall()
            names = [
                name
                for (name,) in columns
                if name not in ("loaded_at", "run_id", "source_file") and not name.endswith("__raw")
            ]
            select = ", ".join('"' + name.replace('"', '""') + '"' for name in names)
            rows = connection.execute(f'SELECT {select} FROM "{schema}"."{table}"').fetchall()
            snapshot[f"{schema}.{table}"] = sorted(
                [tuple(_freeze(item) for item in row) for row in rows], key=repr
            )
    return snapshot


@pytest.mark.parametrize("format_name", ["ch", "de", "hubspot_ui"])
def test_all_four_formats_produce_identical_staged_and_matched_results(
    format_name: str,
    built: dict[str, Path],
) -> None:
    assert _semantic_snapshot(built[format_name]) == _semantic_snapshot(built["default"])


def test_large_profile_scale_ten_completes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "test.duckdb"
    monkeypatch.setenv("L2C_DB_PATH", str(database))
    monkeypatch.delenv("L2C_MAPPING", raising=False)
    raw_dir = tmp_path / "raw"
    result = CliRunner().invoke(
        cli.app,
        ["generate", "--seed", "42", "--profile", "large", "--scale", "10",
         "--output-dir", str(raw_dir)],
    )
    assert result.exit_code == 0, result.output
    load_files(raw_dir=raw_dir)
    build_models(artifact_dir=tmp_path)
    report = write_report(output_dir=tmp_path / "out")
    assert report.html_path.is_file() and report.workbook_path.is_file()
    with _connection(database) as connection:
        assert connection.execute(
            "SELECT count(*) FROM staging.stg_hubspot__deals WHERE deal_id LIKE 'BG-%'"
        ).fetchone() == (500,)
        assert connection.execute(
            "SELECT record_id FROM marts.quarantine "
            "WHERE reason='overlapping_order_versions' ORDER BY record_id"
        ).fetchall() == [("PLANT-O-B02:1",), ("PLANT-O-B02:2",)]
