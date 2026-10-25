import copy
import io
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb
import pytest
import yaml
from typer.testing import CliRunner

from l2c import cli
from l2c.config import load_mapping
from l2c.dbt_runner import BuildError, build_models, preview_table
from l2c.generate import generate_data
from l2c.generate.writer import write_files
from l2c.load import load_files
from l2c.logging_setup import setup_logging
from l2c.paths import CONFIG_DIR


@contextmanager
def _connection(path: Path) -> Iterator[duckdb.DuckDBPyConnection]:
    connection = duckdb.connect(
        str(path), read_only=True, config={"autoinstall_known_extensions": False}
    )
    try:
        yield connection
    finally:
        connection.close()


def _query(path: Path, sql: str, parameters: list[Any] | None = None) -> list[tuple]:
    with _connection(path) as connection:
        return connection.execute(sql, parameters or []).fetchall()


@pytest.fixture(autouse=True)
def logs() -> Iterator[None]:
    logger = setup_logging(stream=io.StringIO())
    try:
        yield
    finally:
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)
            handler.close()


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    tables = generate_data(seed=42).tables
    databases = {}
    for format_name in ("default", "ch", "de", "hubspot_ui"):
        directory = tmp_path_factory.mktemp(f"dbt-{format_name}")
        mapping_path = CONFIG_DIR / (
            "mapping.yml" if format_name == "default" else f"mapping.{format_name}.yml"
        )
        write_files(tables, load_mapping(mapping_path), directory / "raw", format_name=format_name)
        database = directory / "test.duckdb"
        load_files(mapping_path=mapping_path, raw_dir=directory / "raw", db_path=database)
        before = _query(database, "SELECT * FROM state.run_manifest ORDER BY 1, 2")
        result = build_models(mapping_path=mapping_path, db_path=database, artifact_dir=directory)
        assert result.nodes >= 62
        assert _query(database, "SELECT * FROM state.run_manifest ORDER BY 1, 2") == before
        databases[format_name] = database
    return databases


def test_all_staging_models_have_real_types_and_cleaned_fields(built: dict[str, Path]) -> None:
    database = built["default"]
    assert _query(
        database, "SELECT count(*) FROM information_schema.tables WHERE table_schema='staging'"
    ) == [(12,)]
    assert _query(
        database,
        "SELECT typeof(amount), typeof(term_months), typeof(contract_start), typeof(company_ids), "
        "is_closed_won, is_open, company_ids FROM staging.stg_hubspot__deals "
        "WHERE deal_id='PLANT-P01'",
    ) == [
        (
            "DECIMAL(38,12)",
            "BIGINT",
            "DATE",
            "VARCHAR[]",
            True,
            False,
            ["PLANT-C-P01a", "PLANT-C-P01b"],
        )
    ]
    assert _query(
        database,
        "SELECT email FROM staging.stg_hubspot__contacts "
        "WHERE contact_id IN ('PLANT-A14','PLANT-A14b') ORDER BY contact_id",
    ) == [("anna.keller@kanzlei-keller.ch",), ("anna.keller@kanzlei-keller.ch",)]
    assert _query(
        database,
        "SELECT domain_clean FROM staging.stg_hubspot__companies "
        "WHERE company_id IN ('PLANT-A09','PLANT-A09b') ORDER BY company_id",
    ) == [("acme-legal.ch",), ("acme-legal.ch",)]
    assert _query(
        database,
        "SELECT name, city FROM staging.stg_hubspot__companies WHERE company_id='PLANT-A20'",
    ) == [("Müller & Söhne Rechtsanwälte AG", "Zürich")]
    assert _query(
        database,
        "SELECT lifecycle_stage FROM staging.stg_hubspot__contacts WHERE contact_id='PLANT-A02'",
    ) == [("lead_old",)]


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


def test_quarantine_has_exact_planted_findings_and_retains_raw_evidence(
    built: dict[str, Path],
) -> None:
    rows = _query(
        built["default"],
        'SELECT source_table, record_id, "column", raw_value, reason '
        "FROM marts.quarantine ORDER BY 1,2,3",
    )
    assert set(rows) == {
        ("hubspot_deals", "PLANT-Q02", "currency", "USD", "no_fx_rate"),
        ("younium_accounts", "PLANT-Q01", "domain", "gmail.com", "generic_email_domain"),
        (
            "younium_accounts",
            "PLANT-Q03",
            "hubspot_company_id",
            "1.23457E+11",
            "id_corrupted_by_excel",
        ),
        (
            "younium_accounts",
            "PLANT-R07",
            "domain",
            "https://www.acme-legal.ch/path",
            "ambiguous_domain",
        ),
        ("younium_bookings", "PLANT-O-Q02-V1-BOOK", "currency", "USD", "no_fx_rate"),
        ("younium_invoices", "PLANT-Q04", "amount", "n/a", "unparseable_amount"),
        ("younium_invoices", "PLANT-Q05", "service_period_start", "not-a-date", "unparseable_date"),
        ("younium_orders", "PLANT-O-Q02:1", "currency", "USD", "no_fx_rate"),
    }
    contract = yaml.safe_load(
        Path(__file__).with_name("planted_cases.yml").read_text(encoding="utf-8")
    )
    for case_id, case in contract["cases"].items():
        records = {
            (table, ":".join(str(record[key]) for key in contract["primary_keys"][table]))
            for table, keys in case["records"].items()
            for record in keys
        }
        actual = {
            (table, record_id, column, reason)
            for table, record_id, column, _, reason in rows
            if (table, record_id) in records
        }
        expected = {
            (
                item["source_table"],
                item["record_id"],
                item["column"],
                item.get("model_reason", item["reason"]),
            )
            for item in case["expected_quarantine"]
        }
        assert actual == expected, case_id
    assert _query(
        built["default"], "SELECT amount FROM raw.younium_invoices WHERE invoice_number='PLANT-Q04'"
    ) == [("n/a",)]
    assert _query(
        built["default"],
        "SELECT count(*) FROM intermediate.int_deal_order_match WHERE deal_id='PLANT-Q02'",
    ) == [(0,)]
    assert _query(
        built["default"],
        "SELECT count(*) FROM intermediate.int_order_versions "
        "WHERE order_number IN ('PLANT-O-Q02','PLANT-O-R07')",
    ) == [(0,)]
    assert _query(
        built["default"], "SELECT count(*) FROM marts.quarantine WHERE record_id LIKE '%A13%'"
    ) == [(0,)]


def test_account_matching_prefers_ids_and_never_picks_an_ambiguous_domain(
    built: dict[str, Path],
) -> None:
    rows = _query(
        built["default"],
        "SELECT account_number, company_id, match_method, quarantine_reason, "
        "candidate_count FROM intermediate.int_account_match WHERE account_number IN "
        "('PLANT-R06','PLANT-R07','PLANT-Q01','PLANT-Q03','PLANT-Y-A09')",
    )
    assert set(rows) == {
        ("PLANT-R06", "PLANT-C-R06", "domain", None, 1),
        ("PLANT-R07", None, "ambiguous", "ambiguous", 2),
        ("PLANT-Q01", None, "quarantined", "generic_email_domain", 0),
        ("PLANT-Q03", None, "quarantined", "id_corrupted_by_excel", 1),
        ("PLANT-Y-A09", "PLANT-A09", "hubspot_company_id", None, 1),
    }


def test_order_versions_and_new_deal_duplicate_exception(built: dict[str, Path]) -> None:
    database = built["default"]
    assert _query(
        database,
        "SELECT version, is_current FROM intermediate.int_order_versions "
        "WHERE order_number='PLANT-R23' ORDER BY version",
    ) == [(1, False), (2, True)]
    assert _query(
        database,
        "SELECT is_current FROM intermediate.int_order_versions WHERE order_number='PLANT-O-R21'",
    ) == [(False,)]
    assert _query(
        database,
        "SELECT is_matched, has_draft_order, order_number "
        "FROM intermediate.int_deal_order_match WHERE deal_id='PLANT-R21'",
    ) == [(False, True, None)]
    assert _query(
        database,
        "SELECT order_number, version, match_method, duplicate_order_numbers "
        "FROM intermediate.int_deal_order_match WHERE deal_id='PLANT-R22'",
    ) == [("PLANT-O-R22", 1, "duplicate_push", ["PLANT-O-R22b"])]
    assert _query(
        database,
        "SELECT is_matched FROM intermediate.int_deal_order_match "
        "WHERE deal_id IN ('PLANT-R12','PLANT-R29') ORDER BY deal_id",
    ) == [(False,), (False,)]


def test_fx_intervals_always_use_the_last_rate_on_or_before_the_requested_date(
    built: dict[str, Path],
) -> None:
    database = built["default"]
    for when in (date(2026, 10, 15), date(2026, 10, 31), date(2026, 11, 30)):
        expected = _query(
            database,
            "SELECT date, rate_to_chf FROM staging.stg_ref__fx_rates "
            "WHERE currency='EUR' AND date <= ? ORDER BY date DESC LIMIT 1",
            [when],
        )
        actual = _query(
            database,
            "SELECT rate_date, rate_to_chf FROM intermediate.int_fx "
            "WHERE currency='EUR' AND effective_start <= ? "
            "AND (effective_end > ? OR effective_end IS NULL)",
            [when, when],
        )
        assert actual == expected
    assert _query(
        database,
        "SELECT rate_to_chf FROM intermediate.int_fx "
        "WHERE currency='EUR' AND effective_end IS NULL",
    ) == [(Decimal("0.9400"),)]
    assert _query(database, "SELECT count(*) FROM intermediate.int_fx WHERE currency='USD'") == [
        (0,)
    ]


@pytest.fixture(scope="module")
def adversarial(tmp_path_factory: pytest.TempPathFactory) -> Path:
    directory = tmp_path_factory.mktemp("adversarial")
    data = copy.deepcopy(generate_data().tables)

    def find(table: str, key: str, identifier: str) -> dict:
        return next(row for row in data[table] if row[key] == identifier)

    find("hubspot_contacts", "contact_id", "PLANT-T-A13")["created_at"] = "not-a-date"
    find("hubspot_contacts", "contact_id", "PLANT-A15")["company_id"] = "1.23e+11"
    find("hubspot_deals", "deal_id", "PLANT-D-A13")["amount"] = "not-money"
    find("younium_order_charges", "charge_id", "PLANT-O-R01-V1-SEAT")["quantity"] = "ten"
    find("younium_accounts", "account_number", "PLANT-R06").update(
        hubspot_company_id="PLANT-C-R06", domain="https://www.acme-legal.ch/path"
    )
    find("younium_accounts", "account_number", "PLANT-Y-A13")["domain"] = "gmail.com"
    unmatched = dict(find("younium_accounts", "account_number", "PLANT-Q01"))
    unmatched.update(
        account_number="PLANT-TEST-UNMATCHED",
        hubspot_company_id=None,
        domain="no-such-company.synthetic.example",
    )
    data["younium_accounts"].append(unmatched)
    old = find("younium_orders", "order_number", "PLANT-R23")
    draft = dict(old)
    draft.update(version=3, status="Draft", hubspot_deal_id=None)
    data["younium_orders"].append(draft)
    bad_version = dict(find("younium_orders", "order_number", "PLANT-O-R09"))
    bad_version["version"] = "unknown"
    data["younium_orders"].append(bad_version)
    order = find("younium_orders", "order_number", "PLANT-O-R12")
    charge = find("younium_order_charges", "order_number", "PLANT-O-R12")
    first_change = date(2026, 10, 1)
    order["effective_end"] = charge["effective_end"] = first_change
    for version, start, end in [
        (2, first_change, date(2026, 10, 16)),
        (3, date(2026, 10, 16), date(2027, 4, 30)),
    ]:
        changed = dict(order)
        changed.update(
            version=version, hubspot_deal_id="PLANT-R12", effective_start=start, effective_end=end
        )
        data["younium_orders"].append(changed)
        changed_charge = dict(charge)
        changed_charge.update(
            charge_id=f"PLANT-TEST-R12-V{version}",
            version=version,
            effective_start=start,
            effective_end=end,
        )
        data["younium_order_charges"].append(changed_charge)
    early_fx = dict(find("younium_invoices", "invoice_number", "PLANT-R15"))
    early_fx.update(
        invoice_number="PLANT-TEST-EARLY-FX", currency="EUR", posted_date=date(2025, 9, 1)
    )
    data["younium_invoices"].append(early_fx)
    blank_currency = dict(find("hubspot_deals", "deal_id", "PLANT-R05"))
    blank_currency.update(deal_id="PLANT-TEST-NO-CURRENCY", currency=None)
    data["hubspot_deals"].append(blank_currency)
    mapping = CONFIG_DIR / "mapping.yml"
    write_files(data, load_mapping(mapping), directory / "raw")
    database = directory / "test.duckdb"
    load_files(raw_dir=directory / "raw", db_path=database, mapping_path=mapping)
    build_models(db_path=database, mapping_path=mapping, artifact_dir=directory)
    return database


def test_unparseable_dates_numbers_and_foreign_ids_are_findings(adversarial: Path) -> None:
    rows = _query(adversarial, 'SELECT record_id, "column", reason FROM marts.quarantine')
    assert {
        ("PLANT-T-A13", "created_at", "unparseable_date"),
        ("PLANT-A15", "company_id", "id_corrupted_by_excel"),
        ("PLANT-D-A13", "amount", "unparseable_amount"),
        ("PLANT-O-R01-V1-SEAT", "quantity", "unparseable_amount"),
        ("PLANT-O-R09:unknown", "version", "unparseable_amount"),
        ("PLANT-TEST-EARLY-FX", "currency", "no_fx_rate"),
        ("PLANT-TEST-NO-CURRENCY", "currency", "no_fx_rate"),
    } <= set(rows)
    assert _query(
        adversarial,
        "SELECT count(*) FROM intermediate.int_order_versions "
        "WHERE order_number IN ('PLANT-O-R01','PLANT-O-R09')",
    ) == [(0,)]


def test_explicit_matching_wins_and_unmatched_rows_are_never_guessed(adversarial: Path) -> None:
    assert _query(
        adversarial,
        "SELECT company_id, match_method FROM intermediate.int_account_match "
        "WHERE account_number='PLANT-R06'",
    ) == [("PLANT-C-R06", "hubspot_company_id")]
    assert _query(
        adversarial,
        "SELECT company_id, is_quarantined FROM intermediate.int_account_match "
        "WHERE account_number='PLANT-Y-A13'",
    ) == [("PLANT-A13", False)]
    assert _query(
        adversarial,
        "SELECT company_id, match_method FROM intermediate.int_account_match "
        "WHERE account_number='PLANT-TEST-UNMATCHED'",
    ) == [(None, "unmatched")]


def test_ambiguous_change_deals_are_quarantined_and_drafts_never_become_current(
    adversarial: Path,
) -> None:
    assert _query(
        adversarial,
        "SELECT candidate_count, order_number, is_matched, quarantine_reason "
        "FROM intermediate.int_deal_order_match WHERE deal_id='PLANT-R12'",
    ) == [(2, None, False, "ambiguous")]
    assert _query(
        adversarial,
        "SELECT reason FROM marts.quarantine "
        "WHERE source_table='hubspot_deals' AND record_id='PLANT-R12'",
    ) == [("ambiguous",)]
    assert _query(
        adversarial,
        "SELECT version, is_current FROM intermediate.int_order_versions "
        "WHERE order_number='PLANT-R23' ORDER BY version",
    ) == [(1, False), (2, True), (3, False)]


def test_show_is_read_only_limited_and_handles_qualified_names(
    built: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = built["default"]
    monkeypatch.setenv("L2C_DB_PATH", str(database))
    preview = preview_table("stg_hubspot__contacts")
    assert len(preview.rows) == 50
    assert preview == preview_table("staging.stg_hubspot__contacts")
    result = CliRunner().invoke(cli.app, ["show", "int_account_match"])
    assert result.exit_code == 0, result.output
    assert "account_number" in result.output and "match_method" in result.output
    before = _query(database, "SELECT count(*) FROM raw.hubspot_companies")
    with pytest.raises(ValueError, match="not found"):
        preview_table('x"; DROP TABLE raw.hubspot_companies; --')
    assert _query(database, "SELECT count(*) FROM raw.hubspot_companies") == before


def test_failed_builds_close_connections_and_do_not_touch_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = generate_data().tables
    data["hubspot_companies"].append(dict(data["hubspot_companies"][0]))
    expected_count = len(data["hubspot_companies"])
    mapping = CONFIG_DIR / "mapping.yml"
    write_files(data, load_mapping(mapping), tmp_path / "raw")
    database = tmp_path / "test.duckdb"
    monkeypatch.setenv("L2C_DB_PATH", str(database))
    load_files(raw_dir=tmp_path / "raw", mapping_path=mapping)
    before = _query(database, "SELECT * FROM state.run_manifest ORDER BY 1,2")
    with pytest.raises(BuildError, match="dbt build failed"):
        build_models(artifact_dir=tmp_path)
    assert _query(database, "SELECT * FROM state.run_manifest ORDER BY 1,2") == before
    assert _query(database, "SELECT count(*) FROM raw.hubspot_companies") == [(expected_count,)]


def test_missing_database_is_a_clear_nonzero_cli_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("L2C_DB_PATH", str(tmp_path / "missing.duckdb"))
    result = CliRunner().invoke(cli.app, ["build"])
    assert result.exit_code == 1 and "run l2c load first" in result.output
    assert not (tmp_path / "missing.duckdb").exists()
    result = CliRunner().invoke(cli.app, ["show", "int_fx"])
    assert result.exit_code == 1 and "run l2c load first" in result.output
