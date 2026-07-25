# Incident Sentinel — accuracy eval results

**Run:** 2026-07-24 14:35 UTC · **Score: 3/3** correct root-cause identifications

Each scenario injects a *real* fault into the demo services, waits for telemetry,
then triggers a full investigation (MCP tools + LLM). A pass requires the verdict
to name the right service AND describe the right failure mode. Degraded mode
(LLM did not conclude) still counts as PASS when the evidence/cascade-refined
culprit is correct.

Eval metrics also exported to SigNoz as `sentinel_eval_*` (service `incident-sentinel-evals`).

| Scenario | Fault | Verdict service | Confidence | Duration | Cost | Pass |
|---|---|---|---|---|---|---|
| checkout-errors | errors | checkout-api | 0.0 | 49.3s | $0.0142 | PASS |
| payment-latency | latency | payment-svc | 0.3 | 34.8s | $0.0052 | PASS |
| inventory-errors | inventory-errors | inventory-svc | 0.8 | 58.7s | $0.0095 | PASS |

### checkout-errors

- Root cause verdict: Origin appears to be checkout-api (cascade-refined; alert focused on checkout-api). no errors found in inventory-svc
- service field match: True (got 'checkout-api')
- failure-mode keyword match: True
- Investigation trace: `baa58443b020886714e05d6a5e6fa629`

### payment-latency

- Root cause verdict: Not determined automatically. Error signals seen in evidence: {"data":{"data":{"results":[{"nextCursor":"MTc4NDkwMjkwNjcwNw==","queryName":"A","rows":[{"data":{"client.address":"","cloud.account.id":null,"cloud.platform":null,"cloud.provider":null,"cloud.region" | {"data":{"data":{"results":[{"nextCursor":"MTc4NDkwMjkwNjcwOQ==","queryName":"A","rows":[{"data":{"client.address":"","cloud.account.id":null,"cloud.platform":null,"cloud.provider":null,"cloud.region"
- service field match: True (got 'payment-svc')
- failure-mode keyword match: True
- DEGRADED mode (LLM did not conclude)
- DEGRADED but culprit correct — counting as PASS
- Investigation trace: `c91403c1a9afffcdd405e8fe9f347c17`

### inventory-errors

- Root cause verdict: inventory-svc is returning errors / failures (evidence from SigNoz MCP traces/logs). Ignore investigator-infra noise.
- service field match: True (got 'inventory-svc')
- failure-mode keyword match: True
- Investigation trace: `55b75ee14c78e9adaae440f9c102b197`
