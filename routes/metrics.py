"""Prometheus scrape endpoint.

SECURITY: Gated by a shared-secret bearer token (`METRICS_TOKEN` env var),
not network-level IP restriction — nginx.conf proxies every path (including
this one) straight through to the app, so there is no reverse-proxy layer
that already scopes this to internal callers the way node_exporter's
`127.0.0.1`-only bind does. Same shape as app.py's existing
`/init-database-secret-endpoint-12345` token gate. Prometheus's own
`scrape_configs` support `authorization: {credentials: <token>}` natively.
"""
import hmac
import os

from flask import Blueprint, Response, request
from prometheus_client import CONTENT_TYPE_LATEST

from extensions import limiter, security_logger
from services.metrics_service import render_metrics

metrics_bp = Blueprint('metrics', __name__)


@metrics_bp.route('/metrics', methods=['GET'])
@limiter.limit("60 per minute")
def metrics():
    token = os.environ.get('METRICS_TOKEN')
    if not token:
        return Response('Metrics endpoint is not enabled. Set METRICS_TOKEN.\n',
                         status=403, mimetype='text/plain')

    provided = request.headers.get('Authorization', '')
    expected = f'Bearer {token}'
    if not hmac.compare_digest(provided, expected):
        security_logger.warning(f"Unauthorized /metrics scrape attempt from {request.remote_addr}")
        return Response('Unauthorized\n', status=403, mimetype='text/plain')

    return Response(render_metrics(), mimetype=CONTENT_TYPE_LATEST)
