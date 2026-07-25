# Slack / Telegram incident report format (sketch)

## Required fields (JSON internal shape)

```json
{
  "summary": "string — one sentence",
  "root_cause": "string — hypothesis",
  "confidence": 0.0,
  "severity": "critical|warning|info",
  "alert_name": "string",
  "rule_id": "string",
  "service": "string|null",
  "evidence": [
    {"label": "string", "webUrl": "https://signoz.../...", "detail": "string"}
  ],
  "suggested_actions": ["string"],
  "investigation_trace_url": "https://signoz.../trace/..."
}
```

## Slack Block Kit outline

1. Header: `:rotating_light: Incident Sentinel — {alert_name}`
2. Section: summary + severity + confidence
3. Section: **Root cause** (hypothesis)
4. Section: **Evidence** — bullet list with `<webUrl|label>` links
5. Section: **Suggested actions** — numbered list
6. Context footer: link to copilot's own investigation trace (self-observability)

## Degraded mode (LLM failure)

Same shape, but `root_cause` = "Automated evidence bundle (LLM unavailable)" and
`confidence` = 0. Evidence still populated from MCP tool results.
