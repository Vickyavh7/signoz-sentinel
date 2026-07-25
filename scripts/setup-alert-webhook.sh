#!/usr/bin/env bash
# Create SigNoz webhook channel + checkout-error-spike rule (idempotent-ish).
# Run on Foundry host with SIGNOZ admin session.
# Usage:
#   SIGNOZ_URL=http://127.0.0.1:8080 \
#   SIGNOZ_EMAIL=admin@example.com \
#   SIGNOZ_PASSWORD='...' \
#   SIGNOZ_ORG_ID=<your-org-id> \
#   WEBHOOK_URL=http://<node-ip>:32080/webhook/signoz \
#   ./scripts/setup-alert-webhook.sh
set -euo pipefail
SIGNOZ_URL="${SIGNOZ_URL:-http://127.0.0.1:8080}"
WEBHOOK_URL="${WEBHOOK_URL:?set WEBHOOK_URL to http://<node>:32080/webhook/signoz}"
EMAIL="${SIGNOZ_EMAIL:-admin@example.com}"
PASSWORD="${SIGNOZ_PASSWORD:?set SIGNOZ_PASSWORD}"
ORG_ID="${SIGNOZ_ORG_ID:?set SIGNOZ_ORG_ID}"

TOKEN=$(curl -fsS -X POST "$SIGNOZ_URL/api/v2/sessions/email_password" \
  -H 'Content-Type: application/json' \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\",\"orgId\":\"$ORG_ID\"}" \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["data"]["accessToken"])')

AUTH=( -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' )

# Channel (skip if name exists)
EXISTING=$(curl -fsS "${AUTH[@]}" "$SIGNOZ_URL/api/v1/channels" \
  | python3 -c 'import sys,json; print(any(c.get("name")=="incident-sentinel-webhook" for c in json.load(sys.stdin).get("data") or []))')
if [[ "$EXISTING" != "True" ]]; then
  curl -fsS -X POST "$SIGNOZ_URL/api/v1/channels" "${AUTH[@]}" \
    -d "{\"name\":\"incident-sentinel-webhook\",\"type\":\"webhook\",\"webhook_configs\":[{\"url\":\"$WEBHOOK_URL\",\"send_resolved\":true}]}" \
    >/dev/null
  echo "Created channel incident-sentinel-webhook → $WEBHOOK_URL"
else
  echo "Channel incident-sentinel-webhook already exists"
fi

# Rule (create if no checkout-error-spike)
HAS_RULE=$(curl -fsS "${AUTH[@]}" "$SIGNOZ_URL/api/v1/rules" \
  | python3 -c 'import sys,json; d=json.load(sys.stdin); rules=(d.get("data") or {}).get("rules") or []; print(any("checkout-error-spike"==r.get("alert") for r in rules))')
if [[ "$HAS_RULE" != "True" ]]; then
  curl -fsS -X POST "$SIGNOZ_URL/api/v1/rules" "${AUTH[@]}" -d @- <<'JSON' >/dev/null
{
  "alert": "checkout-error-spike",
  "alertType": "TRACES_BASED_ALERT",
  "ruleType": "threshold_rule",
  "severity": "warning",
  "description": "Elevated error spans on checkout-api — triggers Incident Sentinel",
  "evalWindow": "5m0s",
  "frequency": "1m0s",
  "condition": {
    "compositeQuery": {
      "queries": [
        {
          "type": "builder_query",
          "spec": {
            "name": "A",
            "signal": "traces",
            "aggregations": [{"expression": "count()"}],
            "filter": {"expression": "service.name = 'checkout-api' AND has_error = true"},
            "disabled": false
          }
        }
      ]
    },
    "op": "1",
    "target": 3,
    "matchType": "1",
    "selectedQueryName": "A"
  },
  "labels": {"service": "checkout-api", "team": "hackathon"},
  "preferredChannels": ["incident-sentinel-webhook"],
  "version": "v5"
}
JSON
  echo "Created rule checkout-error-spike"
else
  echo "Rule checkout-error-spike already exists"
fi

echo "Done. Fire with: NS=foundry ./demo/break.sh errors  (wait ~1–5m for eval)"
