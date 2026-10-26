"""Export proposals for review; live changes are planned for v0.2."""

import csv
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from l2c.logging_setup import log_step
from l2c.output_data import atomic_output, read_database, read_mart
from l2c.paths import OUT_DIR, resolve_repo_path


@dataclass(frozen=True)
class ProposalExport:
    path: Path
    rows: int


def propose_fixes(
    *, db_path: str | Path | None = None, output_dir: Path = OUT_DIR, run_id: str | None = None
) -> ProposalExport:
    started = perf_counter()
    run_id = run_id or uuid4().hex
    result = None
    try:
        with read_database(db_path) as connection:
            table = read_mart(connection, "fix_proposals")
        destination = resolve_repo_path(output_dir) / "fix_proposals.csv"
        with atomic_output(destination) as temporary:
            with temporary.open("w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.writer(stream, lineterminator="\n")
                writer.writerow([*table.columns, "approved"])
                for row in sorted(table.rows, key=lambda item: item["proposal_id"]):
                    writer.writerow([*(row[column] for column in table.columns), ""])
        result = ProposalExport(destination, len(table.rows))
        return result
    finally:
        log_step(
            run_id=run_id,
            step="fixes.propose",
            rows=result.rows if result else None,
            seconds=perf_counter() - started,
            status="ok" if result else "failed",
        )
