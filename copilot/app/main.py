"""FastAPI entrypoint — SigNoz alert webhook + health."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.responses import PlainTextResponse

from .investigator import Investigator
from .postmortem import get_postmortem, list_postmortems
from .telemetry import setup_telemetry

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("incident-sentinel")

setup_telemetry()
app = FastAPI(title="Incident Sentinel", version="0.1.0")
investigator = Investigator()


@app.get("/healthz")
def healthz():
    return {"ok": True, "service": "incident-sentinel"}


@app.post("/webhook/signoz")
async def signoz_webhook(request: Request, background: BackgroundTasks):
    payload: Any
    try:
        payload = await request.json()
    except Exception:
        payload = {"raw": (await request.body()).decode("utf-8", errors="replace")}
    log.info("Received SigNoz webhook: %s", str(payload)[:500])
    # Normalize Alertmanager-style arrays
    alerts = []
    if isinstance(payload, dict) and "alerts" in payload:
        alerts = payload.get("alerts") or []
    else:
        alerts = [payload]

    def run_one(alert: dict):
        return investigator.investigate(alert if isinstance(alert, dict) else {"payload": alert})

    # Ack immediately and investigate in the background: large LLMs can take
    # minutes, and SigNoz/Alertmanager webhook delivery times out quickly.
    if alerts:
        for a in alerts:
            background.add_task(run_one, a if isinstance(a, dict) else {"payload": a})
    else:
        background.add_task(run_one, {"alert_name": "empty-webhook", "payload": payload})

    return {"accepted": True, "queued": max(len(alerts), 1)}


@app.post("/investigate")
def investigate_manual(body: dict[str, Any]):
    """Manual trigger for demos without waiting for an alert."""
    return investigator.investigate(body)


@app.get("/postmortems")
def postmortems_index():
    return {"postmortems": list_postmortems()}


@app.get("/postmortems/{rule_id}", response_class=PlainTextResponse)
def postmortem_detail(rule_id: str):
    pm = get_postmortem(rule_id)
    if not pm:
        return PlainTextResponse("not found", status_code=404)
    return pm["markdown"]
