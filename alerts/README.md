# Alert rule definitions for Incident Sentinel demo
# Import via SigNoz UI or API after admin signup.

## checkout-error-spike

- **Name:** checkout-error-spike
- **Type:** Trace-based threshold
- **Filter:** `service.name = 'checkout-api' AND has_error = true`
- **Condition:** count > 3 in 5 minutes
- **Severity:** warning
- **Preferred channel:** `incident-sentinel-webhook` (points at NodePort 32080 `/webhook/signoz`)

## payment-latency-spike

- **Name:** payment-latency-spike
- **Type:** Trace-based threshold / p99 latency
- **Filter:** `service.name = 'payment-svc'`
- **Condition:** p99 duration > 1500ms for 5 minutes
- **Severity:** warning
- **Preferred channel:** `incident-sentinel-webhook`

## sentinel-cost-budget (meta-alert — watcher watched)

- **Name:** sentinel-cost-budget
- **Type:** Metric threshold
- **Metric:** `sentinel_cost_usd_total` (or Query Builder sum over interval)
- **Condition:** increase > `$COST_BUDGET_USD` (default 5.0) in 1 hour
- **Severity:** info
- **Preferred channel:** same Slack channel used by reports

## Notification channel

Live snapshot: [`alerts-live.json`](alerts-live.json) (exported from Foundry).

Create/recreate with:

```bash
# on Foundry host
WEBHOOK_URL=http://<node-ip>:32080/webhook/signoz \
SIGNOZ_PASSWORD='...' SIGNOZ_ORG_ID='<your-org-id>' \
../scripts/setup-alert-webhook.sh
```

Channel body shape SigNoz accepts:

```json
{
  "name": "incident-sentinel-webhook",
  "type": "webhook",
  "webhook_configs": [
    { "url": "http://<node-ip>:32080/webhook/signoz", "send_resolved": true }
  ]
}
```

Replace node IP with any k8s node that exposes NodePort `32080` and is reachable from the SigNoz Docker network.
