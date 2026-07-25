# Getting started (clean env)

Generic setup without lab-specific hosts. Replace placeholders with your values.

## Foundry SigNoz + MCP

1. Use `foundry/casting.yaml` and `foundry/casting.yaml.lock` with foundryctl / Foundry docs.
2. Expose UI (`:8080`), OTLP HTTP (`:4318`), MCP (`:8000` /mcp).
3. Register an admin, create a Service Account API key with Admin or Editor role.

## Secrets (Kubernetes)

Create secret `incident-sentinel-secrets` in namespace `foundry` with keys:

- `SIGNOZ_API_KEY`
- `LLM_API_KEY`
- `SLACK_WEBHOOK_URL` (optional)

Always set all three together when rotating — updating only one key can wipe the others depending on your apply method.

## Auth note

- Long-lived **Service Account** keys → `SIGNOZ-API-KEY` header (see `copilot/app/mcp_client.py`)
- User JWT login tokens → `Authorization: Bearer …` only (do not send JWTs as `SIGNOZ-API-KEY`)

## Deploy

```bash
export FOUNDRY_HOST=<signoz-reachable-host>
export LLM_PROVIDER=openai
export LLM_MODEL=<your-model>
export LLM_BASE_URL=<openai-compatible-base-url>   # optional
export SIGNOZ_API_KEY=...
export LLM_API_KEY=...
export SLACK_WEBHOOK_URL=...   # optional
./scripts/deploy-k8s.sh
```

## Alerts

```bash
export WEBHOOK_URL=http://<node-ip>:32080/webhook/signoz
./scripts/setup-alert-webhook.sh
```

Optional dashboards: import JSON from `dashboards/`, or run `scripts/setup-agent-quality-dashboard.sh` after setting `SIGNOZ_PASSWORD` and `SIGNOZ_ORG_ID`.

## Smoke test

```bash
curl -sS http://<node-ip>:32080/healthz
NS=foundry ./demo/break.sh errors
```
