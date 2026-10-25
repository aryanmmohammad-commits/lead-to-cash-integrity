"""A thin deterministic background, independent of the planted-case registry."""

import random
from datetime import timedelta
from decimal import Decimal

from l2c.config import RulesConfig
from l2c.generate.model import Dataset, FixtureBuilder, Row, add_months, month_end


class BackgroundBuilder(FixtureBuilder):
    def identifier(self, kind: str, suffix: str = "") -> str:
        return f"BG-{kind}-{self.case_id}{suffix}"


BackgroundDeal = tuple[BackgroundBuilder, Row, Row, Row]


def _territory(country: str, rules: RulesConfig) -> str:
    return next(
        (name for name, countries in rules.territory_by_country.items() if country in countries),
        rules.default_territory,
    )


def _add_owners(data: Dataset, scale: int) -> None:
    for index in range(6 * scale):
        data["hubspot_owners"].append(
            {
                "owner_id": f"OWN-{index + 1:06d}",
                "name": f"Synthetic Owner Müller {index + 1}",
                "team": "DACH" if index % 2 == 0 else "France",
            }
        )


def _companies(
    data: Dataset, rules: RulesConfig, rng: random.Random, scale: int
) -> tuple[list[Row], dict[str, Row]]:
    companies, accounts = [], {}
    countries = [
        "Switzerland",
        "Germany",
        "Austria",
        "Switzerland",
        "Germany",
        "France",
        "Liechtenstein",
        "Netherlands",
    ]
    for index in range(30 * scale):
        b = BackgroundBuilder(data, rules, f"{index + 1:06d}")
        company = b.company()
        country = rng.choice(countries)
        company.update(
            name=f"Synthetic {rng.choice(['Müller', 'Keller', 'Söhne', 'Zürich'])} "
            f"Rechtsberatung {index + 1} AG",
            country=country,
            territory=_territory(country, rules),
            city="Zürich" if country == "Switzerland" else "Synthetic City",
            owner_id=f"OWN-{index % (6 * scale) + 1:06d}",
            younium_account_number=None,
        )
        companies.append(company)
        if index % 30 < 28:
            account = b.account(company, record_id=f"A-{index + 1:06d}")
            account.update(
                currency="CHF" if index % 5 < 3 else "EUR",
                legal_entity="Legartis Deutschland GmbH"
                if country == "Germany"
                else "Legartis Technology AG",
            )
            accounts[str(company["company_id"])] = account
    # Light background dirt, with every problem type also represented by a planted case.
    companies[-1]["tier"] = None
    return companies, accounts


def _deals(
    data: Dataset, rules: RulesConfig, companies: list[Row], scale: int
) -> list[BackgroundDeal]:
    deals = []
    for index in range(50 * scale):
        block, position = divmod(index, 50)
        company = companies[block * 30 + position % 30]
        b = BackgroundBuilder(data, rules, f"{index + 1:06d}")
        stage = (
            rules.closed_won_stage
            if position < 20
            else rules.closed_lost_stage
            if position < 33
            else rules.open_deal_stages[position % len(rules.open_deal_stages)]
        )
        two_items = position < 40
        amount = Decimal("13200") if two_items else Decimal("12000")
        deal, item = b.deal(
            company,
            amount=amount,
            stage=stage,
            currency="CHF" if (block * 30 + position % 30) % 5 < 3 else "EUR",
            start=add_months(rules.as_of_date.replace(day=1), -5),
        )
        deal["owner_id"] = company["owner_id"]
        if stage in rules.open_deal_stages:
            deal["close_date"] = rules.as_of_date + timedelta(days=position + 1)
        item.update(unit_price=Decimal("1200"), amount=Decimal("12000"))
        if two_items:
            b.add(
                "hubspot_line_items",
                line_item_id=f"{deal['deal_id']}-PLATFORM",
                deal_id=deal["deal_id"],
                sku="LGT-PLATFORM",
                quantity=1,
                unit_price=Decimal("1200"),
                amount=Decimal("1200"),
            )
        deals.append((b, company, deal, item))
    return deals


def _subscriptions(
    deals: list[BackgroundDeal], accounts: dict[str, Row], rules: RulesConfig
) -> None:
    for index, (b, company, deal, item) in enumerate(deals):
        position = index % 50
        if 20 <= position < 40:
            continue
        active = position < 20
        order, charge = b.subscription(
            accounts[str(company["company_id"])],
            deal,
            item,
            record_id=f"O-{index + 1:06d}",
            status="Active" if active else "Draft",
        )
        charge["mrr"] = Decimal("1000")
        if not active:
            continue
        platform = dict(charge)
        platform.update(
            charge_id=f"{order['order_number']}-V1-PLATFORM",
            sku="LGT-PLATFORM",
            product="Platform",
            charge_plan="Annual platform",
            quantity=1,
            mrr=Decimal("100"),
        )
        b.add("younium_order_charges", **platform)
        one_off = dict(charge)
        one_off.update(
            charge_id=f"{order['order_number']}-ONBOARDING",
            sku="LGT-ONBOARDING",
            product="Onboarding",
            charge_plan="One-off onboarding",
            charge_type="One-off",
            quantity=1,
            price=Decimal("5000"),
            mrr=Decimal("0"),
        )
        b.add("younium_order_charges", **one_off)
        if position < 10:
            renewal = dict(order)
            renewal.update(
                version=2,
                hubspot_deal_id=None,
                effective_start=order["effective_end"],
                effective_end=add_months(order["effective_end"], 12),
            )
            b.add("younium_orders", **renewal)
            for previous in (charge, platform):
                future = dict(previous)
                future.update(
                    charge_id=f"{previous['charge_id']}-V2",
                    version=2,
                    effective_start=renewal["effective_start"],
                    effective_end=renewal["effective_end"],
                )
                b.add("younium_order_charges", **future)
            b.booking(renewal, event="renewal", classification="Expansion", change=Decimal("0"))
        for invoice_index in range(13 if position < 10 else 12):
            service_start = add_months(deal["contract_start"], min(invoice_index // 2, 5))
            amount = (
                Decimal("5000")
                if invoice_index == 12
                else Decimal("1000" if invoice_index % 2 == 0 else "100")
            )
            b.invoice(
                order,
                record_id=f"I-{index + 1:06d}-{invoice_index + 1:02d}",
                amount=amount,
                start=service_start,
                end=month_end(service_start),
            )


def _contacts(
    data: Dataset, rules: RulesConfig, rng: random.Random, companies: list[Row], scale: int
) -> None:
    won = {
        row["company_ids"]
        for row in data["hubspot_deals"]
        if row["stage"] == rules.closed_won_stage
    }
    opened = {
        row["company_ids"]
        for row in data["hubspot_deals"]
        if row["stage"] in rules.open_deal_stages
    }
    for index in range(80 * scale):
        company = companies[index % len(companies)]
        contact = BackgroundBuilder(data, rules, f"{index + 1:06d}").contact(company)
        stage = (
            "customer"
            if company["company_id"] in won
            else "opportunity"
            if company["company_id"] in opened
            else "lead"
        )
        if stage == "lead":
            presale = rules.lifecycle_order[1 : rules.lifecycle_order.index("opportunity")]
            stage = presale[index % len(presale)]
        contact.update(
            email=f"person{index + 1}@{company['domain']}",
            lifecycle_stage=stage,
            lead_status=None
            if stage == "customer"
            else "OPEN_DEAL"
            if stage == "opportunity"
            else "NEW",
            owner_id=company["owner_id"],
            original_source=rng.choice(rules.original_source_allowed),
        )
    data["hubspot_contacts"][-1]["original_source"] = None


def add_background(data: Dataset, rules: RulesConfig, *, seed: int, scale: int = 1) -> None:
    rng = random.Random(seed)
    _add_owners(data, scale)
    companies, accounts = _companies(data, rules, rng, scale)
    deals = _deals(data, rules, companies, scale)
    _subscriptions(deals, accounts, rules)
    _contacts(data, rules, rng, companies, scale)


def add_reference_data(data: Dataset, rules: RulesConfig, *, seed: int) -> None:
    # note: Every product, price and FX rate here is synthetic, not market/company data.
    products = [
        ("LGT-PLATFORM", "Platform", "Annual platform", "Recurring", "1200"),
        ("LGT-SEAT", "Seats", "Annual seats", "Recurring", "1200"),
        ("LGT-REVIEW-PACK", "Review pack", "Monthly usage", "Usage", "50"),
        ("LGT-ONBOARDING", "Onboarding", "One-off onboarding", "One-off", "5000"),
    ]
    for sku, product, plan, charge_type, price in products:
        data["ref_product_catalog"].append(
            {
                "sku": sku,
                "product": product,
                "charge_plan": plan,
                "charge_type": charge_type,
                "list_price": Decimal(price),
                "currency": "CHF",
            }
        )
    start = add_months(rules.as_of_date.replace(day=1), -13)
    start = min(start, *(row["booking_date"] for row in data["younium_bookings"]))
    day = start
    while day <= month_end(rules.as_of_date):
        data["ref_fx_rates"].append(
            {"date": day, "currency": "CHF", "rate_to_chf": Decimal("1.0000")}
        )
        day += timedelta(days=1)
    rng = random.Random(seed)
    for offset in range(-12, 1):
        rate = Decimal("0.9400") if offset == 0 else Decimal(rng.randrange(9200, 9701)) / 10000
        data["ref_fx_rates"].append(
            {
                "date": month_end(add_months(rules.as_of_date, offset)),
                "currency": "EUR",
                "rate_to_chf": rate.quantize(Decimal("0.0001")),
            }
        )
