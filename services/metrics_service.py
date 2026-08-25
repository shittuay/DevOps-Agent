"""Prometheus metrics instrumentation for DevOps Agent.

Records per-request HTTP metrics (count + latency) via before/after-request
hooks and exposes a renderer for `routes/metrics.py`'s `/metrics` endpoint.

**Multi-process aware.** `devops-agent.service` runs gunicorn with
`--workers 3 --threads 8` (3 separate OS processes) — a bare `prometheus_client`
registry is process-local, so scraping through gunicorn would return whichever
worker happened to handle that request, with counters appearing to jump/reset
across scrapes. `render_metrics()` uses prometheus_client's multiprocess mode
(`MultiProcessCollector`, keyed off `PROMETHEUS_MULTIPROC_DIR`) to aggregate
across all 3 workers when that env var is set (production); it falls back to
the default process-local registry otherwise (local dev, tests — single
process, multiprocess mode would just add overhead for no benefit).

Enabling multiprocess mode in production additionally requires:
  - `PROMETHEUS_MULTIPROC_DIR` set to a writable, gunicorn-startup-cleared
    directory (see `devops-agent.service`'s `ExecStartPre`).
  - A `child_exit` hook in `gunicorn.conf.py` calling
    `multiprocess.mark_process_dead(worker.pid)`, or dead workers' metric
    files leak and get double-counted after a restart.
"""
import os
import time
import logging

from flask import request, g
from prometheus_client import Counter, Histogram, CollectorRegistry, generate_latest, multiprocess

logger = logging.getLogger(__name__)

# Buckets span from sub-second API calls up to the agent's longest legitimate
# turn (CHAT_MAX_TURN_SECONDS = 840s, see app.py) — default prometheus_client
# buckets top out at 10s, which would collapse every chat request into the
# +Inf bucket and lose all resolution on the endpoint that matters most.
_DURATION_BUCKETS = (0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300, 600, 900)

HTTP_REQUESTS_TOTAL = Counter(
    'http_requests_total',
    'Total HTTP requests received',
    ['method', 'endpoint', 'status'],
)

HTTP_REQUEST_DURATION_SECONDS = Histogram(
    'http_request_duration_seconds',
    'HTTP request duration in seconds',
    ['method', 'endpoint'],
    buckets=_DURATION_BUCKETS,
)


def init_app(app):
    """Wire before/after-request hooks that record HTTP request metrics."""

    @app.before_request
    def _metrics_start_timer():
        g._metrics_start = time.monotonic()

    @app.after_request
    def _metrics_record(response):
        start = getattr(g, '_metrics_start', None)
        if start is not None:
            # request.endpoint is None for unmatched routes (404s, bot scans
            # of random paths) — bucket those under one label instead of the
            # raw path, or a scan flood turns into unbounded label cardinality.
            endpoint = request.endpoint or 'unmatched'
            HTTP_REQUEST_DURATION_SECONDS.labels(request.method, endpoint).observe(
                time.monotonic() - start
            )
            HTTP_REQUESTS_TOTAL.labels(request.method, endpoint, response.status_code).inc()
        return response

    logger.info("Metrics instrumentation wired (multiprocess=%s)", bool(_multiproc_dir()))


def _multiproc_dir():
    return os.environ.get('PROMETHEUS_MULTIPROC_DIR')


def render_metrics() -> bytes:
    """Render current metrics in Prometheus text exposition format."""
    if _multiproc_dir():
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)
    else:
        from prometheus_client import REGISTRY as registry
    return generate_latest(registry)
