"""Gunicorn config — required for multiprocess Prometheus metrics.

`devops-agent.service` runs 3 worker processes. `services/metrics_service.py`
aggregates their counters via `prometheus_client`'s multiprocess mode
(`PROMETHEUS_MULTIPROC_DIR`), which needs a worker's metric files marked dead
on exit — otherwise a crashed or recycled worker's counters stay on disk and
get double-counted alongside its replacement's. See PROMETHEUS_MULTIPROC_DIR
docs: https://prometheus.github.io/client_python/multiprocess/
"""
from prometheus_client import multiprocess


def child_exit(server, worker):
    multiprocess.mark_process_dead(worker.pid)
