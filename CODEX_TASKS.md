# Codex tasks: the whole system, one project

One folder, one repo, one system. Paste ONE task at a time into Codex. After each task, run its
"Check it" commands, read what changed, and commit (a commit is only a save point, not a new
project). If something fails, paste the error to Codex; if it is still stuck, bring it to Claude.

Every task starts with: **Read AGENTS.md first and follow it.**

---

## Task 1: Scaffold, config, CLI skeleton

```
Read AGENTS.md first and follow it.

1. pyproject.toml for package "l2c" (src layout), console script "l2c = l2c.cli:app", the
   dependencies in AGENTS.md. A .gitignore for .venv/, data/, out/, *.duckdb, l2c_dbt/target/,
   l2c_dbt/logs/, l2c_dbt/dbt_packages/, __pycache__/.
2. src/l2c/paths.py, src/l2c/logging_setup.py, src/l2c/config.py (pydantic models for both yml
   files; a bad value fails with a clear message naming the key).
3. src/l2c/cli.py with these typer commands (each prints "not built yet" and exits 1 for now):
   generate, load, build, remember, decisions import, fixes propose, fixes apply,
   fixes rollback, report, slack, show, doctor, pull hubspot, pull younium, run.
   Every command that reads source files accepts --mapping (default config/mapping.yml, or env
   L2C_MAPPING).
4. config/rules.yml with exactly:

   as_of_date: "2026-10-31"
   base_currency: CHF
   lifecycle_order: [subscriber, lead, marketingqualifiedlead, salesqualifiedlead, opportunity, customer, evangelist, other]
   lead_status_allowed: [NEW, OPEN, IN_PROGRESS, OPEN_DEAL, UNQUALIFIED, ATTEMPTED_TO_CONTACT, CONNECTED, BAD_TIMING]
   customer_lead_status: null          # null = propose clearing the field
   original_source_allowed: [ORGANIC_SEARCH, PAID_SEARCH, EMAIL_MARKETING, SOCIAL_MEDIA, REFERRALS, OTHER_CAMPAIGNS, DIRECT_TRAFFIC, OFFLINE, PAID_SOCIAL]
   open_deal_stages: [appointmentscheduled, qualifiedtobuy, presentationscheduled, decisionmakerboughtin, contractsent]
   closed_won_stage: closedwon
   closed_lost_stage: closedlost
   stale_open_deal_days: 30
   territory_by_country:
     DACH: [Switzerland, Germany, Austria, Liechtenstein]
     France: [France]
   default_territory: Other
   won_not_billed_days: 30
   amount_tolerance_pct: 2.0           # pct = abs(order_acv - deal_acv) / deal_acv * 100, rounded to 4 decimals
   start_date_tolerance_days: 15
   renewal_window_days: 60
   push_line_item_tolerance_pct: 1.0
   stale_exception_days: 14
   sanity_max_drop_pct: 20
   arr_months: 12
   term_tolerance_months: 1
   generic_email_domains: [gmail.com, outlook.com, hotmail.com, yahoo.com, icloud.com, gmx.ch, gmx.de, gmx.net, web.de, bluewin.ch]

5. config/mapping.yml: per table a "file" name, a "format" block (delimiter ",", encoding
   "utf-8-sig", date_format "%Y-%m-%d", decimal ".", thousands ""), a "columns" map from
   canonical name to source column, and an optional "values" map per column (label -> internal
   value; empty in the default file).
   HubSpot tables (source names are HubSpot API names):
   - hubspot_companies: company_id=hs_object_id, name=name, domain=domain, country=country,
     owner_id=hubspot_owner_id, territory=territory, tier=tier,
     younium_account_number=younium_account_number, created_at=createdate
   - hubspot_contacts: contact_id=hs_object_id, email=email, company_id=associatedcompanyid,
     lifecycle_stage=lifecyclestage, lead_status=hs_lead_status,
     original_source=hs_analytics_source, owner_id=hubspot_owner_id, created_at=createdate
   - hubspot_deals: deal_id=hs_object_id, deal_name=dealname, company_ids=associated_company_id,
     deal_type=dealtype, motion=deal_motion, stage=dealstage, amount=amount,
     currency=deal_currency_code, close_date=closedate, contract_start=contract_start_date,
     contract_end=contract_end_date, term_months=term_months,
     billing_frequency=billing_frequency, owner_id=hubspot_owner_id, created_at=createdate
   - hubspot_line_items: line_item_id=hs_object_id, deal_id=deal_id, sku=hs_sku,
     quantity=quantity, unit_price=price, amount=amount
   - hubspot_owners: owner_id=id, name=name, team=team
   Younium and reference tables (source names equal canonical names in the synthetic data):
   - younium_accounts: account_number, name, hubspot_company_id, domain, legal_entity, currency
   - younium_orders: order_number, version, account_number, hubspot_deal_id, status,
     effective_start, effective_end, term_months, auto_renew, cancellation_date, currency
   - younium_order_charges: charge_id, order_number, version, sku, product, charge_plan,
     charge_type, quantity, price, billing_period, mrr, effective_start, effective_end
   - younium_invoices: invoice_number, account_number, order_number, status, is_credit, amount,
     currency, service_period_start, service_period_end, posted_date
   - younium_bookings: booking_id, order_number, version, event, classification, cmrr_change,
     currency, booking_date
   - ref_fx_rates: date, currency, rate_to_chf
   - ref_product_catalog: sku, product, charge_plan, charge_type, list_price, currency

Commit message suggestion: "Scaffold and config".
```

**Check it**

```powershell
python -m venv .venv              # create a private Python environment for this project
.\.venv\Scripts\Activate.ps1      # turn that environment on in this terminal
pip install -e .                  # install your package so the l2c command exists and sees your edits
l2c --help                        # list every command; all should appear
git add . ; git commit -m "Scaffold and config"   # save point
```

---

## Task 2: Synthetic data for both systems, with every planted case

```
Read AGENTS.md first and follow it.

Build src/l2c/generate/background.py, cases.py, writer.py and "l2c generate --seed 42".
It writes all 12 CSVs to data/raw/. Same seed = byte-identical files.

Small but complete: every problem type is a planted case; the background is thin.
- cases.py is a registry: one small function per planted case, each adding the rows it needs on
  both sides. Adding a new problem later = one function + one entry in tests/planted_cases.yml.
- Background (default profile "small"): 30 companies, 80 contacts, 50 deals, about 90 line
  items, 6 owners, 28 Younium accounts, 30 orders (about 40 versions), about 90 charges, about
  250 invoices, bookings for each version. Mostly clean and consistent, with light dirt so the
  scorecard is not 100%. Names include umlauts (for example Zürich, Müller).
- "--profile large --scale N" multiplies only the background, for stress runs.
- Deals about 40% closedwon, 25% closedlost, rest open. Currency about 60% CHF, 40% EUR.
  Countries mostly Switzerland, Germany, Austria, some France and others.

ref_fx_rates: CHF = 1.0 every day; EUR month-end rates for 13 months, synthetic, with exactly
0.9400 on 2026-10-31. ref_product_catalog: synthetic SKUs, for example LGT-PLATFORM (Recurring),
LGT-SEAT (Recurring, annual price per seat), LGT-REVIEW-PACK (Usage), LGT-ONBOARDING (One-off).
Mark them synthetic in a "note" comment in the generator.

Plant these. All dates are relative to as_of_date 2026-10-31. Every planted record and its
company uses an ID that starts with PLANT-. Unless a case says otherwise, a planted deal is
otherwise clean and push-ready.

Audit:
PLANT-A01 contact, lifecycle blank, company has an open deal          -> A1, propose opportunity
PLANT-A02 contact, lifecycle "lead_old"                                -> A1
PLANT-A03 contact "customer", company has no closedwon and no open deal
                                                                       -> A2, propose lead, requires_clear_first true
PLANT-A04 contact "salesqualifiedlead", company has a closedwon deal   -> A2, propose customer
PLANT-A05 contact "customer" (closedwon company), lead status NEW      -> A3, propose clearing
PLANT-A06 contact with blank original source                           -> A4 only
PLANT-A07 closedwon deal, blank amount, no order                       -> A5 only (and P5 BLOCKED)
PLANT-A08 closedwon deal, blank contract_end_date                      -> A6 only
PLANT-A09 two companies "acme-legal.ch" and "https://www.ACME-legal.ch/" -> A7 pair, older is primary
PLANT-A10 open deal, close date 31 days before as_of                   -> A8
PLANT-A11 open deal, close date exactly 30 days before as_of           -> not flagged
PLANT-A12 company in Germany, blank territory                          -> A9, propose DACH
PLANT-A13 fully clean company, contacts, closedwon deal, matching order -> in no check at all

Push-readiness (closedwon new deals with no order yet, contract start a few days ago):
PLANT-P01 deal with two companies ("PLANT-C-P01a;PLANT-C-P01b")        -> BLOCKED: P1
PLANT-P02 company has no younium_account_number                        -> BLOCKED: P2
PLANT-P03 deal with no line items                                      -> BLOCKED: P3, P5
PLANT-P04 blank billing_frequency                                      -> BLOCKED: P4
PLANT-P05 line items total 9% below the amount                         -> BLOCKED: P5
PLANT-P06 everything correct, contract start 3 days ago                -> READY; bridge not_yet_billed

Reconciliation:
PLANT-R01 new deal CHF 30,000; order v1 recurring MRR CHF 2,500; same start -> no exception
PLANT-R02 deal CHF 24,000; order MRR CHF 2,040 (exactly 2.0%)          -> no exception
PLANT-R03 deal CHF 24,000; order MRR CHF 2,042 (2.1%)                  -> R3, money 504
PLANT-R04 new deal CHF 18,000, no order, contract start 31 days ago    -> R1, money 18,000
PLANT-R05 same, contract start exactly 30 days ago                     -> no R1; bridge not_yet_billed
PLANT-R06 account with blank hubspot_company_id, domain matches one company, deal and order agree
                                                                       -> matched by domain, no exception
PLANT-R07 account whose domain matches both PLANT-A09 companies        -> quarantine "ambiguous", no R2
PLANT-R08 closedwon deal with blank amount AND a matching order        -> A5 only, never R3
PLANT-R09 deal EUR 24,000; order CHF MRR 1,880 (equal at 0.9400)       -> no exception
PLANT-R11 line items 10 seats x CHF 1,200 = amount 12,000; order charge quantity 8, price 1,200
                                                                       -> R3 money 2,400 and R5 money 2,400
PLANT-R12 upsell deal CHF 6,000, closedwon, contract start 40 days ago, no version with its ID
                                                                       -> R6, money 6,000
PLANT-R13 active order, current version ends 45 days after as_of, auto_renew false, no open renewal deal
                                                                       -> R7 leak, money = order ARR
PLANT-R14 same as R13 but auto_renew true                              -> R7 info, money 0
PLANT-R15 order cancelled 2026-08-31; posted invoice for 2026-09-01 to 2026-09-30, no credit
                                                                       -> R8, money = invoice amount
PLANT-R16 same as R15 plus a credit invoice for that order and period  -> no R8
PLANT-R17 order with one Recurring charge MRR CHF 1,000 and one One-off charge CHF 5,000;
          deal ACV CHF 12,000                                          -> no exception; billing ARR 12,000
PLANT-R18 order with blank hubspot_deal_id, account matched            -> R2, money = order ARR
PLANT-R19 contract start and order start 16 days apart                 -> R4
PLANT-R20 contract start and order start exactly 15 days apart         -> no R4

More HubSpot hygiene:
PLANT-A14 contacts "Anna.Keller@kanzlei-keller.ch" and "anna.keller@kanzlei-keller.ch "
                                                                       -> A10 pair, older is primary
PLANT-A15 contact with blank company                                   -> A11
PLANT-A16 closedwon deal with close date 10 days after as_of           -> A12 "future close date"
PLANT-A17 closedwon deal with contract end before contract start       -> A12 "end before start"
PLANT-A18 closedwon deal, term_months 12, start to end is 24 months    -> A12 "term mismatch"
PLANT-A19 deal whose owner ID is not in hubspot_owners                 -> A13, owner "unassigned"
PLANT-A20 clean company "Müller & Söhne Rechtsanwälte AG" in Zürich    -> no exception; name intact in the report

Quarantine:
PLANT-Q01 Younium account, domain "gmail.com", blank hubspot_company_id -> quarantine generic_email_domain
PLANT-Q02 closedwon deal in USD with a matching order in USD           -> quarantine no_fx_rate; no R3; bridge quarantined
PLANT-Q03 Younium account with hubspot_company_id "1.23457E+11"        -> quarantine id_corrupted_by_excel
PLANT-Q04 invoice of a clean order with amount "n/a"                   -> quarantine unparseable_amount only

More billing:
PLANT-R21 closedwon new deal, contract start 40 days ago, only a Draft order
                                                                       -> R1 "only a draft order"
PLANT-R22 two Active orders carry the same new deal's ID               -> R9 on the higher order number, money = its ARR
PLANT-R23 version 2 with blank hubspot_deal_id, recurring MRR 10% above version 1
                                                                       -> R10, money = MRR change x 12
PLANT-R24 version 2 made by auto-renew (same MRR, blank deal ID); CRM contract ended 2026-09-30
                                                                       -> no exception; bridge renewed_in_billing_only
PLANT-R25 account whose only order was cancelled 2026-09-30; contacts still "customer"
                                                                       -> R11
PLANT-R26 two Younium accounts with the same hubspot_company_id        -> R12
PLANT-R27 order with a Recurring charge MRR CHF 1,500 and a Usage charge (review pack)
                                                                       -> billing ARR 18,000 (usage excluded)
PLANT-R28 charge from exactly 2026-09-30 to exactly 2026-10-31         -> in billing ARR for September, not October
PLANT-R29 closedwon renewal deal, contract start 40 days ago, no version with its ID
                                                                       -> R6

Formats (writer.py), "l2c generate --format default|ch|de|hubspot_ui":
- ch: Younium files with ";" delimiter, dates dd.mm.yyyy, decimal ".", thousands "'" (1'200.50).
- de: Younium files with ";" delimiter, dates dd.mm.yyyy, decimal ",", thousands "." (1.200,50).
- hubspot_ui: HubSpot files with labels instead of internal values (for example
  "Marketing Qualified Lead", "Closed Won") and UI-style headers such as "Record ID".
- ch, de and hubspot_ui write UTF-8 with a BOM and CRLF line endings, like Excel on Windows.
Create config/mapping.ch.yml, mapping.de.yml and mapping.hubspot_ui.yml to match. The same seed
in any format must give the same results (tested in Task 11).

Write tests/planted_cases.yml: for each ID, its expected checks, proposals, push status,
money_at_risk_chf and bridge category, exactly as above.

Commit message suggestion: "Synthetic data with planted cases".
```

**Check it**

```powershell
l2c generate --seed 42        # write the 12 synthetic CSV files into data\raw
Get-ChildItem data\raw        # list the files to see they are all there
git add . ; git commit -m "Synthetic data with planted cases"   # save point
```

---

## Task 3: Loader, manifest, sanity gate

```
Read AGENTS.md first and follow it.

Build src/l2c/load.py and "l2c load":
- Load every table in mapping.yml from data/raw into raw.<table>, all columns as text, plus
  loaded_at, run_id, source_file. Replace each table on every run. Read each file with the
  delimiter and encoding from its format block ("utf-8-sig" strips an Excel BOM; CRLF is fine).
- Write state.run_manifest rows: run_id, table, source_file, file_sha256, row_count, loaded_at,
  status.
- Sanity gate: compare each table's row count with the last successful run. If any table drops
  by more than sanity_max_drop_pct, stop with a clear message and a non-zero exit code, and
  mark the run failed. No baseline = pass. "--force" overrides with a logged warning.
- Close the connection at the end.
- tests/test_loader.py: load twice into a temp DB and assert identical counts and no duplicate
  source IDs; cut hubspot_deals.csv in half in a temp copy and assert the gate stops the run.

Commit message suggestion: "Loader and sanity gate".
```

**Check it**

```powershell
l2c load                          # copy the CSVs into DuckDB raw tables, with the sanity gate
pytest -q tests\test_loader.py    # run only the loader tests, short output
git add . ; git commit -m "Loader and sanity gate"   # save point
```

---

## Task 4: dbt project, staging and intermediate models

```
Read AGENTS.md first and follow it.

1. Create l2c_dbt/ by hand (do not run "dbt init"): dbt_project.yml, profiles.yml using
   env_var('L2C_DB_PATH', 'data/l2c.duckdb'), macros/src_col.sql (AGENTS.md rule 3).
   Declare all raw tables as dbt sources.
2. src/l2c/dbt_runner.py: run dbt with dbtRunner (from dbt.cli.main), project and profiles
   dir l2c_dbt, vars = {rules: ..., mapping: ...}. Wire it to "l2c build".
3. Staging: stg_hubspot__companies, __contacts, __deals, __line_items, __owners,
   stg_younium__accounts, __orders, __order_charges, __invoices, __bookings,
   stg_ref__fx_rates, __product_catalog. Canonical names via src_col, real types, trimmed
   text, lower-case emails, domain_clean, is_closed_won / is_open flags, company_ids split
   into a list. Unique and not_null tests on every ID (orders: order_number + version).
   Parse with macros parse_number, parse_date and map_value, driven by each table's format and
   values blocks (AGENTS.md "Source files"). Build the quarantine model with every reason listed
   there; quarantined rows are left out of matching and ARR.
4. Intermediate: int_fx (rate lookup: latest on or before a date), int_order_versions (current
   version flag), int_account_match (with match_method and quarantine reason),
   int_deal_order_match, all as AGENTS.md "Matching" says.
5. "l2c show <table>": print the first 50 rows of any table.

Commit message suggestion: "dbt staging and matching".
```

**Check it**

```powershell
l2c build                              # run all dbt models and their tests
l2c show int_account_match             # look at how each Younium account was matched
git add . ; git commit -m "dbt staging and matching"   # save point
```

---

## Task 5: All checks, exceptions, scorecard, fix proposals

```
Read AGENTS.md first and follow it.

1. One model per check: chk_a1_... to chk_a13_..., chk_p_push_readiness, chk_r1_... to
   chk_r12_..., exactly as AGENTS.md "Checks" says, all with the common columns.
2. push_readiness: one row per closedwon new deal with no matched order: deal_id, owner_id,
   status (READY or BLOCKED), reasons.
3. exceptions: union of every check row except READY push rows.
4. audit_scorecard: check_id, description, rows_checked, rows_failed, pass_rate (0 to 1,
   4 decimals). Denominators: A1-A4, A10, A11 all contacts; A5, A6, A12 closedwon deals; A7,
   A9 all companies; A8 open deals; A13 deals plus companies; P closedwon new deals without an
   order; R1, R3-R6 closedwon deals of the right motion; R2, R7 active orders; R8 posted
   non-credit invoices; R9 new deals with an order; R10 versions 2 and later; R11 accounts with a
   cancelled order; R12 all accounts. Add one row "Q" for quarantined rows out of all rows.
5. fix_proposals: proposal_id (stable hash of check_id, object_type, record_id, property),
   check_id, object_type, record_id, property, current_value, proposed_value,
   requires_clear_first, reason.
6. Tests on our outputs only: check_id accepted values, pass_rate between 0 and 1,
   proposal_id unique, money_at_risk_chf not negative.

Commit message suggestion: "All checks".
```

**Check it**

```powershell
l2c build                         # rebuild everything, checks included
l2c show audit_scorecard          # the health score per check
l2c show push_readiness           # which won deals are READY or BLOCKED
git add . ; git commit -m "All checks"   # save point
```

---

## Task 6: ARR and the ARR bridge

```
Read AGENTS.md first and follow it.

Build arr_billing_monthly, arr_crm_monthly and arr_bridge exactly as AGENTS.md "ARR" says.
Add a dbt test (singular test) that the bridge categories sum to billing ARR minus CRM ARR
to the cent at the as_of month-end.

Commit message suggestion: "ARR bridge".
```

**Check it**

```powershell
l2c build                         # rebuild with the ARR models and the bridge test
l2c show arr_bridge               # each cause of the gap and its amount in CHF
git add . ; git commit -m "ARR bridge"   # save point
```

---

## Task 7: Exception memory and decisions

```
Read AGENTS.md first and follow it.

1. src/l2c/memory.py and "l2c remember": after a build, read exceptions and update
   state.exception_log with the statuses in AGENTS.md "Exception memory". Save the scorecard
   to state.scorecard_history with the run_id. Build the weekly change line.
2. src/l2c/decisions.py and "l2c decisions import <xlsx>": read the Exceptions tab (columns
   decision = accept or assign, reason, assignee) and the Fixes tab (approved) of the review
   workbook into state.decisions. An accept without a reason is rejected with a message.
3. tests/test_memory.py with a temp DB:
   - PLANT-A06: run, then fill its original source in a temp copy, run again -> status fixed.
   - PLANT-R18: run, accept it with a reason, run again -> accepted and hidden; change its
     order's MRR in a temp copy, run again -> reopened.

Commit message suggestion: "Exception memory".
```

**Check it**

```powershell
l2c remember                      # update the exception log and score history for this run
l2c show exception_log            # each exception with status, owner and first seen
pytest -q tests\test_memory.py    # run the memory tests, short output
git add . ; git commit -m "Exception memory"   # save point
```

---

## Task 8: Fixes: propose, apply, rollback

```
Read AGENTS.md first and follow it.

1. "l2c fixes propose": write out/fix_proposals.csv with an empty approved column.
2. src/l2c/hubspot_client.py: a small client with batch_read and batch_update for contacts and
   companies (CRM v3 batch endpoints, max 100 per call), retries with tenacity on 429 and 5xx,
   token from env HUBSPOT_TOKEN. Define an interface so tests can pass a FakeHubSpotClient.
3. "l2c fixes apply": dry run by default (plan printed grouped by object and property, written
   to out/apply_plan.json, no network). "--live" follows AGENTS.md "Fix safety" exactly.
   Only approved rows (yes, y, true, any case) from the CSV or from state.decisions.
4. "l2c fixes rollback --run <run_id>": dry run by default, "--live" restores old values.
5. tests/test_fixes.py with the fake client: unapproved rows never appear in a plan;
   requires_clear_first makes two writes in order; applying twice writes nothing the second
   time; rollback restores the old value.

Commit message suggestion: "Fixes apply and rollback".
```

**Check it**

```powershell
l2c fixes propose                 # write the fix proposals file into out\
l2c fixes apply                   # dry run: show what would change in HubSpot; writes nothing
pytest -q tests\test_fixes.py     # run the fix tests with the fake HubSpot client
git add . ; git commit -m "Fixes apply and rollback"   # save point
```

---

## Task 9 (MIDDLE): Report, review workbook, Slack digest

```
Read AGENTS.md first and follow it.

Skip exception memory, the change line and score history; those are v0.2.

1. "l2c fixes propose": write out/fix_proposals.csv from fix_proposals, with an empty
   "approved" column at the end.
2. "l2c report" writes:
   - out/report.html: ONE self-contained file (inline CSS, no external files or scripts).
     Top: CRM ARR, billing ARR and the gap, in CHF. Then: the scorecard table; the ARR
     bridge as an inline SVG gap waterfall from zero to the total gap; the push-readiness
     list; exceptions grouped by owner, sorted by money at risk, then severity; a
     quarantine summary (count per reason, marked "not valued" where there is no CHF
     amount). Footer: "Synthetic data. Independent demo."
   - out/review.xlsx with tabs Scorecard, Exceptions (empty decision, reason, assignee
     columns), Fixes (empty approved column), Push readiness, ARR bridge, Quarantine.
     Header row bold and frozen, columns sized to content.
3. "l2c slack": print a message with the gap, the scorecard summary and the top 5
   exceptions by money at risk. "--send" posts it only if env SLACK_WEBHOOK_URL is set.
4. "l2c run": generate, load, build, fixes propose, report, in that order; stop at the
   first failure.
5. The commands not in this version (remember, decisions import, fixes apply,
   fixes rollback, doctor, pull hubspot, pull younium) print
   "planned for v0.2 - see README roadmap" and exit 1.
6. Tests: the HTML contains PLANT-R04 and its CHF amount; the workbook has all six tabs;
   fix_proposals.csv has the approved column.

Commit message suggestion: "Report and workbook".
```

**Check it**

```powershell
l2c run                           # the whole pipeline, start to finish
start out\report.html             # open the HTML report in your browser
start out\review.xlsx             # open the review workbook in Excel
l2c slack                         # print the Slack message without sending it
git add . ; git commit -m "Report and workbook"   # save point
```

---

## Task 10: Connect to their systems: doctor and pulls

```
Read AGENTS.md first and follow it.

1. src/l2c/doctor.py and "l2c doctor --mapping <file>", exactly as AGENTS.md "Connecting to a
   real company" says. Print a short table per file, then READY or NOT READY and what to change
   in the mapping file. Exit code 0 for READY, 1 for NOT READY. Never change the files.
2. src/l2c/pull/hubspot.py and "l2c pull hubspot": read-only CRM v3 pull as AGENTS.md says,
   with tenacity retries on 429 and 5xx. Writes data/raw CSVs in the synthetic API-name shape.
3. config/younium_api.yml (base URL, endpoints, field names, all marked "assumed") and
   src/l2c/pull/younium.py with "l2c pull younium" reading it.
4. Tests with fake HTTP responses only: tests/test_pull_hubspot.py (pagination across 3 pages,
   a 429 then success, associations written to the right columns), tests/test_pull_younium.py,
   tests/test_doctor.py (a temp export with a missing column, an unmapped label, a German date
   in an ISO file and an Excel-corrupted ID must give NOT READY and name all four).

Commit message suggestion: "Doctor and API pulls".
```

**Check it**

```powershell
l2c doctor                        # check the files in data\raw against mapping.yml
l2c generate --seed 42 --format de   # write the same data in German format
l2c doctor --mapping config\mapping.de.yml   # the German files should be READY with the German mapping
l2c generate --seed 42            # put the default files back
pytest -q tests\test_doctor.py tests\test_pull_hubspot.py tests\test_pull_younium.py   # run these tests only
git add . ; git commit -m "Doctor and API pulls"   # save point
```

---

## Task 11: Every planted case tested, CI, README

```
Read AGENTS.md first and follow it.

1. tests/test_planted_cases.py: run the whole pipeline into a temp DB once (session fixture)
   and assert every case in tests/planted_cases.yml gets exactly its expected checks,
   proposals, push status, money_at_risk_chf and bridge category. PLANT-A13 must appear in no
   check. Assert billing ARR for PLANT-R17 is 12,000.
2. tests/test_end_to_end.py: "l2c run" succeeds twice in a row on a temp DB and the second run's
   change line shows 0 new.
3. tests/test_formats.py: generate the same seed in default, ch, de and hubspot_ui formats, run
   each with its mapping file, and assert exceptions, audit_scorecard and arr_bridge are
   identical. Also run "--profile large --scale 10" once and assert it completes.
4. .github/workflows/ci.yml: on push and pull_request, ubuntu-latest, Python 3.11,
   pip install -e ., ruff check ., pytest -q.
5. README.md, in this order: the problem in one paragraph; the one-line flow; the analogy
   (check-in desk before the push, passport control after it, a side room where a person
   decides); what you get (the outputs, with a short sample of each); run it in five commands;
   use it on your own exports (run l2c doctor first; mapping.yml formats and value maps;
   read-only pulls; data stays local); the checks and what
   each planted case proves; design choices; AI-assisted, human-owned; limits (synthetic data,
   assumed field names); why I built this (answers a public job posting from Legartis;
   independent demo, not affiliated; no logo or branding). Add the CI badge.

Commit message suggestion: "Planted-case tests, CI, README".
```

**Check it**

```powershell
ruff check .                      # find style problems and simple bugs
pytest -q                         # run every test, short output
git add . ; git commit -m "Planted-case tests, CI, README"   # save point
```

---

## Ship it

First create an empty repo named `lead-to-cash-integrity` on github.com (no README, no license).

```powershell
git branch -M main                # make sure the branch is called main
git remote add origin https://github.com/aryanmmohammad-commits/lead-to-cash-integrity.git   # connect to the GitHub repo
git push -u origin main           # upload the code
```

Then open the repo's Actions tab on GitHub and check that CI is green.

---

## Optional Task 12: Kafka event consumer

```
Read AGENTS.md first and follow it. You may add one dependency: confluent-kafka.

Add docker-compose.yml with a single Redpanda broker. Add src/l2c/events.py and
"l2c listen": consume topic younium.order.changed (JSON with event_id, order_number,
occurred_at). Skip events whose event_id is already in state.processed_events (idempotency).
For a valid event, rerun the checks and print the exceptions for that order's account.
Send events that fail to parse to topic younium.order.changed.dlq. Add "l2c send-test-event"
to publish one sample event. Test the idempotency logic without a broker.
```
