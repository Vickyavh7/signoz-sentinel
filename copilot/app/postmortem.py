"""Auto-generated postmortem artifacts from completed investigations."""
from __future__ import annotations

import logging
import time
from collections import OrderedDict
from typing import Any

import httpx

from .config import settings

log = logging.getLogger(__name__)

# Last N postmortems kept in memory, served via GET /postmortems.
_STORE: OrderedDict[str, dict[str, Any]] = OrderedDict()
_MAX_KEPT = 20


def build_postmortem(report: dict[str, Any], meta: dict[str, Any]) -> str:
    """Render a markdown postmortem from the investigation report + run metadata."""
    ts = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
    alert = report.get("alert_name", "unknown-alert")
    lines = [
        f"# Postmortem: {alert}",
        "",
        f"- **Date:** {ts}",
        f"- **Severity:** {report.get('severity', 'warning')}",
        f"- **Primary service:** {report.get('service', 'unknown')}",
        f"- **Confidence:** {report.get('confidence', 0)}",
        f"- **Investigation duration:** {meta.get('duration_s', 0):.1f}s"
        f" · **Cost:** ${meta.get('cost_usd', 0):.4f}"
        f" · **Tokens:** {meta.get('tokens_in', 0)}/{meta.get('tokens_out', 0)}",
    ]
    if meta.get("trace_id"):
        lines.append(f"- **Investigation trace:** `{meta['trace_id']}` (service `{settings.service_name}` in SigNoz)")
    if report.get("degraded"):
        lines.append("- **Note:** degraded mode — LLM analysis incomplete, evidence-only report")
    lines += ["", "## Summary", "", report.get("summary", ""), ""]
    if report.get("impact"):
        lines += ["## Impact", "", str(report["impact"]), ""]
    timeline = report.get("timeline") or []
    if timeline:
        lines += ["## Timeline", ""] + [f"- {t}" for t in timeline] + [""]
    lines += ["## Root cause", "", report.get("root_cause", ""), ""]
    evidence = report.get("evidence") or []
    if evidence:
        lines += ["## Evidence", ""]
        for e in evidence:
            lines.append(f"- **{e.get('label', 'evidence')}** — {e.get('detail', '')}")
            if e.get("webUrl"):
                lines.append(f"  - {e['webUrl']}")
        lines.append("")
    actions = report.get("suggested_actions") or []
    if actions:
        lines += ["## Action items", ""] + [f"- [ ] {a}" for a in actions] + [""]
    remediation = report.get("proposed_remediation") or {}
    if remediation.get("action"):
        lines += ["## Notes (optional remediation idea — not executed)", "", f"- {remediation['action']}", ""]
    lines += ["---", "", "*Generated automatically by Incident Sentinel.*"]
    return "\n".join(lines)


def save_postmortem(rule_id: str, markdown: str, report: dict[str, Any]) -> None:
    _STORE[rule_id] = {
        "rule_id": rule_id,
        "alert_name": report.get("alert_name"),
        "created_at": time.time(),
        "markdown": markdown,
    }
    while len(_STORE) > _MAX_KEPT:
        _STORE.popitem(last=False)


def list_postmortems() -> list[dict[str, Any]]:
    return [
        {k: v[k] for k in ("rule_id", "alert_name", "created_at")}
        for v in reversed(_STORE.values())
    ]


def get_postmortem(rule_id: str) -> dict[str, Any] | None:
    return _STORE.get(rule_id)


def post_postmortem_to_slack(markdown: str) -> None:
    """Post the postmortem as a follow-up Slack message (best effort)."""
    if not settings.slack_webhook_url:
        return
    try:
        # Slack section blocks cap at 3000 chars; trim to fit and avoid
        # nested code fences breaking the outer block.
        body = markdown.replace("```", "'''")
        if len(body) > 2900:
            body = body[:2900] + "\n…(truncated)"
        with httpx.Client(timeout=30.0) as client:
            r = client.post(
                settings.slack_webhook_url,
                json={
                    "text": "Incident Sentinel postmortem",
                    "blocks": [
                        {
                            "type": "section",
                            "text": {"type": "mrkdwn", "text": ":memo: *Auto-generated postmortem*\n```" + body + "```"},
                        }
                    ],
                },
            )
            r.raise_for_status()
        log.info("Posted postmortem to Slack")
    except Exception:
        log.exception("Failed to post postmortem to Slack")
