# --timeout 120: gevent workers use a heartbeat timeout (not per-request) — long Kimi
# swarm calls (up to 290s) survive past this because gevent yields on I/O. nginx
# proxy_read_timeout 300 is the actual per-request hard limit.
web: gunicorn app:app --bind 0.0.0.0:$PORT --worker-class gevent --workers 1 --worker-connections 1000 --timeout 120