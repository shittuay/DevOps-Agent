---
id: kubernetes-troubleshooting
name: Kubernetes Troubleshooting
triggers: [pod, deployment, crashloop, kubectl, namespace, container, node, k8s, kubernetes, evicted, pending, oomkilled, imagepullbackoff, restarting, crash, liveness, readiness, resource limit]
compatible_providers: [kubernetes]
---
# Kubernetes Troubleshooting Context

## Pod Lifecycle Diagnosis
1. `list_pods` → check STATUS and RESTARTS count
2. `describe_pod` → check Events section for scheduling failures, image pull errors, OOMKilled
3. `get_pod_logs` → tail last 100 lines; add `previous=true` for last crashed container

## Common Issues

### CrashLoopBackOff
- App exits immediately → check logs for startup error or missing env var
- OOMKilled → increase memory limit or fix memory leak
- Liveness probe failing too fast → increase `initialDelaySeconds`
- Missing ConfigMap/Secret → `describe_pod` shows `CreateContainerError`

### Pending Pod
- Insufficient CPU/memory → `list_nodes` shows Allocatable vs Requested
- Node selector / affinity no match → check `nodeSelector` in spec
- PVC not bound → `kubectl describe pvc` for provisioner errors
- Taint/toleration mismatch → `describe_node` shows taints

### ImagePullBackOff
- Wrong image tag → verify registry:tag exists
- Private registry → check imagePullSecret is in the correct namespace
- Rate limiting (Docker Hub) → configure authenticated pull

## Resource Limits Best Practices
- Always set both `requests` and `limits`
- CPU limit without memory limit → OOMKill risk from noisy neighbors
- Set memory limit = 2× memory request for JVM workloads (JVM ignores cgroup limit by default pre-Java 11)
- Use VPA (Vertical Pod Autoscaler) in recommendation mode to tune values based on actual usage

## HPA Troubleshooting
- `kubectl describe hpa` → check "Events" and "Conditions"
- `AbleToScale=False` → check Deployment has `replicas` field, not managed by another controller
- Metrics not available → verify `metrics-server` is running

## Quick Commands
- `list_pods` with namespace filter
- `get_pod_logs` with `previous=True` for crashed containers
- `describe_pod` for events and conditions
- `list_nodes` to check node capacity and conditions
