"""OpenTelemetry setup — GenAI semconv + Sentinel metrics."""
from __future__ import annotations

import logging

from opentelemetry import metrics, trace
from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from .config import settings

_tracer = None
_meter = None


def setup_telemetry() -> None:
    global _tracer, _meter
    resource = Resource.create(
        {
            "service.name": settings.service_name,
            "deployment.environment": "hackathon",
            "service.version": "0.1.0",
        }
    )
    endpoint = settings.otel_endpoint.rstrip("/")

    tp = TracerProvider(resource=resource)
    tp.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces"))
    )
    trace.set_tracer_provider(tp)
    _tracer = trace.get_tracer("incident-sentinel")

    reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(endpoint=f"{endpoint}/v1/metrics"),
        export_interval_millis=15000,
    )
    mp = MeterProvider(resource=resource, metric_readers=[reader])
    metrics.set_meter_provider(mp)
    _meter = metrics.get_meter("incident-sentinel")

    lp = LoggerProvider(resource=resource)
    lp.add_log_record_processor(
        BatchLogRecordProcessor(OTLPLogExporter(endpoint=f"{endpoint}/v1/logs"))
    )
    set_logger_provider(lp)
    root = logging.getLogger()
    root.addHandler(LoggingHandler(level=logging.INFO, logger_provider=lp))
    if not root.handlers or len(root.handlers) == 1:
        logging.basicConfig(level=logging.INFO)


def get_tracer():
    return _tracer or trace.get_tracer("incident-sentinel")


def get_meter():
    return _meter or metrics.get_meter("incident-sentinel")


def estimate_cost_usd(input_tokens: int, output_tokens: int) -> float:
    return (
        input_tokens / 1_000_000.0 * settings.price_input_per_mtok
        + output_tokens / 1_000_000.0 * settings.price_output_per_mtok
    )
