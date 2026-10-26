"""Offline digest by default; sending requires an explicit call and webhook."""

import os
from collections.abc import Callable
from pathlib import Path
from time import perf_counter
from uuid import uuid4

import requests

from l2c.logging_setup import log_step
from l2c.output_data import ReviewData, chf, read_review_data, scorecard_summary


def _slack_text(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def format_digest(data: ReviewData) -> str:
    lines = [
        f"Lead-to-cash integrity as of {data.rules.as_of_date}",
        f"CRM ARR: {chf(data.crm_arr)}",
        f"Billing ARR: {chf(data.billing_arr)}",
        f"ARR gap (billing minus CRM): {chf(data.gap)}",
        f"Scorecard: {scorecard_summary(data)}.",
        "Top 5 exceptions by money at risk:",
    ]
    for index, row in enumerate(data.ranked_exceptions[:5], 1):
        lines.append(
            f"{index}. {row['check_id']} {row['record_id']}: {chf(row['money_at_risk_chf'])}; "
            f"{row['severity']}; owner {row['owner_id']}; {row['reason']}"
        )
    if not data.tables["exceptions"].rows:
        lines.append("No exceptions.")
    lines.append("Synthetic data. Independent demo.")
    return "\n".join(_slack_text(line) for line in lines)


def build_digest(*, db_path: str | Path | None = None, run_id: str | None = None) -> str:
    started = perf_counter()
    run_id = run_id or uuid4().hex
    message = None
    try:
        data = read_review_data(db_path)
        message = format_digest(data)
        return message
    finally:
        log_step(
            run_id=run_id,
            step="slack.preview",
            rows=None,
            seconds=perf_counter() - started,
            status="ok" if message is not None else "failed",
        )


def send_digest(
    message: str, *, post: Callable[..., requests.Response] | None = None, run_id: str | None = None
) -> None:
    started = perf_counter()
    run_id = run_id or uuid4().hex
    sent = False
    try:
        webhook = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
        if not webhook:
            raise ValueError("SLACK_WEBHOOK_URL must be set to send the Slack digest")
        try:
            response = (post or requests.post)(webhook, json={"text": message}, timeout=10)
            response.raise_for_status()
        except requests.RequestException as exc:
            # Webhook URLs contain credentials; requests error strings can expose them.
            raise ValueError("Slack delivery failed; check webhook access and try again") from exc
        sent = True
    finally:
        log_step(
            run_id=run_id,
            step="slack.send",
            rows=None,
            seconds=perf_counter() - started,
            status="ok" if sent else "failed",
        )
