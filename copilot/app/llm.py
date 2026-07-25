"""LLM helpers — OpenAI-compatible + mock provider for demos without keys."""
from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from .config import settings
from .telemetry import estimate_cost_usd, get_tracer

log = logging.getLogger(__name__)


SYSTEM_PROMPT = """You are Incident Sentinel, a senior SRE investigating a fired SigNoz alert.
Each turn respond with ONLY a single JSON object (no markdown, no prose):
{"action":"tool","tool":"<name>","arguments":{...},"hypothesis":"<current guess>"}
or when done:
{"action":"conclude",
 "summary":"one-line incident statement",
 "root_cause":"the most specific cause the evidence supports, and WHY NOW (what changed)",
 "confidence":0.0-1.0,
 "service":"<culprit service exact name — deepest origin, not a mid-chain symptom>",
 "impact":"who/what is affected (endpoints, dependency chain, user-facing symptom)",
 "timeline":["<time or step>: <observed event>", "..."],
 "evidence":[{"label":"...","webUrl":"...","detail":"..."}],
 "suggested_actions":["investigation follow-ups only — no auto-remediation"]}

Available tools (ONLY these — never invent other tool names):
- signoz_list_alerts
- signoz_get_alert_history (ruleId optional)
- signoz_list_services
- signoz_search_traces (arguments may include serviceName, hasError)
- signoz_get_trace_details (traceId)
- signoz_search_logs
- signoz_query_metrics

Do NOT call signoz_authenticate or any auth tool; credentials are already configured.

Dependency chain for this demo (upstream → downstream):
  checkout-api → payment-svc → inventory-svc
Errors cascade UP. A 500 on payment-svc is often caused by inventory-svc failing underneath.
Always blame the DEEPEST service that shows the anomaly.

Investigation method:
0) START from the service named in the alert labels — pass that serviceName to searches first.
   Never blame "incident-sentinel" (that is this copilot's own telemetry).
1) Classify: error-driven vs latency-driven vs cost/meta.
   - Errors: signoz_search_traces hasError=true for the alerted service.
   - Latency: search traces WITHOUT hasError; compare durations to normal (~tens of ms).
2) If the alerted service has errors, ALWAYS call signoz_get_trace_details on one failing
   traceId. Walk child spans: the culprit is the deepest span that itself errors (or is slow)
   while its children succeed — or the leaf service with no children.
3) Corroborate with logs (second signal) before concluding.
4) "Why now": when the anomaly started + plausible change (deploy/config/dependency/traffic).
5) After at most 4 tool calls you MUST conclude.
6) confidence >= 0.5 only when two signals agree. Keep evidence webUrls from tools.
"""


def chat(messages: list[dict[str, str]]) -> tuple[str, int, int]:
    """Returns (content, input_tokens, output_tokens)."""
    tracer = get_tracer()
    provider = settings.llm_provider.lower()
    with tracer.start_as_current_span("gen_ai.chat") as span:
        span.set_attribute("gen_ai.system", provider)
        span.set_attribute("gen_ai.request.model", settings.llm_model)
        span.set_attribute("gen_ai.operation.name", "chat")
        if provider == "mock" or not settings.llm_api_key:
            content = _mock_response(messages)
            span.set_attribute("gen_ai.usage.input_tokens", 200)
            span.set_attribute("gen_ai.usage.output_tokens", 150)
            span.set_attribute("sentinel.cost.usd", estimate_cost_usd(200, 150))
            return content, 200, 150

        if provider == "anthropic":
            content, tin, tout = _anthropic(messages)
        else:
            content, tin, tout = _openai_compatible(messages)

        span.set_attribute("gen_ai.usage.input_tokens", tin)
        span.set_attribute("gen_ai.usage.output_tokens", tout)
        span.set_attribute("sentinel.cost.usd", estimate_cost_usd(tin, tout))
        return content, tin, tout


def _openai_compatible(messages: list[dict[str, str]]) -> tuple[str, int, int]:
    base = settings.llm_base_url or "https://api.openai.com/v1"
    if settings.llm_provider.lower() == "groq" and not settings.llm_base_url:
        base = "https://api.groq.com/openai/v1"
    url = f"{base.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.llm_api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": settings.llm_model,
        "messages": [{"role": "system", "content": SYSTEM_PROMPT}] + messages,
        "temperature": 0.2,
        "max_tokens": 1024,
    }
    # Large hosted models (e.g. NVIDIA 70B) can take 30-90s per completion;
    # retry once on timeout before giving up.
    last_exc: Exception | None = None
    for attempt in range(2):
        try:
            with httpx.Client(timeout=settings.llm_timeout_seconds) as client:
                r = client.post(url, headers=headers, json=body)
                r.raise_for_status()
                data = r.json()
            break
        except (httpx.TimeoutException, httpx.TransportError) as e:
            last_exc = e
            log.warning("LLM call attempt %d failed: %s", attempt + 1, e)
    else:
        raise last_exc  # type: ignore[misc]
    content = data["choices"][0]["message"]["content"]
    usage = data.get("usage") or {}
    return content, int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0))


def _anthropic(messages: list[dict[str, str]]) -> tuple[str, int, int]:
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": settings.llm_api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    body = {
        "model": settings.llm_model or "claude-3-5-haiku-latest",
        "max_tokens": 2048,
        "system": SYSTEM_PROMPT,
        "messages": messages,
    }
    with httpx.Client(timeout=90.0) as client:
        r = client.post(url, headers=headers, json=body)
        r.raise_for_status()
        data = r.json()
    content = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
    usage = data.get("usage") or {}
    return content, int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0))


def _mock_response(messages: list[dict[str, str]]) -> str:
    """Deterministic tool-calling mock so demos work without an API key."""
    joined = " ".join(m.get("content", "") for m in messages).lower()
    tool_rounds = joined.count("tool result")
    if tool_rounds == 0:
        return json.dumps(
            {
                "action": "tool",
                "tool": "signoz_search_traces",
                "arguments": {"hasError": True},
                "hypothesis": "Likely error spans on the alerted checkout path",
            }
        )
    if tool_rounds == 1:
        return json.dumps(
            {
                "action": "tool",
                "tool": "signoz_search_logs",
                "arguments": {"bodyContains": "failed"},
                "hypothesis": "Looking for payment/checkout failure logs correlated to traces",
            }
        )
    return json.dumps(
        {
            "action": "conclude",
            "summary": "Checkout failures driven by payment-gateway errors",
            "root_cause": "Elevated ERROR_RATE on payment-svc / checkout-api causing 502s on /checkout",
            "confidence": 0.72,
            "service": "checkout-api",
            "evidence": [
                {
                    "label": "Error traces for checkout-api",
                    "webUrl": f"{settings.signoz_url}/traces",
                    "detail": "has_error spans clustered on checkout/payment",
                }
            ],
            "suggested_actions": [
                "Inspect payment-svc error rate and recent deploys",
                "Correlate failing trace_id with payment failed logs in SigNoz",
                "Run demo/break.sh heal after mitigation",
            ],
        }
    )


def parse_llm_json(content: str) -> dict[str, Any]:
    content = content.strip()
    if content.startswith("```"):
        content = content.strip("`")
        if content.startswith("json"):
            content = content[4:]
    return json.loads(content)
