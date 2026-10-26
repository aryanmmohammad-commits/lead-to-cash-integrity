"""Exact manifest expectations against one session-scoped pipeline run."""

from collections import Counter
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import yaml

from l2c.output_data import read_database

CONTRACT = yaml.safe_load(
    Path(__file__).with_name("planted_cases.yml").read_text(encoding="utf-8")
)


def _query(database: Path, sql: str, parameters: list[Any] | None = None) -> list[tuple]:
    with read_database(database) as connection:
        return connection.execute(sql, parameters or []).fetchall()


@pytest.fixture(scope="module")
def planted_contract() -> dict:
    return CONTRACT


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


@pytest.mark.parametrize("case_id", sorted(CONTRACT["cases"]))
def test_every_planted_check_owner_severity_money_and_proposal_is_exact(
    case_id: str,
    pipeline_db: Path,
    planted_contract: dict,
) -> None:
    database = pipeline_db
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
    deal_ids = [key["deal_id"] for key in case["records"].get("hubspot_deals", [])]
    push = _query(
        database,
        "SELECT deal_id, status, reasons, failed_checks, days_since_contract_start "
        "FROM marts.push_readiness",
    )
    selected = [row for row in push if row[0] in deal_ids]
    if case["expected_push_status"]:
        assert selected == [
            (
                case_id,
                case["expected_push_status"],
                case["expected_push_reasons"],
                case["expected_push_failed_checks"],
                case["expected_days_since_contract_start"],
            )
        ]
    else:
        assert selected == []


@pytest.mark.parametrize("case_id", sorted(CONTRACT["cases"]))
def test_planted_arr_and_signed_bridge_contributions_are_exact(
    case_id: str, pipeline_db: Path, planted_contract: dict
) -> None:
    database = pipeline_db
    case = planted_contract["cases"][case_id]
    rows = _query(
        database,
        "SELECT object_type, record_id, category, amount_chf "
        "FROM intermediate.int_arr_bridge_ledger",
    )
    selected = [row for row in rows if row[:2] in _case_objects(case)]
    if case["bridge_category"]:
        amounts: Counter = Counter()
        for _, _, category, amount in selected:
            if amount:
                amounts[category] += amount
        expected = case.get("bridge_amount_chf")
        if expected is None:
            assert any(row[2] == case["bridge_category"] for row in selected)
            assert not amounts  # Unknown FX is never assigned an invented CHF value.
        else:
            assert amounts == {case["bridge_category"]: Decimal(str(expected))}
    else:
        assert not any(row[3] for row in selected)
    for system, source_table, key in (
        ("billing", "younium_orders", "order_number"),
        ("crm", "hubspot_deals", "deal_id"),
    ):
        ids = sorted({record[key] for record in case["records"].get(source_table, [])})
        for when, expected in case.get(f"expected_{system}_arr_chf", {}).items():
            assert _query(
                database,
                f"SELECT coalesce(sum(arr_chf),0) FROM marts.arr_{system}_monthly "
                f"WHERE month_end = ? AND list_contains(?, {key})",
                [date.fromisoformat(when), ids],
            ) == [(Decimal(str(expected)),)]


def test_default_seed_has_zero_unexplained_and_preserves_the_three_real_causes(
    pipeline_db: Path,
) -> None:
    database = pipeline_db
    assert _query(
        database,
        "SELECT amount_chf FROM marts.arr_bridge WHERE category='unexplained'",
    ) == [(Decimal("0.00"),)]
    assert _query(
        database,
        "SELECT record_id, amount_chf FROM intermediate.int_arr_bridge_ledger "
        "WHERE category='crm_data_gaps' AND amount_chf<>0 ORDER BY record_id",
    ) == [
        ("PLANT-O-A08", Decimal("12000.00")),
        ("PLANT-O-A17", Decimal("12000.00")),
        ("PLANT-O-R08", Decimal("12000.00")),
    ]
    assert _query(
        database,
        "SELECT deal_id, amount IS NULL, contract_end IS NULL, contract_end < contract_start "
        "FROM staging.stg_hubspot__deals "
        "WHERE deal_id IN ('PLANT-A08','PLANT-A17','PLANT-R08') ORDER BY deal_id",
    ) == [
        ("PLANT-A08", False, True, None),
        ("PLANT-A17", False, False, True),
        ("PLANT-R08", True, False, False),
    ]
