# AGENTS.md: rules for any coding agent working in this repo

## What this project is

`lead-to-cash-integrity` is ONE system. It checks a B2B SaaS company's HubSpot CRM against its
billing system (Younium), finds where data and money do not line up, explains the ARR gap, and
proposes fixes that a person approves before anything is written back to HubSpot.

It is an independent demo on synthetic data. No real company data, ever.

The whole flow:

```
HubSpot + Younium files (any format, via mapping.yml) or read-only API pulls
  -> loader (raw, untouched, run ID, sanity gate)
  -> dbt in DuckDB: staging -> intermediate (matching, current versions, FX)
       -> marts: audit A1-A13, push-readiness P1-P5, reconciliation R1-R12, quarantine,
                 exceptions, scorecard, fix proposals, ARR monthly, ARR bridge
  -> exception memory (state schema, owned by Python)
  -> outputs: HTML report, Excel review workbook, Slack digest
  -> people decide in the workbook
  -> fixes apply (dry run by default; live only with a token) -> HubSpot, logged, can roll back
```

## Stack (do not add dependencies without asking)

Python 3.11+, duckdb, dbt-duckdb, pandas, faker, pyyaml, pydantic, typer, openpyxl, jinja2,
requests, tenacity, pytest, ruff.

The developer works on Windows with PowerShell. Code must also run on Linux (CI).
Use `pathlib` for paths. No bash-only scripts.

## Layout

```
lead-to-cash-integrity/
  AGENTS.md
  README.md
  pyproject.toml              # package "l2c", console script "l2c = l2c.cli:app"
  .github/workflows/ci.yml
  config/
    rules.yml                 # every business rule and tolerance
    mapping.yml               # per table: file, format, columns, value maps (default format)
    mapping.ch.yml            # same data exported in Swiss format (example)
    mapping.de.yml            # same data exported in German format (example)
    mapping.hubspot_ui.yml    # HubSpot UI export with labels instead of internal values (example)
    younium_api.yml           # Younium API endpoints and field names (assumed until confirmed)
  src/l2c/
    cli.py                    # typer app (commands listed in CODEX_TASKS.md)
    config.py                 # pydantic models for rules.yml and mapping.yml
    paths.py                  # repo root, data dir, out dir, DB path (env L2C_DB_PATH)
    logging_setup.py          # one structured line per step: run_id, step, rows, seconds, status
    generate/background.py    # small random layer for both systems
    generate/cases.py         # case registry: one small function per planted case
    generate/writer.py        # writes CSVs in a chosen format (default, ch, de, hubspot_ui)
    load.py                   # CSV -> DuckDB raw schema, manifest, sanity gate
    doctor.py                 # checks a real export against mapping.yml before any run
    pull/hubspot.py           # read-only HubSpot API pull into data/raw (same shape as files)
    pull/younium.py           # read-only Younium API pull; endpoints from config/younium_api.yml
    dbt_runner.py             # runs dbt programmatically (dbtRunner) with vars from config
    memory.py                 # exception memory: state schema, statuses, history
    decisions.py              # reads decisions back from the review workbook
    fixes.py                  # propose, apply (dry run / live), rollback
    hubspot_client.py         # HubSpot API client (batch read/update, retries); fakeable
    report.py                 # HTML report (jinja2) and Excel workbook (openpyxl)
    slack.py                  # Slack digest (dry run unless SLACK_WEBHOOK_URL is set)
    templates/report.html.j2
  l2c_dbt/
    dbt_project.yml
    profiles.yml              # duckdb path from env_var('L2C_DB_PATH', 'data/l2c.duckdb')
    macros/src_col.sql
    models/staging/           # stg_hubspot__*, stg_younium__*, stg_ref__*
    models/intermediate/      # int_order_versions, int_account_match, int_deal_order_match, int_fx
    models/marts/checks/      # chk_a1_* .. chk_a13_*, chk_p_push_readiness, chk_r1_* .. chk_r12_*
    models/marts/             # quarantine, exceptions, audit_scorecard, push_readiness, fix_proposals,
                              # arr_billing_monthly, arr_crm_monthly, arr_bridge
  data/raw/                   # generated CSVs (gitignored)
  data/l2c.duckdb             # local database (gitignored)
  out/                        # report, workbook, proposal files (gitignored)
  tests/
    planted_cases.yml         # every planted ID and its exact expected result
```

## Non-negotiable rules

1. **Raw data is never changed.** The loader writes `raw.<table>` exactly as the CSV is (all
   columns as text), plus `loaded_at`, `run_id`, `source_file`. Each load replaces the table, so
   running twice never duplicates rows.
2. **Rules live in `config/rules.yml`.** No magic numbers or allowed-value lists in SQL or Python.
   The CLI validates rules.yml with pydantic and passes it to dbt as vars.
3. **Column names live in `config/mapping.yml`.** Staging models never hard-code a source column
   name. They use the macro `src_col(table, canonical)`, which looks the name up in
   `var('mapping')` and returns the quoted source column.
4. **A fixed as-of date.** All "days since" and "month-end" logic uses `as_of_date` from
   rules.yml, never today's date.
5. **Dirty data is a finding, not a build failure.** dbt tests guard our own models (keys,
   structure, output values). Never put accepted_values tests on dirty source columns.
6. **Never guess a match.** If a matching step finds two or more candidates, the row goes to
   quarantine with its specific cause: `multiple_company_id_matches`,
   `multiple_company_domain_matches` or `multiple_deal_order_matches`. Overlapping versions use
   `overlapping_order_versions`. It is reported, never silently picked.
7. **State is owned by Python.** The `state` schema (exception log, decisions, history, change
   log, run manifest) is written only by Python. dbt never creates, drops or writes `state`.
8. **Network calls happen only** in `fixes apply --live`, `fixes rollback --live` and
   `slack --send`. Everything else runs offline. Tests never touch the network: they use a fake
   HubSpot client and a temp DB (set L2C_DB_PATH to a tmp_path file).
9. **Synthetic data is small, complete and deterministic.** Every problem type is a planted case
   (one or two rows each); the random background layer stays thin. Fixed seed, byte-identical
   output. Planted records use IDs that start with `PLANT-`; background records never do.
   `--profile large --scale N` multiplies only the background, for stress runs; never committed.
   Planted cases cycle through `planted_owner_ids` in sorted case-ID order, independently of
   the seed and background scale. Deliberately missing/unknown owners and finance ownership stay intact.
10. **Every rule has a planted case** in tests/planted_cases.yml and a pytest that asserts its
    exact expected result.
11. **DuckDB lock on Windows:** close every Python DuckDB connection before running dbt, and
    open a fresh one after.
12. **Style:** ruff clean, type hints, small functions, logging with the run ID. No notebooks.
13. **After each task**, print: files changed, commands to verify, and anything you were unsure
    of.

## Data conventions: HubSpot side

Synthetic files use HubSpot API internal property names and internal values.
(UI exports use labels like "Marketing Qualified Lead"; mapping.yml may later add a value map.)

- Lifecycle stage, earliest to latest: subscriber, lead, marketingqualifiedlead,
  salesqualifiedlead, opportunity, customer, evangelist, other.
- Lead status: NEW, OPEN, IN_PROGRESS, OPEN_DEAL, UNQUALIFIED, ATTEMPTED_TO_CONTACT, CONNECTED,
  BAD_TIMING.
- Original source: ORGANIC_SEARCH, PAID_SEARCH, EMAIL_MARKETING, SOCIAL_MEDIA, REFERRALS,
  OTHER_CAMPAIGNS, DIRECT_TRAFFIC, OFFLINE, PAID_SOCIAL.
- Deal stages: appointmentscheduled, qualifiedtobuy, presentationscheduled,
  decisionmakerboughtin, contractsent (open), closedwon, closedlost.
- Deal `amount` = annual contract value (ACV) in the deal currency (CHF or EUR).
- Deal `deal_motion` = new, upsell or renewal.
- A deal's associated companies are one text column, IDs separated by `;`.
- Line item `price` = annual price per seat; `quantity` = seats.
- Company `younium_account_number` is filled by the Younium connector once synced.

## Data conventions: Younium side

Built on Younium's documented model. Exact field names in a real tenant will differ;
mapping.yml absorbs that.

- Account: account_number (A-000001 style), name, hubspot_company_id (may be blank), domain,
  legal_entity (Legartis Technology AG or Legartis Deutschland GmbH, synthetic), currency.
- Order = subscription. Every activated change creates a new **version** with its own effective
  dates. Each version row carries `hubspot_deal_id` of the deal that caused it (an assumption).
  Status: Draft, Active, Cancelled, Expired. Also term_months, auto_renew, cancellation_date.
- Current version = highest version that is not Draft.
- Order charge: charge_type Recurring, One-off or Usage; quantity; price; billing_period
  Monthly, Quarterly or Annual; `mrr` (monthly value); effective_start, effective_end.
- MRR counts **Recurring charges only**. One-off and Usage never count toward ARR.
- Invoice: invoice_number (I-000001 style), status Draft or Posted, `is_credit`, amount,
  service_period_start, service_period_end, posted_date. A posted invoice is never edited; a
  credit invoice corrects it.
- Booking: event (activation, change, renewal, cancellation), classification (New Business,
  Expansion, Contraction, Churn), cmrr_change, booking_date.
- FX: `fx_rates` has rate_to_chf per currency per date. Use the latest rate on or before the
  date needed. Base currency CHF.

## Source files: formats, value maps, quarantine

Real exports differ from the synthetic ones, so every difference is configuration, not code.

- **Format per file** in mapping.yml: delimiter (`,` or `;`), encoding (`utf-8-sig` handles the
  Excel BOM), date_format (`%Y-%m-%d` or `%d.%m.%Y`), decimal (`.` or `,`), thousands (`''`,
  `'` Swiss, `.` German). The loader uses delimiter and encoding; staging parses with the rest.
- **Value maps per column** in mapping.yml: label -> internal value, for example
  "Marketing Qualified Lead" -> marketingqualifiedlead. A portal in German gets its own labels
  the same way. Unmapped values pass through and are flagged by the checks.
- **Parsing happens in staging** with macros `parse_number`, `parse_date`, `map_value`, using
  DuckDB `try_` functions. Raw stays text.
- **Quarantine** (model `quarantine`: source_table, record_id, column, raw_value, reason). Rows
  that cannot be trusted go here, are counted in the report, and are left out of matching and
  ARR. Each cause has one name: `multiple_company_domain_matches` (a domain matches several
  companies), `multiple_company_id_matches` (an explicit company ID matches several rows),
  `multiple_deal_order_matches` (a deal matches several billing versions/orders),
  `overlapping_order_versions` (several versions are effective at the same month-end),
  `generic_email_domain` (domains in `generic_email_domains` are never used for matching),
  `no_fx_rate`, `unparseable_amount`, `unparseable_date`, and `id_corrupted_by_excel`
  (an ID like `1.23457E+11`). No generic `ambiguous` quarantine reason is used.

## Matching (int_account_match, int_deal_order_match)

Account to company, in order: (1) account.hubspot_company_id; (2) cleaned domain equals one
company's cleaned domain; (3) two or more companies match -> quarantine
`multiple_company_domain_matches` (or `multiple_company_id_matches` for the explicit-ID step);
(4) none -> unmatched.
Cleaned domain: lowercase; remove http://, https://, www., trailing slash and any path.

Deal to order version: by `hubspot_deal_id` on the version row. Draft versions never count as a
match. A deal of motion "new" matches version 1. A deal of motion "upsell" or "renewal" matches
the version that carries its ID. If two non-draft orders carry the same new deal's ID, match the
lowest order number and flag the other as R9.

## Checks

Every check model has these columns: `check_id, severity, object_type, record_id, owner_id,
reason, details, money_at_risk_chf`. Severity: hygiene (A, R11, R12), risk (P, R4), leak (R1,
R2, R3, R5, R6, R8, R9, R10, R7 when auto-renew is off), info (R7 when auto-renew is on).
Owner: deal owner for deal checks, company owner for company and contact checks, "finance" for
R2, R8, R9, R10 and R12. A record whose owner is missing or unknown gets owner "unassigned".

Evidence-based lifecycle for a contact, from its company's deals: company has a closedwon deal
-> customer; else an open deal -> opportunity; else lead.

### A. Audit (HubSpot data foundation)

| ID | Flags | Proposal |
|----|-------|----------|
| A1 | Contact lifecycle blank or not an allowed value | Evidence-based stage |
| A2 | Valid stage that contradicts evidence: "customer" without a closedwon deal; or lead / MQL / SQL / opportunity while the company has a closedwon deal | Evidence-based stage; `requires_clear_first = true` when the proposal is earlier than the current value |
| A3 | Customer with lead status NEW, OPEN, IN_PROGRESS, ATTEMPTED_TO_CONTACT or CONNECTED; or a non-customer whose company has an open deal and whose status is not OPEN_DEAL | `customer_lead_status` from rules.yml for customers (null = clear); else OPEN_DEAL. Customer rule wins |
| A4 | Contact with blank original source | None (HubSpot calculates this property) |
| A5 | closedwon deal with blank or zero amount | None |
| A6 | closedwon deal with blank contract start, contract end or term | None |
| A7 | Two or more companies with the same cleaned domain | Merge pair; oldest createdate is primary |
| A8 | Open deal with close date more than `stale_open_deal_days` before as_of_date (exactly that many = not flagged) | None |
| A9 | Company with blank territory or tier | Territory from `territory_by_country`; tier flag only |
| A10 | Two or more contacts with the same email, ignoring case and spaces | Merge pair; oldest createdate is primary |
| A11 | Contact with no company | None |
| A12 | closedwon deal with impossible dates: close date after as_of_date; contract end on or before contract start; or term_months differs from the months between start and end by more than `term_tolerance_months` | None; reason names which rule |
| A13 | Deal or company whose owner is blank or not in hubspot_owners | None (owner becomes "unassigned") |

### P. Push-readiness (closedwon deals of motion new, not yet matched to an order)

`push_readiness` includes `days_since_contract_start`, calculated using `as_of_date`, and
every failing P1-P5 check as a human-readable reason, with stable IDs in `failed_checks`.
Status precedence: DRAFT_ONLY if only a Draft order exists; otherwise OVERDUE if
`days_since_contract_start > won_not_billed_days`; otherwise BLOCKED if any P1-P5 check fails;
otherwise READY. Exactly the grace-period limit is not overdue. Age/draft statuses retain all
failing P reasons; they do not create extra P failures (R1 captures overdue billing).
Sort OVERDUE first, then DRAFT_ONLY, BLOCKED and READY, oldest contract start first within status.

| ID | Must be true |
|----|--------------|
| P1 | Exactly one associated company |
| P2 | That company has a younium_account_number |
| P3 | At least one line item, and every SKU exists in product_catalog |
| P4 | contract start, term_months, billing_frequency and currency are filled |
| P5 | Line items total within `push_line_item_tolerance_pct` of the deal amount (blank amount fails) |

### R. Reconciliation

| ID | Flags | money_at_risk_chf |
|----|-------|-------------------|
| R1 | closedwon "new" deal with no matched non-draft order, and as_of_date minus contract start is more than `won_not_billed_days` (exactly = not flagged). Reason "no order" or "only a draft order" | Deal ACV |
| R2 | Order with no closedwon deal (unmatched, not quarantined) | Order ARR |
| R3 | Matched new deal: deal ACV vs version-1 recurring MRR x 12, both in CHF, differ by more than `amount_tolerance_pct` (exactly = pass). Skip if amount is blank | Absolute difference |
| R4 | Matched deal: contract start vs version effective start more than `start_date_tolerance_days` apart (exactly = pass) | null |
| R5 | Matched deal: total line-item seats vs total recurring charge quantity differ | Seat difference x line-item price, in CHF |
| R6 | closedwon upsell or renewal deal, contract start more than `won_not_billed_days` ago, with no non-draft version carrying its ID | Deal ACV |
| R7 | Active order whose current version ends within `renewal_window_days` of as_of_date and no open renewal deal on its company | Order ARR if auto_renew is false; 0 with severity info if true |
| R8 | Posted, non-credit invoice whose service period starts after the order's cancellation_date, with no credit invoice for the same order and period | Invoice amount in CHF |
| R9 | Deal pushed twice: a second non-draft order carries the same new deal's ID | That order's ARR |
| R10 | Billing change without a CRM deal: a version 2+ with blank hubspot_deal_id whose recurring MRR differs from the previous version | Absolute MRR change x 12 |
| R11 | Cancelled in billing, still customer in CRM: no active order for the account at as_of_date, at least one cancelled order, and contacts still "customer" | null |
| R12 | Two or more Younium accounts with the same hubspot_company_id | null |

## ARR

- Month-ends: the 12 month-ends up to and including the month-end of as_of_date.
- **Billing ARR** (arr_billing_monthly), per order per month-end: Recurring charges of the
  version active on that date (effective_start <= month-end < effective_end), order not
  cancelled on or before that date; MRR x 12 converted to CHF at that month-end.
- **CRM ARR** (arr_crm_monthly), per deal per month-end: closedwon deals with
  contract_start <= month-end < contract_end; amount converted to CHF at that month-end.
- **ARR bridge** (arr_bridge), at the as_of month-end only, from CRM ARR to billing ARR, one row
  per category with amount_chf: won_not_billed (unmatched deals: R1 plus those still inside the
  grace period, shown separately as not_yet_billed), billed_not_in_crm (R2), double_billed (R9),
  billing_only_change (R10), renewed_in_billing_only (auto-renew versions with no deal, active in
  billing after the CRM contract ended), quarantined, value_mismatch (matched pairs flagged R3,
  R5 or R6), timing (matched pairs flagged R4), within_tolerance (other matched pairs with a
  difference), `crm_arr_not_valued` (a matched, billed closedwon contract cannot contribute CRM
  ARR because its amount or contract dates are missing, or its end is on/before its start),
  unexplained (anything left). Intentional audit cases A08, A17 and R08 belong to
  `crm_arr_not_valued`; the default seed must have zero unexplained ARR.
  The sum of all categories must equal billing ARR minus CRM ARR to the cent.
- The report's gap waterfall starts at zero, shows non-zero bridge categories in descending
  absolute amount, and ends at the total gap. Labels use whole CHF with thousands separators.
  CRM ARR and billing ARR appear in the top cards only.

## Exception memory (memory.py, state schema)

- Key: `check_id:object_type:record_id`. Fingerprint: hash of the values in `details`.
- Statuses: new (first run seen), open (seen again), fixed (no longer in exceptions),
  accepted (a decision with a reason; hidden while the fingerprint is unchanged),
  reopened (was fixed or accepted, and appears again or the fingerprint changed).
- Tables: state.run_manifest, state.exception_log (key, check_id, record_id, status, owner_id,
  first_seen_run, last_seen_run, first_seen_at, fingerprint, accepted_reason),
  state.decisions, state.scorecard_history, state.change_log.
- Change line for the report: "N new, N fixed, N reopened, N still open (N older than
  `stale_exception_days` days)".

## Connecting to a real company (doctor.py, pull/)

- `l2c doctor --mapping <file>` checks real exports in data/raw before any run: missing files,
  missing or extra columns, values not covered by value maps or allowed lists, unparseable dates
  and numbers, Excel-corrupted IDs, generic email domains. It ends with READY or NOT READY and a
  short list of what to change in mapping.yml. It never changes the files.
- `l2c pull hubspot`: read-only HubSpot CRM v3 pull (companies, contacts, deals, line items,
  owners, deal-company and line-item-deal associations), pagination with `after`, token from env
  HUBSPOT_TOKEN. It writes data/raw CSVs in exactly the synthetic shape, so the rest of the
  pipeline does not know or care where the data came from.
- `l2c pull younium`: the same for Younium, with endpoints and field names read from
  config/younium_api.yml, because the real names are assumptions until confirmed in a tenant.
- Both pulls are tested with fake HTTP responses. No test calls a real API.

## Fix safety (fixes.py, hubspot_client.py)

- `fixes propose` writes out/fix_proposals.csv with an empty "approved" column.
- `fixes apply` is a dry run by default: plan only, no network. `--live` needs env HUBSPOT_TOKEN.
- Live: batch-read current values first and skip rows already correct (so applying twice writes
  nothing); batch updates of at most 100 records; a requires_clear_first row is two writes,
  clear then set; retries with backoff on 429 and 5xx; every write goes to state.change_log with
  old and new value.
- `fixes rollback --run <run_id>` restores old values from the change log (dry run by default).
