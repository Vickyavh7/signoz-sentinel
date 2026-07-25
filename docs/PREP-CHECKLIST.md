# Prep checklist (Phase 0)

Human actions you must complete yourself (cannot be automated):

- [ ] Register at https://www.wemakedevs.org/hackathons/signoz (team 1–4)
- [ ] Join SigNoz Slack: https://signoz.io/slack
- [ ] Create LLM API key (OpenAI / Anthropic / Gemini / Groq) OR plan Ollama on Foundry host
- [ ] Create Slack Incoming Webhook (or Telegram bot) for incident reports
- [ ] Put secrets in `.env` on the Foundry host / k8s Secret — never commit

## Reading notes (completed in prep)

| Topic | Source | Takeaway for Incident Sentinel |
|-------|--------|--------------------------------|
| Foundry | https://signoz.io/docs/install/docker/ | `casting.yaml` + lock required; MCP via `mcp.spec.enabled` |
| MCP tools | https://github.com/SigNoz/signoz-mcp-server | Use search_traces/logs, get_trace_details, query_metrics, list_services, alert history |
| GenAI semconv | https://opentelemetry.io/docs/specs/semconv/gen-ai/ | `gen_ai.system`, `gen_ai.request.model`, `gen_ai.usage.*` on LLM spans |
| Slack Block Kit | Slack docs | Header + sections + deep-link buttons for report UX |

## Report format sketch

See `docs/REPORT-FORMAT.md`.
