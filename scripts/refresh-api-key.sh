#!/usr/bin/env bash
# Refresh short-lived SigNoz access token into the foundry Secret (demo only).
# Prefer a long-lived Service Account API key from the SigNoz UI for production demos.
set -euo pipefail
SIGNOZ_URL="${SIGNOZ_URL:-http://127.0.0.1:8080}"
EMAIL="${SIGNOZ_EMAIL:-admin@example.com}"
PASSWORD="${SIGNOZ_PASSWORD:?set SIGNOZ_PASSWORD}"
ORG_ID="${SIGNOZ_ORG_ID:-<your-org-id>}"
NS="${NS:-foundry}"

TOKEN=$(curl -fsS -X POST "$SIGNOZ_URL/api/v2/sessions/email_password" \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\",\"orgId\":\"$ORG_ID\"}" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['data']['accessToken'])")

kubectl -n "$NS" create secret generic incident-sentinel-secrets \
  --from-literal=SIGNOZ_API_KEY="$TOKEN" \
  --from-literal=LLM_API_KEY="${LLM_API_KEY:-}" \
  --from-literal=SLACK_WEBHOOK_URL="${SLACK_WEBHOOK_URL:-}" \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl -n "$NS" rollout restart deploy/incident-sentinel
echo "Updated SIGNOZ_API_KEY and restarted incident-sentinel"
