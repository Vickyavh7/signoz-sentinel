# Rules Compliance — what we can and cannot do before Jul 20

Source: https://www.wemakedevs.org/hackathons/signoz/rules (fetched 2026-07-13)

## The rule that matters most

> Rule 8: "Teams can plan and discuss strategy in advance, but coding and design work
> should begin only after the hackathon starts. Written notes, sketches, and diagrams
> are permitted beforehand."

## What we do about it

**Allowed now (before Jul 20) — and what this repo contains until then:**

- Written plans, architecture diagrams, decision logs, prompt sketches (this `docs/` tree)
- Registering, joining the SigNoz Slack, reading docs (Foundry, MCP, OTel GenAI semconv)
- Environment setup: self-hosting SigNoz itself is explicitly encouraged *before* the
  event (the Early Win challenge is literally "self-host SigNoz and explore it before
  July 19"). Installing Foundry + SigNoz + the MCP server on our host is setup, not
  project code.
- The Early Win blog (separate pre-event prize, due Jul 19)

**Not before Jul 20:**

- Copilot application code (`copilot/`), demo-service code (`demo/`), dashboards,
  alert definitions built *for the project*

**Never:**

- Backdating or date-shifting commits to disguise early work. Git history, blog
  timestamps, and judges' diligence make this both dishonest and easy to detect —
  disqualification risk for a prize we can win honestly. We commit and push
  progressively during the hackathon week with real timestamps; an active,
  organic commit history during the event is itself good presentation evidence.

## Other rules with direct action items

| Rule | Action |
|------|--------|
| Field req 1: Install SigNoz using Foundry | Foundry deployment on the standalone host; NOT our existing Helm install |
| Field req 3: repo must include `casting.yaml` + `casting.yaml.lock` | Committed under `foundry/`; judges may re-run it |
| Rule 7: AI assistant use must be declared | Declare in the submission form + blog. Failure = disqualification |
| Rule 6: blog on Medium/Dev.to/Substack | Dev.to, same account as the Early Win blog |
| Field req 2: use MCP server, Query Builder, dashboards, alerts | All four are core to the design |
| Rule 1/9: team of 1-4, changeable before start | Decide team composition before Jul 20 |
