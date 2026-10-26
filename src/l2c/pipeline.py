"""The v0.1 pipeline: five sequential steps, stopping on the first exception."""

import os
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from l2c.dbt_runner import build_models
from l2c.fixes import ProposalExport, propose_fixes
from l2c.generate import ExportFormat, generate_files
from l2c.load import load_files
from l2c.paths import CONFIG_DIR, OUT_DIR, RAW_DIR, resolve_repo_path
from l2c.report import ReportOutputs, write_report


@dataclass(frozen=True)
class PipelineResult:
    run_id: str
    proposals: ProposalExport
    report: ReportOutputs


def run_pipeline(
    *,
    mapping_path: str | Path | None = None,
    seed: int = 42,
    format_name: str = "default",
    raw_dir: Path = RAW_DIR,
    output_dir: Path = OUT_DIR,
    db_path: str | Path | None = None,
    artifact_dir: Path | None = None,
    force: bool = False,
) -> PipelineResult:
    format_name = ExportFormat(format_name).value
    default = CONFIG_DIR / (
        "mapping.yml" if format_name == "default" else f"mapping.{format_name}.yml"
    )
    mapping = resolve_repo_path(mapping_path or os.environ.get("L2C_MAPPING") or default)
    raw_dir, output_dir = resolve_repo_path(raw_dir), resolve_repo_path(output_dir)
    run_id = uuid4().hex
    generate_files(
        seed=seed,
        format_name=format_name,
        mapping_path=mapping,
        output_dir=raw_dir,
        run_id=run_id,
    )
    load_files(mapping_path=mapping, raw_dir=raw_dir, db_path=db_path, force=force, run_id=run_id)
    build_models(mapping_path=mapping, db_path=db_path, artifact_dir=artifact_dir, run_id=run_id)
    proposals = propose_fixes(db_path=db_path, output_dir=output_dir, run_id=run_id)
    report = write_report(db_path=db_path, output_dir=output_dir, run_id=run_id)
    return PipelineResult(run_id, proposals, report)
