from datetime import date
from pathlib import Path

import pytest
import yaml

from l2c.config import ConfigError, load_mapping, load_rules
from l2c.paths import DEFAULT_MAPPING_PATH, DEFAULT_RULES_PATH


def test_default_configs_are_complete() -> None:
    rules = load_rules()
    mapping = load_mapping(DEFAULT_MAPPING_PATH)

    assert rules.as_of_date == date(2026, 10, 31)
    assert rules.base_currency == "CHF"
    assert rules.customer_lead_status is None
    assert rules.arr_months == 12
    assert set(mapping.tables) == {
        "hubspot_companies",
        "hubspot_contacts",
        "hubspot_deals",
        "hubspot_line_items",
        "hubspot_owners",
        "younium_accounts",
        "younium_orders",
        "younium_order_charges",
        "younium_invoices",
        "younium_bookings",
        "ref_fx_rates",
        "ref_product_catalog",
    }
    assert mapping.tables["hubspot_deals"].columns["company_ids"] == "associated_company_id"
    assert mapping.tables["hubspot_contacts"].columns["lifecycle_stage"] == "lifecyclestage"
    for name, table in mapping.tables.items():
        assert table.file == f"{name}.csv"
        assert table.values == {}
        assert table.format.model_dump() == {
            "delimiter": ",",
            "encoding": "utf-8-sig",
            "date_format": "%Y-%m-%d",
            "decimal": ".",
            "thousands": "",
        }
        if name.startswith(("younium_", "ref_")):
            assert all(canonical == source for canonical, source in table.columns.items())


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("as_of_date", "2026-02-30"),
        ("as_of_date", 0),
        ("base_currency", "chf"),
        ("stale_open_deal_days", -1),
        ("won_not_billed_days", True),
        ("renewal_window_days", 1.5),
        ("arr_months", 0),
        ("sanity_max_drop_pct", 101),
        ("amount_tolerance_pct", float("nan")),
        ("push_line_item_tolerance_pct", -1),
        ("lifecycle_order", []),
        ("lead_status_allowed", ["NEW", "NEW"]),
        ("customer_lead_status", "not-an-allowed-status"),
        ("closed_won_stage", "contractsent"),
        ("closed_lost_stage", "closedwon"),
        ("territory_by_country", {"DACH": ["Germany"], "Other": ["Germany"]}),
        ("unknown_setting", 1),
        ("initial_order_version", 0),
        ("change_deal_motions", ["new", "upsell"]),
        ("months_per_year", 0),
        ("customer_lifecycle_stage", "not-a-stage"),
        ("open_deal_lead_status", "not-a-status"),
        ("auto_renew_severity", "urgent"),
        ("arr_bridge_categories", ["timing", "timing"]),
    ],
)
def test_invalid_rules_name_the_key(tmp_path: Path, key: str, value: object) -> None:
    data = yaml.safe_load(DEFAULT_RULES_PATH.read_text(encoding="utf-8"))
    data[key] = value
    path = tmp_path / "rules.yml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")

    with pytest.raises(ConfigError) as error:
        load_rules(path)

    assert str(path) in str(error.value)
    assert key in str(error.value)


@pytest.mark.parametrize(
    ("section", "key", "value"),
    [
        ("format", "encoding", "not-a-real-codec"),
        ("format", "delimiter", "||"),
        ("format", "date_format", "%Y-%m"),
        ("format", "decimal", "!"),
        ("format", "thousands", "."),
        ("columns", "contact_id", ""),
        ("values", "missing_column", {"Label": "value"}),
    ],
)
def test_invalid_mapping_names_nested_key(
    tmp_path: Path, section: str, key: str, value: object
) -> None:
    data = yaml.safe_load(DEFAULT_MAPPING_PATH.read_text(encoding="utf-8"))
    data["hubspot_contacts"][section][key] = value
    path = tmp_path / "mapping.yml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")

    with pytest.raises(ConfigError) as error:
        load_mapping(path)

    assert f"hubspot_contacts.{section}" in str(error.value)
    assert key in str(error.value)


def test_mapping_supports_german_format_and_ui_value_maps(tmp_path: Path) -> None:
    data = yaml.safe_load(DEFAULT_MAPPING_PATH.read_text(encoding="utf-8"))
    table = data["hubspot_contacts"]
    table["format"].update(delimiter=";", date_format="%d.%m.%Y", decimal=",", thousands=".")
    table["columns"]["lifecycle_stage"] = "Lifecycle Stage"
    table["values"] = {"lifecycle_stage": {"Marketing Qualified Lead": "marketingqualifiedlead"}}
    path = tmp_path / "mapping.yml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8-sig")

    mapped = load_mapping(path).tables["hubspot_contacts"]

    assert mapped.format.decimal == ","
    assert mapped.columns["lifecycle_stage"] == "Lifecycle Stage"
    assert mapped.values["lifecycle_stage"]["Marketing Qualified Lead"] == "marketingqualifiedlead"


@pytest.mark.parametrize("contents", ["{}", "[]", "", "hubspot_contacts: ["])
def test_empty_or_malformed_mapping_is_rejected(tmp_path: Path, contents: str) -> None:
    path = tmp_path / "mapping.yml"
    path.write_text(contents, encoding="utf-8")
    with pytest.raises(ConfigError, match="mapping.yml"):
        load_mapping(path)


def test_missing_config_has_readable_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="Cannot read configuration.*missing.yml"):
        load_rules(tmp_path / "missing.yml")


def test_invalid_unquoted_date_names_the_key(tmp_path: Path) -> None:
    path = tmp_path / "rules.yml"
    path.write_text(
        DEFAULT_RULES_PATH.read_text(encoding="utf-8").replace('"2026-10-31"', "2026-02-30"),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="as_of_date:.*YYYY-MM-DD"):
        load_rules(path)
