# Submission checklist (Agents of SigNoz)

## Included in this repo

- [x] Foundry `casting.yaml` + `casting.yaml.lock`
- [x] Incident Sentinel copilot (MCP + LLM + OTel + postmortems)
- [x] Demo apps + fault script
- [x] Alert specs (errors, latency, cost budget)
- [x] Dashboards (Incident Overview, Copilot Operations, Agent Quality)
- [x] Accuracy evals + `evals/RESULTS.md`
- [x] Blog draft (`blog/hackathon-blog-draft.md`)
- [x] Demo video script (`docs/DEMO-VIDEO.md`)

## You still need to submit

- [ ] Public GitHub URL: https://github.com/Vickyavh7/signoz-sentinel
- [ ] Demo video URL (2–3 min)
- [ ] Blog URL (Dev.to / Medium / Substack)
- [ ] WeMakeDevs form — **Track 01**
- [ ] **Declare AI assistant use**
- [ ] Team member list (1–4)

## Demo video script

1. Show SigNoz healthy + services  
2. `./demo/break.sh errors`  
3. Alert firing → Slack Incident Sentinel report  
4. Postmortem (`/postmortems/...`)  
5. Investigation trace + Copilot Operations + Agent Quality  
6. Flash `evals/RESULTS.md`  
7. Cost meta-alert (self-spend)
