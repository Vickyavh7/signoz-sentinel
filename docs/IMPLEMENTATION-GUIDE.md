# Implementation guide — deploy & configure Incident Sentinel

End-to-end guide matching how this project was brought up: **SigNoz via Foundry (with MCP)** → **Kubernetes demo + copilot** → **alerts/webhook** → **dashboards** → **smoke test**.

No lab-specific IPs or secrets. Replace placeholders with your values.

Related docs:

- Short checklist: [`GETTING-STARTED.md`](GETTING-STARTED.md)
- Architecture: [`ARCHITECTURE.md`](ARCHITECTURE.md)
- Alerts detail: [`../alerts/README.md`](../alerts/README.md)
- Demo video script: [`DEMO-VIDEO.md`](DEMO-VIDEO.md)

---

## 0. What you will run

| Piece | Role |
|---|---|
| **Foundry host** (Docker) | SigNoz UI `:8080`, OTLP `:4317`/`:4318`, MCP `:8000` |
| **Kubernetes** (ns `foundry`) | Demo chain `checkout-api` → `payment-svc` → `inventory-svc` + Incident Sentinel |
| **Copilot NodePort** | `32080` → FastAPI webhook `/webhook/signoz` + `/investigate` |
| **LLM** | OpenAI-compatible API (NVIDIA NIM / OpenAI / etc.) |
| **Optional Slack** | Incoming webhook for incident reports |

```text
Demo apps ──OTLP──► SigNoz (+ MCP)
                        │ alert webhook
                        ▼
              Incident Sentinel ──OTLP──► same SigNoz
                        │
                        └── Slack / postmortems
```

---

## 1. Prerequisites

- Docker with enough free disk/RAM for SigNoz Compose (~4GB+ free recommended)
- `kubectl` access to a cluster
- LLM API key (OpenAI-compatible)
- Optional: Slack Incoming Webhook URL
- Foundry / `foundryctl` per current [SigNoz Foundry docs](https://signoz.io)

### Host tip (older Linux)

If `foundryctl` fails with a **glibc too old** error, run Foundry tooling inside a newer Debian/Ubuntu container that mounts the host Docker socket (same pattern as many Compose installs). The casting files in this repo stay the same.

---

## 2. Install SigNoz with Foundry + MCP

This repo ships the hackathon-required casting files:

- [`foundry/casting.yaml`](../foundry/casting.yaml) — Compose flavor, **MCP enabled**
- [`foundry/casting.yaml.lock`](../foundry/casting.yaml.lock) — pinned images for reproduce

Minimal casting shape:

```yaml
apiVersion: v1alpha1
kind: Installation
metadata:
  name: signoz
spec:
  deployment:
    flavor: compose
    mode: docker
  mcp:
    spec:
      enabled: true
```

### Cast

From a machine that can reach Docker on the Foundry host:

```bash
cd foundry
# Exact foundryctl invocation follows current SigNoz Foundry docs, e.g.:
#   foundryctl cast -f casting.yaml
# Prefer the lockfile when the CLI supports it so judges get the same pins.
```

### Ports to expose / verify

| Port | Service |
|---|---|
| `8080` | SigNoz UI + API |
| `4317` | OTLP gRPC |
| `4318` | OTLP HTTP (demo + copilot use this) |
| `8000` | SigNoz MCP (`/mcp`) |

Smoke:

```bash
curl -sS -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8080/
# Expect 200 (or redirect to login)
```

### ClickHouse Keeper tip

If Keeper / ClickHouse becomes unstable after cast, pin an older **telemetrykeeper** image (or re-cast from the committed lock). Image drift was a real failure mode during development.

---

## 3. Create admin + Service Account API key

1. Open `http://<foundry-host>:8080` and complete first-time signup.
2. Note your **org ID** (Settings / org switcher / network calls after login).
3. Create a **Service Account** with **Admin** or **Editor**.
4. Generate a long-lived **API key** on that service account.

### Auth rules (important)

| Credential | Header | Use for |
|---|---|---|
| Service Account API key | `SIGNOZ-API-KEY: <key>` | MCP tools + copilot (`SIGNOZ_API_KEY` env) |
| User login JWT | `Authorization: Bearer <jwt>` | Browser / setup scripts that call `/api/v2/sessions/...` |

Do **not** send a user JWT as `SIGNOZ-API-KEY`. Wrong auth looks like “MCP is broken” (401/403).

---

## 4. Configure environment

```bash
cp .env.example .env
```

Key variables (also used by `scripts/deploy-k8s.sh`):

| Variable | Example / meaning |
|---|---|
| `FOUNDRY_HOST` | IP/DNS of Foundry host reachable from k8s pods |
| `SIGNOZ_API_KEY` | Service Account key |
| `LLM_API_KEY` | Provider key |
| `LLM_PROVIDER` | `openai` for OpenAI-compatible APIs |
| `LLM_MODEL` | e.g. `meta/llama-3.1-70b-instruct` |
| `LLM_BASE_URL` | e.g. `https://integrate.api.nvidia.com/v1` |
| `SLACK_WEBHOOK_URL` | Optional Slack incoming webhook |
| `LLM_TIMEOUT_SECONDS` | Default `150` — large models need headroom |
| `COST_BUDGET_USD` | Used for cost meta-alert threshold (default `5.0`) |

Deployed copilot points at:

- `SIGNOZ_URL=http://$FOUNDRY_HOST:8080`
- `MCP_URL=http://$FOUNDRY_HOST:8000/mcp`
- `OTEL_EXPORTER_OTLP_ENDPOINT=http://$FOUNDRY_HOST:4318`

Ensure **k8s nodes can reach** those ports on the Foundry host (security groups / firewall).

---

## 5. Deploy demo apps + Incident Sentinel

```bash
export FOUNDRY_HOST=<signoz-reachable-host>
export LLM_PROVIDER=openai
export LLM_MODEL=meta/llama-3.1-70b-instruct
export LLM_BASE_URL=https://integrate.api.nvidia.com/v1
export SIGNOZ_API_KEY='...'
export LLM_API_KEY='...'
export SLACK_WEBHOOK_URL='...'   # optional but recommended

./scripts/deploy-k8s.sh
```

What the script does:

1. Creates namespace `foundry` (override with `NS=...`).
2. Applies `demo/demo-app.yaml` with OTLP host substituted.
3. Packs `copilot/app` into a ConfigMap and runs `python:3.11-slim` + uvicorn.
4. Creates/updates Secret `incident-sentinel-secrets` (**all three keys together** — updating one key alone can wipe the others depending on apply method).
5. Exposes Service **NodePort `32080`**.

Verify:

```bash
kubectl -n foundry get pods,svc
curl -sS http://<node-ip>:32080/healthz
```

In SigNoz → **Services**, you should eventually see `checkout-api`, `payment-svc`, `inventory-svc`, and later `incident-sentinel`.

---

## 6. Wire alerts → copilot webhook

SigNoz must reach the copilot. From the Foundry Docker network, use a **node IP** (or internal IP) that exposes NodePort `32080`:

```text
WEBHOOK_URL=http://<node-ip>:32080/webhook/signoz
```

### Automated channel + checkout rule

Run on the Foundry host (or any host that can hit SigNoz API with admin password):

```bash
export SIGNOZ_URL=http://127.0.0.1:8080
export SIGNOZ_EMAIL=admin@example.com
export SIGNOZ_PASSWORD='...'
export SIGNOZ_ORG_ID='<your-org-id>'
export WEBHOOK_URL=http://<node-ip>:32080/webhook/signoz

./scripts/setup-alert-webhook.sh
```

Creates:

- Notification channel `incident-sentinel-webhook`
- Trace alert `checkout-error-spike` (checkout errors → webhook)

### Additional alerts (UI or JSON)

See [`alerts/README.md`](../alerts/README.md) and JSON under `alerts/`:

| Alert | Purpose |
|---|---|
| `checkout-error-spike` | Demo error path |
| `payment-latency-p99` / payment latency | Latency-only path |
| `sentinel-cost-budget` | Meta-alert on `sentinel_cost_usd_total` (watcher watched) |

Point preferred channel at `incident-sentinel-webhook` (or Slack for human-facing cost pages).

Webhook behavior: the FastAPI handler **acks quickly** and runs the investigation in the background (large LLMs are too slow for sync webhook delivery).

---

## 7. Dashboards

Import via SigNoz UI (**Dashboards → Import**) from:

| File | Purpose |
|---|---|
| `dashboards/incident-overview.json` | Demo / incident overview |
| `dashboards/copilot-operations.json` | Investigation / LLM / MCP tool volume |
| `dashboards/agent-quality.json` | Cost + eval pass ratio |

Or refresh Agent Quality via API:

```bash
export SIGNOZ_URL=http://127.0.0.1:8080
export SIGNOZ_EMAIL=admin@example.com
export SIGNOZ_PASSWORD='...'
export SIGNOZ_ORG_ID='<your-org-id>'
./scripts/setup-agent-quality-dashboard.sh
```

---

## 8. End-to-end smoke test

### Fault injection

```bash
NS=foundry ./demo/break.sh errors          # or: latency | inventory-errors
# Heal when done:
NS=foundry ./demo/break.sh heal
```

Wait 1–5 minutes for the alert eval window, or trigger manually:

```bash
curl -sS -X POST http://<node-ip>:32080/investigate \
  -H 'Content-Type: application/json' \
  -d '{
    "ruleId": "demo-1",
    "alert_name": "checkout-error-spike",
    "labels": {"service": "checkout-api"},
    "status": "firing"
  }'
```

### What “success” looks like

1. Slack report (if webhook configured) with root cause + evidence links  
2. Postmortem: `GET http://<node-ip>:32080/postmortems/<ruleId>`  
3. SigNoz → service `incident-sentinel` → trace `sentinel.investigate` with `gen_ai.chat` / tool spans  
4. Copilot Operations / Agent Quality panels update  

### Accuracy evals (optional)

```bash
python3 evals/run_evals.py \
  --base http://<node-ip>:32080 \
  --otlp http://<foundry-host>:4318
# Results: evals/RESULTS.md
```

---

## 9. Configuration checklist

- [ ] Foundry cast with `foundry/casting.yaml` (+ lock) and MCP enabled  
- [ ] UI / OTLP / MCP ports reachable from k8s  
- [ ] Service Account API key (not user JWT) in `SIGNOZ_API_KEY`  
- [ ] Secret has `SIGNOZ_API_KEY`, `LLM_API_KEY`, `SLACK_WEBHOOK_URL` set together  
- [ ] Demo + copilot pods Running; `/healthz` OK  
- [ ] Webhook channel URL reachable from SigNoz → NodePort `32080`  
- [ ] At least `checkout-error-spike` firing path verified  
- [ ] Dashboards imported  
- [ ] Optional: cost budget alert + evals run  

---

## 10. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| MCP 401/403 | JWT used as API key | Use Service Account key + `SIGNOZ-API-KEY` |
| Webhook timeout / missing reports | Sync investigation too slow | Confirm async webhook path; raise `LLM_TIMEOUT_SECONDS` |
| No demo services in SigNoz | OTLP host wrong / blocked | Check `FOUNDRY_HOST` and `:4318` from pods |
| Secret “lost” keys | Partial secret apply | Re-apply all three keys via `deploy-k8s.sh` |
| Foundry won’t start on old OS | glibc | Run foundryctl in Debian container + host Docker socket |
| Keeper / CH flaky | Image pin | Re-cast from `casting.yaml.lock` / pin keeper |

---

## 11. AI assistance disclosure

Development used AI coding assistants (e.g. Cursor). Humans directed design, reviewed code/docs, and validated demo and eval claims. Declare AI use on the hackathon submission form (or in the project description if there is no dedicated checkbox).
