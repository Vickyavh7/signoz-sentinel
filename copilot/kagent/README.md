# Optional kagent packaging (stretch)

Only after Checkpoints 1–5 are green. This does **not** replace the custom
FastAPI copilot — it packages the same investigation prompt + SigNoz MCP tools
as a Kubernetes-native Agent CRD.

## Manifests (apply after installing kagent Helm charts)

```yaml
apiVersion: kagent.dev/v1alpha1
kind: ModelConfig
metadata:
  name: sentinel-model
  namespace: foundry
spec:
  provider: OpenAI  # or Anthropic / Ollama
  model: gpt-4o-mini
  apiKeySecret: incident-sentinel-secrets
  apiKeySecretKey: LLM_API_KEY
---
apiVersion: kagent.dev/v1alpha1
kind: ToolServer
metadata:
  name: signoz-mcp
  namespace: foundry
spec:
  type: Remote
  remote:
    url: http://FOUNDRY_HOST:8000/mcp
    headers:
      SIGNOZ-API-KEY: from-secret
---
apiVersion: kagent.dev/v1alpha1
kind: Agent
metadata:
  name: incident-sentinel-kagent
  namespace: foundry
spec:
  description: SRE incident investigator over SigNoz MCP
  modelConfig: sentinel-model
  systemMessage: |
    You are Incident Sentinel. Investigate fired SigNoz alerts using MCP tools
    (search traces/logs, get trace details, list services). Conclude with root
    cause, confidence, evidence webUrls, and suggested actions.
  tools:
    - type: McpServer
      mcpServer:
        name: signoz-mcp
```

## Notes

- Enable kagent OTel export to `http://FOUNDRY_HOST:4318`
- Keep webhook + Slack report in the custom FastAPI service — kagent is an
  alternate investigation runtime for demos, not the alert ingress
- CRD API versions may differ by kagent release — verify against
  https://kagent.dev/ before applying
