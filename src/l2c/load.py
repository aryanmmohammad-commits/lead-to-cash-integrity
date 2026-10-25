"""Load untouched CSV text into DuckDB, with atomic replacement and an audit trail."""

import csv
import hashlib
import io
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from time import perf_counter
from uuid import uuid4

import duckdb
import pandas as pd

from l2c.config import MappingConfig, RulesConfig, TableMapping, load_mapping, load_rules
from l2c.logging_setup import log_step, setup_logging
from l2c.paths import RAW_DIR, get_db_path, resolve_repo_path


class LoadError(ValueError):
    """A load attempt failed; run_id identifies its manifest entries."""

    def __init__(self, message: str, *, run_id: str) -> None:
        super().__init__(f"Load run {run_id} failed: {message}")
        self.run_id = run_id


class SanityGateError(LoadError):
    """One or more source row counts dropped beyond the configured tolerance."""


@dataclass
class _Source:
    table: str
    path: Path
    file_sha256: str | None = None
    headers: tuple[str, ...] = ()
    rows: list[tuple[str, ...]] = field(default_factory=list)
    row_count: int | None = None


@dataclass(frozen=True)
class LoadResult:
    run_id: str
    row_counts: dict[str, int]
    loaded_at: datetime


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _ensure_manifest(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute("CREATE SCHEMA IF NOT EXISTS state")
    connection.execute("""
        CREATE TABLE IF NOT EXISTS state.run_manifest (
            run_id VARCHAR NOT NULL,
            "table" VARCHAR NOT NULL,
            source_file VARCHAR NOT NULL,
            file_sha256 VARCHAR,
            row_count BIGINT,
            loaded_at TIMESTAMPTZ NOT NULL,
            status VARCHAR NOT NULL,
            PRIMARY KEY (run_id, "table")
        )
    """)


def _last_successful_counts(connection: duckdb.DuckDBPyConnection) -> dict[str, int]:
    rows = connection.execute("""
        SELECT "table", row_count
        FROM state.run_manifest
        WHERE status = 'success'
        QUALIFY row_number() OVER (
            PARTITION BY "table" ORDER BY loaded_at DESC, run_id DESC
        ) = 1
    """).fetchall()
    return dict(rows)


def _read_source(source: _Source, mapping: TableMapping) -> None:
    contents = source.path.read_bytes()
    source.file_sha256 = hashlib.sha256(contents).hexdigest()
    text = contents.decode(mapping.format.encoding)
    reader = csv.reader(
        io.StringIO(text, newline=""), delimiter=mapping.format.delimiter, strict=True
    )
    header = next(reader, None)
    if not header or any(column == "" for column in header):
        raise ValueError("CSV must have a nonempty header for every column")
    normalized = [column.casefold() for column in header]
    if len(normalized) != len(set(normalized)):
        raise ValueError("duplicate CSV headers cannot be preserved in DuckDB")
    reserved = set(normalized) & {"loaded_at", "run_id", "source_file"}
    if reserved:
        raise ValueError(f"CSV headers collide with load metadata: {', '.join(sorted(reserved))}")
    missing = set(mapping.columns.values()) - set(header)
    if missing:
        raise ValueError(f"mapped source columns are missing: {', '.join(sorted(missing))}")
    source.headers = tuple(header)
    for row in reader:
        if len(row) != len(header):
            raise ValueError(
                f"CSV line {reader.line_num}: expected {len(header)} columns, got {len(row)}"
            )
        source.rows.append(tuple(row))
    source.row_count = len(source.rows)


def _read_sources(sources: list[_Source], mapping: MappingConfig) -> list[str]:
    errors = []
    for source in sources:
        try:
            _read_source(source, mapping.tables[source.table])
        except (OSError, UnicodeError, LookupError, csv.Error, ValueError) as exc:
            errors.append(f"{source.table} ({source.path}): {exc}")
    return errors


def _sanity_drops(
    sources: list[_Source], baseline: dict[str, int], tolerance: float
) -> list[tuple[_Source, str]]:
    drops = []
    for source in sources:
        previous = baseline.get(source.table)
        current = source.row_count
        if previous is None or previous == 0 or current is None:
            continue
        lost = previous - current
        if Decimal(lost) * 100 > Decimal(str(tolerance)) * previous:
            percentage = Decimal(lost) * 100 / previous
            message = (
                f"{source.table}: {previous} -> {current} rows "
                f"({percentage:.2f}% drop; sanity_max_drop_pct={tolerance:g}%)"
            )
            drops.append((source, message))
    return drops


def _write_manifest(
    connection: duckdb.DuckDBPyConnection,
    sources: list[_Source],
    run_id: str,
    loaded_at: datetime,
    status: str,
) -> None:
    connection.executemany(
        "INSERT INTO state.run_manifest "
        '(run_id, "table", source_file, file_sha256, row_count, loaded_at, status) '
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (
                run_id,
                source.table,
                str(source.path),
                source.file_sha256,
                source.row_count,
                loaded_at,
                status,
            )
            for source in sources
        ],
    )


def _replace_table(
    connection: duckdb.DuckDBPyConnection, source: _Source, run_id: str, loaded_at: datetime
) -> None:
    # dtype=object prevents pandas from interpreting IDs, empty strings, or dirty values.
    frame = pd.DataFrame(source.rows, columns=source.headers, dtype=object)
    connection.register("_l2c_csv_source", frame)
    columns = ", ".join(
        f"CAST({_quote(column)} AS VARCHAR) AS {_quote(column)}" for column in source.headers
    )
    try:
        connection.execute(
            f"CREATE OR REPLACE TABLE raw.{_quote(source.table)} AS "
            f"SELECT {columns}, ?::TIMESTAMPTZ AS loaded_at, ?::VARCHAR AS run_id, "
            "?::VARCHAR AS source_file FROM _l2c_csv_source",
            [loaded_at, run_id, str(source.path)],
        )
    finally:
        connection.unregister("_l2c_csv_source")


def _apply_load(
    connection: duckdb.DuckDBPyConnection,
    sources: list[_Source],
    run_id: str,
    loaded_at: datetime,
) -> None:
    connection.execute("BEGIN TRANSACTION")
    try:
        connection.execute("CREATE SCHEMA IF NOT EXISTS raw")
        for source in sources:
            _replace_table(connection, source, run_id, loaded_at)
        _write_manifest(connection, sources, run_id, loaded_at, "success")
        connection.execute("COMMIT")
    except Exception:
        connection.execute("ROLLBACK")
        raise


def _load(
    connection: duckdb.DuckDBPyConnection,
    sources: list[_Source],
    mapping: MappingConfig,
    rules: RulesConfig,
    *,
    run_id: str,
    loaded_at: datetime,
    force: bool,
    started: float,
) -> None:
    _ensure_manifest(connection)
    if connection.execute(
        "SELECT count(*) FROM state.run_manifest WHERE run_id = ?", [run_id]
    ).fetchone()[0]:
        raise LoadError("run_id is already recorded; use a new run_id", run_id=run_id)
    try:
        errors = _read_sources(sources, mapping)
        if errors:
            raise LoadError("; ".join(errors), run_id=run_id)
        drops = _sanity_drops(
            sources, _last_successful_counts(connection), rules.sanity_max_drop_pct
        )
        if drops and not force:
            raise SanityGateError(
                "Sanity gate stopped the load: "
                + "; ".join(message for _, message in drops)
                + ". Use --force to override after reviewing the source files.",
                run_id=run_id,
            )
        for source, message in drops:
            logging.getLogger("l2c").warning(
                message,
                extra={
                    "run_id": run_id,
                    "step": f"load.sanity_override --force: {message}",
                    "rows": source.row_count,
                    "seconds": perf_counter() - started,
                    "status": "warning",
                },
            )
        _apply_load(connection, sources, run_id, loaded_at)
    except Exception:
        _write_manifest(connection, sources, run_id, loaded_at, "failed")
        raise


def load_files(
    *,
    mapping_path: str | Path | None = None,
    raw_dir: Path = RAW_DIR,
    db_path: str | Path | None = None,
    force: bool = False,
    run_id: str | None = None,
    rules: RulesConfig | None = None,
) -> LoadResult:
    """Snapshot every mapped CSV, gate row counts, and commit the complete load together."""
    started = perf_counter()
    run_id = run_id or uuid4().hex
    loaded_at = datetime.now(UTC)
    connection = None
    result = None
    logger = logging.getLogger("l2c")
    if not logger.handlers:
        setup_logging()
    try:
        mapping = load_mapping(mapping_path)
        rules = rules or load_rules()
        raw_dir = resolve_repo_path(raw_dir)
        sources = [
            _Source(table, (raw_dir / spec.file).resolve())
            for table, spec in mapping.tables.items()
        ]
        database = resolve_repo_path(db_path) if db_path is not None else get_db_path()
        database.parent.mkdir(parents=True, exist_ok=True)
        connection = duckdb.connect(str(database), config={"autoinstall_known_extensions": False})
        _load(
            connection,
            sources,
            mapping,
            rules,
            run_id=run_id,
            loaded_at=loaded_at,
            force=force,
            started=started,
        )
        result = LoadResult(
            run_id, {source.table: len(source.rows) for source in sources}, loaded_at
        )
        return result
    except (duckdb.Error, OSError, UnicodeError, ValueError) as exc:
        if isinstance(exc, LoadError):
            raise
        raise LoadError(str(exc), run_id=run_id) from exc
    finally:
        if connection is not None:
            connection.close()
        log_step(
            run_id=run_id,
            step="load",
            rows=sum(result.row_counts.values()) if result is not None else None,
            seconds=perf_counter() - started,
            status="ok" if result is not None else "failed",
        )
