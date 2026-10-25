import csv
import json
import os
import subprocess
import sys
from collections import Counter
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from l2c.cli import app
from l2c.config import load_mapping, load_rules
from l2c.generate import ExportFormat, GeneratedData, generate_data, generate_files
from l2c.generate.cases import CASES
from l2c.generate.model import Dataset, Row, add_months
from l2c.generate.writer import write_files
from l2c.paths import CONFIG_DIR, REPO_ROOT


@pytest.fixture(scope="module")
def generated() -> GeneratedData:
    return generate_data(seed=42)


@pytest.fixture(scope="module")
def manifest() -> dict:
    path = REPO_ROOT / "tests" / "planted_cases.yml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _only(records: Dataset, table: str) -> Row:
    rows = records[table]
    assert len(rows) == 1
    return rows[0]


def _row(records: Dataset, table: str, key: str, value: object) -> Row:
    return next(row for row in records[table] if row[key] == value)


def test_registry_and_manifest_cover_every_specified_case(manifest: dict) -> None:
    expected = {
        *[f"PLANT-A{index:02d}" for index in range(1, 21)],
        *[f"PLANT-P{index:02d}" for index in range(1, 7)],
        *[f"PLANT-Q{index:02d}" for index in range(1, 6)],
        *[f"PLANT-R{index:02d}" for index in range(1, 30) if index != 10],
    }
    assert set(CASES) == set(manifest["cases"]) == expected
    assert len({function.__name__ for function in CASES.values()}) == len(expected)
    assert manifest["as_of_date"] == "2026-10-31"


@pytest.mark.parametrize("case_id", sorted(CASES))
def test_manifest_covers_every_supporting_record_and_result(
    case_id: str, generated: GeneratedData, manifest: dict
) -> None:
    records = generated.planted_records[case_id]
    expected = manifest["cases"][case_id]
    actual = {
        table: [{key: row[key] for key in manifest["primary_keys"][table]} for row in rows]
        for table, rows in records.items()
    }
    assert actual == expected["records"]
    assert set(expected["money_at_risk_chf"]) == set(expected["expected_checks"])
    assert set(expected["expected_checks"]) == {
        row["check_id"] for row in expected["check_records"]
    }
    assert all(
        str(next(iter(key.values()))).startswith("PLANT-")
        for keys in actual.values()
        for key in keys
    )
    assert len(expected["expected_push_reasons"]) == len(set(expected["expected_push_reasons"]))
    if expected["expected_push_status"] == "BLOCKED":
        assert expected["expected_push_reasons"]
    elif expected["expected_push_status"] == "READY":
        assert expected["expected_push_reasons"] == []
    for result in expected["check_records"]:
        assert result["money_at_risk_chf"] == expected["money_at_risk_chf"][result["check_id"]]


def test_background_sizes_and_scaling_leave_plants_and_references_unchanged(
    generated: GeneratedData,
) -> None:
    counts = {
        "hubspot_companies": 30,
        "hubspot_contacts": 80,
        "hubspot_deals": 50,
        "hubspot_line_items": 90,
        "hubspot_owners": 6,
        "younium_accounts": 28,
        "younium_orders": 40,
        "younium_order_charges": 90,
        "younium_invoices": 250,
        "younium_bookings": 40,
    }
    large = generate_data(seed=42, profile="large", scale=10)
    assert generated.planted_records == large.planted_records
    for table, count in counts.items():
        planted_count = sum(
            len(records.get(table, [])) for records in generated.planted_records.values()
        )
        assert len(generated.tables[table]) - planted_count == count
        assert len(large.tables[table]) - planted_count == count * 10
    for table in ("ref_fx_rates", "ref_product_catalog"):
        assert large.tables[table] == generated.tables[table]
    background_deals = [
        row
        for row in generated.tables["hubspot_deals"]
        if not str(row["deal_id"]).startswith("PLANT-")
    ]
    assert Counter(row["stage"] for row in background_deals)["closedwon"] == 20
    assert Counter(row["currency"] for row in background_deals) == {"CHF": 30, "EUR": 20}


def test_seed_affects_only_random_background_and_historical_fx(generated: GeneratedData) -> None:
    other = generate_data(seed=17)
    assert other.tables != generated.tables
    assert other.planted_records == generated.planted_records
    assert other.tables["ref_product_catalog"] == generated.tables["ref_product_catalog"]


def test_keys_references_and_version_bookings_are_complete(
    generated: GeneratedData, manifest: dict
) -> None:
    data = generated.tables
    for table, rows in data.items():
        keys = [tuple(row[column] for column in manifest["primary_keys"][table]) for row in rows]
        assert len(keys) == len(set(keys)), table
    companies = {row["company_id"] for row in data["hubspot_companies"]}
    deals = {row["deal_id"] for row in data["hubspot_deals"]}
    accounts = {row["account_number"] for row in data["younium_accounts"]}
    orders = {(row["order_number"], row["version"]) for row in data["younium_orders"]}
    assert all(row["account_number"] in accounts for row in data["younium_orders"])
    assert all(row["deal_id"] in deals for row in data["hubspot_line_items"])
    assert all(
        row["hubspot_deal_id"] in deals
        for row in data["younium_orders"]
        if row["hubspot_deal_id"] is not None
    )
    assert all(
        company in companies
        for row in data["hubspot_deals"]
        for company in str(row["company_ids"]).split(";")
    )
    assert all(
        row["hubspot_company_id"] in companies
        for row in data["younium_accounts"]
        if row["hubspot_company_id"] not in (None, "1.23457E+11")
    )
    assert all(
        row["order_number"] in {key[0] for key in orders} for row in data["younium_invoices"]
    )
    assert all(
        row["company_id"] in companies
        for row in data["hubspot_contacts"]
        if row["company_id"] is not None
    )
    assert all(
        (row["order_number"], row["version"]) in orders for row in data["younium_order_charges"]
    )
    assert {(row["order_number"], row["version"]) for row in data["younium_bookings"]} == orders
    assert all(
        row["younium_account_number"] in accounts
        for row in data["hubspot_companies"]
        if row["younium_account_number"] is not None
    )


def test_activation_bookings_reflect_recurring_charges(generated: GeneratedData) -> None:
    recurring: Counter = Counter()
    for charge in generated.tables["younium_order_charges"]:
        if charge["charge_type"] == "Recurring":
            recurring[(charge["order_number"], charge["version"])] += charge["mrr"]
    for booking in generated.tables["younium_bookings"]:
        key = (booking["order_number"], booking["version"])
        before = recurring.get((booking["order_number"], booking["version"] - 1), 0)
        expected = recurring[key] if booking["event"] == "activation" else recurring[key] - before
        assert booking["cmrr_change"] == expected, key


def test_all_dates_follow_configured_as_of_date() -> None:
    rules = load_rules().model_copy(update={"as_of_date": date(2027, 10, 31)})
    generated = generate_data(rules=rules)
    case = generated.planted_records["PLANT-A16"]
    assert _only(case, "hubspot_deals")["close_date"] == date(2027, 11, 10)
    case = generated.planted_records["PLANT-R28"]
    assert _only(case, "younium_order_charges")["effective_start"] == date(2027, 9, 30)
    assert _only(case, "younium_order_charges")["effective_end"] == date(2027, 10, 31)
    assert generated.tables["ref_fx_rates"][-1]["date"] == date(2027, 10, 31)


def test_fresh_processes_write_identical_bytes_with_different_hash_seeds(tmp_path: Path) -> None:
    snapshots = []
    for hash_seed in ("11", "123"):
        output = tmp_path / hash_seed
        environment = dict(os.environ, PYTHONHASHSEED=hash_seed, PYTHONIOENCODING="utf-8")
        environment.pop("L2C_MAPPING", None)
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "l2c.cli",
                "generate",
                "--seed",
                "42",
                "--output-dir",
                str(output),
            ],
            cwd=REPO_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        assert result.returncode == 0, result.stderr
        snapshots.append({path.name: path.read_bytes() for path in output.glob("*.csv")})
    assert len(snapshots[0]) == 12
    assert snapshots[0] == snapshots[1]


def test_synthetic_fx_and_catalog_are_complete(generated: GeneratedData) -> None:
    rows = generated.tables["ref_fx_rates"]
    chf = [row for row in rows if row["currency"] == "CHF"]
    eur = [row for row in rows if row["currency"] == "EUR"]
    assert len(eur) == 13
    assert eur[-1] == {
        "currency": "EUR",
        "date": date(2026, 10, 31),
        "rate_to_chf": Decimal("0.9400"),
    }
    assert all(row["rate_to_chf"] == Decimal("1") for row in chf)
    assert [row["date"] for row in chf] == [
        chf[0]["date"] + timedelta(days=day) for day in range(len(chf))
    ]
    assert chf[0]["date"] <= min(
        row["booking_date"] for row in generated.tables["younium_bookings"]
    )
    catalog = generated.tables["ref_product_catalog"]
    assert {row["sku"] for row in catalog} == {
        "LGT-PLATFORM",
        "LGT-SEAT",
        "LGT-REVIEW-PACK",
        "LGT-ONBOARDING",
    }
    assert {row["charge_type"] for row in catalog} == {"Recurring", "Usage", "One-off"}


@pytest.mark.parametrize("format_name", [item.value for item in ExportFormat])
def test_formats_are_byte_identical_on_repeat_and_losslessly_round_trip(
    format_name: str,
    tmp_path: Path,
    generated: GeneratedData,
) -> None:
    mapping = load_mapping(
        CONFIG_DIR / ("mapping.yml" if format_name == "default" else f"mapping.{format_name}.yml")
    )
    write_files(generated.tables, mapping, tmp_path, format_name=format_name)
    first = {path.name: path.read_bytes() for path in tmp_path.glob("*.csv")}
    write_files(generate_data(seed=42).tables, mapping, tmp_path, format_name=format_name)
    assert first == {path.name: path.read_bytes() for path in tmp_path.glob("*.csv")}
    assert len(first) == 12
    for table, spec in mapping.tables.items():
        raw = first[spec.file]
        assert raw.startswith(b"\xef\xbb\xbf")
        if format_name != "default":
            assert b"\r\n" in raw
            assert b"\n" not in raw.replace(b"\r\n", b"")
        with (tmp_path / spec.file).open(encoding=spec.format.encoding, newline="") as stream:
            reader = csv.DictReader(stream, delimiter=spec.format.delimiter)
            assert reader.fieldnames == list(spec.columns.values())
            exported = list(reader)
        assert len(exported) == len(generated.tables[table])
        for before, after in zip(generated.tables[table], exported, strict=True):
            for column, expected in before.items():
                cell = after[spec.columns[column]]
                cell = spec.values.get(column, {}).get(cell, cell)
                if expected is None:
                    assert cell == ""
                elif isinstance(expected, bool):
                    assert cell == str(expected).lower()
                elif isinstance(expected, date):
                    assert datetime.strptime(cell, spec.format.date_format).date() == expected
                elif isinstance(expected, Decimal):
                    normalized = (
                        cell.replace(spec.format.thousands, "") if spec.format.thousands else cell
                    )
                    assert Decimal(normalized.replace(spec.format.decimal, ".")) == expected
                else:
                    assert cell == str(expected)
    assert "Müller & Söhne Rechtsanwälte AG".encode() in first["hubspot_companies.csv"]
    assert b"1.23457E+11" in first["younium_accounts.csv"]
    assert b"n/a" in first["younium_invoices.csv"]
    if format_name == "ch":
        assert b"1'200.00" in first["younium_order_charges.csv"]
    if format_name == "de":
        assert b"1.200,00" in first["younium_order_charges.csv"]
    if format_name == "hubspot_ui":
        assert b"Record ID" in first["hubspot_deals.csv"]
        assert b"Closed Won" in first["hubspot_deals.csv"]
        assert b"Marketing Qualified Lead" in first["hubspot_contacts.csv"]
        assert b"lead_old" in first["hubspot_contacts.csv"]


@pytest.mark.parametrize("format_name", [item.value for item in ExportFormat])
def test_generate_cli_selects_the_requested_mapping(format_name: str, tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app, ["generate", "--seed", "42", "--format", format_name, "--output-dir", str(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    assert "Generated 12 synthetic CSVs" in result.output
    assert len(list(tmp_path.glob("*.csv"))) == 12
    text = (tmp_path / "hubspot_deals.csv").read_text(encoding="utf-8-sig")
    if format_name == "hubspot_ui":
        assert "Record ID" in text and "Closed Won" in text
    else:
        assert text.startswith("hs_object_id,")


def test_mapping_override_and_environment_are_respected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("L2C_MAPPING", str(CONFIG_DIR / "mapping.hubspot_ui.yml"))
    output = tmp_path / "environment"
    generate_files(output_dir=output)
    assert (output / "hubspot_deals.csv").read_text(encoding="utf-8-sig").startswith("Record ID,")
    output = tmp_path / "explicit"
    generate_files(output_dir=output, mapping_path=CONFIG_DIR / "mapping.yml")
    assert (
        (output / "hubspot_deals.csv").read_text(encoding="utf-8-sig").startswith("hs_object_id,")
    )


def test_invalid_generation_options_do_not_write_files(tmp_path: Path) -> None:
    output = tmp_path / "invalid"
    result = CliRunner().invoke(app, ["generate", "--scale", "2", "--output-dir", str(output)])
    assert result.exit_code == 1
    assert "scale: use --profile large" in result.output
    logs = [json.loads(line) for line in result.output.splitlines() if line.startswith("{")]
    assert len(logs) == 1
    assert logs[0]["step"] == "generate" and logs[0]["status"] == "failed"
    assert len(logs[0]["run_id"]) == 32
    assert not output.exists()
    result = CliRunner().invoke(app, ["generate", "--scale", "0", "--output-dir", str(output)])
    assert result.exit_code != 0
    assert not output.exists()


@pytest.mark.parametrize("bad_file", ["../escape.csv", "hubspot_contacts.csv"])
def test_bad_output_mapping_cannot_escape_or_overwrite_another_table(
    bad_file: str,
    generated: GeneratedData,
    tmp_path: Path,
) -> None:
    mapping = load_mapping(CONFIG_DIR / "mapping.yml")
    mapping.tables["hubspot_companies"].file = bad_file
    output = tmp_path / "invalid"
    with pytest.raises(ValueError, match="mapping.*file"):
        write_files(generated.tables, mapping, output)
    assert not output.exists()


def test_audit_fixture_evidence_and_proposals(generated: GeneratedData, manifest: dict) -> None:
    cases = generated.planted_records
    for number, stage in [(1, None), (2, "lead_old"), (3, "customer"), (4, "salesqualifiedlead")]:
        key = f"PLANT-A{number:02d}"
        contact = _only(cases[key], "hubspot_contacts")
        assert contact["lifecycle_stage"] == stage
        proposal = manifest["cases"][key]["expected_proposals"][0]
        assert proposal["current_value"] == stage
        assert proposal["proposed_value"] == (
            "opportunity" if number == 1 else "lead" if number == 3 else "customer"
        )
        assert proposal["requires_clear_first"] == (number == 3)
        stage_expected = (
            "appointmentscheduled" if number == 1 else "closedlost" if number == 3 else "closedwon"
        )
        assert _only(cases[key], "hubspot_deals")["stage"] == stage_expected
    assert _only(cases["PLANT-A05"], "hubspot_contacts")["lead_status"] == "NEW"
    assert manifest["cases"]["PLANT-A05"]["expected_proposals"][0]["proposed_value"] is None
    assert _only(cases["PLANT-A06"], "hubspot_contacts")["original_source"] is None
    assert _only(cases["PLANT-A07"], "hubspot_deals")["amount"] is None
    assert "younium_orders" not in cases["PLANT-A07"]
    assert _only(cases["PLANT-A08"], "hubspot_deals")["contract_end"] is None
    assert _only(cases["PLANT-A12"], "hubspot_companies")["country"] == "Germany"
    assert _only(cases["PLANT-A12"], "hubspot_companies")["territory"] is None
    assert _only(cases["PLANT-A15"], "hubspot_contacts")["company_id"] is None
    assert _only(cases["PLANT-A19"], "hubspot_deals")["owner_id"] not in {
        row["owner_id"] for row in generated.tables["hubspot_owners"]
    }
    company = _only(cases["PLANT-A20"], "hubspot_companies")
    assert (
        company["name"]
        == manifest["cases"]["PLANT-A20"]["expected_name"]
        == "Müller & Söhne Rechtsanwälte AG"
    )
    assert company["city"] == manifest["cases"]["PLANT-A20"]["expected_city"] == "Zürich"


def test_duplicate_pairs_have_the_correct_primary(generated: GeneratedData, manifest: dict) -> None:
    companies = generated.planted_records["PLANT-A09"]["hubspot_companies"]
    assert [row["domain"] for row in companies] == ["acme-legal.ch", "https://www.ACME-legal.ch/"]
    contacts = generated.planted_records["PLANT-A14"]["hubspot_contacts"]
    assert [row["email"] for row in contacts] == [
        "Anna.Keller@kanzlei-keller.ch",
        "anna.keller@kanzlei-keller.ch ",
    ]
    for case, rows, key in [
        ("PLANT-A09", companies, "company_id"),
        ("PLANT-A14", contacts, "contact_id"),
    ]:
        primary, secondary = sorted(rows, key=lambda row: row["created_at"])
        merge = manifest["cases"][case]["expected_proposals"][0]
        assert merge["primary_id"] == primary[key]
        assert merge["secondary_id"] == secondary[key]


@pytest.mark.parametrize(
    ("case_id", "days"),
    [
        ("PLANT-A10", 31),
        ("PLANT-A11", 30),
        ("PLANT-R04", 31),
        ("PLANT-R05", 30),
        ("PLANT-R12", 40),
        ("PLANT-R21", 40),
        ("PLANT-R29", 40),
    ],
)
def test_exact_age_boundaries(case_id: str, days: int, generated: GeneratedData) -> None:
    deal = _row(generated.planted_records[case_id], "hubspot_deals", "deal_id", case_id)
    column = "close_date" if case_id.startswith("PLANT-A") else "contract_start"
    assert (date(2026, 10, 31) - deal[column]).days == days


def test_impossible_dates_only_change_the_requested_field(generated: GeneratedData) -> None:
    cases = generated.planted_records
    assert _only(cases["PLANT-A16"], "hubspot_deals")["close_date"] == date(2026, 11, 10)
    deal = _only(cases["PLANT-A17"], "hubspot_deals")
    assert deal["contract_end"] < deal["contract_start"]
    deal = _only(cases["PLANT-A18"], "hubspot_deals")
    assert deal["term_months"] == 12
    assert deal["contract_end"] == add_months(deal["contract_start"], 24)


def test_push_cases_have_isolated_failures(generated: GeneratedData, manifest: dict) -> None:
    cases = generated.planted_records
    assert _only(cases["PLANT-P01"], "hubspot_deals")["company_ids"] == "PLANT-C-P01a;PLANT-C-P01b"
    assert _only(cases["PLANT-P02"], "hubspot_companies")["younium_account_number"] is None
    assert "hubspot_line_items" not in cases["PLANT-P03"]
    assert _only(cases["PLANT-P04"], "hubspot_deals")["billing_frequency"] is None
    gap = cases["PLANT-P05"]
    amount = _only(gap, "hubspot_deals")["amount"]
    item_total = sum(row["amount"] for row in gap["hubspot_line_items"])
    assert (amount - item_total) / amount == Decimal("0.09")
    expected = [["P1"], ["P2"], ["P3", "P5"], ["P4"], ["P5"], []]
    for index, reasons in enumerate(expected, 1):
        case_id = f"PLANT-P{index:02d}"
        assert manifest["cases"][case_id]["expected_push_reasons"] == reasons
        assert _only(cases[case_id], "hubspot_deals")["contract_start"] == date(2026, 10, 28)
        assert "younium_orders" not in cases[case_id]


@pytest.mark.parametrize(
    ("case_id", "amount", "mrr", "pct"),
    [
        ("PLANT-R01", "30000", "2500", "0"),
        ("PLANT-R02", "24000", "2040", "2.0"),
        ("PLANT-R03", "24000", "2042", "2.1"),
        ("PLANT-R11", "12000", "800", "20"),
    ],
)
def test_exact_recurring_amounts(
    case_id: str, amount: str, mrr: str, pct: str, generated: GeneratedData, manifest: dict
) -> None:
    records = generated.planted_records[case_id]
    deal = _only(records, "hubspot_deals")
    charge = _only(records, "younium_order_charges")
    assert deal["amount"] == Decimal(amount)
    assert charge["mrr"] == Decimal(mrr)
    difference = abs(charge["mrr"] * 12 - deal["amount"])
    assert difference / deal["amount"] * 100 == Decimal(pct)
    if "R3" in manifest["cases"][case_id]["expected_checks"]:
        assert difference == manifest["cases"][case_id]["money_at_risk_chf"]["R3"]


def test_fx_seats_and_unbilled_changes(generated: GeneratedData) -> None:
    cases = generated.planted_records
    fx = cases["PLANT-R09"]
    assert _only(fx, "hubspot_deals")["currency"] == "EUR"
    assert _only(fx, "younium_orders")["currency"] == "CHF"
    assert (
        _only(fx, "hubspot_deals")["amount"] * Decimal("0.94")
        == _only(fx, "younium_order_charges")["mrr"] * 12
    )
    seats = cases["PLANT-R11"]
    assert _only(seats, "hubspot_line_items")["quantity"] == 10
    assert _only(seats, "younium_order_charges")["quantity"] == 8
    assert _only(seats, "hubspot_line_items")["unit_price"] == Decimal("1200")
    for case, motion in [("PLANT-R12", "upsell"), ("PLANT-R29", "renewal")]:
        assert _row(cases[case], "hubspot_deals", "deal_id", case)["motion"] == motion
        assert not any(row["hubspot_deal_id"] == case for row in cases[case]["younium_orders"])


def test_matching_and_quarantine_inputs(generated: GeneratedData, manifest: dict) -> None:
    cases = generated.planted_records
    account = _only(cases["PLANT-R06"], "younium_accounts")
    assert account["hubspot_company_id"] is None
    assert _only(cases["PLANT-R06"], "hubspot_companies")["domain"] in account["domain"]
    assert (
        _only(cases["PLANT-R07"], "younium_accounts")["domain"] == "https://www.acme-legal.ch/path"
    )
    assert (
        _only(cases["PLANT-Q01"], "younium_accounts")["domain"]
        in load_rules().generic_email_domains
    )
    assert _only(cases["PLANT-Q03"], "younium_accounts")["hubspot_company_id"] == "1.23457E+11"
    assert _only(cases["PLANT-Q04"], "younium_invoices")["amount"] == "n/a"
    assert _only(cases["PLANT-Q05"], "younium_invoices")["service_period_start"] == "not-a-date"
    assert _only(cases["PLANT-Q02"], "hubspot_deals")["currency"] == "USD"
    assert _only(cases["PLANT-Q02"], "younium_orders")["currency"] == "USD"
    assert "USD" not in {row["currency"] for row in generated.tables["ref_fx_rates"]}
    assert manifest["cases"]["PLANT-Q02"]["expected_checks"] == []
    assert _only(cases["PLANT-R08"], "hubspot_deals")["amount"] is None
    assert _only(cases["PLANT-R08"], "younium_order_charges")["mrr"] > 0


def test_renewal_cancellation_and_credit_inputs(generated: GeneratedData, manifest: dict) -> None:
    cases = generated.planted_records
    for case, auto_renew in [("PLANT-R13", False), ("PLANT-R14", True)]:
        order = _only(cases[case], "younium_orders")
        assert order["auto_renew"] == auto_renew
        assert (order["effective_end"] - date(2026, 10, 31)).days == 45
    for case in ("PLANT-R15", "PLANT-R16"):
        order = _only(cases[case], "younium_orders")
        assert order["cancellation_date"] == date(2026, 8, 31)
        invoices = cases[case]["younium_invoices"]
        assert all(
            row["status"] == "Posted"
            and row["service_period_start"] == date(2026, 9, 1)
            and row["service_period_end"] == date(2026, 9, 30)
            for row in invoices
        )
        assert sum(row["is_credit"] for row in invoices) == (case == "PLANT-R16")
    order = _only(cases["PLANT-R25"], "younium_orders")
    assert order["status"] == "Cancelled" and order["cancellation_date"] == date(2026, 9, 30)
    assert _only(cases["PLANT-R25"], "hubspot_contacts")["lifecycle_stage"] == "customer"
    accounts = cases["PLANT-R26"]["younium_accounts"]
    assert len(accounts) == 2 and len({row["hubspot_company_id"] for row in accounts}) == 1
    assert manifest["cases"]["PLANT-R14"]["money_at_risk_chf"] == {"R7": 0}


def test_draft_duplicate_push_and_version_changes(generated: GeneratedData) -> None:
    cases = generated.planted_records
    assert _only(cases["PLANT-R21"], "younium_orders")["status"] == "Draft"
    duplicates = cases["PLANT-R22"]["younium_orders"]
    assert len(duplicates) == 2
    assert len({row["hubspot_deal_id"] for row in duplicates}) == 1
    assert [row["order_number"] for row in duplicates] == ["PLANT-O-R22", "PLANT-O-R22b"]
    for case, expected_change in [("PLANT-R23", Decimal("100")), ("PLANT-R24", Decimal("0"))]:
        orders = cases[case]["younium_orders"]
        charges = cases[case]["younium_order_charges"]
        assert [row["version"] for row in orders] == [1, 2]
        assert orders[1]["hubspot_deal_id"] is None
        assert charges[1]["mrr"] - charges[0]["mrr"] == expected_change
        assert charges[0]["effective_end"] == charges[1]["effective_start"]
    assert cases["PLANT-R24"]["younium_orders"][1]["effective_start"] == date(2026, 9, 30)


@pytest.mark.parametrize(
    ("case", "month", "arr"),
    [
        ("PLANT-R17", date(2026, 10, 31), Decimal("12000")),
        ("PLANT-R27", date(2026, 10, 31), Decimal("18000")),
        ("PLANT-R28", date(2026, 9, 30), Decimal("12000")),
        ("PLANT-R28", date(2026, 10, 31), Decimal("0")),
    ],
)
def test_arr_fixture_charge_types_and_exclusive_end(
    case: str,
    month: date,
    arr: Decimal,
    generated: GeneratedData,
    manifest: dict,
) -> None:
    charges = generated.planted_records[case]["younium_order_charges"]
    recurring = sum(
        row["mrr"] * 12
        for row in charges
        if row["charge_type"] == "Recurring"
        and row["effective_start"] <= month < row["effective_end"]
    )
    assert (
        recurring == arr == manifest["cases"][case]["expected_billing_arr_chf"][month.isoformat()]
    )
    if case == "PLANT-R17":
        assert next(row for row in charges if row["charge_type"] == "One-off")["price"] == 5000
    if case == "PLANT-R27":
        assert next(row for row in charges if row["charge_type"] == "Usage")["mrr"] > 0


def test_clean_case_has_consistent_evidence_and_billing(
    generated: GeneratedData, manifest: dict
) -> None:
    records = generated.planted_records["PLANT-A13"]
    deal = _only(records, "hubspot_deals")
    assert deal["stage"] == "closedwon"
    assert _only(records, "hubspot_contacts")["lifecycle_stage"] == "customer"
    assert deal["amount"] == _only(records, "younium_order_charges")["mrr"] * 12
    assert _only(records, "younium_orders")["hubspot_deal_id"] == deal["deal_id"]
    assert _only(records, "younium_accounts")["hubspot_company_id"] == "PLANT-A13"
    assert manifest["cases"]["PLANT-A13"]["expected_checks"] == []
