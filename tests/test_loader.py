import csv
import hashlib
import io
import json
import shutil
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import duckdb
import pytest
import yaml
from typer.testing import CliRunner

import l2c.load as loader
from l2c import cli
from l2c.config import load_mapping, load_rules
from l2c.generate import generate_data
from l2c.generate.writer import write_files
from l2c.load import LoadError, SanityGateError, load_files
from l2c.logging_setup import setup_logging
from l2c.paths import CONFIG_DIR


@pytest.fixture(scope="module")
def exports(tmp_path_factory: pytest.TempPathFactory) -> Path:
    directory = tmp_path_factory.mktemp("loader-exports")
    write_files(generate_data(seed=42).tables, load_mapping(CONFIG_DIR / "mapping.yml"), directory)
    return directory


@pytest.fixture
def isolated(tmp_path: Path, exports: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    directory = tmp_path / "raw"
    shutil.copytree(exports, directory)
    database = tmp_path / "nested" / "test.duckdb"
    monkeypatch.setenv("L2C_DB_PATH", str(database))
    monkeypatch.delenv("L2C_MAPPING", raising=False)
    return directory, database


@pytest.fixture(autouse=True)
def step_logs() -> Iterator[io.StringIO]:
    stream = io.StringIO()
    logger = setup_logging(stream=stream)
    try:
        yield stream
    finally:
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)
            handler.close()


@contextmanager
def _read_db(database: Path) -> Iterator[duckdb.DuckDBPyConnection]:
    # A read-only reopen also detects leaked writable connections on Windows.
    connection = duckdb.connect(str(database), read_only=True)
    try:
        yield connection
    finally:
        connection.close()


def _quote(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _raw_snapshot(database: Path) -> dict[str, Counter]:
    with _read_db(database) as connection:
        tables = connection.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'raw'"
        ).fetchall()
        return {
            table: Counter(
                connection.execute(
                    f"SELECT * EXCLUDE (loaded_at, run_id, source_file) FROM raw.{_quote(table)}"
                ).fetchall()
            )
            for (table,) in tables
        }


def _cut_deals(directory: Path) -> int:
    path = directory / "hubspot_deals.csv"
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.reader(stream)
        header = next(reader)
        rows = list(reader)
    remaining = len(rows) // 2
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(header)
        writer.writerows(rows[:remaining])
    return remaining


def _small_export(tmp_path: Path, rows: int) -> tuple[Path, Path]:
    directory = tmp_path / "small"
    directory.mkdir(exist_ok=True)
    mapping = {
        "sample": {
            "file": "sample.csv",
            "format": {
                "delimiter": ",",
                "encoding": "utf-8-sig",
                "date_format": "%Y-%m-%d",
                "decimal": ".",
                "thousands": "",
            },
            "columns": {"record_id": "Record ID", "value": "Raw Value"},
        }
    }
    path = tmp_path / "mapping.yml"
    path.write_text(yaml.safe_dump(mapping), encoding="utf-8")
    with (directory / "sample.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["Record ID", "Raw Value"])
        writer.writerows([(str(index).zfill(5), "n/a") for index in range(rows)])
    return directory, path


def test_load_twice_replaces_every_table_without_duplicate_ids(isolated: tuple[Path, Path]) -> None:
    directory, database = isolated
    before = {path.name: path.read_bytes() for path in directory.glob("*.csv")}
    first = load_files(raw_dir=directory, run_id="first")
    snapshot = _raw_snapshot(database)
    second = load_files(raw_dir=directory, run_id="second")
    assert first.row_counts == second.row_counts
    assert _raw_snapshot(database) == snapshot
    assert {path.name: path.read_bytes() for path in directory.glob("*.csv")} == before
    primary_keys = yaml.safe_load(
        (Path(__file__).parent / "planted_cases.yml").read_text(encoding="utf-8")
    )["primary_keys"]
    mapping = load_mapping(CONFIG_DIR / "mapping.yml")
    with _read_db(database) as connection:
        for table, table_mapping in mapping.tables.items():
            identifiers = ", ".join(
                _quote(table_mapping.columns[key]) for key in primary_keys[table]
            )
            ids = connection.execute(f"SELECT {identifiers} FROM raw.{_quote(table)}").fetchall()
            assert len(ids) == len(set(ids)) == second.row_counts[table]
            assert connection.execute(
                f"SELECT DISTINCT run_id FROM raw.{_quote(table)}"
            ).fetchall() == [("second",)]
        assert connection.execute(
            "SELECT run_id, status, count(*) FROM state.run_manifest GROUP BY ALL ORDER BY run_id"
        ).fetchall() == [("first", "success", 12), ("second", "success", 12)]
        rows = connection.execute(
            'SELECT "table", file_sha256, source_file, row_count '
            "FROM state.run_manifest WHERE run_id = ?",
            ["second"],
        ).fetchall()
        for table, checksum, filename, row_count in rows:
            path = directory / mapping.tables[table].file
            assert checksum == hashlib.sha256(path.read_bytes()).hexdigest()
            assert filename == str(path.resolve())
            assert row_count == second.row_counts[table]


def test_halved_source_is_blocked_and_failed_runs_never_become_baselines(
    isolated: tuple[Path, Path],
) -> None:
    directory, database = isolated
    first = load_files(raw_dir=directory, run_id="baseline")
    before = _raw_snapshot(database)
    remaining = _cut_deals(directory)
    for run_id in ("blocked", "blocked-again"):
        with pytest.raises(
            SanityGateError, match="hubspot_deals.*sanity_max_drop_pct=20%"
        ) as error:
            load_files(raw_dir=directory, run_id=run_id)
        assert error.value.run_id == run_id
        assert f"{first.row_counts['hubspot_deals']} -> {remaining} rows" in str(error.value)
        assert "--force" in str(error.value)
        assert _raw_snapshot(database) == before
        with _read_db(database) as connection:
            assert connection.execute(
                "SELECT DISTINCT run_id FROM raw.hubspot_deals"
            ).fetchall() == [(first.run_id,)]
            assert (
                connection.execute(
                    "SELECT count(*) FROM state.run_manifest WHERE run_id = ? AND status = ?",
                    [run_id, "failed"],
                ).fetchone()[0]
                == 12
            )
            assert (
                connection.execute(
                    'SELECT row_count FROM state.run_manifest WHERE run_id = ? AND "table" = ?',
                    [run_id, "hubspot_deals"],
                ).fetchone()[0]
                == remaining
            )


def test_force_logs_warning_and_establishes_a_new_successful_baseline(
    isolated: tuple[Path, Path],
    step_logs: io.StringIO,
) -> None:
    directory, database = isolated
    load_files(raw_dir=directory, run_id="baseline")
    remaining = _cut_deals(directory)
    forced = load_files(raw_dir=directory, run_id="forced", force=True)
    assert forced.row_counts["hubspot_deals"] == remaining
    assert load_files(raw_dir=directory).row_counts == forced.row_counts
    logs = [json.loads(line) for line in step_logs.getvalue().splitlines()]
    warnings = [line for line in logs if line["status"] == "warning"]
    assert len(warnings) == 1
    assert warnings[0]["run_id"] == "forced"
    assert "--force" in warnings[0]["step"] and "hubspot_deals" in warnings[0]["step"]
    with _read_db(database) as connection:
        assert connection.execute(
            "SELECT DISTINCT status FROM state.run_manifest WHERE run_id = 'forced'"
        ).fetchall() == [("success",)]


@pytest.mark.parametrize(
    ("tolerance", "remaining", "blocked"),
    [
        (0.0, 4, True),
        (20.0, 4, False),
        (20.0, 3, True),
        (100.0, 0, False),
    ],
)
def test_sanity_gate_uses_configured_threshold_and_strict_boundary(
    tolerance: float,
    remaining: int,
    blocked: bool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory, mapping = _small_export(tmp_path, 5)
    database = tmp_path / "test.duckdb"
    monkeypatch.setenv("L2C_DB_PATH", str(database))
    rules = load_rules().model_copy(update={"sanity_max_drop_pct": tolerance})
    load_files(mapping_path=mapping, raw_dir=directory, rules=rules)
    _small_export(tmp_path, remaining)
    if blocked:
        with pytest.raises(SanityGateError):
            load_files(mapping_path=mapping, raw_dir=directory, rules=rules)
    else:
        assert load_files(mapping_path=mapping, raw_dir=directory, rules=rules).row_counts == {
            "sample": remaining
        }


def test_zero_baseline_and_header_only_files_are_valid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory, mapping = _small_export(tmp_path, 0)
    monkeypatch.setenv("L2C_DB_PATH", str(tmp_path / "test.duckdb"))
    assert load_files(mapping_path=mapping, raw_dir=directory).row_counts == {"sample": 0}
    _small_export(tmp_path, 3)
    assert load_files(mapping_path=mapping, raw_dir=directory).row_counts == {"sample": 3}


@pytest.mark.parametrize("format_name", ["default", "ch", "de", "hubspot_ui"])
def test_every_format_stays_untouched_text_in_raw(
    format_name: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mapping_path = CONFIG_DIR / (
        "mapping.yml" if format_name == "default" else f"mapping.{format_name}.yml"
    )
    mapping = load_mapping(mapping_path)
    directory = tmp_path / "raw"
    write_files(generate_data(seed=42).tables, mapping, directory, format_name=format_name)
    database = tmp_path / "test.duckdb"
    monkeypatch.setenv("L2C_DB_PATH", str(database))
    load_files(mapping_path=mapping_path, raw_dir=directory)
    actual = _raw_snapshot(database)
    with _read_db(database) as connection:
        for table, spec in mapping.tables.items():
            path = directory / spec.file
            with path.open(encoding=spec.format.encoding, newline="") as stream:
                reader = csv.reader(stream, delimiter=spec.format.delimiter)
                header = next(reader)
                expected = Counter(tuple(row) for row in reader)
            assert actual[table] == expected
            columns = connection.execute(f"DESCRIBE raw.{_quote(table)}").fetchall()
            assert [column[0] for column in columns] == [
                *header,
                "loaded_at",
                "run_id",
                "source_file",
            ]
            assert all(column[1] == "VARCHAR" for column in columns[:-3])


def test_extra_columns_dirty_values_and_duplicate_ids_are_not_normalized(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory, mapping = _small_export(tmp_path, 0)
    rows = [
        ("00001", " n/a ", 'Müller; "quoted"\r\nZürich', "1.23457E+11"),
        ("00001", "", "NULL", "1.200,50"),
        ("00002", "NA", "null", "1'200.50"),
    ]
    with (directory / "sample.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["Record ID", "Raw Value", 'Unmapped "note"', "select"])
        writer.writerows(rows)
    database = tmp_path / "test.duckdb"
    monkeypatch.setenv("L2C_DB_PATH", str(database))
    result = load_files(mapping_path=mapping, raw_dir=directory)
    assert result.row_counts == {"sample": 3}
    assert _raw_snapshot(database)["sample"] == Counter(rows)


@pytest.mark.parametrize("failure", ["missing", "bad_width", "duplicate_header", "reserved_header"])
def test_structural_failures_preserve_previous_raw_and_record_failed_manifest(
    failure: str,
    isolated: tuple[Path, Path],
) -> None:
    directory, database = isolated
    load_files(raw_dir=directory, run_id="baseline")
    before = _raw_snapshot(database)
    path = directory / "hubspot_deals.csv"
    if failure == "missing":
        path.unlink()
    elif failure == "bad_width":
        with path.open(encoding="utf-8-sig", newline="") as stream:
            header = next(csv.reader(stream))
        with path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(header)
            writer.writerow(["only-one-column"])
    else:
        text = {
            "duplicate_header": "hs_object_id,hs_object_id\n1,2\n",
            "reserved_header": "hs_object_id,run_id\n1,2\n",
        }[failure]
        path.write_text(text, encoding="utf-8-sig")
    with pytest.raises(LoadError, match="hubspot_deals"):
        load_files(raw_dir=directory, run_id="broken", force=True)
    assert _raw_snapshot(database) == before
    with _read_db(database) as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM state.run_manifest "
                "WHERE run_id = 'broken' AND status = 'failed'"
            ).fetchone()[0]
            == 12
        )
        checksum, count = connection.execute(
            "SELECT file_sha256, row_count FROM state.run_manifest "
            "WHERE run_id = 'broken' AND \"table\" = 'hubspot_deals'"
        ).fetchone()
        assert count is None
        assert checksum == (
            None if failure == "missing" else hashlib.sha256(path.read_bytes()).hexdigest()
        )


def test_late_database_failure_rolls_back_all_replacements(
    isolated: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory, database = isolated
    load_files(raw_dir=directory, run_id="baseline")
    before = _raw_snapshot(database)
    replace = loader._replace_table

    def fail_last(
        connection: duckdb.DuckDBPyConnection,
        source: loader._Source,
        run_id: str,
        loaded_at: datetime,
    ) -> None:
        if source.table == "ref_product_catalog":
            raise duckdb.IOException("simulated late database failure")
        replace(connection, source, run_id, loaded_at)

    monkeypatch.setattr(loader, "_replace_table", fail_last)
    with pytest.raises(LoadError, match="simulated late database failure"):
        load_files(raw_dir=directory, run_id="failed-write")
    assert _raw_snapshot(database) == before
    with _read_db(database) as connection:
        assert connection.execute(
            "SELECT DISTINCT run_id FROM raw.hubspot_companies"
        ).fetchall() == [("baseline",)]
        assert (
            connection.execute(
                "SELECT count(*) FROM state.run_manifest "
                "WHERE run_id = 'failed-write' AND status = 'failed'"
            ).fetchone()[0]
            == 12
        )


def test_reusing_a_run_id_cannot_overwrite_history(isolated: tuple[Path, Path]) -> None:
    directory, database = isolated
    load_files(raw_dir=directory, run_id="unique")
    with pytest.raises(LoadError, match="already recorded"):
        load_files(raw_dir=directory, run_id="unique", force=True)
    with _read_db(database) as connection:
        assert connection.execute("SELECT count(*) FROM state.run_manifest").fetchone()[0] == 12
        assert connection.execute("SELECT DISTINCT status FROM state.run_manifest").fetchall() == [
            ("success",)
        ]


def test_cli_mapping_override_gate_and_force(
    isolated: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory, _ = isolated
    monkeypatch.setattr(cli, "RAW_DIR", directory)
    runner = CliRunner()
    first = runner.invoke(cli.app, ["load", "--mapping", str(CONFIG_DIR / "mapping.yml")])
    assert first.exit_code == 0, first.output
    assert "Loaded 12 tables" in first.output
    _cut_deals(directory)
    blocked = runner.invoke(cli.app, ["load"])
    assert blocked.exit_code == 1
    assert "Sanity gate stopped" in blocked.output and "hubspot_deals" in blocked.output
    forced = runner.invoke(cli.app, ["load", "--force"])
    assert forced.exit_code == 0, forced.output
    assert '"status": "warning"' in forced.output


def test_mapping_environment_selects_a_custom_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory, mapping = _small_export(tmp_path, 2)
    monkeypatch.setenv("L2C_DB_PATH", str(tmp_path / "test.duckdb"))
    monkeypatch.setenv("L2C_MAPPING", str(mapping))
    monkeypatch.setattr(cli, "RAW_DIR", directory)
    result = CliRunner().invoke(cli.app, ["load"])
    assert result.exit_code == 0, result.output
    assert "Loaded 1 tables (2 rows)" in result.output
