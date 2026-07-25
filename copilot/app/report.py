"""Slack / stdout report formatter."""
from __future__ import annotations

import logging
from typing import Any

import httpx

from .config import settings

log = logging.getLogger(__name__)


def format_blocks(report: dict[str, Any], investigation_trace_id: str | None = None) -> list[dict]:
    severity = report.get("severity") or "warning"
    emoji = {"critical": ":rotating_light:", "warning": ":warning:", "info": ":information_source:"}.get(
        severity, ":mag:"
    )
    evidence_lines = []
    for e in report.get("evidence") or []:
        label = e.get("label", "evidence")
        url = e.get("webUrl") or settings.signoz_url
        detail = e.get("detail", "")
        evidence_lines.append(f"• <{url}|{label}> — {detail}")
    actions = report.get("suggested_actions") or []
    action_text = "\n".join(f"{i+1}. {a}" for i, a in enumerate(actions)) or "_none_"
    timeline = report.get("timeline") or []
    timeline_text = "\n".join(f"• {t}" for t in timeline)
    footer = f"<{settings.signoz_url}|Open SigNoz>"
    if investigation_trace_id:
        footer += f" · Investigation trace `{investigation_trace_id}`"
    if report.get("degraded"):
        footer += " · :warning: degraded mode (LLM analysis incomplete — evidence-only report)"

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"{emoji} Incident Sentinel — {report.get('alert_name', 'alert')}"[:150],
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*Summary:* {report.get('summary', '')}\n"
                    f"*Severity:* {severity} · *Confidence:* {report.get('confidence', 0)}"
                ),
            },
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Root cause*\n{report.get('root_cause', '')}"},
        },
    ]
    if report.get("impact"):
        blocks.append(
            {"type": "section", "text": {"type": "mrkdwn", "text": f"*Impact*\n{report['impact']}"}}
        )
    if timeline_text:
        blocks.append(
            {"type": "section", "text": {"type": "mrkdwn", "text": f"*Timeline*\n{timeline_text}"}}
        )
    blocks.extend(
        [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*Evidence*\n" + ("\n".join(evidence_lines) or "_none_"),
                },
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Suggested actions*\n{action_text}"},
            },
        ]
    )
    if report.get("cascade_refined"):
        footer += " · cascade-refined culprit"
    blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": footer}]})
    return blocks


def post_report(report: dict[str, Any], investigation_trace_id: str | None = None) -> dict[str, Any]:
    blocks = format_blocks(report, investigation_trace_id)
    text = report.get("summary") or "Incident Sentinel report"
    if settings.slack_webhook_url:
        with httpx.Client(timeout=30.0) as client:
            r = client.post(
                settings.slack_webhook_url,
                json={"text": text, "blocks": blocks},
            )
            r.raise_for_status()
        log.info("Posted report to Slack")
        return {"channel": "slack", "ok": True}
    # Fallback: log structured report for demos without Slack
    log.info("SLACK_WEBHOOK_URL unset — report:\n%s", text)
    for b in blocks:
        log.info("block: %s", b)
    return {"channel": "stdout", "ok": True, "blocks": blocks}
