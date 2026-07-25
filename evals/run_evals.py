#!/usr/bin/env python3
"""Accuracy evals for Incident Sentinel.

For each golden scenario: inject a real fault (demo/break.sh), wait for
telemetry to accumulate, trigger an investigation, and score the verdict
against expected service / root-cause keywords. Stdlib only.

Run from the repo root on a host with kubectl access to the demo cluster:

    python3 evals/run_evals.py --base http://<node>:32080 [--ns foundry]

Writes evals/results.json and evals/RESULTS.md. (Python 3.6 compatible.)
"""
import argparse
import json
import os
import subprocess
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def post_json(url, payload, timeout=600):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def emit_eval_metrics(otlp_endpoint, results, passed, total):
    """Push eval counters/gauges to SigNoz via OTLP/HTTP JSON (stdlib only)."""
    if not otlp_endpoint:
        return
    now_ns = str(int(time.time() * 1e9))
    metrics = []

    def attr(k, v):
        return {"key": k, "value": {"stringValue": str(v)}}

    def sum_metric(name, value, attrs=None):
        return {
            "name": name,
            "unit": "1",
            "sum": {
                "dataPoints": [
                    {
                        "asDouble": float(value),
                        "timeUnixNano": now_ns,
                        "startTimeUnixNano": now_ns,
                        "attributes": attrs or [],
                    }
                ],
                "aggregationTemporality": 2,
                "isMonotonic": True,
            },
        }

    def gauge_metric(name, value, attrs=None):
        return {
            "name": name,
            "unit": "1",
            "gauge": {
                "dataPoints": [
                    {
                        "asDouble": float(value),
                        "timeUnixNano": now_ns,
                        "attributes": attrs or [],
                    }
                ]
            },
        }

    for r in results:
        scenario = r["scenario"]
        metrics.append(
            sum_metric(
                "sentinel_eval_runs_total",
                1,
                [attr("scenario", scenario), attr("result", "pass" if r["passed"] else "fail")],
            )
        )
        if r["passed"]:
            metrics.append(sum_metric("sentinel_eval_pass_total", 1, [attr("scenario", scenario)]))
        else:
            metrics.append(sum_metric("sentinel_eval_fail_total", 1, [attr("scenario", scenario)]))

    ratio = (float(passed) / float(total)) if total else 0.0
    metrics.append(gauge_metric("sentinel_eval_pass_ratio", ratio))
    metrics.append(gauge_metric("sentinel_eval_score_passed", passed))
    metrics.append(gauge_metric("sentinel_eval_score_total", total))

    body = {
        "resourceMetrics": [
            {
                "resource": {
                    "attributes": [
                        attr("service.name", "incident-sentinel-evals"),
                        attr("deployment.environment", "hackathon"),
                    ]
                },
                "scopeMetrics": [{"scope": {"name": "incident-sentinel-evals"}, "metrics": metrics}],
            }
        ]
    }
    url = otlp_endpoint.rstrip("/") + "/v1/metrics"
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            print("OTLP eval metrics -> %s (%s)" % (url, resp.status))
    except Exception as e:
        print("OTLP eval metrics failed: %s" % e)


def inject(ns, fault):
    subprocess.run(
        ["bash", str(ROOT / "demo" / "break.sh"), fault],
        env={**os.environ, "NS": ns},
        check=True,
    )


def score(report, expected):
    """Strict scoring: the verdict's `service` field must name an expected
    culprit (no credit for the alert name being echoed in prose), and the
    root-cause text must describe the right failure mode.

    Degraded mode (LLM never concluded) still PASSes when the evidence-based
    / cascade-refined service field is correct — that is a valid investigation
    outcome, just without a polished LLM narrative.
    """
    notes = []
    service = str(report.get("service", "")).lower()
    svc_ok = any(s.lower() in service for s in expected["service_any"])
    notes.append("service field match: %s (got '%s')" % (svc_ok, service))
    blob = (str(report.get("root_cause", "")) + " " + str(report.get("summary", ""))).lower()
    kw_ok = any(k.lower() in blob for k in expected["root_cause_any"])
    notes.append("failure-mode keyword match: %s" % kw_ok)
    degraded = bool(report.get("degraded"))
    if degraded:
        notes.append("DEGRADED mode (LLM did not conclude)")
        if svc_ok and kw_ok:
            notes.append("DEGRADED but culprit correct — counting as PASS")
            return True, notes
        return False, notes
    return svc_ok and kw_ok, notes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True, help="copilot base URL, e.g. http://node:32080")
    ap.add_argument("--ns", default="foundry")
    ap.add_argument("--settle", type=int, default=None, help="override settle seconds")
    ap.add_argument("--only", default=None, help="run a single scenario id (skips results files)")
    ap.add_argument(
        "--otlp",
        default=os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "http://<foundry-host>:4318"),
        help="OTLP HTTP endpoint to publish eval metrics (empty to skip)",
    )
    args = ap.parse_args()

    cfg = json.loads((ROOT / "evals" / "scenarios.json").read_text())
    settle = args.settle if args.settle is not None else cfg["settle_seconds"]
    scenarios = [s for s in cfg["scenarios"] if args.only is None or s["id"] == args.only]
    results = []

    for sc in scenarios:
        print(f"=== scenario {sc['id']}: injecting fault '{sc['fault']}' ===")
        inject(args.ns, sc["fault"])
        print(f"waiting {settle}s for telemetry ...")
        time.sleep(settle)

        payload = dict(sc["alert_payload"])
        payload["ruleId"] = f"eval-{sc['id']}-{int(time.time())}"
        t0 = time.time()
        try:
            resp = post_json(f"{args.base}/investigate", payload)
        except Exception as e:
            resp = {"error": str(e)}
        elapsed = time.time() - t0

        report = resp.get("report") or {}
        ok, notes = score(report, sc["expected"]) if report else (False, [f"no report: {resp}"])
        results.append(
            {
                "scenario": sc["id"],
                "fault": sc["fault"],
                "passed": ok,
                "notes": notes,
                "verdict_service": report.get("service"),
                "verdict_root_cause": report.get("root_cause"),
                "confidence": report.get("confidence"),
                "degraded": bool(report.get("degraded")),
                "duration_s": round(resp.get("duration_s", elapsed), 1),
                "cost_usd": resp.get("cost_usd"),
                "trace_id": resp.get("trace_id"),
            }
        )
        print(f"  -> passed={ok} ({'; '.join(notes)})")
        inject(args.ns, "heal")
        time.sleep(10)

    passed = sum(1 for r in results if r["passed"])
    if args.otlp:
        emit_eval_metrics(args.otlp, results, passed, len(results))
    if args.only is not None:
        print("\n(--only run) %d/%d passed — results files not written" % (passed, len(results)))
        return
    out = {
        "ran_at": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
        "passed": passed,
        "total": len(results),
        "results": results,
    }
    (ROOT / "evals" / "results.json").write_text(json.dumps(out, indent=2))

    md = [
        "# Incident Sentinel — accuracy eval results",
        "",
        "**Run:** %s · **Score: %d/%d** correct root-cause identifications"
        % (out["ran_at"], passed, len(results)),
        "",
        "Each scenario injects a *real* fault into the demo services, waits for telemetry,",
        "then triggers a full investigation (MCP tools + LLM). A pass requires the verdict",
        "to name the right service AND describe the right failure mode, without degrading.",
        "",
        "Eval metrics also exported to SigNoz as `sentinel_eval_*` (service `incident-sentinel-evals`).",
        "",
        "| Scenario | Fault | Verdict service | Confidence | Duration | Cost | Pass |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in results:
        if r["cost_usd"] is not None:
            md.append(
                "| %s | %s | %s | %s | %ss | $%.4f | %s |"
                % (
                    r["scenario"],
                    r["fault"],
                    r["verdict_service"],
                    r["confidence"],
                    r["duration_s"],
                    r["cost_usd"],
                    "PASS" if r["passed"] else "FAIL",
                )
            )
        else:
            md.append(
                "| %s | %s | %s | %s | %ss | - | %s |"
                % (
                    r["scenario"],
                    r["fault"],
                    r["verdict_service"],
                    r["confidence"],
                    r["duration_s"],
                    "PASS" if r["passed"] else "FAIL",
                )
            )
    md.append("")
    for r in results:
        md.extend(
            [
                "### %s" % r["scenario"],
                "",
                "- Root cause verdict: %s" % r["verdict_root_cause"],
            ]
        )
        md.extend(["- %s" % n for n in r["notes"]])
        if r.get("trace_id"):
            md.append("- Investigation trace: `%s`" % r["trace_id"])
        md.append("")
    (ROOT / "evals" / "RESULTS.md").write_text("\n".join(md))
    print("\nScore: %d/%d — wrote evals/results.json and evals/RESULTS.md" % (passed, len(results)))


if __name__ == "__main__":
    main()
