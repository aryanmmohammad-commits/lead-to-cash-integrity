# Lead-to-cash integrity

[![CI](https://github.com/aryanmmohammad-commits/lead-to-cash-integrity/actions/workflows/ci.yml/badge.svg)](https://github.com/aryanmmohammad-commits/lead-to-cash-integrity/actions/workflows/ci.yml)

A closed-won deal in HubSpot does not prove that billing started, that the right number of
seats was billed, or that a renewal made it back into CRM. This independent B2B SaaS demo
compares HubSpot CRM with Younium billing, finds where data and money do not line up,
explains the annual recurring revenue (ARR) gap in CHF, and proposes fixes for human review.
All data is synthetic.

`HubSpot + Younium files -> raw loader -> dbt in DuckDB -> checks + ARR bridge -> HTML + Excel + fix proposals -> human review`

Think of three desks. Push readiness is the check-in desk before a deal is pushed to
Younium: are its company, line items and contract fields complete? Reconciliation is
passport control after the push: did the subscription arrive, and do its dates, seats and
recurring value agree with CRM? The review workbook is a side room where a person decides
what to fix, accept or investigate. v0.1 produces the findings and proposals; importing
those decisions and applying approved changes are roadmap work.

## What you get

These are actual outputs from `l2c run --seed 42`, using the fixed as-of date **2026-10-31**:
**CRM ARR CHF 826,224**, **billing ARR CHF 736,008**, **gap CHF -90,216**.

- `out/report.html`: a self-contained report with the scorecard, ARR gap waterfall,
  push readiness, exceptions grouped by owner and quarantine counts.
- `out/review.xlsx`: six tabs: Scorecard, Exceptions, Fixes, Push readiness, ARR bridge and
  Quarantine. Yellow decision, reason, assignee and approval cells start empty for review.
- `out/fix_proposals.csv`: eight proposals, each with an empty `approved` column.
- `l2c slack`: an offline digest with ARR totals, the scorecard summary and the top five
  exceptions. Sending requires `--send` and `SLACK_WEBHOOK_URL`.

Three rows from `audit_scorecard` (P aggregates the five push checks):

| Check | Description | Rows checked | Rows failed | Pass rate |
| --- | --- | ---: | ---: | ---: |
| A1 | Invalid or missing contact lifecycle | 136 | 2 | 98.53% |
| P | Won new deals ready for billing push | 10 | 6 | 40.00% |
| R1 | Won new deal not billed after grace period | 71 | 2 | 97.18% |

The `PLANT-R04` exception row:

| check_id | severity | object_type | record_id | owner_id | reason | money_at_risk_chf |
| --- | --- | --- | --- | --- | --- | ---: |
| R1 | leak | deal | PLANT-R04 | OWN-000001 | no order | 18,000.00 |

Its `details` evidence is:

```json
{"amount":18000.000000000000,"currency":"CHF","contract_start":"2026-09-30","has_draft_order":false}
```

The same deal is **OVERDUE**, 31 days after contract start, with the reason
"contract started 31 days ago; billing grace period is 30 days". Its `failed_checks` is
empty: the source data passes push checks, but billing has not started.

The bridge below lists every category. The waterfall starts at **CHF 0**, shows the
non-zero categories in descending absolute amount, and ends at the total gap.

| Bridge category | Signed amount (CHF) |
| --- | ---: |
| Not yet billed | -90,000 |
| CRM data gaps (blank amount or dates) | +36,000 |
| Won not billed | -30,000 |
| Value mismatch | -19,896 |
| Billed not in CRM | +12,000 |
| Double billed | +12,000 |
| Quarantined | -12,000 |
| Renewed in billing only | +12,000 |
| Timing | -12,000 |
| Billing only change | +1,200 |
| Within tolerance | +480 |
| Unexplained (zero; no bar) | 0 |
| **Total gap: billing minus CRM** | **-90,216** |

A positive bar means billing ARR is higher than CRM ARR for that cause; a negative bar
means it is lower.

`crm_data_gaps` is the database category behind **CRM data gaps (blank amount or dates)**.
It contains three billed contracts, each contributing CHF 12,000:

| CRM deal | Billing order | CRM data gap |
| --- | --- | --- |
| PLANT-A08 | PLANT-O-A08 | Blank contract end |
| PLANT-A17 | PLANT-O-A17 | Contract end before its start |
| PLANT-R08 | PLANT-O-R08 | Blank amount |

They stay visible as audit findings while their billing ARR remains in the independent
billing total. No CRM value or dates are invented to make the bridge balance.

One real fix proposal is `PLANT-A03`: change contact `lifecyclestage` from `customer` to
`lead`, with `requires_clear_first = true`. It is a proposal for review; v0.1 does not apply it.
The Slack preview begins:

```text
Lead-to-cash integrity as of 2026-10-31
CRM ARR: CHF 826,224.00
Billing ARR: CHF 736,008.00
ARR gap (billing minus CRM): CHF -90,216.00
Scorecard: 27 checks; 27 with findings; 0 without findings.
Top 5 exceptions by money at risk:
1. R1 PLANT-R04: CHF 18,000.00; leak; owner OWN-000001; no order
```

## A net ARR gap hides problems that cancel each other out

The CHF -90,216 net gap combines **CHF +73,680** and **CHF -163,896** of contributions.
For example, CHF +12,000 of duplicate billing and CHF -12,000 of timing differences
cancel in the total even though both need investigation. A small net gap would not prove
that CRM and billing agree. The bridge explains the causes; the exception rows identify
the records. Money at risk is a separate measure and should not be summed as the ARR gap.

## Run it in five commands

Requires Python 3.11 or later. From the repository root in PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e .
.venv\Scripts\l2c.exe run
.venv\Scripts\l2c.exe show exceptions --where "record_id = 'PLANT-R04'"
.venv\Scripts\l2c.exe show arr_bridge
```

Open `out/report.html` and `out/review.xlsx`. On Linux, use `.venv/bin/python` and
`.venv/bin/l2c` for the same commands. The default seed is 42. `run` executes generation,
loading, dbt build/tests, proposal export and reporting, stopping at the first failure.

`L2C_DB_PATH` selects another database. `--raw-dir` and `--output-dir` select input and
output folders; `--mapping` overrides `L2C_MAPPING`. For another format, run
`l2c run --format de` (or `ch`, `hubspot_ui`). The loader's row-count sanity gate remains
on; `--force` explicitly overrides a large row-count drop.

For a stress run, `l2c generate --profile large --scale 10` scales only the background;
follow it with `l2c load`, `l2c build` and `l2c report`. `l2c run` generates the small demo.
Refresh an existing build's outputs with `l2c fixes propose` and `l2c report`.

## Checks and what each planted case proves

Audit checks A1-A13 cover CRM foundations; P1-P5 cover a new deal's readiness to enter
billing; R1-R12 reconcile CRM with subscriptions, versions, invoices and renewals.
Q findings quarantine unreliable source records. Check IDs and fixture IDs are distinct:
for example, `PLANT-A13` is the clean control, while check A13 detects unknown owners.

[tests/planted_cases.yml](tests/planted_cases.yml) is the exact expected-result contract
for all 61 cases, including supporting record IDs, checks, proposals, owners, severity,
push status, CHF money at risk, quarantine and ARR contributions. Tests run the pipeline
once into a session-scoped temporary database and compare every case with that contract.

| Audit case | What it proves |
| --- | --- |
| PLANT-A01 | Blank lifecycle raises A1; open-deal evidence proposes opportunity. |
| PLANT-A02 | Unknown lifecycle raises A1; won-deal evidence proposes customer. |
| PLANT-A03 | Customer without a won deal raises A2; moving back to lead requires clearing first. |
| PLANT-A04 | SQL with a won deal raises A2 and proposes customer. |
| PLANT-A05 | Customer with lead status NEW raises A3 and proposes clearing it. |
| PLANT-A06 | Blank original source raises A4; no write proposal for a calculated property. |
| PLANT-A07 | Blank unbilled amount raises A5 and P5; push is BLOCKED. |
| PLANT-A08 | Blank contract end raises A6; billing ARR goes to CRM data gaps (blank amount or dates). |
| PLANT-A09 | Cleaned duplicate company domains raise A7; the oldest company is primary. |
| PLANT-A10 | Open deal beyond the stale limit raises A8. |
| PLANT-A11 | Exactly at the stale limit passes A8. |
| PLANT-A12 | Blank territory raises A9; country determines the territory proposal. |
| PLANT-A13 | A fully consistent CRM/billing bundle raises no check. |
| PLANT-A14 | Email case and spaces do not hide duplicates; A10 keeps the oldest contact. |
| PLANT-A15 | Contact without a company raises A11. |
| PLANT-A16 | Future close date raises A12. |
| PLANT-A17 | Contract end before start raises A12 and CRM data gaps (blank amount or dates). |
| PLANT-A18 | Term/date mismatch raises A12. |
| PLANT-A19 | Unknown owner raises A13 and routes the finding to unassigned. |
| PLANT-A20 | Umlauts and other Unicode text survive all four export formats. |

| Push case | What it proves |
| --- | --- |
| PLANT-P01 | Two associated companies fail P1; BLOCKED. |
| PLANT-P02 | Missing Younium account number fails P2; BLOCKED. |
| PLANT-P03 | No line items fail P3 and P5; both reasons remain visible; BLOCKED. |
| PLANT-P04 | Blank billing frequency fails P4; BLOCKED. |
| PLANT-P05 | Line-item/deal amount difference fails P5; BLOCKED. |
| PLANT-P06 | All push checks pass; READY within the billing grace period. |

| Reconciliation case | What it proves |
| --- | --- |
| PLANT-R01 | Equal CRM ACV and recurring billing ARR pass. |
| PLANT-R02 | Exactly at the amount tolerance passes R3; the bridge retains the difference. |
| PLANT-R03 | Beyond the amount tolerance raises R3; the gap is value mismatch. |
| PLANT-R04 | 31 days without an order raises R1 for CHF 18,000; OVERDUE. |
| PLANT-R05 | Exactly 30 days without an order passes R1; READY, still not yet billed. |
| PLANT-R06 | A unique cleaned domain matches when the explicit company ID is absent. |
| PLANT-R07 | A domain matching several companies is quarantined; no company is guessed. |
| PLANT-R08 | Blank matched CRM amount raises A5, skips R3 and contributes to CRM data gaps (blank amount or dates). |
| PLANT-R09 | Currency-equivalent EUR/CHF values pass after FX conversion. |
| PLANT-R11 | Missing billed seats raise R3 and R5 with the expected CHF values. |
| PLANT-R12 | Won upsell without its own billing version raises R6. |
| PLANT-R13 | Renewal approaching with auto-renew off raises R7 as a leak. |
| PLANT-R14 | Auto-renew on makes R7 informational, with zero money at risk. |
| PLANT-R15 | Uncredited posted invoice after cancellation raises R8. |
| PLANT-R16 | A credit for the same order and service period prevents R8. |
| PLANT-R17 | One-off charges stay out of ARR; billing ARR is CHF 12,000. |
| PLANT-R18 | Billing without a won CRM deal raises R2; billed not in CRM. |
| PLANT-R19 | Start dates beyond tolerance raise R4, with no invented money at risk. |
| PLANT-R20 | Exactly at the start-date tolerance passes R4. |
| PLANT-R21 | Draft order never matches; R1 says only a draft order; DRAFT_ONLY. |
| PLANT-R22 | A second order for the same new deal raises R9; double billed. |
| PLANT-R23 | Version 2 changes recurring value without a CRM deal: R10; billing only change. |
| PLANT-R24 | Auto-renew after the CRM term ends is renewed in billing only. |
| PLANT-R25 | Cancelled account with customer contacts raises R11. |
| PLANT-R26 | Two billing accounts for one CRM company raise R12. |
| PLANT-R27 | Usage charges stay out of ARR even with non-zero MRR. |
| PLANT-R28 | Effective end is exclusive; an ended charge contributes no ARR. |
| PLANT-R29 | Won renewal without its own billing version raises R6 and contributes to value mismatch. |

R10 is a check ID; there is no separate `PLANT-R10` fixture. `PLANT-R23` proves that check.

| Quarantine / bridge case | What it proves |
| --- | --- |
| PLANT-Q01 | A generic email domain cannot be used for account matching. |
| PLANT-Q02 | Missing FX quarantines affected records; no CHF rate is invented. |
| PLANT-Q03 | An Excel scientific-notation ID is quarantined. |
| PLANT-Q04 | An unparseable invoice amount is quarantined; raw text stays intact. |
| PLANT-Q05 | An unparseable invoice date is quarantined. |
| PLANT-B01 | Billing starts after month-end: a timing contribution, not unexplained ARR. |
| PLANT-B02 | Deliberately overlapping versions 1 and 2 are both quarantined and excluded from billing ARR. |

Background order versions do not overlap. The default
seed's unexplained bridge amount is zero, and the bridge balances to the cent.

## Design choices

- **Raw stays untouched.** Source values load as text, with run metadata. Parsing happens
  in staging. Each load replaces the raw tables, so a second run does not duplicate rows.
- **Quarantine instead of guessing.** Ambiguous matches, overlapping versions, broken IDs,
  bad dates/numbers and missing FX retain their specific causes and raw evidence.
- **Rules and mappings live in config.** `config/rules.yml` owns thresholds, allowed values
  and the as-of date; mappings own source columns, delimiters, encodings, dates, decimal and
  thousands separators, and value maps. Staging uses `src_col` rather than source names.
- **Four formats, identical results.** Default, Swiss (`ch`), German (`de`) and HubSpot UI
  labels (`hubspot_ui`) produce identical exceptions, scorecards and ARR bridges for the
  same seed. Tests also compare the other semantic model outputs.
- **Two independent ARR totals.** Billing uses effective recurring charges; CRM uses active
  closed-won contracts. Month-end FX uses the latest available rate on or before that date.
  One-off and usage charges never contribute billing ARR.
- **Offline and repeatable.** The pipeline uses synthetic files, a fixed seed and temporary
  test databases. Network access is explicit for Slack sending; v0.1 does not write to CRM.

CI runs on pushes and pull requests using Ubuntu and Python 3.11. To verify locally:

```powershell
.venv\Scripts\ruff.exe check .
.venv\Scripts\python.exe -m pytest -q
```

The suite includes two consecutive real `l2c run` calls with identical exceptions,
format equivalence, exact planted-case assertions and a large-profile scale-10 build.

## AI-assisted, human-owned

I used AI assistance to build this demo. I own the business assumptions, code review and
validation. Rules, planted inputs and expected outputs are inspectable; CI checks the
results. A person reviews proposals and decides what should change.

## Limits

This is synthetic data, not a production integration or a representation of Legartis's
systems. Younium field names and endpoints, and the assumption that each order version
carries the deal ID that caused it, need validation in a real tenant. Mappings absorb export
differences, but do not prove that those assumptions hold.

v0.1 produces review artifacts. It does not import workbook decisions, remember exceptions
week to week, run `l2c doctor`, pull source APIs or apply/roll back HubSpot fixes. Those CLI
placeholders print `planned for v0.2 - see README roadmap` and exit with code 1.

## Roadmap v0.2

- Exception memory week to week: new, open, fixed, accepted and reopened findings, a change
  line and scorecard history; import workbook decisions with reasons and assignees.
- Safe live fixes to HubSpot: approved proposals, dry run by default, read before writing,
  clear-before-set where needed, a write log and rollback.
- `l2c doctor`: inspect exports against their mappings before a run, without changing files.
- Read-only HubSpot and Younium API pulls into the same raw-file layout.
- A Kafka consumer for order-changed events, with duplicate-event handling and invalid-event routing.

## Why I built this

I built this as a practical response to a public job posting from Legartis: a small,
inspectable example of checking the handoff between CRM and billing and explaining the
money behind the findings. It is an independent demo on synthetic data, is not affiliated
with Legartis, and uses no Legartis logo or branding.
