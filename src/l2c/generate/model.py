"""Canonical synthetic rows and small helpers shared by planted/background data."""

from calendar import monthrange
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import TypeAlias

from l2c.config import MappingConfig, RulesConfig

Scalar: TypeAlias = str | int | bool | date | Decimal | None
Row: TypeAlias = dict[str, Scalar]
Dataset: TypeAlias = dict[str, list[Row]]


def add_months(day: date, months: int) -> date:
    index = day.year * 12 + day.month - 1 + months
    year, month = divmod(index, 12)
    return date(year, month + 1, min(day.day, monthrange(year, month + 1)[1]))


def month_end(day: date) -> date:
    return day.replace(day=monthrange(day.year, day.month)[1])


def empty_dataset(mapping: MappingConfig) -> Dataset:
    return {name: [] for name in mapping.tables}


@dataclass
class Scenario:
    company: Row
    contact: Row | None
    deal: Row
    account: Row
    order: Row | None
    line_item: Row
    charge: Row | None


@dataclass
class FixtureBuilder:
    data: Dataset
    rules: RulesConfig
    case_id: str
    records: Dataset = field(default_factory=dict)

    @property
    def code(self) -> str:
        return self.case_id.removeprefix("PLANT-")

    def identifier(self, kind: str, suffix: str = "") -> str:
        return f"PLANT-{kind}-{self.code}{suffix}"

    def add(self, table: str, **values: Scalar) -> Row:
        row = dict(values)
        self.data[table].append(row)
        self.records.setdefault(table, []).append(row)
        return row

    def company(self, *, record_id: str | None = None, suffix: str = "") -> Row:
        return self.add(
            "hubspot_companies",
            company_id=record_id or self.identifier("C", suffix),
            name=f"Synthetic {self.code}{suffix} Rechtsberatung AG",
            domain=f"{self.code.lower()}{suffix}.synthetic.example",
            country="Switzerland",
            city="Zürich",
            owner_id="OWN-000001",
            territory="DACH",
            tier="B",
            younium_account_number=self.identifier("Y", suffix),
            created_at=self.rules.as_of_date - timedelta(days=730),
        )

    def contact(self, company: Row, *, record_id: str | None = None) -> Row:
        return self.add(
            "hubspot_contacts",
            contact_id=record_id or self.identifier("T"),
            email=f"person@{company['domain']}",
            company_id=company["company_id"],
            lifecycle_stage="customer",
            lead_status=None,
            original_source=self.rules.original_source_allowed[0],
            owner_id="OWN-000001",
            created_at=self.rules.as_of_date - timedelta(days=700),
        )

    def account(self, company: Row, *, record_id: str | None = None) -> Row:
        account = self.add(
            "younium_accounts",
            account_number=record_id or self.identifier("Y"),
            name=company["name"],
            hubspot_company_id=company["company_id"],
            domain=company["domain"],
            legal_entity="Legartis Technology AG",
            currency="CHF",
        )
        company["younium_account_number"] = account["account_number"]
        return account

    def deal(
        self,
        company: Row,
        *,
        record_id: str | None = None,
        amount: Decimal = Decimal("12000"),
        start: date | None = None,
        end: date | None = None,
        motion: str = "new",
        stage: str | None = None,
        currency: str = "CHF",
        quantity: int = 10,
    ) -> tuple[Row, Row]:
        start = start or self.rules.as_of_date - timedelta(days=60)
        deal = self.add(
            "hubspot_deals",
            deal_id=record_id or self.identifier("D"),
            deal_name=f"Synthetic {self.code} {motion}",
            company_ids=company["company_id"],
            deal_type="newbusiness" if motion == "new" else "existingbusiness",
            motion=motion,
            stage=stage or self.rules.closed_won_stage,
            amount=amount,
            currency=currency,
            close_date=start - timedelta(days=1),
            contract_start=start,
            contract_end=end or add_months(start, 12),
            term_months=12,
            billing_frequency="Annual",
            owner_id="OWN-000001",
            created_at=start - timedelta(days=30),
        )
        item = self.add(
            "hubspot_line_items",
            line_item_id=f"{deal['deal_id']}-LI",
            deal_id=deal["deal_id"],
            sku="LGT-SEAT",
            quantity=quantity,
            unit_price=amount / quantity,
            amount=amount,
        )
        return deal, item

    def subscription(
        self,
        account: Row,
        deal: Row,
        item: Row,
        *,
        record_id: str | None = None,
        status: str = "Active",
        mrr: Decimal | None = None,
    ) -> tuple[Row, Row]:
        order = self.add(
            "younium_orders",
            order_number=record_id or self.identifier("O"),
            version=1,
            account_number=account["account_number"],
            hubspot_deal_id=deal["deal_id"],
            status=status,
            effective_start=deal["contract_start"],
            effective_end=deal["contract_end"],
            term_months=12,
            auto_renew=True,
            cancellation_date=None,
            currency=account["currency"],
        )
        charge = self.add(
            "younium_order_charges",
            charge_id=f"{order['order_number']}-V1-SEAT",
            order_number=order["order_number"],
            version=1,
            sku=item["sku"],
            product="Seats",
            charge_plan="Annual seats",
            charge_type="Recurring",
            quantity=item["quantity"],
            price=item["unit_price"],
            billing_period="Annual",
            mrr=mrr if mrr is not None else Decimal(str(deal["amount"])) / 12,
            effective_start=order["effective_start"],
            effective_end=order["effective_end"],
        )
        self.booking(order, event="activation", classification="New Business", change=charge["mrr"])
        return order, charge

    def booking(self, order: Row, *, event: str, classification: str, change: Scalar) -> Row:
        return self.add(
            "younium_bookings",
            booking_id=f"{order['order_number']}-V{order['version']}-BOOK",
            order_number=order["order_number"],
            version=order["version"],
            event=event,
            classification=classification,
            cmrr_change=change,
            currency=order["currency"],
            booking_date=order["effective_start"],
        )

    def invoice(
        self,
        order: Row,
        *,
        record_id: str | None = None,
        amount: Scalar = Decimal("1000"),
        start: date | None = None,
        end: date | None = None,
        credit: bool = False,
    ) -> Row:
        start = start or self.rules.as_of_date.replace(day=1)
        return self.add(
            "younium_invoices",
            invoice_number=record_id or self.identifier("I"),
            account_number=order["account_number"],
            order_number=order["order_number"],
            status="Posted",
            is_credit=credit,
            amount=amount,
            currency=order["currency"],
            service_period_start=start,
            service_period_end=end or month_end(start),
            posted_date=start,
        )

    def bundle(
        self,
        *,
        main: str = "deal",
        billed: bool = True,
        contact: bool = True,
        amount: Decimal = Decimal("12000"),
        start: date | None = None,
        end: date | None = None,
        stage: str | None = None,
        currency: str = "CHF",
        status: str = "Active",
    ) -> Scenario:
        company = self.company(record_id=self.case_id if main == "company" else None)
        person = (
            self.contact(company, record_id=self.case_id if main == "contact" else None)
            if contact
            else None
        )
        account = self.account(company, record_id=self.case_id if main == "account" else None)
        account["currency"] = currency
        deal, item = self.deal(
            company,
            record_id=self.case_id if main == "deal" else None,
            amount=amount,
            start=start,
            end=end,
            stage=stage,
            currency=currency,
        )
        if person is not None and stage and stage != self.rules.closed_won_stage:
            is_open = stage in self.rules.open_deal_stages
            person.update(
                lifecycle_stage="opportunity" if is_open else "lead",
                lead_status="OPEN_DEAL" if is_open else "NEW",
            )
        order, charge = None, None
        if billed:
            order, charge = self.subscription(
                account,
                deal,
                item,
                record_id=self.case_id if main == "order" else None,
                status=status,
            )
        return Scenario(company, person, deal, account, order, item, charge)

    def next_version(
        self,
        scenario: Scenario,
        *,
        start: date,
        end: date,
        mrr: Decimal,
        quantity: int = 10,
        event: str = "change",
    ) -> tuple[Row, Row]:
        assert scenario.order is not None and scenario.charge is not None
        previous = scenario.charge["mrr"]
        scenario.order["effective_end"] = start
        scenario.charge["effective_end"] = start
        order = self.add("younium_orders", **dict(scenario.order))
        order.update(
            version=2,
            hubspot_deal_id=None,
            effective_start=start,
            effective_end=end,
            status="Active",
            cancellation_date=None,
        )
        charge = self.add("younium_order_charges", **dict(scenario.charge))
        charge.update(
            charge_id=f"{order['order_number']}-V2-SEAT",
            version=2,
            effective_start=start,
            effective_end=end,
            mrr=mrr,
            quantity=quantity,
        )
        change = mrr - Decimal(str(previous))
        self.booking(order, event=event, classification="Expansion", change=change)
        return order, charge
