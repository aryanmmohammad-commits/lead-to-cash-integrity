# Lead-to-cash integrity

An independent B2B SaaS demo that compares synthetic HubSpot CRM and Younium billing data.
All data is synthetic. Business rules live in `config/rules.yml`; export formats, source
columns and value maps live in the mapping files.

## Run the v0.1 demo

Requires Python 3.11 or later. From PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e .
.venv\Scripts\l2c.exe run
```

`run` executes generate, load, build, fixes propose and report, in that order. It stops at
the first failure. The seed defaults to 42. `L2C_DB_PATH` overrides the local database;
`--mapping` overrides `L2C_MAPPING` and the default mapping. For another export format:

```powershell
l2c run --format de
l2c show exceptions --where "record_id like '%R04%'"
```

Use `--raw-dir` and `--output-dir` with `run` to choose source and output folders. The loader's
row-count sanity gate remains enabled; `--force` explicitly overrides a large row-count drop.

## Review outputs

- `out/report.html`: a self-contained report with CHF ARR totals, scorecard, an SVG gap
  waterfall starting at zero, push readiness, named owners and quarantine counts. No external assets.
- `out/review.xlsx`: Scorecard, Exceptions, Fixes, Push readiness, ARR bridge and Quarantine.
  Yellow cells are empty review inputs. Exceptions retains the original finding text in
  `finding_reason`; `decision`, `reason` and `assignee` start empty. Fixes has an empty
  `approved` column. These inputs are reserved for the v0.2 review workflow.
- `out/fix_proposals.csv`: all built proposals with an empty `approved` column at the end.

Refresh outputs from an existing build with `l2c fixes propose` and `l2c report`.
Unpriced findings are marked **not valued**. A real zero CHF amount stays zero.

Push readiness shows days since contract start and every failing check in plain language.
It lists OVERDUE first, followed by DRAFT_ONLY, BLOCKED and READY. A Draft order takes status
precedence over age; otherwise a deal becomes overdue strictly after the configured billing
grace period. Failing checks remain visible in either case.

The default seed's unexplained ARR is zero. The three intentionally dirty CRM contracts below
each have CHF 12,000 of billing ARR but cannot contribute CRM ARR. Their CHF 36,000 total is
classified as `crm_arr_not_valued`, preserving the audit cases and the independent ARR totals:

| Deal | Billing order | Cause |
| --- | --- | --- |
| PLANT-A08 | PLANT-O-A08 | Missing CRM contract end |
| PLANT-A17 | PLANT-O-A17 | CRM contract end precedes its start |
| PLANT-R08 | PLANT-O-R08 | Missing CRM amount |

`l2c slack` prints the ARR gap, scorecard summary and top five exceptions. It stays offline
even when a webhook is configured. Sending requires both an explicit `--send` and the
`SLACK_WEBHOOK_URL` environment variable:

```powershell
l2c slack
l2c slack --send
```

## Roadmap

v0.2 is planned to add:

- Exception memory, the change line and score history (`remember`).
- Workbook decision import (`decisions import`).
- Approved fixes, dry runs, live HubSpot changes and rollback (`fixes apply`, `fixes rollback`).
- Export diagnostics and read-only API pulls (`doctor`, `pull hubspot`, `pull younium`).

These commands currently print `planned for v0.2 - see README roadmap` and exit with code 1.

## Verify

```powershell
python -m pytest -q
ruff check .
l2c run
l2c show arr_bridge
```

Tests use temporary databases and fake HTTP responses. The demo pipeline runs offline.
