import copy
import io
from collections import Counter
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
from l2c.config import load_mapping, load_rules
from l2c.dbt_runner import BuildError, build_models, preview_table
from l2c.generate import generate_data
from l2c.generate.cases import CASES
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


@pytest.fixture(scope="module")
def planted_contract() -> dict:
    return yaml.safe_load(Path(__file__).with_name("planted_cases.yml").read_text(encoding="utf-8"))


def _case_objects(case: dict) -> set[tuple[str, str]]:
    types = {
        "hubspot_companies": "company",
        "hubspot_contacts": "contact",
        "hubspot_deals": "deal",
        "younium_accounts": "account",
        "younium_invoices": "invoice",
    }
    objects = set()
    for table, records in case["records"].items():
        for record in records:
            if table in types:
                objects.add((types[table], str(next(iter(record.values())))))
            elif table == "younium_orders":
                objects.add(("order", record["order_number"]))
                objects.add(("order_version", f"{record['order_number']}:{record['version']}"))
    return objects


@pytest.mark.parametrize("case_id", sorted(CASES))
def test_every_planted_check_owner_severity_money_and_proposal_is_exact(
    case_id: str,
    built: dict[str, Path],
    planted_contract: dict,
) -> None:
    database = built["default"]
    case = planted_contract["cases"][case_id]
    objects = _case_objects(case)
    rows = _query(
        database,
        "SELECT check_id, object_type, record_id, owner_id, severity, "
        "money_at_risk_chf, reason FROM marts.exceptions",
    )
    actual = Counter(row[:6] for row in rows if (row[1], row[2]) in objects)
    expected = Counter(
        (
            row["check_id"],
            row["object_type"],
            row["record_id"],
            row["owner_id"],
            row["severity"],
            row["money_at_risk_chf"],
        )
        for row in case["check_records"]
    )
    assert actual == expected
    for finding in case["check_records"]:
        if finding.get("reason"):
            assert any(
                row[0] == finding["check_id"]
                and row[2] == finding["record_id"]
                and row[6] == finding["reason"]
                for row in rows
            )
    proposals = _query(
        database,
        "SELECT check_id, object_type, record_id, property, current_value, "
        "proposed_value, requires_clear_first FROM marts.fix_proposals",
    )
    actual_proposals = Counter(row for row in proposals if (row[1], row[2]) in objects)
    expected_proposals = []
    for proposal in case["expected_proposals"]:
        if proposal["action"] == "merge":
            expected_proposals.append(
                (
                    "A7" if proposal["object_type"] == "company" else "A10",
                    proposal["object_type"],
                    proposal["secondary_id"],
                    "merge",
                    proposal["secondary_id"],
                    proposal["primary_id"],
                    False,
                )
            )
        else:
            expected_proposals.append(
                (
                    case["expected_checks"][0],
                    "contact" if proposal["source_table"] == "hubspot_contacts" else "company",
                    proposal["record_id"],
                    proposal["property"],
                    proposal["current_value"],
                    proposal["proposed_value"],
                    proposal["requires_clear_first"],
                )
            )
    assert actual_proposals == Counter(expected_proposals)
    if case["expected_push_status"]:
        deal_ids = [key["deal_id"] for key in case["records"]["hubspot_deals"]]
        push = _query(database, "SELECT deal_id, status, reasons FROM marts.push_readiness")
        selected = [row for row in push if row[0] in deal_ids]
        assert selected == [(case_id, case["expected_push_status"], case["expected_push_reasons"])]


def test_scorecard_denominators_failed_record_counts_and_push_aggregation(
    built: dict[str, Path],
) -> None:
    database = built["default"]
    counts = dict(_query(database, "SELECT check_id, rows_checked FROM marts.audit_scorecard"))
    assert len(counts) == 27
    for check in ("A1", "A2", "A3", "A4", "A10", "A11"):
        assert (
            counts[check]
            == _query(database, "SELECT count(*) FROM staging.stg_hubspot__contacts")[0][0]
        )
    for check in ("A5", "A6", "A12"):
        assert (
            counts[check]
            == _query(
                database, "SELECT count(*) FROM staging.stg_hubspot__deals WHERE is_closed_won"
            )[0][0]
        )
    assert counts["A13"] == sum(
        _query(
            database,
            "SELECT (SELECT count(*) FROM staging.stg_hubspot__deals), "
            "(SELECT count(*) FROM staging.stg_hubspot__companies)",
        )[0]
    )
    assert counts["P"] == _query(database, "SELECT count(*) FROM marts.push_readiness")[0][0]
    assert _query(database, "SELECT rows_failed FROM marts.audit_scorecard WHERE check_id='P'") == [
        (6,)
    ]
    assert _query(
        database, "SELECT count(*) FROM marts.exceptions WHERE record_id='PLANT-P03'"
    ) == [(2,)]
    assert _query(database, "SELECT count(*) FROM marts.exceptions WHERE check_id='P'") == [(0,)]
    assert (
        counts["R10"]
        == _query(database, "SELECT count(*) FROM staging.stg_younium__orders WHERE version>=2")[0][
            0
        ]
    )
    assert _query(database, "SELECT rows_failed FROM marts.audit_scorecard WHERE check_id='Q'") == [
        (8,)
    ]
    assert _query(
        database,
        "SELECT count(*) FROM marts.audit_scorecard "
        "WHERE pass_rate <> round(pass_rate,4) OR pass_rate NOT BETWEEN 0 AND 1",
    ) == [(0,)]
    all_rows = sum(
        _query(database, f'SELECT count(*) FROM staging."{table}"')[0][0]
        for (table,) in _query(
            database,
            "SELECT table_name FROM information_schema.tables WHERE table_schema='staging'",
        )
    )
    assert counts["Q"] == all_rows


def test_proposals_have_stable_ids_and_only_supported_audit_actions(built: dict[str, Path]) -> None:
    rows = _query(
        built["default"],
        "SELECT proposal_id, check_id, object_type, record_id, property FROM marts.fix_proposals",
    )
    assert rows
    assert len({row[0] for row in rows}) == len(rows)
    for proposal_id, check_id, object_type, record_id, property_name in rows:
        assert len(proposal_id) == 32
        assert check_id in {"A1", "A2", "A3", "A7", "A9", "A10"}
        assert object_type in {"company", "contact"}
        assert record_id and property_name
    assert _query(
        built["default"],
        "SELECT requires_clear_first FROM marts.fix_proposals WHERE record_id='PLANT-A03'",
    ) == [(True,)]
    assert _query(
        built["default"],
        "SELECT proposed_value FROM marts.fix_proposals WHERE record_id='PLANT-A05'",
    ) == [(None,)]


def test_r04_can_be_selected_with_the_requested_where_option(
    built: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("L2C_DB_PATH", str(built["default"]))
    result = CliRunner().invoke(
        cli.app, ["show", "exceptions", "--where", "record_id like '%R04%'"]
    )
    assert result.exit_code == 0, result.output
    assert "PLANT-R04" in result.output and "18000" in result.output
    assert "PLANT-R05" not in result.output


@pytest.fixture(scope="module")
def configured_checks(tmp_path_factory: pytest.TempPathFactory) -> Path:
    directory = tmp_path_factory.mktemp("configured-checks")
    data = generate_data().tables

    def find(table: str, key: str, identifier: str) -> dict:
        return next(row for row in data[table] if row[key] == identifier)

    find("hubspot_contacts", "contact_id", "PLANT-A01").update(
        lifecycle_stage="lead", lead_status="NEW", owner_id="OWN-000003"
    )
    find("hubspot_companies", "company_id", "PLANT-C-A01")["owner_id"] = "OWN-000002"
    find("hubspot_deals", "deal_id", "PLANT-D-A01")["owner_id"] = "OWN-000004"
    find("hubspot_companies", "company_id", "PLANT-A20")["owner_id"] = None
    find("hubspot_deals", "deal_id", "PLANT-P01")["company_ids"] = None
    find("hubspot_deals", "deal_id", "PLANT-P04")["currency"] = None
    find("hubspot_line_items", "deal_id", "PLANT-P06")["sku"] = "no-such-product"
    find("younium_orders", "account_number", "PLANT-R25")["cancellation_date"] = None
    renewal = dict(find("hubspot_deals", "deal_id", "PLANT-D-R13"))
    renewal.update(deal_id="PLANT-TEST-RENEWAL", motion="renewal", stage="contractsent")
    data["hubspot_deals"].append(renewal)
    credit = dict(find("younium_invoices", "invoice_number", "PLANT-R15"))
    credit.update(
        invoice_number="PLANT-TEST-DRAFT-CREDIT", is_credit=True, amount=-1000, status="Draft"
    )
    data["younium_invoices"].append(credit)
    item = dict(find("hubspot_line_items", "deal_id", "PLANT-R11"))
    item.update(line_item_id="PLANT-TEST-OTHER-PRICE", quantity=1, unit_price=500, amount=500)
    data["hubspot_line_items"].append(item)
    order = dict(find("younium_orders", "order_number", "PLANT-O-R22b"))
    order["order_number"] = "PLANT-O-R22c"
    data["younium_orders"].append(order)
    charge = dict(find("younium_order_charges", "order_number", "PLANT-O-R22b"))
    charge.update(charge_id="PLANT-O-R22c-V1-SEAT", order_number="PLANT-O-R22c")
    data["younium_order_charges"].append(charge)
    rules = load_rules().model_copy(
        update={
            "customer_lead_status": "UNQUALIFIED",
            "amount_tolerance_pct": 2.1,
            "start_date_tolerance_days": 16,
            "push_line_item_tolerance_pct": 9.2,
            "stale_open_deal_days": 31,
            "won_not_billed_days": 31,
            "term_tolerance_months": 12,
            "renewal_window_days": 45,
        }
    )
    mapping = CONFIG_DIR / "mapping.yml"
    write_files(data, load_mapping(mapping), directory / "raw")
    database = directory / "test.duckdb"
    load_files(mapping_path=mapping, raw_dir=directory / "raw", db_path=database)
    build_models(db_path=database, artifact_dir=directory, rules=rules)
    return database


def test_configured_tolerances_are_inclusive_and_not_hard_coded(configured_checks: Path) -> None:
    rows = _query(configured_checks, "SELECT check_id, record_id FROM marts.exceptions")
    for check_id, record_id in (
        ("R3", "PLANT-R03"),
        ("R4", "PLANT-R19"),
        ("A8", "PLANT-A10"),
        ("R1", "PLANT-R04"),
        ("A12", "PLANT-A18"),
    ):
        assert (check_id, record_id) not in rows
    assert _query(
        configured_checks,
        "SELECT status, reasons FROM marts.push_readiness WHERE deal_id='PLANT-P05'",
    ) == [("READY", [])]
    assert _query(
        configured_checks,
        "SELECT severity, money_at_risk_chf FROM marts.exceptions "
        "WHERE check_id='R7' AND record_id='PLANT-R14'",
    ) == [("info", Decimal("0.00"))]


def test_contact_owners_customer_precedence_and_unknown_company_owners(
    configured_checks: Path,
    built: dict[str, Path],
) -> None:
    assert _query(
        configured_checks,
        "SELECT owner_id FROM marts.exceptions WHERE check_id='A3' AND record_id='PLANT-A01'",
    ) == [("OWN-000002",)]
    assert _query(
        configured_checks,
        "SELECT record_id, proposed_value FROM marts.fix_proposals "
        "WHERE check_id='A3' AND record_id IN ('PLANT-A01','PLANT-A05') ORDER BY record_id",
    ) == [("PLANT-A01", "OPEN_DEAL"), ("PLANT-A05", "UNQUALIFIED")]
    assert _query(
        configured_checks,
        "SELECT owner_id FROM marts.exceptions WHERE check_id='A13' AND record_id='PLANT-A20'",
    ) == [("unassigned",)]
    proposal = "SELECT proposal_id FROM marts.fix_proposals WHERE record_id='PLANT-A05'"
    assert _query(configured_checks, proposal) == _query(built["default"], proposal)


def test_push_reports_missing_company_currency_and_unknown_sku(configured_checks: Path) -> None:
    assert _query(
        configured_checks,
        "SELECT deal_id, status, reasons FROM marts.push_readiness "
        "WHERE deal_id IN ('PLANT-P01','PLANT-P04','PLANT-P06') ORDER BY deal_id",
    ) == [
        ("PLANT-P01", "BLOCKED", ["P1", "P2"]),
        ("PLANT-P04", "BLOCKED", ["P4"]),
        ("PLANT-P06", "BLOCKED", ["P3"]),
    ]


def test_open_renewals_credits_and_ambiguous_seat_prices(configured_checks: Path) -> None:
    assert _query(
        configured_checks,
        "SELECT count(*) FROM marts.exceptions WHERE check_id='R7' AND record_id='PLANT-R13'",
    ) == [(0,)]
    assert _query(
        configured_checks,
        "SELECT count(*) FROM marts.exceptions WHERE check_id='R8' AND record_id='PLANT-R15'",
    ) == [(0,)]
    assert _query(
        configured_checks,
        "SELECT money_at_risk_chf FROM marts.exceptions "
        "WHERE check_id='R5' AND record_id='PLANT-R11'",
    ) == [(None,)]
    assert _query(
        configured_checks,
        "SELECT count(*) FROM marts.exceptions WHERE check_id='R11' AND record_id='PLANT-R25'",
    ) == [(1,)]


def test_duplicate_push_scorecard_counts_failed_deals_instead_of_duplicate_orders(
    configured_checks: Path,
) -> None:
    assert _query(
        configured_checks,
        "SELECT record_id FROM marts.exceptions WHERE check_id='R9' ORDER BY record_id",
    ) == [("PLANT-O-R22b",), ("PLANT-O-R22c",)]
    assert _query(
        configured_checks,
        "SELECT rows_failed FROM marts.audit_scorecard WHERE check_id='R9'",
    ) == [(1,)]


def test_missing_database_is_a_clear_nonzero_cli_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("L2C_DB_PATH", str(tmp_path / "missing.duckdb"))
    result = CliRunner().invoke(cli.app, ["build"])
    assert result.exit_code == 1 and "run l2c load first" in result.output
    assert not (tmp_path / "missing.duckdb").exists()
    result = CliRunner().invoke(cli.app, ["show", "int_fx"])
    assert result.exit_code == 1 and "run l2c load first" in result.output
