"""Write canonical fixture rows using only mapping-defined headers/formats/labels."""

import csv
from datetime import date
from decimal import Decimal
from pathlib import Path

from l2c.config import FileFormat, MappingConfig
from l2c.generate.model import Dataset, Scalar


def _number(value: Decimal, file_format: FileFormat) -> str:
    text = format(value, "f")
    whole, _, fraction = text.partition(".")
    if file_format.thousands:
        sign = "-" if whole.startswith("-") else ""
        whole = sign + format(int(whole.lstrip("-")), ",").replace(",", file_format.thousands)
    fraction = fraction.ljust(2, "0")
    return whole + file_format.decimal + fraction


def _cell(value: Scalar, file_format: FileFormat, values: dict[str, str]) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, date):
        return value.strftime(file_format.date_format)
    if isinstance(value, Decimal):
        return _number(value, file_format)
    text = str(value)
    return next((label for label, internal in values.items() if internal == text), text)


def write_files(
    data: Dataset, mapping: MappingConfig, output_dir: Path, *, format_name: str = "default"
) -> dict[str, int]:
    """Validate the entire export before creating any files, then replace each CSV."""
    if set(data) != set(mapping.tables):
        raise ValueError("mapping: tables must match the canonical synthetic dataset")
    destinations: dict[str, str] = {}
    for table, rows in data.items():
        columns = mapping.tables[table].columns
        for row in rows:
            unknown = row.keys() - columns.keys()
            if unknown:
                raise ValueError(f"mapping.{table}.columns: missing {', '.join(sorted(unknown))}")
        destination = (output_dir / mapping.tables[table].file).resolve()
        if not destination.is_relative_to(output_dir.resolve()):
            raise ValueError(f"mapping.{table}.file: must stay inside the output directory")
        file_key = str(destination).casefold()
        if file_key in destinations:
            raise ValueError(f"mapping.{table}.file: duplicates {destinations[file_key]}")
        destinations[file_key] = table
    output_dir.mkdir(parents=True, exist_ok=True)
    counts = {}
    for table, table_mapping in mapping.tables.items():
        path = output_dir / table_mapping.file
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding=table_mapping.format.encoding, newline="") as stream:
            writer = csv.writer(
                stream,
                delimiter=table_mapping.format.delimiter,
                lineterminator="\n" if format_name == "default" else "\r\n",
            )
            writer.writerow(table_mapping.columns.values())
            for row in data[table]:
                writer.writerow(
                    [
                        _cell(
                            row.get(column),
                            table_mapping.format,
                            table_mapping.values.get(column, {}),
                        )
                        for column in table_mapping.columns
                    ]
                )
        counts[table] = len(data[table])
    return counts
