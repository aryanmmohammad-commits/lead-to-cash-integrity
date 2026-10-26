"""Read complete, consistent mart snapshots without changing the database."""

import calendar
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

import duckdb

from l2c.config import RulesConfig, load_rules
from l2c.paths import get_db_path, resolve_repo_path

Row = dict[str, Any]


@dataclass(frozen=True)
class Table:
    columns: tuple[str, ...]
    rows: list[Row]


@contextmanager
def read_database(db_path: str | Path | None = None) -> Iterator[duckdb.DuckDBPyConnection]:
    database = resolve_repo_path(db_path) if db_path is not None else get_db_path()
    if not database.is_file():
        raise ValueError(f"Database {database} does not exist; run l2c run first")
    connection = duckdb.connect(
        str(database),
        read_only=True,
        config={"autoinstall_known_extensions": False, "enable_external_access": False},
    )
    try:
        connection.execute("BEGIN TRANSACTION")
        yield connection
    except duckdb.Error as exc:
        raise ValueError(f"Cannot read built marts; run l2c build first: {exc}") from exc
    finally:
        connection.close()


def read_mart(connection: duckdb.DuckDBPyConnection, name: str) -> Table:
    if not name.isidentifier():
        raise ValueError("Invalid mart name")
    cursor = connection.execute(f'SELECT * FROM marts."{name}"')
    columns = tuple(column[0] for column in cursor.description)
    return Table(columns, [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()])


@contextmanager
def atomic_output(destination: Path) -> Iterator[Path]:
    """Replace an output only after its complete temporary file has been closed."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        dir=destination.parent, suffix=destination.suffix, delete=False
    ) as file:
        temporary = Path(file.name)
    try:
        yield temporary
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def chf(value: Decimal | int | float | None) -> str:
    return "not valued" if value is None else f"CHF {value:,.2f}"


def chf_whole(value: Decimal | int | float) -> str:
    return f"CHF {value:,.0f}"


def exception_priority(row: Row, rules: RulesConfig) -> tuple:
    ranks = {severity: index for index, severity in enumerate(rules.exception_severity_order)}
    amount = row["money_at_risk_chf"]
    return (
        amount is None,
        -amount if amount is not None else Decimal(0),
        ranks.get(row["severity"], len(ranks)),
        row["check_id"],
        row["record_id"],
    )


@dataclass(frozen=True)
class ReviewData:
    rules: RulesConfig
    month_end: date
    crm_arr: Decimal
    billing_arr: Decimal
    tables: dict[str, Table]
    owner_names: dict[str, str] = field(default_factory=dict)

    def owner_name(self, owner_id: str) -> str:
        if owner_id in self.owner_names:
            return self.owner_names[owner_id]
        if owner_id == self.rules.finance_owner_id:
            return "Finance"
        if owner_id == self.rules.unassigned_owner_id:
            return "Unassigned"
        return "Unknown owner"

    @property
    def gap(self) -> Decimal:
        return self.billing_arr - self.crm_arr

    @property
    def ranked_exceptions(self) -> list[Row]:
        return sorted(
            self.tables["exceptions"].rows, key=lambda row: exception_priority(row, self.rules)
        )


def read_review_data(
    db_path: str | Path | None = None, *, rules: RulesConfig | None = None
) -> ReviewData:
    rules = rules or load_rules()
    month_end = rules.as_of_date.replace(
        day=calendar.monthrange(rules.as_of_date.year, rules.as_of_date.month)[1]
    )
    with read_database(db_path) as connection:
        tables = {
            name: read_mart(connection, name)
            for name in (
                "audit_scorecard",
                "exceptions",
                "fix_proposals",
                "push_readiness",
                "arr_bridge",
                "quarantine",
            )
        }
        totals = [
            connection.execute(
                f"SELECT coalesce(sum(arr_chf),0) FROM marts.arr_{system}_monthly "
                "WHERE month_end = ?",
                [month_end],
            ).fetchone()[0]
            for system in ("crm", "billing")
        ]
        owner_names = dict(
            connection.execute("SELECT owner_id, name FROM staging.stg_hubspot__owners").fetchall()
        )
    bridge = tables["arr_bridge"].rows
    if any(row["month_end"] != month_end for row in bridge):
        raise ValueError("ARR bridge uses a different month; run l2c build with the current rules")
    if sum((row["amount_chf"] for row in bridge), Decimal(0)) != totals[1] - totals[0]:
        raise ValueError("ARR bridge does not reconcile to the monthly totals; run l2c build")
    for name, key in (
        ("audit_scorecard", lambda row: list(rules.check_catalog).index(row["check_id"])),
        ("fix_proposals", lambda row: row["proposal_id"]),
        (
            "push_readiness",
            lambda row: (
                rules.push_status_order.index(row["status"]),
                -row["days_since_contract_start"]
                if row["days_since_contract_start"] is not None
                else float("inf"),
                row["deal_id"],
            ),
        ),
        ("arr_bridge", lambda row: rules.arr_bridge_categories.index(row["category"])),
        (
            "quarantine",
            lambda row: (row["reason"], row["source_table"], row["record_id"], row["column"]),
        ),
    ):
        table = tables[name]
        tables[name] = Table(table.columns, sorted(table.rows, key=key))
    return ReviewData(rules, month_end, totals[0], totals[1], tables, owner_names)


def scorecard_summary(data: ReviewData) -> str:
    scores = data.tables["audit_scorecard"].rows
    failing = sum(row["rows_failed"] > 0 for row in scores)
    return (
        f"{len(scores)} checks; {failing} with findings; {len(scores) - failing} without findings"
    )
