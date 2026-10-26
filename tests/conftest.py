"""Share the four built export formats across database and output contract tests."""

from pathlib import Path

import duckdb
import pytest

from l2c.config import load_mapping
from l2c.dbt_runner import build_models
from l2c.generate import generate_data
from l2c.generate.writer import write_files
from l2c.load import load_files
from l2c.paths import CONFIG_DIR
from l2c.pipeline import run_pipeline


def _manifest(database: Path) -> list[tuple]:
    connection = duckdb.connect(
        str(database), read_only=True, config={"autoinstall_known_extensions": False}
    )
    try:
        return connection.execute("SELECT * FROM state.run_manifest ORDER BY 1,2").fetchall()
    finally:
        connection.close()


@pytest.fixture(scope="session")
def pipeline_db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    directory = tmp_path_factory.mktemp("pipeline")
    database = directory / "test.duckdb"
    result = run_pipeline(
        seed=42,
        mapping_path=CONFIG_DIR / "mapping.yml",
        raw_dir=directory / "raw",
        output_dir=directory / "out",
        db_path=database,
        artifact_dir=directory,
    )
    assert result.report.html_path.is_file()
    assert result.report.workbook_path.is_file()
    assert result.proposals.path.is_file()
    return database


@pytest.fixture(scope="session")
def built(tmp_path_factory: pytest.TempPathFactory, pipeline_db: Path) -> dict[str, Path]:
    tables = generate_data(seed=42).tables
    databases = {"default": pipeline_db}
    for format_name in ("ch", "de", "hubspot_ui"):
        directory = tmp_path_factory.mktemp(f"dbt-{format_name}")
        mapping_path = CONFIG_DIR / (
            "mapping.yml" if format_name == "default" else f"mapping.{format_name}.yml"
        )
        write_files(tables, load_mapping(mapping_path), directory / "raw", format_name=format_name)
        database = directory / "test.duckdb"
        load_files(mapping_path=mapping_path, raw_dir=directory / "raw", db_path=database)
        before = _manifest(database)
        result = build_models(mapping_path=mapping_path, db_path=database, artifact_dir=directory)
        assert result.nodes >= 148
        assert _manifest(database) == before
        databases[format_name] = database
    return databases
