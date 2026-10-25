"""Repository paths, resolved independently of the current working directory."""

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "config"
DATA_DIR = REPO_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
OUT_DIR = REPO_ROOT / "out"
DEFAULT_DB_PATH = DATA_DIR / "l2c.duckdb"
DEFAULT_RULES_PATH = CONFIG_DIR / "rules.yml"
DEFAULT_MAPPING_PATH = CONFIG_DIR / "mapping.yml"


def resolve_repo_path(path: str | Path) -> Path:
    """Resolve relative paths against the repository, including environment values."""
    expanded = Path(path).expanduser()
    return (expanded if expanded.is_absolute() else REPO_ROOT / expanded).resolve()


def get_db_path() -> Path:
    """Read the override at call time so temporary databases work in tests."""
    return resolve_repo_path(os.environ.get("L2C_DB_PATH") or DEFAULT_DB_PATH)


def get_mapping_path(path: str | Path | None = None) -> Path:
    """An explicit path takes precedence over L2C_MAPPING and the default."""
    return resolve_repo_path(path or os.environ.get("L2C_MAPPING") or DEFAULT_MAPPING_PATH)
