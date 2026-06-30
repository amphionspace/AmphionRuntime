from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram, start_http_server

ACTIVE_SESSIONS = Gauge("asr_active_sessions", "Current active ASR WebSocket sessions")
PARTIAL_TOTAL = Counter("asr_partial_total", "Total partial ASR events", ["model_id"])
FINAL_TOTAL = Counter("asr_final_total", "Total final ASR events", ["model_id"])
ERROR_TOTAL = Counter("asr_error_total", "Total ASR errors", ["model_id", "code"])
DECODE_LATENCY_MS = Histogram(
    "asr_decode_latency_ms",
    "Batch decode latency in milliseconds",
    buckets=(1, 2, 5, 10, 20, 50, 100, 200, 500, 1000),
)
BATCH_SIZE = Histogram(
    "asr_decode_batch_size",
    "Observed decode batch size",
    buckets=(1, 2, 4, 8, 16, 32, 50, 64, 128),
)
QUEUE_DEPTH = Gauge("asr_decode_queue_depth", "Current decode queue depth")


def start_metrics_server(listen: str | None) -> None:
    if not listen:
        return
    host, port_text = listen.rsplit(":", 1)
    start_http_server(int(port_text), addr=host)
