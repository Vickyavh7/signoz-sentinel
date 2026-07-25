"""Thin HTTP client for SigNoz MCP server (JSON-RPC style over HTTP)."""
from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from .config import settings
from .telemetry import get_tracer

log = logging.getLogger(__name__)


class MCPClient:
    def __init__(
        self,
        url: str | None = None,
        api_key: str | None = None,
        timeout: float = 60.0,
    ):
        self.url = (url or settings.mcp_url).rstrip("/")
        self.api_key = api_key if api_key is not None else settings.signoz_api_key
        self.timeout = timeout
        self._id = 0

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if self.api_key:
            # Login JWTs work as Authorization Bearer. SIGNOZ-API-KEY is for
            # long-lived PATs; sending a JWT as SIGNOZ-API-KEY makes upstream
            # SigNoz return 401 even though Bearer would succeed.
            if self.api_key.startswith("eyJ"):
                h["Authorization"] = f"Bearer {self.api_key}"
            else:
                h["SIGNOZ-API-KEY"] = self.api_key
                h["Authorization"] = f"Bearer {self.api_key}"
        return h

    def _next_id(self) -> int:
        self._id += 1
        return self._id

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        tracer = get_tracer()
        with tracer.start_as_current_span("sentinel.tool") as span:
            span.set_attribute("sentinel.tool", name)
            span.set_attribute("gen_ai.tool.name", name)
            payload = {
                "jsonrpc": "2.0",
                "id": self._next_id(),
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments or {}},
            }
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    r = client.post(self.url, headers=self._headers(), json=payload)
                    r.raise_for_status()
                    data = self._parse_response(r)
                if isinstance(data, dict) and data.get("error"):
                    span.set_attribute("error", True)
                    span.set_attribute("sentinel.tool.error", str(data["error"]))
                    raise RuntimeError(f"MCP error: {data['error']}")
                result = data.get("result", data) if isinstance(data, dict) else data
                # Normalize content blocks
                if isinstance(result, dict) and "content" in result:
                    texts = []
                    for block in result["content"]:
                        if isinstance(block, dict) and block.get("type") == "text":
                            texts.append(block.get("text", ""))
                    if texts:
                        joined = "\n".join(texts)
                        try:
                            return json.loads(joined)
                        except json.JSONDecodeError:
                            return joined
                return result
            except Exception as e:
                span.record_exception(e)
                span.set_attribute("error", True)
                raise

    def _parse_response(self, r: httpx.Response) -> Any:
        ctype = r.headers.get("content-type", "")
        text = r.text
        if "text/event-stream" in ctype:
            # Collect last data: JSON line from SSE
            last = None
            for line in text.splitlines():
                if line.startswith("data:"):
                    chunk = line[5:].strip()
                    if chunk and chunk != "[DONE]":
                        try:
                            last = json.loads(chunk)
                        except json.JSONDecodeError:
                            last = chunk
            return last if last is not None else {"raw": text}
        try:
            return r.json()
        except json.JSONDecodeError:
            return {"raw": text}

    # Convenience wrappers used by the investigator
    def get_alert_history(self, rule_id: str | None = None, **kwargs) -> Any:
        args = {**kwargs}
        if rule_id:
            args["ruleId"] = rule_id
        return self.call_tool("signoz_get_alert_history", args)

    def list_services(self, start: str | None = None, end: str | None = None) -> Any:
        args = {}
        if start:
            args["start"] = start
        if end:
            args["end"] = end
        return self.call_tool("signoz_list_services", args)

    def search_traces(self, **kwargs) -> Any:
        return self.call_tool("signoz_search_traces", kwargs)

    def get_trace_details(self, trace_id: str) -> Any:
        return self.call_tool("signoz_get_trace_details", {"traceId": trace_id})

    def search_logs(self, **kwargs) -> Any:
        return self.call_tool("signoz_search_logs", kwargs)

    def query_metrics(self, **kwargs) -> Any:
        return self.call_tool("signoz_query_metrics", kwargs)

    def list_alerts(self) -> Any:
        return self.call_tool("signoz_list_alerts", {})
