"""Investigation agent loop."""
from __future__ import annotations

import logging
import re
import time
from typing import Any

from opentelemetry import trace

from .config import settings
from .llm import chat, parse_llm_json
from .mcp_client import MCPClient
from .postmortem import build_postmortem, post_postmortem_to_slack, save_postmortem
from .report import post_report
from .telemetry import estimate_cost_usd, get_meter, get_tracer

log = logging.getLogger(__name__)

TOOL_MAP = {
    "signoz_list_alerts": lambda mcp, args: mcp.list_alerts(),
    "signoz_get_alert_history": lambda mcp, args: mcp.get_alert_history(**args),
    "signoz_list_services": lambda mcp, args: mcp.list_services(**args),
    "signoz_search_traces": lambda mcp, args: mcp.search_traces(**args),
    "signoz_get_trace_details": lambda mcp, args: mcp.get_trace_details(args.get("traceId") or args.get("trace_id", "")),
    "signoz_search_logs": lambda mcp, args: mcp.search_logs(**args),
    "signoz_query_metrics": lambda mcp, args: mcp.query_metrics(**args),
}


class Investigator:
    def __init__(self):
        self.mcp = MCPClient()
        self._recent: dict[str, float] = {}
        self._inflight = 0
        meter = get_meter()
        self.tokens_counter = meter.create_counter("sentinel_tokens_total")
        self.cost_counter = meter.create_counter("sentinel_cost_usd_total")
        self.duration_hist = meter.create_histogram("sentinel_investigation_duration_seconds")
        self.tool_errors = meter.create_counter("sentinel_tool_errors_total")

    def should_skip(self, rule_id: str) -> bool:
        now = time.time()
        last = self._recent.get(rule_id, 0)
        if now - last < settings.dedupe_seconds:
            return True
        if self._inflight >= settings.max_concurrent:
            return True
        return False

    def investigate(self, alert_payload: dict[str, Any]) -> dict[str, Any]:
        rule_id = str(
            alert_payload.get("ruleId")
            or alert_payload.get("ruleID")
            or alert_payload.get("labels", {}).get("alertname")
            or alert_payload.get("alert_name")
            or "unknown"
        )
        alert_name = (
            alert_payload.get("alert_name")
            or alert_payload.get("alertName")
            or alert_payload.get("labels", {}).get("alertname")
            or rule_id
        )
        if self.should_skip(rule_id):
            log.info("Skipping duplicate/busy investigation for %s", rule_id)
            return {"skipped": True, "rule_id": rule_id}

        self._inflight += 1
        self._recent[rule_id] = time.time()
        tracer = get_tracer()
        t0 = time.time()
        total_in = total_out = 0
        evidence_bundle: list[dict] = []

        with tracer.start_as_current_span("sentinel.investigate") as root:
            root.set_attribute("sentinel.rule_id", rule_id)
            root.set_attribute("sentinel.alert_name", str(alert_name))
            ctx = root.get_span_context()
            trace_id = format(ctx.trace_id, "032x") if ctx.is_valid else None

            messages = [
                {
                    "role": "user",
                    "content": (
                        f"Investigate this SigNoz alert payload:\n{alert_payload}\n"
                        f"Alert name: {alert_name}. Rule id: {rule_id}.\n"
                        f"Alerted service (from labels): {_alerted_service(alert_payload) or 'unknown'}.\n"
                        "Demo dependency chain (upstream→downstream): "
                        "checkout-api → payment-svc → inventory-svc.\n"
                        "Search the alerted service first. Blame the deepest origin of the fault."
                    ),
                }
            ]
            report: dict[str, Any] | None = None

            llm_failures = 0
            try:
                for step in range(settings.max_steps):
                    with tracer.start_as_current_span("sentinel.step") as step_span:
                        step_span.set_attribute("sentinel.step", step)
                        try:
                            content, tin, tout = chat(messages)
                        except Exception as e:
                            llm_failures += 1
                            log.warning("LLM call failed (%d): %s", llm_failures, e)
                            if llm_failures >= 2:
                                break  # degrade to evidence-based fallback report
                            continue
                        total_in += tin
                        total_out += tout
                        self.tokens_counter.add(tin, {"model": settings.llm_model, "direction": "input"})
                        self.tokens_counter.add(tout, {"model": settings.llm_model, "direction": "output"})
                        try:
                            decision = parse_llm_json(content)
                        except Exception as e:
                            log.warning("Bad LLM JSON: %s — %s", e, content[:300])
                            messages.append({"role": "assistant", "content": content})
                            messages.append(
                                {
                                    "role": "user",
                                    "content": "Respond with valid JSON only as specified.",
                                }
                            )
                            continue

                        hyp = decision.get("hypothesis")
                        if hyp:
                            step_span.set_attribute("sentinel.hypothesis", str(hyp)[:256])

                        if decision.get("action") == "conclude":
                            report = decision
                            report["alert_name"] = alert_name
                            report["rule_id"] = rule_id
                            report.setdefault("severity", "warning")
                            break

                        if decision.get("action") == "tool":
                            tool = decision.get("tool")
                            args = decision.get("arguments") or {}
                            messages.append({"role": "assistant", "content": content})
                            try:
                                fn = TOOL_MAP.get(tool)
                                if not fn:
                                    raise RuntimeError(f"unknown tool {tool}")
                                result = fn(self.mcp, args)
                                evidence_bundle.append({"tool": tool, "args": args, "result": _trim(result)})
                                messages.append(
                                    {
                                        "role": "user",
                                        "content": f"Tool result for {tool}:\n{_trim(result)}",
                                    }
                                )
                            except Exception as e:
                                self.tool_errors.add(1, {"tool": str(tool)})
                                log.exception("Tool %s failed", tool)
                                messages.append(
                                    {
                                        "role": "user",
                                        "content": f"Tool {tool} failed: {e}. Continue or conclude.",
                                    }
                                )
                            continue

                        messages.append({"role": "assistant", "content": content})
                        messages.append(
                            {
                                "role": "user",
                                "content": 'Unknown action. Use action "tool" or "conclude".',
                            }
                        )

                if report is None:
                    report = _fallback_report(alert_payload, alert_name, rule_id, evidence_bundle)
                evidence_bundle = _ensure_alerted_service_evidence(
                    self.mcp, alert_payload, evidence_bundle
                )
                report = _refine_culprit(report, alert_payload, evidence_bundle)
                report = _enrich_latency_language(report, alert_name, alert_payload)
                report = _enrich_error_language(report, alert_name, alert_payload)
                if report.get("cascade_refined") and report.get("degraded"):
                    # Evidence-based culprit is trustworthy enough for a usable report.
                    svc = report.get("service") or "unknown"
                    report["summary"] = (
                        report.get("summary")
                        or f"{alert_name}: elevated failures with origin {svc} (cascade-refined)"
                    )
                    if "Not determined automatically" in str(report.get("root_cause", "")):
                        report["root_cause"] = (
                            f"{svc} shows error/failure signals in MCP evidence; "
                            f"alert focused on {_alerted_service(alert_payload) or svc}."
                        )
                    report["confidence"] = max(float(report.get("confidence") or 0), 0.55)

                cost = estimate_cost_usd(total_in, total_out)
                self.cost_counter.add(cost, {"model": settings.llm_model})
                root.set_attribute("sentinel.cost.usd", cost)
                root.set_attribute("gen_ai.usage.input_tokens", total_in)
                root.set_attribute("gen_ai.usage.output_tokens", total_out)

                posted = post_report(report, investigation_trace_id=trace_id)
                duration = time.time() - t0
                self.duration_hist.record(duration)
                result = {
                    "skipped": False,
                    "report": report,
                    "posted": posted,
                    "trace_id": trace_id,
                    "tokens_in": total_in,
                    "tokens_out": total_out,
                    "cost_usd": cost,
                    "duration_s": duration,
                }
                try:
                    md = build_postmortem(report, result)
                    save_postmortem(rule_id, md, report)
                    post_postmortem_to_slack(md)
                    result["postmortem"] = f"/postmortems/{rule_id}"
                except Exception:
                    log.exception("Postmortem generation failed")
                return result
            finally:
                self._inflight = max(0, self._inflight - 1)


def _trim(obj: Any, limit: int = 4000) -> str:
    s = str(obj)
    return s if len(s) <= limit else s[:limit] + "...(truncated)"


# Upstream → downstream. Errors cascade UP the chain.
_CHAIN = ("checkout-api", "payment-svc", "inventory-svc")
_CHAIN_ALIASES = {
    "checkout-api": ("checkout-api", "checkout"),
    "payment-svc": ("payment-svc", "payment", "payment-api"),
    "inventory-svc": ("inventory-svc", "inventory"),
}


def _alerted_service(alert_payload: dict[str, Any]) -> str | None:
    labels = alert_payload.get("labels") if isinstance(alert_payload.get("labels"), dict) else {}
    for key in ("service", "service.name", "service_name"):
        val = (labels or {}).get(key) or alert_payload.get(key)
        if val:
            return str(val)
    return None


def _normalize_service(name: str) -> str | None:
    low = name.lower().strip()
    if low in ("incident-sentinel", "unknown", ""):
        return None
    for canonical, aliases in _CHAIN_ALIASES.items():
        if any(a in low for a in aliases):
            return canonical
    return name


def _services_with_errors(evidence: list[dict]) -> set[str]:
    """Services that appear in evidence blobs near error markers."""
    found: set[str] = set()
    for e in evidence:
        blob = str(e.get("result", ""))
        low = blob.lower()
        # Mentions of known services in an error-ish blob
        if not any(m in low for m in _ERROR_MARKERS):
            # still count explicit has_error / status 5xx near service names
            if "has_error" not in low and "status_code\":5" not in low and "500" not in low:
                continue
        for canonical, aliases in _CHAIN_ALIASES.items():
            if any(a in low for a in aliases):
                found.add(canonical)
        for m in re.findall(r'"service(?:\.name|Name|_name)?"\s*:\s*"([^"]+)"', blob):
            canon = _normalize_service(m)
            if canon and (any(x in low for x in _ERROR_MARKERS) or "has_error" in low or "500" in low):
                found.add(canon if canon in _CHAIN_ALIASES else canon)
    return found


def _deepest_erroring(erroring: set[str]) -> str | None:
    deepest = None
    for svc in _CHAIN:
        if svc in erroring:
            deepest = svc
    return deepest


def _searched_service(evidence: list[dict], service: str) -> bool:
    aliases = _CHAIN_ALIASES.get(service, (service,))
    for e in evidence:
        args_s = str(e.get("args") or {}).lower()
        if any(a in args_s for a in aliases):
            return True
    return False


def _ensure_alerted_service_evidence(mcp: MCPClient, alert_payload: dict, evidence: list[dict]) -> list[dict]:
    """If the alert names a demo service we never queried, pull error traces for it."""
    raw = _alerted_service(alert_payload) or ""
    alerted = _normalize_service(raw)
    if not alerted or alerted not in _CHAIN:
        return evidence
    if _searched_service(evidence, alerted):
        return evidence
    try:
        result = mcp.search_traces(serviceName=alerted, hasError=True)
        evidence = list(evidence) + [
            {
                "tool": "signoz_search_traces",
                "args": {"serviceName": alerted, "hasError": True},
                "result": _trim(result),
            }
        ]
        log.info("Auto-fetched error traces for alerted service %s", alerted)
    except Exception:
        log.exception("Auto-fetch for alerted service %s failed", alerted)
    return evidence


def _enrich_error_language(
    report: dict[str, Any], alert_name: str, alert_payload: dict[str, Any]
) -> dict[str, Any]:
    """Keep error-alert narratives about the culprit service, not LLM infra noise."""
    blob = f"{alert_name} {alert_payload}".lower()
    if "error" not in blob and "fail" not in blob:
        return report
    rc = str(report.get("root_cause") or "")
    sm = str(report.get("summary") or "")
    combined = (rc + " " + sm).lower()
    # Strip known self/LLM distractions from the narrative
    if "nvidia" in combined or "incident-sentinel" in combined or "chat/completions" in combined:
        svc = report.get("service") or _alerted_service(alert_payload) or "service"
        report["root_cause"] = (
            f"{svc} is returning errors / failures (evidence from SigNoz MCP traces/logs). "
            f"Ignore investigator-infra noise."
        )
        report["summary"] = f"{alert_name}: errors on {svc}"
        return report
    if not any(k in combined for k in ("error", "fail", "exception", "5xx", "500", "runtime")):
        svc = report.get("service") or _alerted_service(alert_payload) or "service"
        report["root_cause"] = f"Error spike / failures on {svc}. {rc}".strip()
        if "error" not in sm.lower() and "fail" not in sm.lower():
            report["summary"] = f"{alert_name}: errors on {svc}"
    return report


def _enrich_latency_language(
    report: dict[str, Any], alert_name: str, alert_payload: dict[str, Any]
) -> dict[str, Any]:
    """If this is a latency alert, ensure the narrative mentions latency explicitly."""
    blob = f"{alert_name} {alert_payload}".lower()
    if not any(k in blob for k in ("latency", "p99", "duration", "slow")):
        return report
    rc = str(report.get("root_cause") or "")
    sm = str(report.get("summary") or "")
    if not any(k in (rc + sm).lower() for k in ("latency", "slow", "duration", "delay", "p99", "ms")):
        svc = report.get("service") or _alerted_service(alert_payload) or "service"
        report["root_cause"] = f"Elevated latency on {svc}. {rc}".strip()
        if "latency" not in sm.lower():
            report["summary"] = f"{alert_name}: elevated latency on {svc}"
    return report


def _refine_culprit(report: dict[str, Any], alert_payload: dict, evidence: list[dict]) -> dict[str, Any]:
    """Prefer deepest erroring service; never blame upstream of the alerted service.

    Errors cascade UP the demo chain. If the alert names inventory-svc, a
    payment-svc 500 is almost always a symptom — not the origin.
    """
    erroring = _services_with_errors(evidence)
    deepest = _deepest_erroring(erroring)
    alerted = _normalize_service(_alerted_service(alert_payload) or "")
    current = _normalize_service(str(report.get("service") or ""))

    chosen = current
    if alerted and alerted in _CHAIN:
        # Only consider alerted service or something DEEPER in the chain.
        candidates = [
            s for s in erroring if s in _CHAIN and _CHAIN.index(s) >= _CHAIN.index(alerted)
        ]
        if candidates:
            chosen = max(candidates, key=lambda s: _CHAIN.index(s))
        else:
            # No deeper/at-alert evidence parsed — still trust the alert focus over
            # any upstream mid-chain blame the LLM may have produced.
            if current in _CHAIN and _CHAIN.index(current) < _CHAIN.index(alerted):
                chosen = alerted
            elif deepest and deepest in _CHAIN and _CHAIN.index(deepest) >= _CHAIN.index(alerted):
                chosen = deepest
            else:
                chosen = alerted
    elif deepest:
        chosen = deepest

    if chosen and chosen != current:
        log.info(
            "Cascade refine: service %s → %s (alerted=%s erroring=%s)",
            current,
            chosen,
            alerted,
            sorted(erroring),
        )
        report["service"] = chosen
        report["cascade_refined"] = True
        rc = str(report.get("root_cause") or "")
        leaf = chosen.split("-")[0]
        if chosen not in rc.lower() and leaf not in rc.lower():
            report["root_cause"] = (
                f"Origin appears to be {chosen} (cascade-refined; "
                f"alert focused on {alerted or 'unknown'}). {rc}"
            ).strip()
    elif chosen:
        report["service"] = chosen
    if str(report.get("service", "")).lower() == "incident-sentinel":
        report["service"] = alerted or deepest or "unknown"
        report["cascade_refined"] = True
    return report


_SERVICE_KEYS = ("service", "service.name", "service_name", "serviceName", "k8s.deployment.name")
_ERROR_MARKERS = ("error", "exception", "failed", "timeout", "refused", "5xx", "unavailable")


def _extract_services(alert_payload: dict[str, Any], evidence: list[dict]) -> list[str]:
    found: list[str] = []
    labels = alert_payload.get("labels") if isinstance(alert_payload.get("labels"), dict) else {}
    for key in _SERVICE_KEYS:
        val = (labels or {}).get(key) or alert_payload.get(key)
        if val and str(val) not in found:
            found.append(str(val))
    for e in evidence:
        blob = str(e.get("result", ""))
        for m in re.findall(r'"service(?:\.name|Name|_name)?"\s*:\s*"([^"]+)"', blob):
            if m not in found:
                found.append(m)
    return found[:5]


def _extract_error_lines(evidence: list[dict], limit: int = 3) -> list[str]:
    lines: list[str] = []
    for e in evidence:
        for raw in str(e.get("result", "")).splitlines():
            low = raw.lower()
            if any(marker in low for marker in _ERROR_MARKERS):
                snippet = raw.strip()[:200]
                if snippet and snippet not in lines:
                    lines.append(snippet)
                    if len(lines) >= limit:
                        return lines
    return lines


def _fallback_report(
    alert_payload: dict[str, Any],
    alert_name: str,
    rule_id: str,
    evidence: list[dict],
) -> dict[str, Any]:
    """Degraded-mode report when the LLM never returns a valid conclusion.

    Built strictly from the alert payload and the raw MCP tool evidence so
    the output reflects what was actually observed, and is explicit that
    automated root-cause analysis did not complete.
    """
    services = _extract_services(alert_payload, evidence)
    error_lines = _extract_error_lines(evidence)
    tools_used = sorted({e["tool"] for e in evidence})

    if tools_used:
        summary = (
            f"{alert_name}: gathered {len(evidence)} evidence item(s) via "
            f"{', '.join(tools_used)}; automated root-cause analysis did not complete."
        )
    else:
        summary = f"{alert_name}: alert received but no telemetry evidence was collected."

    if error_lines:
        root_cause = "Not determined automatically. Error signals seen in evidence: " + " | ".join(error_lines)
    else:
        root_cause = "Not determined automatically — review the linked evidence manually."

    suggested = []
    if services:
        suggested.append(f"Review traces and logs for: {', '.join(services)} in SigNoz")
    if "signoz_search_logs" not in tools_used:
        suggested.append("Search logs around the alert window for the affected service")
    suggested.append("Check recent deploys/config changes correlated with the alert start time")

    return {
        "action": "conclude",
        "summary": summary,
        "root_cause": root_cause,
        "confidence": 0.3 if evidence else 0.1,
        "severity": alert_payload.get("severity")
        or (alert_payload.get("labels") or {}).get("severity")
        or "warning",
        "alert_name": alert_name,
        "rule_id": rule_id,
        "service": services[0] if services else "unknown",
        "degraded": True,
        "evidence": [
            {
                "label": f"tool:{e['tool']}",
                "webUrl": settings.signoz_url,
                "detail": str(e["result"])[:400],
            }
            for e in evidence[:5]
        ]
        or [
            {
                "label": "SigNoz",
                "webUrl": f"{settings.signoz_url}/traces",
                "detail": "No tool evidence collected; open traces filtered by has_error",
            }
        ],
        "suggested_actions": suggested,
    }
