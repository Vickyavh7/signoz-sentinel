#!/usr/bin/env bash
# Toggle fault injection on demo services in namespace foundry.
# Usage: ./break.sh <scenario>
#   scenarios: errors | latency | heal | inventory-errors
set -euo pipefail
NS="${NS:-foundry}"
scenario="${1:-errors}"

case "$scenario" in
  errors)
    kubectl -n "$NS" set env deployment/checkout-api ERROR_RATE=0.5 EXTRA_LATENCY_MS=800
    kubectl -n "$NS" set env deployment/payment-svc ERROR_RATE=0.4 EXTRA_LATENCY_MS=1200
    echo "Injected elevated error rate + latency on checkout/payment"
    ;;
  latency)
    kubectl -n "$NS" set env deployment/payment-svc ERROR_RATE=0.0 EXTRA_LATENCY_MS=2500
    kubectl -n "$NS" set env deployment/checkout-api ERROR_RATE=0.0 EXTRA_LATENCY_MS=500
    echo "Injected latency-only fault"
    ;;
  inventory-errors)
    kubectl -n "$NS" set env deployment/inventory-svc ERROR_RATE=0.6 EXTRA_LATENCY_MS=300
    echo "Injected inventory failures"
    ;;
  heal)
    kubectl -n "$NS" set env deployment/checkout-api ERROR_RATE=0.05 EXTRA_LATENCY_MS=0
    kubectl -n "$NS" set env deployment/payment-svc ERROR_RATE=0.0 EXTRA_LATENCY_MS=0
    kubectl -n "$NS" set env deployment/inventory-svc ERROR_RATE=0.0 EXTRA_LATENCY_MS=0
    echo "Healed demo services to near-healthy defaults"
    ;;
  *)
    echo "Unknown scenario: $scenario" >&2
    echo "Use: errors | latency | inventory-errors | heal" >&2
    exit 1
    ;;
esac
