"""CLI scaffold. Pipeline commands intentionally fail until they are built."""

from pathlib import Path
from typing import Annotated, NoReturn

import typer

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


def _not_built() -> NoReturn:
    typer.echo("not built yet")
    raise typer.Exit(code=1)


@app.command()
def generate(mapping: MappingOption = DEFAULT_MAPPING) -> None:
    """Generate deterministic synthetic source files."""
    _not_built()


@app.command(name="load")
def load_sources(mapping: MappingOption = DEFAULT_MAPPING) -> None:
    """Load source files into the raw schema."""
    _not_built()


@app.command()
def build(mapping: MappingOption = DEFAULT_MAPPING) -> None:
    """Build and test dbt models with the source mapping."""
    _not_built()


@app.command()
def remember() -> None:
    """Update exception memory after a build."""
    _not_built()


@decisions_app.command(name="import")
def import_decisions() -> None:
    """Import decisions from the review workbook."""
    _not_built()


@fixes_app.command()
def propose() -> None:
    """Export fix proposals for human approval."""
    _not_built()


@fixes_app.command()
def apply() -> None:
    """Plan approved fixes; applying fixes will default to a dry run."""
    _not_built()


@fixes_app.command()
def rollback() -> None:
    """Plan restoration of values from a previous fix run."""
    _not_built()


@app.command()
def report() -> None:
    """Create the HTML report and Excel review workbook."""
    _not_built()


@app.command()
def slack() -> None:
    """Preview the Slack digest."""
    _not_built()


@app.command()
def show() -> None:
    """Preview a database table."""
    _not_built()


@app.command()
def doctor(mapping: MappingOption = DEFAULT_MAPPING) -> None:
    """Check source exports against the mapping without changing them."""
    _not_built()


@pull_app.command()
def hubspot(mapping: MappingOption = DEFAULT_MAPPING) -> None:
    """Pull read-only HubSpot data into the source file layout."""
    _not_built()


@pull_app.command()
def younium(mapping: MappingOption = DEFAULT_MAPPING) -> None:
    """Pull read-only Younium data into the source file layout."""
    _not_built()


@app.command()
def run(mapping: MappingOption = DEFAULT_MAPPING) -> None:
    """Run the complete synthetic-data pipeline."""
    _not_built()


if __name__ == "__main__":
    app()
