"""Gunicorn config — required for multiprocess Prometheus metrics.

`devops-agent.service` runs 3 worker processes. `services/metrics_service.py`
aggregates their counters via `prometheus_client`'s multiprocess mode
(`PROMETHEUS_MULTIPROC_DIR`), which needs a worker's metric files marked dead
on exit — otherwise a crashed or recycled worker's counters stay on disk and
get double-counted alongside its replacement's. See PROMETHEUS_MULTIPROC_DIR
docs: https://prometheus.github.io/client_python/multiprocess/

**Gunicorn auto-loads this file from the working directory even with no
`--config` flag on the command line** — so this hook runs on every worker
exit regardless of whether the unit file's `PROMETHEUS_MULTIPROC_DIR`
Environment= line is actually in place. `multiprocess.mark_process_dead()`
raises `TypeError` (not a clean no-op) when that env var is unset — a bare
call here previously crashed the whole gunicorn arbiter on the very first
worker recycle, taking the site down (2026-08-25 incident, see
CLAUDE_RUNBOOK.md). Guard it.
"""
import os

from prometheus_client import multiprocess


def child_exit(server, worker):
    if os.environ.get('PROMETHEUS_MULTIPROC_DIR'):
        multiprocess.mark_process_dead(worker.pid)
