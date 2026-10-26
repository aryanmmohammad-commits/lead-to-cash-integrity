"""Two real CLI runs must replace raw data and preserve the same findings."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from l2c import cli
from l2c.output_data import read_database


def test_run_twice_has_identical_exceptions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "test.duckdb"
    monkeypatch.setenv("L2C_DB_PATH", str(database))
    monkeypatch.delenv("L2C_MAPPING", raising=False)
    arguments = [
        "run", "--seed", "42", "--raw-dir", str(tmp_path / "raw"),
        "--output-dir", str(tmp_path / "out"),
    ]
    snapshots = []
    for _ in range(2):
        result = CliRunner().invoke(cli.app, arguments)
        assert result.exit_code == 0, result.output
        assert "Pipeline complete" in result.output
        for name in ("report.html", "review.xlsx", "fix_proposals.csv"):
            assert (tmp_path / "out" / name).is_file()
        with read_database(database) as connection:
            snapshots.append(
                connection.execute(
                    "SELECT * FROM marts.exceptions ORDER BY check_id, object_type, record_id"
                ).fetchall()
            )
    assert snapshots[0]
    assert snapshots[1] == snapshots[0]
