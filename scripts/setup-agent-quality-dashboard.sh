#!/usr/bin/env bash
# Create or refresh the Agent Quality dashboard in SigNoz (Foundry).
# Usage (on Foundry host):
#   SIGNOZ_PASSWORD=... SIGNOZ_ORG_ID=... ./scripts/setup-agent-quality-dashboard.sh
set -euo pipefail
SIGNOZ_URL="${SIGNOZ_URL:-http://127.0.0.1:8080}"
EMAIL="${SIGNOZ_EMAIL:-admin@example.com}"
PASSWORD="${SIGNOZ_PASSWORD:?set SIGNOZ_PASSWORD}"
ORG_ID="${SIGNOZ_ORG_ID:?set SIGNOZ_ORG_ID}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SPEC="$ROOT/dashboards/agent-quality.spec.json"

TOKEN=$(curl -fsS -X POST "$SIGNOZ_URL/api/v2/sessions/email_password" \
  -H 'Content-Type: application/json' \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\",\"orgId\":\"$ORG_ID\"}" \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["data"]["accessToken"])')

AUTH=( -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' )

# Build a live dashboard payload from the lightweight spec
python3 - "$SPEC" <<'PY' > /tmp/agent-quality-dashboard.json
import json, sys, uuid
spec = json.load(open(sys.argv[1]))
widgets = []
layout = []
for i, w in enumerate(spec["widgets"]):
    wid = str(uuid.uuid4())
    qdata = []
    for qd in w["query"]["builder"]["queryData"]:
        item = {
            "queryName": qd["queryName"],
            "expression": qd["queryName"],
            "dataSource": qd["dataSource"],
            "aggregations": qd["aggregations"],
            "disabled": False,
            "legend": qd.get("legend", ""),
            "groupBy": [],
            "functions": [],
            "having": {"expression": ""},
            "orderBy": [],
            "limit": None,
            "stepInterval": None,
            "source": "",
        }
        if "filter" in qd:
            item["filter"] = qd["filter"]
        qdata.append(item)
    widgets.append({
        "id": wid,
        "title": w["title"],
        "description": "",
        "panelTypes": w.get("panelTypes", "graph"),
        "yAxisUnit": w.get("yAxisUnit", "none"),
        "query": {
            "queryType": "builder",
            "builder": {"queryData": qdata, "queryFormulas": [], "queryTraceOperator": []},
            "promql": [{"name": "A", "query": "", "legend": "", "disabled": False}],
            "clickhouse_sql": [{"name": "A", "query": "", "legend": "", "disabled": False}],
            "id": str(uuid.uuid4()),
            "unit": "",
        },
        "fillSpans": False,
        "opacity": "1",
        "softMax": 0,
        "softMin": 0,
        "stackedBarChart": False,
        "thresholds": [],
        "timePreferance": "GLOBAL_TIME",
        "nullZeroValues": "zero",
    })
    layout.append({
        "i": wid,
        "x": (i % 2) * 6,
        "y": (i // 2) * 6,
        "w": 6,
        "h": 6,
        "moved": False,
        "static": False,
    })

payload = {
    "title": spec["title"],
    "description": spec.get("description", ""),
    "tags": spec.get("tags", []),
    "widgets": widgets,
    "layout": layout,
    "variables": {},
    "version": "v5",
}
json.dump({"data": payload}, sys.stdout)
PY

# Delete existing dashboard with same title if present, then create
EXISTING=$(curl -fsS "${AUTH[@]}" "$SIGNOZ_URL/api/v1/dashboards" \
  | python3 -c 'import sys,json; d=json.load(sys.stdin); ids=[x.get("id") or x.get("uuid") for x in (d.get("data") or []) if (x.get("data") or x).get("title")=="Agent Quality" or x.get("title")=="Agent Quality"]; print(ids[0] if ids else "")' 2>/dev/null || true)

# SigNoz list shape varies — try a more defensive parse
EXISTING=$(curl -fsS "${AUTH[@]}" "$SIGNOZ_URL/api/v1/dashboards" | python3 - <<'PY'
import sys, json
d = json.load(sys.stdin)
items = d.get("data") or []
for x in items:
    title = x.get("title") or (x.get("data") or {}).get("title")
    if title == "Agent Quality":
        print(x.get("id") or x.get("uuid") or "")
        break
PY
)

BODY=$(python3 -c 'import json; print(json.dumps(json.load(open("/tmp/agent-quality-dashboard.json"))["data"]))')

if [[ -n "${EXISTING}" ]]; then
  curl -fsS -X PUT "$SIGNOZ_URL/api/v1/dashboards/$EXISTING" "${AUTH[@]}" -d "$BODY" >/tmp/aq-out.json
  echo "Updated Agent Quality dashboard id=$EXISTING"
else
  curl -fsS -X POST "$SIGNOZ_URL/api/v1/dashboards" "${AUTH[@]}" -d "$BODY" >/tmp/aq-out.json
  echo "Created Agent Quality dashboard:"
  python3 -c 'import json; d=json.load(open("/tmp/aq-out.json")); print(d.get("data", d))'
fi

# Export live copy into repo path if writable
python3 - <<'PY'
import json
raw = json.load(open("/tmp/aq-out.json"))
data = raw.get("data") or raw
out = {
  "title": "Agent Quality",
  "exportedAt": __import__("time").strftime("%Y-%m-%d"),
  "source": "live-signoz-foundry",
  "dashboard": data if isinstance(data, dict) and "widgets" in data else data,
}
json.dump(out, open("/tmp/agent-quality-export.json", "w"), indent=2)
print("Wrote /tmp/agent-quality-export.json")
PY
