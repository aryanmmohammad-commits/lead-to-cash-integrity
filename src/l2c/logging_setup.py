"""One JSON log line per pipeline step, carrying its run ID."""

import json
import logging
from typing import TextIO


class StepFormatter(logging.Formatter):
    """Keep the step log machine-readable and on a single line."""

    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(
            {
                "run_id": getattr(record, "run_id", None),
                "step": getattr(record, "step", record.getMessage()),
                "rows": getattr(record, "rows", None),
                "seconds": getattr(record, "seconds", None),
                "status": getattr(record, "status", record.levelname.lower()),
            },
            ensure_ascii=False,
        )


def setup_logging(*, level: int = logging.INFO, stream: TextIO | None = None) -> logging.Logger:
    """Configure only the l2c logger; repeated setup does not duplicate output."""
    logger = logging.getLogger("l2c")
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        handler.close()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(StepFormatter())
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False
    return logger


def log_step(*, run_id: str, step: str, rows: int | None, seconds: float, status: str) -> None:
    """Record a completed step without changing the root logger."""
    logger = logging.getLogger("l2c")
    if not logger.handlers:
        logger = setup_logging()
    logger.info(
        step,
        extra={
            "run_id": run_id,
            "step": step,
            "rows": rows,
            "seconds": seconds,
            "status": status,
        },
    )
