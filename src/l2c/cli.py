"""Offline integrity pipeline and explicit placeholders for the v0.2 roadmap."""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, NoReturn

import pandas as pd
import typer

from l2c.config import ConfigError
from l2c.dbt_runner import build_models, preview_table
from l2c.fixes import propose_fixes
from l2c.generate import ExportFormat, Profile, generate_files
from l2c.load import load_files
from l2c.logging_setup import setup_logging
from l2c.paths import OUT_DIR, RAW_DIR
from l2c.pipeline import run_pipeline
from l2c.report import write_report
from l2c.slack import build_digest, send_digest

MappingOption = Annotated[
    Path,
    typer.Option(
        "--mapping",
        envvar="L2C_MAPPING",
        help="Source mapping YAML; relative paths are resolved from the repository root.",
    ),
]
DEFAULT_MAPPING = Path("config/mapping.yml")

app = typer.Typer(help="Check synthetic HubSpot CRM against Younium billing.", no_args_is_help=True)
decisions_app = typer.Typer(help="Import human review decisions.", no_args_is_help=True)
fixes_app = typer.Typer(help="Propose, apply and roll back approved fixes.", no_args_is_help=True)
pull_app = typer.Typer(help="Read-only source pulls.", no_args_is_help=True)
app.add_typer(decisions_app, name="decisions")
app.add_typer(fixes_app, name="fixes")
app.add_typer(pull_app, name="pull")


def _planned() -> NoReturn:
    typer.echo("planned for v0.2 - see README roadmap")
    raise typer.Exit(code=1)


@contextmanager
def _output_command() -> Iterator[None]:
    logger = setup_logging()
    try:
        yield
    except (ValueError, OSError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    finally:
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)
            handler.close()


@app.command()
def generate(
    context: typer.Context,
    mapping: MappingOption = DEFAULT_MAPPING,
    seed: Annotated[int, typer.Option(help="Fixed seed for the background and synthetic FX.")] = 42,
    format_name: Annotated[ExportFormat, typer.Option("--format")] = ExportFormat.DEFAULT,
    profile: Annotated[Profile, typer.Option()] = Profile.SMALL,
    scale: Annotated[int, typer.Option(min=1)] = 1,
    output_dir: Annotated[Path, typer.Option("--output-dir")] = RAW_DIR,
) -> None:
    """Generate deterministic synthetic source files."""
    source = context.get_parameter_source("mapping")
    selected_mapping = None if source is not None and source.name == "DEFAULT" else mapping
    logger = setup_logging()
    try:
        counts = generate_files(
            seed=seed,
            format_name=format_name.value,
            profile=profile.value,
            scale=scale,
            mapping_path=selected_mapping,
            output_dir=output_dir,
        )
    except (ConfigError, ValueError, OSError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    finally:
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)
            handler.close()
    typer.echo(f"Generated {len(counts)} synthetic CSVs in {output_dir}")


@app.command(name="load")
def load_sources(
    mapping: MappingOption = DEFAULT_MAPPING,
    force: Annotated[
        bool, typer.Option(help="Override row-count drops with a logged warning.")
    ] = False,
) -> None:
    """Load source files into the raw schema."""
    logger = setup_logging()
    try:
        result = load_files(mapping_path=mapping, raw_dir=RAW_DIR, force=force)
    except (ConfigError, ValueError, OSError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    finally:
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)
            handler.close()
    typer.echo(
        f"Loaded {len(result.row_counts)} tables ({sum(result.row_counts.values())} rows); "
        f"run {result.run_id}"
    )


@app.command()
def build(mapping: MappingOption = DEFAULT_MAPPING) -> None:
    """Build and test dbt models with the source mapping."""
    logger = setup_logging()
    try:
        result = build_models(mapping_path=mapping)
    except (ConfigError, ValueError, OSError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    finally:
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)
            handler.close()
    typer.echo(f"dbt build passed ({result.nodes} models/tests); run {result.run_id}")


@app.command()
def remember() -> None:
    """Update exception memory after a build."""
    _planned()


@decisions_app.command(name="import")
def import_decisions() -> None:
    """Import decisions from the review workbook."""
    _planned()


@fixes_app.command()
def propose(output_dir: Annotated[Path, typer.Option("--output-dir")] = OUT_DIR) -> None:
    """Export fix proposals for human approval."""
    with _output_command():
        result = propose_fixes(output_dir=output_dir)
    typer.echo(f"Wrote {result.rows} proposals to {result.path}")


@fixes_app.command()
def apply() -> None:
    """Plan approved fixes; applying fixes will default to a dry run."""
    _planned()


@fixes_app.command()
def rollback() -> None:
    """Plan restoration of values from a previous fix run."""
    _planned()


@app.command()
def report(output_dir: Annotated[Path, typer.Option("--output-dir")] = OUT_DIR) -> None:
    """Create the HTML report and Excel review workbook."""
    with _output_command():
        result = write_report(output_dir=output_dir)
    typer.echo(f"Wrote {result.html_path}\nWrote {result.workbook_path}")


@app.command()
def slack(
    send: Annotated[bool, typer.Option("--send", help="Post using SLACK_WEBHOOK_URL.")] = False,
) -> None:
    """Preview the Slack digest."""
    with _output_command():
        message = build_digest()
        typer.echo(message)
        if send:
            send_digest(message)
            typer.echo("Slack digest sent")


@app.command()
def show(
    table: Annotated[str, typer.Argument(help="Table name, optionally prefixed by schema.")],
    where: Annotated[
        str | None, typer.Option("--where", help="Optional SQL filter expression.")
    ] = None,
) -> None:
    """Preview a database table."""
    try:
        preview = preview_table(table, where=where)
    except (ValueError, OSError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(pd.DataFrame(preview.rows, columns=preview.columns).to_string(index=False))


@app.command()
def doctor(mapping: MappingOption = DEFAULT_MAPPING) -> None:
    """Check source exports against the mapping without changing them."""
    _planned()


@pull_app.command()
def hubspot(mapping: MappingOption = DEFAULT_MAPPING) -> None:
    """Pull read-only HubSpot data into the source file layout."""
    _planned()


@pull_app.command()
def younium(mapping: MappingOption = DEFAULT_MAPPING) -> None:
    """Pull read-only Younium data into the source file layout."""
    _planned()


@app.command()
def run(
    context: typer.Context,
    mapping: MappingOption = DEFAULT_MAPPING,
    seed: Annotated[int, typer.Option()] = 42,
    format_name: Annotated[ExportFormat, typer.Option("--format")] = ExportFormat.DEFAULT,
    raw_dir: Annotated[Path, typer.Option("--raw-dir")] = RAW_DIR,
    output_dir: Annotated[Path, typer.Option("--output-dir")] = OUT_DIR,
    force: Annotated[
        bool, typer.Option(help="Override the loader's row-count sanity gate.")
    ] = False,
) -> None:
    """Run the complete synthetic-data pipeline."""
    source = context.get_parameter_source("mapping")
    selected_mapping = None if source is not None and source.name == "DEFAULT" else mapping
    with _output_command():
        result = run_pipeline(
            mapping_path=selected_mapping,
            seed=seed,
            format_name=format_name.value,
            raw_dir=raw_dir,
            output_dir=output_dir,
            force=force,
        )
    typer.echo(
        f"Pipeline complete; run {result.run_id}\nWrote {result.proposals.path}\n"
        f"Wrote {result.report.html_path}\nWrote {result.report.workbook_path}"
    )


if __name__ == "__main__":
    app()
