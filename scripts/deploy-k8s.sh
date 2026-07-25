#!/usr/bin/env bash
# Deploy demo + copilot to k8s ns foundry.
# Usage: FOUNDRY_HOST=x.x.x.x ./scripts/deploy-k8s.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FOUNDRY_HOST="${FOUNDRY_HOST:?set FOUNDRY_HOST to SigNoz/OTLP host IP or DNS}"
NS="${NS:-foundry}"

kubectl get ns "$NS" >/dev/null 2>&1 || kubectl create namespace "$NS"

# Substitute OTLP host into manifests
TMP="$(mktemp -d)"
sed "s|OTLP_HOST_PLACEHOLDER|${FOUNDRY_HOST}|g" "$ROOT/demo/demo-app.yaml" > "$TMP/demo-app.yaml"
if [[ -f "$ROOT/copilot/k8s.yaml" ]]; then
  sed "s|OTLP_HOST_PLACEHOLDER|${FOUNDRY_HOST}|g" "$ROOT/copilot/k8s.yaml" > "$TMP/copilot.yaml" || true
fi

kubectl apply -f "$TMP/demo-app.yaml"

# Sync copilot source into a ConfigMap for the python slim deploy
kubectl -n "$NS" create configmap incident-sentinel-src \
  --from-file=requirements.txt="$ROOT/copilot/requirements.txt" \
  --from-file="$ROOT/copilot/app" \
  --dry-run=client -o yaml | kubectl apply -f -

# Patch deployment to mount ConfigMap files properly — use a simple hostPath-less approach:
# rewrite deploy to install from ConfigMap tree
cat > "$TMP/copilot-deploy.yaml" <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: incident-sentinel-secrets
  namespace: ${NS}
type: Opaque
stringData:
  SIGNOZ_API_KEY: "${SIGNOZ_API_KEY:-}"
  LLM_API_KEY: "${LLM_API_KEY:-}"
  SLACK_WEBHOOK_URL: "${SLACK_WEBHOOK_URL:-}"
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: incident-sentinel
  namespace: ${NS}
spec:
  replicas: 1
  selector:
    matchLabels:
      app: incident-sentinel
  template:
    metadata:
      labels:
        app: incident-sentinel
    spec:
      initContainers:
        - name: materialize
          image: busybox:1.36
          command: ["sh", "-c", "cp -a /cm/. /src/ && mkdir -p /src/app && cp -a /cmap/. /src/app/ && ls -laR /src"]
          volumeMounts:
            - name: cm-root
              mountPath: /cm
            - name: cm-app
              mountPath: /cmap
            - name: src
              mountPath: /src
      containers:
        - name: copilot
          image: python:3.11-slim
          command: ["bash", "-lc"]
          args:
            - pip install -q -r /src/requirements.txt && cd /src && uvicorn app.main:app --host 0.0.0.0 --port 8080
          env:
            - name: SIGNOZ_URL
              value: "http://${FOUNDRY_HOST}:8080"
            - name: MCP_URL
              value: "http://${FOUNDRY_HOST}:8000/mcp"
            - name: OTEL_EXPORTER_OTLP_ENDPOINT
              value: "http://${FOUNDRY_HOST}:4318"
            - name: OTEL_SERVICE_NAME
              value: incident-sentinel
            - name: LLM_PROVIDER
              value: "${LLM_PROVIDER:-mock}"
            - name: LLM_MODEL
              value: "${LLM_MODEL:-mock-sre}"
            - name: LLM_BASE_URL
              value: "${LLM_BASE_URL:-}"
            - name: LLM_TIMEOUT_SECONDS
              value: "${LLM_TIMEOUT_SECONDS:-150}"
            - name: SENTINEL_MAX_STEPS
              value: "${SENTINEL_MAX_STEPS:-6}"
            - name: PRICE_INPUT_PER_MTOK
              value: "${PRICE_INPUT_PER_MTOK:-0.88}"
            - name: PRICE_OUTPUT_PER_MTOK
              value: "${PRICE_OUTPUT_PER_MTOK:-0.88}"
            - name: SIGNOZ_API_KEY
              valueFrom:
                secretKeyRef: { name: incident-sentinel-secrets, key: SIGNOZ_API_KEY, optional: true }
            - name: LLM_API_KEY
              valueFrom:
                secretKeyRef: { name: incident-sentinel-secrets, key: LLM_API_KEY, optional: true }
            - name: SLACK_WEBHOOK_URL
              valueFrom:
                secretKeyRef: { name: incident-sentinel-secrets, key: SLACK_WEBHOOK_URL, optional: true }
            - name: PYTHONUNBUFFERED
              value: "1"
          ports:
            - containerPort: 8080
          volumeMounts:
            - name: src
              mountPath: /src
          readinessProbe:
            httpGet: { path: /healthz, port: 8080 }
            initialDelaySeconds: 30
            periodSeconds: 10
          resources:
            requests: { cpu: "100m", memory: "256Mi" }
            limits: { cpu: "1", memory: "1Gi" }
      volumes:
        - name: src
          emptyDir: {}
        - name: cm-root
          configMap:
            name: incident-sentinel-src
            items:
              - key: requirements.txt
                path: requirements.txt
        - name: cm-app
          configMap:
            name: incident-sentinel-src
            items:
              - key: __init__.py
                path: __init__.py
              - key: config.py
                path: config.py
              - key: telemetry.py
                path: telemetry.py
              - key: mcp_client.py
                path: mcp_client.py
              - key: llm.py
                path: llm.py
              - key: report.py
                path: report.py
              - key: postmortem.py
                path: postmortem.py
              - key: investigator.py
                path: investigator.py
              - key: main.py
                path: main.py
---
apiVersion: v1
kind: Service
metadata:
  name: incident-sentinel
  namespace: ${NS}
spec:
  type: NodePort
  selector:
    app: incident-sentinel
  ports:
    - port: 8080
      targetPort: 8080
      nodePort: 32080
EOF

kubectl apply -f "$TMP/copilot-deploy.yaml"
echo "Deployed to namespace ${NS}. Copilot NodePort: 32080"
echo "Demo break: FOUNDRY_HOST=${FOUNDRY_HOST} NS=${NS} ${ROOT}/demo/break.sh errors"
