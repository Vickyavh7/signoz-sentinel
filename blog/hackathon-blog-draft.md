---
title: "Incident Sentinel: An SRE Copilot That Investigates SigNoz Alerts — and Observes Itself"
published: false
tags: signoz, mcp, opentelemetry, observability
description: We built an incident copilot on SigNoz MCP that posts Slack reports and postmortems, measures its own accuracy, and pages when it overspends — for the Agents of SigNoz hackathon.
cover_image: https://raw.githubusercontent.com/Vickyavh7/signoz-sentinel/main/blog/images/02-agent-quality.png
---

# Incident Sentinel: An SRE Copilot That Investigates SigNoz Alerts — and Observes Itself

When an alert fires at 2am, the expensive part isn’t the paging. It’s the scavenger hunt.

Which service broke?  
Which trace proves it?  
Which log line explains it?  
What changed *now*?

For the **[Agents of SigNoz](https://www.wemakedevs.org/hackathons/signoz)** hackathon (**Track 01 — AI & Agent Observability**), we built **Incident Sentinel**: an SRE incident copilot that investigates SigNoz alerts through the **SigNoz MCP server**, posts an evidence-backed report (and postmortem) to Slack, and — the part we care about most — **observes itself** in the same SigNoz instance.

The agent that debugs your system should not be a black box.

**Repo:** [github.com/Vickyavh7/signoz-sentinel](https://github.com/Vickyavh7/signoz-sentinel)

---

## The problem (one layer up)

AI agents are entering on-call workflows. They call tools, reason over telemetry, and write summaries. But when the agent is wrong, slow, or expensive, teams often have:

- no investigation span  
- no token count  
- no cost signal  
- no way to say “how often is this right?”

That’s the same “flying blind” story we tell about LLM apps — applied to the **incident agent itself**.

---

## What we built

```text
checkout → payment → inventory     (demo apps + fault injection)
        │ OTLP
        ▼
   SigNoz + MCP  (Foundry)
        │ alert webhook
        ▼
   Incident Sentinel
        ├── MCP tools (traces, logs, metrics, alerts)
        ├── LLM investigation loop
        ├── Slack report + markdown postmortem
        └── OTLP → same SigNoz (tokens, cost, agent quality)
```

Concrete pieces:

1. **SigNoz via Foundry** — `casting.yaml` + `casting.yaml.lock` in the repo (hackathon requirement), MCP enabled.  
2. **Fault-injectable demo chain** on Kubernetes: `checkout-api` → `payment-svc` → `inventory-svc`.  
3. **Incident Sentinel** — FastAPI webhook + tool-calling agent over SigNoz MCP.  
4. **Slack reports** with evidence links back into SigNoz.  
5. **Auto-postmortems** — timeline, impact, evidence, cost; also served at `GET /postmortems/{ruleId}`.  
6. **Self-telemetry** — investigation spans, GenAI chat spans, tool spans, `sentinel_tokens_total`, `sentinel_cost_usd_total`.  
7. **Measured accuracy** — real fault evals in `evals/`, not vibes.

We kept the core agent custom (not only a framework wrapper) so we own GenAI attributes and cost metrics end-to-end. kagent packaging remains a stretch path in the repo.

Here’s the live service map during a fault window — demo apps plus the copilot as a first-class service:

![SigNoz services: incident-sentinel alongside checkout, payment, and inventory](https://raw.githubusercontent.com/Vickyavh7/signoz-sentinel/main/blog/images/01-services.png)

*Figure 1. SigNoz Services — the outage services and `incident-sentinel` in one pane.*

---

## How an investigation works

1. A SigNoz alert fires (errors, latency, or our cost meta-alert).  
2. The webhook hits Incident Sentinel (acks fast; work continues in the background).  
3. The LLM chooses MCP tools — search traces, pull trace details, search logs, query metrics.  
4. It correlates across signals and follows the dependency chain.  
5. It concludes with summary, root cause, impact, timeline, and suggested follow-ups.  
6. Slack gets the report; a markdown postmortem is generated.  
7. The whole run is traced back into SigNoz as service `incident-sentinel`.

We intentionally **do not auto-remediate**. The copilot diagnoses; humans keep the execute button. That boundary is a feature for trust, not a missing checkbox.

Our alert rules are the entry point — including the meta-alert on the copilot’s own spend:

![Alert rules: checkout-error-spike, payment-latency-p99, and sentinel-cost-budget firing](https://raw.githubusercontent.com/Vickyavh7/signoz-sentinel/main/blog/images/04-alerts.png)

*Figure 2. Alert Rules — demo outages plus `sentinel-cost-budget` (`kind: meta-alert`).*

And every investigation leaves a real OpenTelemetry trace the on-call can open:

![Flame graph of sentinel.investigate with gen_ai.chat and tool spans](https://raw.githubusercontent.com/Vickyavh7/signoz-sentinel/main/blog/images/06-trace-detail.png)

*Figure 3. A `sentinel.investigate` trace (~50s) — LLM steps and MCP tool calls, not a black box.*

A real postmortem excerpt (auto-generated during a checkout error spike):

```markdown
# Postmortem: checkout-error-spike
- Primary service: checkout-api · Confidence: 0.8
- Investigation duration: 192.3s · Cost: $0.0112

## Summary
checkout-api error spike due to downstream service failure

## Root cause
Origin appears to be checkout-api (cascade-refined).
inventory-svc failure, possibly due to a recent deployment…

## Evidence
- checkout-api trace with error — GET /checkout → 502
```

---

## Favorite design decision: the watcher is watched

We put a **cost-budget meta-alert** on `sentinel_cost_usd_total`.

If the copilot spends too much investigating, *it* pages you.

This isn’t a slideware idea. During testing, a few investigations with a larger hosted model blew through a tiny demo budget. SigNoz fired `sentinel-cost-budget`, routed it to the copilot’s own webhook, and **the copilot investigated its own cost overrun and posted that report to Slack**.

Full circle: the incident agent became the incident.

Operations telemetry for the copilot itself:

![Copilot Operations dashboard with investigation spans, LLM calls, and MCP tool calls](https://raw.githubusercontent.com/Vickyavh7/signoz-sentinel/main/blog/images/03-copilot-operations.png)

*Figure 4. Copilot Operations — investigation volume, GenAI calls, and MCP tool usage.*

---

## Measuring the agent (instead of trusting it)

The most common gap in AI-for-SRE demos: nobody asks **how often the agent is right**.

Our eval harness (`evals/run_evals.py`) injects **real faults**:

| Scenario | Fault | What “pass” means |
|---|---|---|
| checkout-errors | error spike on checkout/payment | names the right service + failure mode |
| payment-latency | latency-only on payment | names payment + latency language |
| inventory-errors | inventory failures (cascade) | names inventory, not a mid-chain symptom |

Scoring is strict: echoing the alert name in prose doesn’t count. The verdict’s `service` field must be correct.

**Latest run: 3/3** (see [`evals/RESULTS.md`](https://github.com/Vickyavh7/signoz-sentinel/blob/main/evals/RESULTS.md)).

The first honest failures taught us more than the passes:

- The agent once blamed **`incident-sentinel` itself** for a latency incident — because its own spans live in the same SigNoz it queries. Self-observability can pollute self-investigation unless you forbid it.  
- Cascade faults made it blame mid-chain services (e.g. payment) when the origin was inventory. We added cascade refinement: never blame *upstream* of the alerted service; prefer the deepest erroring hop in `checkout → payment → inventory`.

Eval metrics are also exported to SigNoz (`sentinel_eval_*`) and shown on an **Agent Quality** dashboard — accuracy as a first-class observability signal:

![Agent Quality dashboard: investigations, LLM calls, cost USD, eval pass ratio](https://raw.githubusercontent.com/Vickyavh7/signoz-sentinel/main/blog/images/02-agent-quality.png)

*Figure 5. Agent Quality — cost, investigation volume, and eval pass ratio in SigNoz.*

---

## What broke while building (the useful part)

Hackathon infrastructure is part of the story:

- **foundryctl on older Linux** needed a newer glibc — we ran it in a Debian container with the host Docker socket.  
- **ClickHouse Keeper** crashed on one image pin; pinning an older keeper image stabilized Foundry.  
- **Auth footguns:** Service Account API keys vs user JWTs are not interchangeable with MCP. Wrong header → 401/403 that looks like “MCP is broken.”  
- **Big models are slow:** webhook delivery must ack immediately; investigations run in the background with timeouts and retries.  
- **Graceful degradation:** if the LLM never returns a valid conclusion, the report is built from MCP evidence only and marked `degraded` — no canned fake root cause.

---

## Enterprise-shaped guardrails (still a hackathon build)

- Dedupe window per alert / rule  
- Concurrency cap and bounded investigation steps  
- Scoped SigNoz Service Account key in a Kubernetes Secret  
- Token + USD cost + duration on every run  
- Evidence-only fallback when the model fails  

Enough to be credible. Not a claim that this is production SaaS tomorrow.

---

## Demo in two minutes

1. `./demo/break.sh errors`  
2. Alert (or `POST /investigate`) → Slack report + postmortem  
3. SigNoz → service `incident-sentinel` → investigation trace  
4. Dashboards: **Copilot Operations** + **Agent Quality**  
5. Flash `evals/RESULTS.md` (3/3)  
6. Point at `sentinel-cost-budget` — the watcher is watched  

---

## Takeaways

1. **Observability for AI agents isn’t only “trace the LLM app.”** Sometimes the agent *is* the SRE workflow.  
2. **Instrument both sides** — the outage and the investigation — on one OpenTelemetry-native backend.  
3. **Measure accuracy** with real faults, or you’re demoing confidence, not competence.  
4. **Meta-alerts on agent cost** turn self-telemetry into something operators can actually page on.

---

## Links

- Hackathon: [Agents of SigNoz](https://www.wemakedevs.org/hackathons/signoz)  
- Repo: [github.com/Vickyavh7/signoz-sentinel](https://github.com/Vickyavh7/signoz-sentinel)  
- SigNoz MCP: [github.com/SigNoz/signoz-mcp-server](https://github.com/SigNoz/signoz-mcp-server)

---

*Built for Agents of SigNoz (WeMakeDevs × SigNoz). AI coding assistants were used during development and will be declared on the submission form.*
