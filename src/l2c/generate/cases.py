"""One independent function per planted case; no random values in planted records."""

from collections.abc import Callable
from datetime import timedelta
from decimal import Decimal

from l2c.config import RulesConfig
from l2c.generate.model import Dataset, FixtureBuilder, Row, Scenario, add_months, month_end

CaseFunction = Callable[[FixtureBuilder], None]
CASES: dict[str, CaseFunction] = {}


def planted(case_id: str) -> Callable[[CaseFunction], CaseFunction]:
    def register(function: CaseFunction) -> CaseFunction:
        if case_id in CASES:
            raise ValueError(f"Duplicate planted case {case_id}")
        CASES[case_id] = function
        return function

    return register


def _contact(scenario: Scenario) -> Row:
    assert scenario.contact is not None
    return scenario.contact


def _order(scenario: Scenario) -> Row:
    assert scenario.order is not None
    return scenario.order


def _charge(scenario: Scenario) -> Row:
    assert scenario.charge is not None
    return scenario.charge


@planted("PLANT-A01")
def blank_lifecycle(b: FixtureBuilder) -> None:
    s = b.bundle(main="contact", billed=False, stage=b.rules.open_deal_stages[0])
    _contact(s)["lifecycle_stage"] = None
    s.deal["close_date"] = b.rules.as_of_date + timedelta(days=1)


@planted("PLANT-A02")
def invalid_lifecycle(b: FixtureBuilder) -> None:
    _contact(b.bundle(main="contact"))["lifecycle_stage"] = "lead_old"


@planted("PLANT-A03")
def customer_without_won_deal(b: FixtureBuilder) -> None:
    s = b.bundle(main="contact", billed=False, stage=b.rules.closed_lost_stage)
    _contact(s).update(lifecycle_stage="customer", lead_status=None)


@planted("PLANT-A04")
def sql_with_won_deal(b: FixtureBuilder) -> None:
    _contact(b.bundle(main="contact"))["lifecycle_stage"] = "salesqualifiedlead"


@planted("PLANT-A05")
def customer_lead_status(b: FixtureBuilder) -> None:
    _contact(b.bundle(main="contact"))["lead_status"] = "NEW"


@planted("PLANT-A06")
def missing_original_source(b: FixtureBuilder) -> None:
    _contact(b.bundle(main="contact"))["original_source"] = None


@planted("PLANT-A07")
def missing_amount_unbilled(b: FixtureBuilder) -> None:
    s = b.bundle(billed=False, start=b.rules.as_of_date - timedelta(days=3))
    s.deal["amount"] = None


@planted("PLANT-A08")
def missing_contract_end(b: FixtureBuilder) -> None:
    b.bundle().deal["contract_end"] = None


@planted("PLANT-A09")
def duplicate_companies(b: FixtureBuilder) -> None:
    first = b.company(record_id=b.case_id)
    second = b.company(record_id=b.case_id + "b", suffix="b")
    first["domain"] = "acme-legal.ch"
    second.update(
        domain="https://www.ACME-legal.ch/", created_at=b.rules.as_of_date - timedelta(days=365)
    )
    b.account(first)
    b.account(second, record_id=b.identifier("Y", "b"))


@planted("PLANT-A10")
def stale_open_deal(b: FixtureBuilder) -> None:
    s = b.bundle(billed=False, stage=b.rules.open_deal_stages[0])
    s.deal["close_date"] = b.rules.as_of_date - timedelta(days=b.rules.stale_open_deal_days + 1)


@planted("PLANT-A11")
def stale_boundary(b: FixtureBuilder) -> None:
    s = b.bundle(billed=False, stage=b.rules.open_deal_stages[0])
    s.deal["close_date"] = b.rules.as_of_date - timedelta(days=b.rules.stale_open_deal_days)


@planted("PLANT-A12")
def missing_territory(b: FixtureBuilder) -> None:
    b.bundle(main="company").company.update(country="Germany", city="Berlin", territory=None)


@planted("PLANT-A13")
def fully_clean(b: FixtureBuilder) -> None:
    b.bundle(main="company")


@planted("PLANT-A14")
def duplicate_contacts(b: FixtureBuilder) -> None:
    s = b.bundle(main="contact")
    first = _contact(s)
    first["email"] = "Anna.Keller@kanzlei-keller.ch"
    second = b.contact(s.company, record_id=b.case_id + "b")
    second.update(
        email="anna.keller@kanzlei-keller.ch ", created_at=b.rules.as_of_date - timedelta(days=365)
    )


@planted("PLANT-A15")
def orphan_contact(b: FixtureBuilder) -> None:
    s = b.bundle(main="contact", billed=False, stage=b.rules.closed_lost_stage)
    _contact(s)["company_id"] = None


@planted("PLANT-A16")
def future_close(b: FixtureBuilder) -> None:
    b.bundle().deal["close_date"] = b.rules.as_of_date + timedelta(days=10)


@planted("PLANT-A17")
def impossible_contract_end(b: FixtureBuilder) -> None:
    s = b.bundle()
    s.deal["contract_end"] = s.deal["contract_start"] - timedelta(days=1)


@planted("PLANT-A18")
def term_mismatch(b: FixtureBuilder) -> None:
    s = b.bundle()
    s.deal["contract_end"] = add_months(s.deal["contract_start"], 24)


@planted("PLANT-A19")
def unknown_owner(b: FixtureBuilder) -> None:
    b.bundle().deal["owner_id"] = "PLANT-MISSING-OWNER"


@planted("PLANT-A20")
def umlaut_company(b: FixtureBuilder) -> None:
    s = b.bundle(main="company")
    s.company.update(name="Müller & Söhne Rechtsanwälte AG", city="Zürich")
    s.account["name"] = s.company["name"]


def _pending(b: FixtureBuilder) -> Scenario:
    return b.bundle(billed=False, start=b.rules.as_of_date - timedelta(days=3))


@planted("PLANT-P01")
def two_associated_companies(b: FixtureBuilder) -> None:
    s = _pending(b)
    s.company["company_id"] = "PLANT-C-P01a"
    s.account["hubspot_company_id"] = s.company["company_id"]
    _contact(s)["company_id"] = s.company["company_id"]
    second = b.company(record_id="PLANT-C-P01b", suffix="b")
    b.account(second, record_id=b.identifier("Y", "b"))
    s.deal["company_ids"] = "PLANT-C-P01a;PLANT-C-P01b"


@planted("PLANT-P02")
def unsynced_company(b: FixtureBuilder) -> None:
    s = _pending(b)
    s.company["younium_account_number"] = None
    b.data["younium_accounts"].remove(s.account)
    b.records["younium_accounts"].remove(s.account)


@planted("PLANT-P03")
def no_line_items(b: FixtureBuilder) -> None:
    s = _pending(b)
    b.data["hubspot_line_items"].remove(s.line_item)
    b.records["hubspot_line_items"].remove(s.line_item)


@planted("PLANT-P04")
def no_billing_frequency(b: FixtureBuilder) -> None:
    _pending(b).deal["billing_frequency"] = None


@planted("PLANT-P05")
def line_item_gap(b: FixtureBuilder) -> None:
    s = _pending(b)
    s.line_item.update(unit_price=Decimal("1092"), amount=Decimal("10920"))


@planted("PLANT-P06")
def push_ready(b: FixtureBuilder) -> None:
    _pending(b)


@planted("PLANT-R01")
def equal_arr(b: FixtureBuilder) -> None:
    b.bundle(amount=Decimal("30000"))


@planted("PLANT-R02")
def amount_tolerance_boundary(b: FixtureBuilder) -> None:
    s = b.bundle(amount=Decimal("24000"))
    _charge(s).update(mrr=Decimal("2040"), price=Decimal("2448"))
    b.records["younium_bookings"][0]["cmrr_change"] = Decimal("2040")


@planted("PLANT-R03")
def amount_mismatch(b: FixtureBuilder) -> None:
    s = b.bundle(amount=Decimal("24000"))
    _charge(s).update(mrr=Decimal("2042"), price=Decimal("2450.40"))
    b.records["younium_bookings"][0]["cmrr_change"] = Decimal("2042")


@planted("PLANT-R04")
def won_not_billed(b: FixtureBuilder) -> None:
    b.bundle(
        billed=False,
        amount=Decimal("18000"),
        start=b.rules.as_of_date - timedelta(days=b.rules.won_not_billed_days + 1),
    )


@planted("PLANT-R05")
def billing_grace_boundary(b: FixtureBuilder) -> None:
    b.bundle(
        billed=False,
        amount=Decimal("18000"),
        start=b.rules.as_of_date - timedelta(days=b.rules.won_not_billed_days),
    )


@planted("PLANT-R06")
def account_match_by_domain(b: FixtureBuilder) -> None:
    s = b.bundle(main="account")
    s.account.update(
        hubspot_company_id=None, domain=f"https://www.{s.company['domain']}/legal/contracts"
    )


@planted("PLANT-R07")
def ambiguous_account(b: FixtureBuilder) -> None:
    company = b.company()
    account = b.account(company, record_id=b.case_id)
    account.update(hubspot_company_id=None, domain="https://www.acme-legal.ch/path")
    # A non-CRM billing order proves quarantine suppresses the would-be R2.
    start = b.rules.as_of_date - timedelta(days=60)
    deal = {
        "deal_id": None,
        "contract_start": start,
        "contract_end": add_months(start, 12),
        "amount": Decimal("12000"),
    }
    item = {"sku": "LGT-SEAT", "quantity": 10, "unit_price": Decimal("1200")}
    b.subscription(account, deal, item)


@planted("PLANT-R08")
def missing_amount_matched(b: FixtureBuilder) -> None:
    b.bundle().deal["amount"] = None


@planted("PLANT-R09")
def currency_equivalence(b: FixtureBuilder) -> None:
    s = b.bundle(amount=Decimal("24000"), currency="EUR")
    s.account["currency"] = "CHF"
    _order(s)["currency"] = "CHF"
    _charge(s).update(mrr=Decimal("1880"), price=Decimal("2256"))
    b.records["younium_bookings"][0].update(currency="CHF", cmrr_change=Decimal("1880"))


@planted("PLANT-R11")
def missing_billed_seats(b: FixtureBuilder) -> None:
    s = b.bundle()
    _charge(s).update(quantity=8, mrr=Decimal("800"))
    b.records["younium_bookings"][0]["cmrr_change"] = Decimal("800")


@planted("PLANT-R12")
def unbilled_upsell(b: FixtureBuilder) -> None:
    s = b.bundle(main="company", start=b.rules.as_of_date - timedelta(days=180))
    b.deal(
        s.company,
        record_id=b.case_id,
        motion="upsell",
        amount=Decimal("6000"),
        start=b.rules.as_of_date - timedelta(days=40),
    )


def _renewal_window(b: FixtureBuilder, auto_renew: bool) -> None:
    end = b.rules.as_of_date + timedelta(days=45)
    s = b.bundle(main="order", start=add_months(end, -12), end=end)
    _order(s)["auto_renew"] = auto_renew


@planted("PLANT-R13")
def renewal_risk(b: FixtureBuilder) -> None:
    _renewal_window(b, False)


@planted("PLANT-R14")
def auto_renew_info(b: FixtureBuilder) -> None:
    _renewal_window(b, True)


def _cancelled_invoice(b: FixtureBuilder) -> tuple[Scenario, Row]:
    cancellation = month_end(add_months(b.rules.as_of_date, -2))
    s = b.bundle(
        main="company",
        contact=False,
        start=add_months(cancellation, -12),
        end=cancellation,
        status="Cancelled",
    )
    _order(s)["cancellation_date"] = cancellation
    invoice = b.invoice(
        _order(s),
        record_id=b.case_id,
        start=cancellation + timedelta(days=1),
        end=month_end(add_months(b.rules.as_of_date, -1)),
    )
    return s, invoice


@planted("PLANT-R15")
def invoice_after_cancellation(b: FixtureBuilder) -> None:
    _cancelled_invoice(b)


@planted("PLANT-R16")
def credited_invoice(b: FixtureBuilder) -> None:
    s, invoice = _cancelled_invoice(b)
    b.invoice(
        _order(s),
        record_id=b.case_id + "-CREDIT",
        amount=Decimal("-1000"),
        start=invoice["service_period_start"],
        end=invoice["service_period_end"],
        credit=True,
    )


@planted("PLANT-R17")
def exclude_one_off(b: FixtureBuilder) -> None:
    s = b.bundle()
    charge = dict(_charge(s))
    charge.update(
        charge_id=b.identifier("CH", "-ONBOARDING"),
        sku="LGT-ONBOARDING",
        product="Onboarding",
        charge_plan="One-off onboarding",
        charge_type="One-off",
        quantity=1,
        price=Decimal("5000"),
        mrr=Decimal("0"),
    )
    b.add("younium_order_charges", **charge)


@planted("PLANT-R18")
def order_without_crm_deal(b: FixtureBuilder) -> None:
    s = b.bundle(main="order", stage=b.rules.closed_lost_stage)
    _order(s)["hubspot_deal_id"] = None


@planted("PLANT-R19")
def start_date_mismatch(b: FixtureBuilder) -> None:
    s = b.bundle()
    start = s.deal["contract_start"] + timedelta(days=b.rules.start_date_tolerance_days + 1)
    _order(s)["effective_start"] = start
    _charge(s)["effective_start"] = start
    b.records["younium_bookings"][0]["booking_date"] = start


@planted("PLANT-R20")
def start_date_boundary(b: FixtureBuilder) -> None:
    s = b.bundle()
    start = s.deal["contract_start"] + timedelta(days=b.rules.start_date_tolerance_days)
    _order(s)["effective_start"] = start
    _charge(s)["effective_start"] = start
    b.records["younium_bookings"][0]["booking_date"] = start


@planted("PLANT-R21")
def only_draft_order(b: FixtureBuilder) -> None:
    b.bundle(status="Draft", start=b.rules.as_of_date - timedelta(days=40))


@planted("PLANT-R22")
def duplicate_push(b: FixtureBuilder) -> None:
    s = b.bundle()
    order, _ = b.subscription(s.account, s.deal, s.line_item, record_id=b.identifier("O", "b"))
    assert str(_order(s)["order_number"]) < str(order["order_number"])


@planted("PLANT-R23")
def billing_only_expansion(b: FixtureBuilder) -> None:
    s = b.bundle(main="order", start=b.rules.as_of_date - timedelta(days=180))
    b.next_version(
        s,
        start=b.rules.as_of_date - timedelta(days=30),
        end=s.deal["contract_end"],
        mrr=Decimal("1100"),
        quantity=11,
    )


@planted("PLANT-R24")
def billing_only_renewal(b: FixtureBuilder) -> None:
    end = month_end(add_months(b.rules.as_of_date, -1))
    s = b.bundle(main="order", start=add_months(end, -12), end=end, status="Expired")
    b.next_version(s, start=end, end=add_months(end, 12), mrr=Decimal("1000"), event="renewal")


@planted("PLANT-R25")
def cancelled_customer(b: FixtureBuilder) -> None:
    end = month_end(add_months(b.rules.as_of_date, -1))
    s = b.bundle(main="account", start=add_months(end, -12), end=end, status="Cancelled")
    _order(s)["cancellation_date"] = end


@planted("PLANT-R26")
def duplicate_billing_accounts(b: FixtureBuilder) -> None:
    s = b.bundle(main="account")
    b.account(s.company, record_id=b.case_id + "b")
    s.company["younium_account_number"] = s.account["account_number"]


@planted("PLANT-R27")
def exclude_usage(b: FixtureBuilder) -> None:
    s = b.bundle(amount=Decimal("18000"))
    charge = dict(_charge(s))
    charge.update(
        charge_id=b.identifier("CH", "-USAGE"),
        sku="LGT-REVIEW-PACK",
        product="Review pack",
        charge_plan="Monthly usage",
        charge_type="Usage",
        quantity=10,
        price=Decimal("50"),
        mrr=Decimal("500"),
        billing_period="Monthly",
    )
    b.add("younium_order_charges", **charge)


@planted("PLANT-R28")
def exclusive_charge_end(b: FixtureBuilder) -> None:
    start = month_end(add_months(b.rules.as_of_date, -1))
    s = b.bundle(start=start, end=month_end(b.rules.as_of_date), status="Expired")
    s.deal["term_months"] = 1
    _order(s)["term_months"] = 1


@planted("PLANT-R29")
def unbilled_renewal(b: FixtureBuilder) -> None:
    end = b.rules.as_of_date - timedelta(days=40)
    s = b.bundle(main="company", start=add_months(end, -12), end=end, status="Expired")
    b.deal(s.company, record_id=b.case_id, motion="renewal", start=end)


@planted("PLANT-Q01")
def generic_domain(b: FixtureBuilder) -> None:
    account = b.account(b.company(), record_id=b.case_id)
    account.update(hubspot_company_id=None, domain="gmail.com")


@planted("PLANT-Q02")
def missing_fx(b: FixtureBuilder) -> None:
    b.bundle(currency="USD")


@planted("PLANT-Q03")
def excel_corrupted_id(b: FixtureBuilder) -> None:
    b.account(b.company(), record_id=b.case_id)["hubspot_company_id"] = "1.23457E+11"


@planted("PLANT-Q04")
def unparseable_invoice_amount(b: FixtureBuilder) -> None:
    b.invoice(_order(b.bundle(main="company")), record_id=b.case_id, amount="n/a")


@planted("PLANT-Q05")
def unparseable_invoice_date(b: FixtureBuilder) -> None:
    invoice = b.invoice(_order(b.bundle(main="company")), record_id=b.case_id)
    invoice["service_period_start"] = "not-a-date"


def add_planted_cases(data: Dataset, rules: RulesConfig) -> dict[str, Dataset]:
    records = {}
    for case_id, function in sorted(CASES.items()):
        builder = FixtureBuilder(data, rules, case_id)
        function(builder)
        records[case_id] = {table: rows for table, rows in builder.records.items() if rows}
    return records
