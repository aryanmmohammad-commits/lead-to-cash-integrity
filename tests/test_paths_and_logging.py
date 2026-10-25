import io
import json
from pathlib import Path

import pytest

from l2c.config import load_mapping
from l2c.logging_setup import log_step, setup_logging
from l2c.paths import (
    DEFAULT_DB_PATH,
    DEFAULT_MAPPING_PATH,
    REPO_ROOT,
    get_db_path,
    get_mapping_path,
)


def test_paths_are_independent_of_working_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("L2C_DB_PATH", raising=False)
    monkeypatch.delenv("L2C_MAPPING", raising=False)
    assert get_db_path() == DEFAULT_DB_PATH
    assert get_mapping_path() == DEFAULT_MAPPING_PATH
    assert load_mapping().tables


def test_path_overrides_are_read_at_call_time(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("L2C_DB_PATH", str(tmp_path / "first.duckdb"))
    assert get_db_path() == tmp_path / "first.duckdb"
    monkeypatch.setenv("L2C_DB_PATH", "data/second.duckdb")
    assert get_db_path() == REPO_ROOT / "data" / "second.duckdb"
    monkeypatch.setenv("L2C_MAPPING", str(DEFAULT_MAPPING_PATH))
    assert load_mapping().tables
    assert get_mapping_path("config/explicit.yml") == REPO_ROOT / "config" / "explicit.yml"


def test_logging_emits_one_json_line_even_after_repeated_setup() -> None:
    stream = io.StringIO()
    logger = setup_logging(stream=stream)
    setup_logging(stream=stream)
    try:
        log_step(run_id="run-42", step="load\nMüller", rows=12, seconds=0.25, status="ok")
        lines = stream.getvalue().splitlines()
        assert len(lines) == 1
        assert json.loads(lines[0]) == {
            "run_id": "run-42",
            "step": "load\nMüller",
            "rows": 12,
            "seconds": 0.25,
            "status": "ok",
        }
    finally:
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)
            handler.close()
