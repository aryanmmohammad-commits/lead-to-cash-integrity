"""Period, rounding and FX edges in a small offline database."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest

from l2c.config import load_mapping, load_rules
from l2c.dbt_runner import build_models
from l2c.generate import generate_data
from l2c.generate.model import Dataset, FixtureBuilder
from l2c.generate.writer import write_files
from l2c.load import load_files


@pytest.fixture(scope="module")
def edge_db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    directory = tmp_path_factory.mktemp("arr-edges")
    mapping = load_mapping()
    rules = load_rules().model_copy(update={"as_of_date": date(2026, 10, 15), "arr_months": 3})
    data: Dataset = {name: [] for name in mapping.tables}
    baseline = generate_data().tables
    for table in ("hubspot_owners", "ref_fx_rates", "ref_product_catalog"):
        data[table] = baseline[table]
    builder = FixtureBuilder(data, rules, "PLANT-EDGE-PRECISION")
    precision = builder.bundle(amount=Decimal("0.01"), start=date(2026, 8, 1))
    assert precision.charge is not None and precision.order is not None
    precision.charge.update(
        mrr=Decimal("0.000416666667"), quantity=5, effective_end=date(2026, 10, 31)
    )
    second = dict(precision.charge)
    second.update(charge_id="PLANT-EDGE-SECOND", effective_end=date(2026, 9, 30))
    data["younium_order_charges"].append(second)
    for kind in ("One-off", "Usage"):
        ignored = dict(precision.charge)
        ignored.update(charge_id=f"PLANT-EDGE-{kind}", charge_type=kind, mrr=Decimal("1000"))
        data["younium_order_charges"].append(ignored)
    draft = dict(precision.order)
    draft.update(version=2, status="Draft")
    data["younium_orders"].append(draft)
    cancelled = FixtureBuilder(data, rules, "PLANT-EDGE-CANCELLED").bundle(
        start=date(2026, 8, 1), status="Cancelled"
    )
    assert cancelled.order is not None
    cancelled.order["cancellation_date"] = date(2026, 9, 30)
    FixtureBuilder(data, rules, "PLANT-EDGE-LATE-FX").bundle(start=date(2026, 8, 1), currency="GBP")
    data["ref_fx_rates"].append(
        {"currency": "GBP", "date": date(2026, 9, 1), "rate_to_chf": Decimal("1.10")}
    )
    write_files(data, mapping, directory / "raw")
    database = directory / "test.duckdb"
    load_files(raw_dir=directory / "raw", db_path=database)
    build_models(db_path=database, artifact_dir=directory, rules=rules)
    return database


def _query(database: Path, sql: str) -> list[tuple]:
    connection = duckdb.connect(
        str(database), read_only=True, config={"autoinstall_known_extensions": False}
    )
    try:
        return connection.execute(sql).fetchall()
    finally:
        connection.close()


def test_midmonth_as_of_and_configured_window_use_month_ends(edge_db: Path) -> None:
    assert _query(edge_db, "SELECT month_end FROM intermediate.int_arr_month_ends ORDER BY 1") == [
        (date(2026, 8, 31),),
        (date(2026, 9, 30),),
        (date(2026, 10, 31),),
    ]


def test_charge_periods_drafts_and_rounding_after_aggregation(edge_db: Path) -> None:
    assert _query(
        edge_db,
        "SELECT month_end, version, arr_chf FROM marts.arr_billing_monthly "
        "WHERE order_number='PLANT-O-EDGE-PRECISION' ORDER BY month_end",
    ) == [
        (date(2026, 8, 31), 1, Decimal("0.01")),
        (date(2026, 9, 30), 1, Decimal("0.01")),
        (date(2026, 10, 31), 1, Decimal("0.00")),
    ]
    assert _query(
        edge_db,
        "SELECT month_end, arr_chf FROM marts.arr_billing_monthly "
        "WHERE order_number='PLANT-O-EDGE-CANCELLED' ORDER BY month_end",
    ) == [(date(2026, 8, 31), Decimal("12000.00"))]
    assert _query(edge_db, "SELECT sum(amount_chf) FROM marts.arr_bridge") == [
        (Decimal("-12000.01"),)
    ]


def test_missing_historical_fx_is_quarantined_and_never_uses_a_future_rate(edge_db: Path) -> None:
    assert _query(
        edge_db,
        "SELECT source_table, record_id FROM marts.quarantine "
        "WHERE reason='no_fx_rate' AND source_table IN ('hubspot_deals','younium_orders') "
        "ORDER BY source_table, record_id",
    ) == [
        ("hubspot_deals", "PLANT-EDGE-LATE-FX"),
        ("younium_orders", "PLANT-O-EDGE-LATE-FX:1"),
    ]
    for model in ("arr_crm_monthly", "arr_billing_monthly"):
        assert _query(edge_db, f"SELECT count(*) FROM marts.{model} WHERE currency='GBP'") == [(0,)]
