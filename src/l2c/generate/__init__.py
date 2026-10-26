"""Deterministic synthetic data generation, without database or network access."""

import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from l2c.config import RulesConfig, load_mapping, load_rules
from l2c.generate.background import add_background, add_reference_data
from l2c.generate.cases import add_planted_cases
from l2c.generate.model import Dataset, empty_dataset
from l2c.generate.writer import write_files
from l2c.logging_setup import log_step
from l2c.paths import CONFIG_DIR, DEFAULT_MAPPING_PATH, RAW_DIR


class ExportFormat(StrEnum):
    DEFAULT = "default"
    CH = "ch"
    DE = "de"
    HUBSPOT_UI = "hubspot_ui"


class Profile(StrEnum):
    SMALL = "small"
    LARGE = "large"


@dataclass
class GeneratedData:
    tables: Dataset
    planted_records: dict[str, Dataset]


def generate_data(
    *, seed: int = 42, rules: RulesConfig | None = None, profile: str = "small", scale: int = 1
) -> GeneratedData:
    profile = Profile(profile)
    if type(scale) is not int or scale < 1:
        raise ValueError("scale: must be a positive integer")
    if profile == Profile.SMALL and scale != 1:
        raise ValueError("scale: use --profile large when --scale is not 1")
    rules = rules or load_rules()
    tables = empty_dataset(load_mapping(DEFAULT_MAPPING_PATH))
    add_background(tables, rules, seed=seed, scale=scale)
    records = add_planted_cases(tables, rules)
    add_reference_data(tables, rules, seed=seed)
    return GeneratedData(tables, records)


def generate_files(
    *,
    seed: int = 42,
    format_name: str = "default",
    profile: str = "small",
    scale: int = 1,
    mapping_path: str | Path | None = None,
    output_dir: Path = RAW_DIR,
    run_id: str | None = None,
) -> dict[str, int]:
    started = perf_counter()
    run_id = run_id or uuid4().hex
    counts = None
    try:
        format_name = ExportFormat(format_name).value
        default = CONFIG_DIR / (
            "mapping.yml" if format_name == "default" else f"mapping.{format_name}.yml"
        )
        mapping = load_mapping(mapping_path or os.environ.get("L2C_MAPPING") or default)
        rules = load_rules()
        generated = generate_data(seed=seed, rules=rules, profile=profile, scale=scale)
        counts = write_files(generated.tables, mapping, output_dir, format_name=format_name)
        return counts
    finally:
        log_step(
            run_id=run_id,
            step="generate",
            rows=sum(counts.values()) if counts is not None else None,
            seconds=perf_counter() - started,
            status="ok" if counts is not None else "failed",
        )
