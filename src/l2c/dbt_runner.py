"""Offline dbt execution and read-only table previews, with closed DuckDB handles."""

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import uuid4

import duckdb

from l2c.config import RulesConfig, load_mapping, load_rules
from l2c.logging_setup import log_step
from l2c.paths import REPO_ROOT, get_db_path, resolve_repo_path

DBT_PROJECT_DIR = REPO_ROOT / "l2c_dbt"


class BuildError(ValueError):
    """dbt compilation, execution or output tests failed."""


@dataclass(frozen=True)
class BuildResult:
    run_id: str
    nodes: int


@dataclass(frozen=True)
class TablePreview:
    columns: list[str]
    rows: list[tuple[Any, ...]]


@contextmanager
def _dbt_environment(database: Path) -> Iterator[None]:
    values = {
        "L2C_DB_PATH": str(database),
        "DBT_SEND_ANONYMOUS_USAGE_STATS": "false",
        "DO_NOT_TRACK": "1",
    }
    previous = {key: os.environ.get(key) for key in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _invoke(arguments: list[str]) -> Any:
    # Import after disabling telemetry, and release dbt's cached adapters on every path.
    from dbt.adapters.duckdb.connections import DuckDBConnectionManager
    from dbt.adapters.factory import reset_adapters
    from dbt.cli.main import dbtRunner

    reset_adapters()
    try:
        return dbtRunner().invoke(arguments)
    finally:
        reset_adapters()
        DuckDBConnectionManager.close_all_connections()


def build_models(
    *,
    mapping_path: str | Path | None = None,
    db_path: str | Path | None = None,
    artifact_dir: Path | None = None,
    run_id: str | None = None,
    rules: RulesConfig | None = None,
) -> BuildResult:
    started = perf_counter()
    run_id = run_id or uuid4().hex
    result = None
    try:
        variables = {
            "rules": (rules or load_rules()).model_dump(mode="json"),
            "mapping": load_mapping(mapping_path).model_dump(mode="json"),
        }
        database = resolve_repo_path(db_path) if db_path is not None else get_db_path()
        if not database.is_file():
            raise BuildError(f"Database {database} does not exist; run l2c load first")
        artifacts = resolve_repo_path(artifact_dir) if artifact_dir is not None else DBT_PROJECT_DIR
        arguments = [
            "--no-send-anonymous-usage-stats",
            "--no-use-colors",
            "--quiet",
            "--no-partial-parse",
            "--log-path",
            str(artifacts / "logs"),
            "build",
            "--project-dir",
            str(DBT_PROJECT_DIR),
            "--profiles-dir",
            str(DBT_PROJECT_DIR),
            "--target-path",
            str(artifacts / "target"),
            "--vars",
            json.dumps(variables),
        ]
        # The loader closes its connections. This function opens none before invoking dbt.
        with _dbt_environment(database):
            invocation = _invoke(arguments)
        if not invocation.success:
            errors = [
                str(item.message)
                for item in getattr(invocation.result, "results", [])
                if getattr(item, "message", None) and str(item.status) not in ("success", "pass")
            ]
            message = str(invocation.exception) if invocation.exception else "; ".join(errors)
            raise BuildError(f"dbt build failed: {message or 'see dbt logs for details'}")
        result = BuildResult(run_id, len(getattr(invocation.result, "results", [])))
        return result
    finally:
        log_step(
            run_id=run_id,
            step="build",
            rows=None,
            seconds=perf_counter() - started,
            status="ok" if result is not None else "failed",
        )


def preview_table(
    table: str, *, db_path: str | Path | None = None, where: str | None = None
) -> TablePreview:
    database = resolve_repo_path(db_path) if db_path is not None else get_db_path()
    if not database.is_file():
        raise ValueError(f"Database {database} does not exist; run l2c load first")
    parts = table.split(".")
    if len(parts) not in (1, 2) or any(not part for part in parts):
        raise ValueError("Use a table name or schema.table")
    connection = duckdb.connect(
        str(database),
        read_only=True,
        config={"autoinstall_known_extensions": False, "enable_external_access": False},
    )
    try:
        query = (
            "SELECT table_schema, table_name FROM information_schema.tables WHERE table_name = ?"
        )
        parameters = [parts[-1]]
        if len(parts) == 2:
            query += " AND table_schema = ?"
            parameters.append(parts[0])
        candidates = connection.execute(query, parameters).fetchall()
        if not candidates:
            raise ValueError(f"Table {table!r} was not found")
        if len(candidates) != 1:
            raise ValueError(f"Table {table!r} is ambiguous; use schema.table")
        qualified = ".".join('"' + part.replace('"', '""') + '"' for part in candidates[0])
        try:
            relation = connection.sql(f"SELECT * FROM {qualified}")
            if where is not None:
                relation = relation.filter(where)
            relation = relation.limit(50)
            return TablePreview(relation.columns, relation.fetchall())
        except duckdb.Error as exc:
            raise ValueError(f"Invalid --where filter or table query: {exc}") from exc
    finally:
        connection.close()
