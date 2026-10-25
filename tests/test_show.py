from collections.abc import Iterator
from pathlib import Path

import duckdb
import pytest
from typer.testing import CliRunner

from l2c.cli import app
from l2c.dbt_runner import preview_table


@pytest.fixture
def preview_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    database = tmp_path / "test.duckdb"
    monkeypatch.setenv("L2C_DB_PATH", str(database))
    connection = duckdb.connect(str(database), config={"autoinstall_known_extensions": False})
    try:
        connection.execute("CREATE SCHEMA marts")
        connection.execute(
            "CREATE TABLE marts.exceptions (record_id VARCHAR, check_id VARCHAR, details VARCHAR)"
        )
        connection.executemany(
            "INSERT INTO marts.exceptions VALUES (?,?,?)",
            [
                (
                    "PLANT-R04" if index == 90 else f"PLANT-SHOW-{index:03d}",
                    "R1" if index == 90 else "A4",
                    "safe; value" if index == 90 else "synthetic",
                )
                for index in range(120)
            ],
        )
    finally:
        connection.close()
    yield database


def test_where_filters_before_the_fifty_row_limit_and_matches_the_cli_example(
    preview_db: Path,
) -> None:
    assert len(preview_table("exceptions").rows) == 50
    filtered = preview_table("exceptions", where="record_id like '%R04%'")
    assert filtered.rows == [("PLANT-R04", "R1", "safe; value")]
    assert filtered == preview_table("marts.exceptions", where="record_id like '%R04%'")
    result = CliRunner().invoke(app, ["show", "exceptions", "--where", "record_id like '%R04%'"])
    assert result.exit_code == 0, result.output
    assert "PLANT-R04" in result.output and "PLANT-SHOW" not in result.output


def test_where_accepts_sql_expressions_semicolons_in_literals_and_empty_results(
    preview_db: Path,
) -> None:
    assert preview_table("exceptions", where="details = 'safe; value'").rows[0][0] == "PLANT-R04"
    assert len(preview_table("exceptions", where="check_id = 'A4'").rows) == 50
    assert preview_table("exceptions", where="record_id = 'no-such-id'").rows == []


@pytest.mark.parametrize(
    "where",
    [
        "record_id like",
        "true); DROP TABLE marts.exceptions; --",
        "true; DELETE FROM marts.exceptions",
        "missing_column = 1",
    ],
)
def test_invalid_filters_are_clear_errors_and_cannot_mutate_data(
    preview_db: Path, where: str
) -> None:
    with pytest.raises(ValueError, match="Invalid --where filter"):
        preview_table("exceptions", where=where)
    result = CliRunner().invoke(app, ["show", "exceptions", "--where", where])
    assert result.exit_code == 1 and "Invalid --where filter" in result.output
    assert preview_table("exceptions", where="record_id = 'PLANT-R04'").rows == [
        ("PLANT-R04", "R1", "safe; value")
    ]


def test_filters_cannot_read_external_files(preview_db: Path, tmp_path: Path) -> None:
    path = tmp_path / "private.txt"
    path.write_text("synthetic private text", encoding="utf-8")
    literal = str(path).replace("'", "''")
    with pytest.raises(ValueError, match="Invalid --where filter"):
        preview_table("exceptions", where=f"EXISTS (SELECT 1 FROM read_text('{literal}'))")
