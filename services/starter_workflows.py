"""Curated pre-built workflow templates + idempotent seeding.

Data lives here (not in scripts/) so app.py can seed it at import under gunicorn —
scripts/seed_workflows.py imports app, so importing that from app.py would be circular.
"""
import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

STARTER_WORKFLOWS: List[Dict[str, Any]] = [
    {
        'name': 'EC2 + Nginx Web Server Setup',
        'description': 'Launch an EC2 instance, install and configure Nginx, and verify the web server is reachable.',
        'category': 'Compute',
        'estimated_minutes': 8,
        'steps': [
            'List available EC2 instances in the default region to see current state.',
            'Launch a new t3.micro EC2 instance with Amazon Linux 2023 in us-east-1 (or the user\'s default region). Tag it Name=nginx-web.',
            'Wait for the instance to reach running state, then retrieve its public IP address.',
            'Use SSM Session Manager to connect to the instance and run: sudo dnf install -y nginx && sudo systemctl enable --now nginx',
            'Create a security group rule allowing inbound TCP port 80 from 0.0.0.0/0 for the instance.',
            'Verify the web server is responding by checking the instance\'s public IP on port 80.',
            'Report the public IP address and confirm Nginx is running.',
        ],
    },
    {
        'name': 'Prometheus + Grafana Monitoring Stack',
        'description': 'Deploy Prometheus and Grafana on an EC2 instance for infrastructure monitoring.',
        'category': 'Monitoring',
        'estimated_minutes': 12,
        'steps': [
            'List EC2 instances to find a suitable monitoring host (t3.small or larger recommended).',
            'If no suitable instance exists, launch a t3.small Amazon Linux 2023 instance tagged Name=monitoring.',
            'Install Docker on the instance via SSM: sudo dnf install -y docker && sudo systemctl enable --now docker',
            'Run Prometheus container: docker run -d --name prometheus -p 9090:9090 prom/prometheus',
            'Run Grafana container: docker run -d --name grafana -p 3000:3000 -e GF_SECURITY_ADMIN_PASSWORD=admin grafana/grafana',
            'Open security group ports 9090 (Prometheus) and 3000 (Grafana) from the user\'s IP range.',
            'Verify both services are running with docker ps and report the access URLs.',
        ],
    },
    {
        'name': 'IAM Access Key Rotation',
        'description': 'Rotate IAM access keys for all IAM users — identify old keys, create new ones, and disable the old ones.',
        'category': 'Security',
        'estimated_minutes': 5,
        'steps': [
            'List all IAM users in the account.',
            'For each user, list their access keys and identify any keys older than 90 days.',
            'For users with old keys, create a new access key (note: the user must update their applications with the new key).',
            'Report which users have keys older than 90 days, the new key IDs created, and instructions for the user to update their credentials before the old keys are disabled.',
            'List IAM users with the MFA device status — flag any users without MFA enabled.',
        ],
    },
    {
        'name': 'CIS Security Audit',
        'description': 'Run a CIS-aligned security audit: check public S3 buckets, open security groups, root account usage, and CloudTrail status.',
        'category': 'Security',
        'estimated_minutes': 6,
        'steps': [
            'List all S3 buckets and check each one for public access settings — report any buckets with public access enabled.',
            'List all security groups and flag any with inbound rules open to 0.0.0.0/0 on sensitive ports (22, 3389, 5432, 3306, 27017).',
            'Check CloudTrail trails — verify at least one trail is enabled and logging to S3.',
            'List IAM users and flag: (a) users without MFA, (b) users with console access but no recent login (>90 days), (c) users with AdministratorAccess policy.',
            'Check if the root account has MFA enabled by reviewing the account summary.',
            'Produce a prioritized summary of findings with recommended remediation steps.',
        ],
    },
    {
        'name': 'S3 Backup Lifecycle Policy',
        'description': 'Apply lifecycle policies to S3 buckets to move old objects to Glacier and delete expired backups.',
        'category': 'Storage',
        'estimated_minutes': 4,
        'steps': [
            'List all S3 buckets in the account.',
            'For each bucket whose name contains "backup" or "archive", check if a lifecycle policy already exists.',
            'For buckets without a lifecycle policy, apply the following rules: (1) Transition objects to S3 Intelligent-Tiering after 30 days, (2) Transition to Glacier after 90 days, (3) Expire (delete) objects after 365 days.',
            'Enable versioning on backup buckets that do not already have it enabled.',
            'Report which buckets had policies applied, which already had policies, and the estimated cost savings from the tiering.',
        ],
    },
    {
        'name': 'RDS Snapshot + Health Check',
        'description': 'Create manual snapshots of all RDS instances and verify database health metrics.',
        'category': 'Database',
        'estimated_minutes': 5,
        'steps': [
            'List all RDS instances and their current status.',
            'For each running RDS instance, create a manual snapshot tagged with today\'s date (e.g., manual-backup-YYYY-MM-DD).',
            'Check CloudWatch metrics for each instance: CPU utilization, free storage space, and database connections over the last 24 hours.',
            'Flag any instances with CPU > 80%, free storage < 20%, or connections near the max_connections limit.',
            'List existing automated snapshots and identify any instances where the latest automated snapshot is more than 24 hours old.',
            'Produce a health summary with findings and recommended actions.',
        ],
    },
    {
        'name': 'EC2 Cost Optimization Audit',
        'description': 'Identify underutilized EC2 instances and unused resources (unattached EBS volumes, unused Elastic IPs).',
        'category': 'Cost',
        'estimated_minutes': 6,
        'steps': [
            'List all running EC2 instances with their instance types and tags.',
            'Check CloudWatch CPU utilization for each instance over the last 7 days — flag instances averaging < 5% CPU (likely candidates for rightsizing or termination).',
            'List all EBS volumes and identify any in "available" state (not attached to any instance) — these are incurring cost with no benefit.',
            'List all Elastic IP addresses — identify any not associated with a running instance.',
            'List all load balancers and identify any with no healthy targets registered.',
            'Produce a cost optimization report with estimated monthly savings for each recommended action.',
        ],
    },
    {
        'name': 'VPC Security Hardening',
        'description': 'Audit and harden VPC security: review NACLs, security groups, flow logs, and public subnet exposure.',
        'category': 'Networking',
        'estimated_minutes': 7,
        'steps': [
            'List all VPCs and their CIDR ranges.',
            'For each VPC, list subnets and identify which are public (have an internet gateway route).',
            'List all security groups — flag any with rules allowing inbound 0.0.0.0/0 on all ports (-1) or dangerous ports (22, 3389).',
            'Check if VPC Flow Logs are enabled for each VPC — report any VPCs without flow logs.',
            'List Network ACLs and flag any with overly permissive allow-all rules.',
            'Check if any EC2 instances in public subnets have public IPs and are not behind a load balancer.',
            'Produce a prioritized security hardening report with specific remediation commands for each finding.',
        ],
    },
    {
        'name': 'Self-Hosted LLM on AWS GPU (EC2 + vLLM)',
        'description': (
            'Deploy an open-weight LLM on a single AWS GPU instance (g5.xlarge, NVIDIA A10G) '
            'with vLLM serving an OpenAI-compatible API, verify it end to end, and report '
            'cost and teardown steps.'
        ),
        'category': 'AI/ML',
        'estimated_minutes': 20,
        'steps': [
            'Before creating anything, ask me for: (a) my public IP in CIDR form (e.g. 203.0.113.10/32) — '
            'the API port must only ever be opened to that address, never 0.0.0.0/0; (b) a long random API '
            'key that clients must send as a Bearer token; (c) the model to serve, defaulting to '
            'Qwen/Qwen2.5-1.5B-Instruct (small, ungated, no Hugging Face token needed). Warn me that a '
            'g5.xlarge is billed hourly (check current EC2 pricing for my region) until it is terminated.',
            'Check GPU capacity: call aws_api_read with service "service-quotas", operation '
            '"get_service_quota", params {"ServiceCode": "ec2", "QuotaCode": "L-DB2E81BA"} '
            '(Running On-Demand G and VT instances, measured in vCPUs). A g5.xlarge needs 4. If the value '
            'is below 4, stop and tell me how to request an increase in Service Quotas — do not launch.',
            'Resolve the AMI with find_ami(distro="dlami-gpu", version="24.04"). This is the AWS Deep '
            'Learning Base GPU AMI, which ships with the NVIDIA driver, Docker and the NVIDIA container '
            'toolkit. Use the returned ami_id; never guess one.',
            'Create a security group named llm-gpu-lab in the default VPC with create_security_group, then '
            'add one inbound rule with authorize_security_group_ingress: TCP 8000 from my CIDR only. Do not '
            'open SSH; this workflow verifies over HTTP.',
            'Launch ONE instance with create_ec2_instance: the resolved ami_id, instance_type g5.xlarge, '
            'the llm-gpu-lab security group, tags {"Name": "llm-gpu-lab", "Project": "llm-gpu-lab"}, and '
            'a user_data script so the instance configures itself on first boot. Write it as these five '
            'lines, each on its own line, substituting MODEL_ID and API_KEY: '
            '(1) #!/bin/bash '
            '(2) exec > /var/log/llm-setup.log 2>&1 '
            '(3) for i in $(seq 1 30); do nvidia-smi && break; sleep 10; done '
            '(4) mkdir -p /opt/hf-cache '
            '(5) docker run -d --name vllm --restart unless-stopped --runtime nvidia --gpus all '
            '-v /opt/hf-cache:/root/.cache/huggingface -p 8000:8000 --ipc=host '
            'vllm/vllm-openai:latest --model MODEL_ID --api-key API_KEY',
            'Wait for the instance to reach running state and report its public IP. The image pull and '
            'model download take roughly 5-15 minutes — say so rather than reporting failure early.',
            'Verify readiness with http_check on http://<public_ip>:8000/health (expected_status 200), '
            'retrying every minute for up to 15 minutes. Then confirm the model is actually served: '
            'http_check http://<public_ip>:8000/v1/models with header Authorization: Bearer <api key> and '
            'expected_status 200. A connection refusal means vLLM is still starting; a 401 means the key '
            'is wrong; anything else, report exactly what came back.',
            'Report: the API base URL (http://<public_ip>:8000/v1), the model name, a sample curl to '
            '/v1/chat/completions, and that any OpenAI-compatible client works by changing only base_url '
            'and api_key. Flag the lab-only shortcuts: plain HTTP, a public IP, and the latest image tag. '
            'Finally, give me the teardown: terminate the llm-gpu-lab instance, then delete the '
            'llm-gpu-lab security group — and remind me the instance keeps billing until I do.',
        ],
    },
    {
        'name': 'LLM Serving on EKS GPU Nodes (vLLM)',
        'description': (
            'Add an NVIDIA GPU node group to an existing EKS cluster, install the NVIDIA device '
            'plugin, and deploy vLLM as a Kubernetes Deployment and Service.'
        ),
        'category': 'AI/ML',
        'estimated_minutes': 30,
        'steps': [
            'List my EKS clusters and ask which one to use. If there are none, stop: creating a cluster is '
            'out of scope for this workflow. Ask me for the model to serve (default '
            'Qwen/Qwen2.5-1.5B-Instruct) and a long random API key for the vLLM server.',
            'Check GPU capacity with aws_api_read (service "service-quotas", operation "get_service_quota", '
            'params {"ServiceCode": "ec2", "QuotaCode": "L-DB2E81BA"}). One g5.xlarge node needs 4 vCPUs; '
            'stop and explain how to request an increase if the quota is lower.',
            'Find the node IAM role and subnets to reuse: describe the cluster, list its node groups, and '
            'read an existing node group with aws_api_read (service "eks", operation "describe_nodegroup"). '
            'If no node group exists to copy the role from, stop and tell me which IAM role is needed '
            '(AmazonEKSWorkerNodePolicy, AmazonEKS_CNI_Policy, AmazonEC2ContainerRegistryReadOnly).',
            'Create a node group named gpu-llm with create_eks_node_group: instance_types ["g5.xlarge"], '
            'ami_type "AL2023_x86_64_NVIDIA" (NVIDIA driver and container toolkit included), '
            'scaling min 1 / max 1 / desired 1, disk_size 100, the same subnets and node role. Wait until it '
            'is ACTIVE and its node is Ready.',
            'Install the NVIDIA device plugin — the AL2023 NVIDIA AMI does not include it, and without it '
            'Kubernetes cannot schedule nvidia.com/gpu. First check whether the node already reports '
            'allocatable nvidia.com/gpu; if not, apply_manifest a DaemonSet in kube-system named '
            'nvidia-device-plugin-daemonset (selector label name=nvidia-device-plugin-ds, image '
            'nvcr.io/nvidia/k8s-device-plugin:v0.17.1, toleration nvidia.com/gpu Exists NoSchedule, '
            'priorityClassName system-node-critical, env FAIL_ON_INIT_ERROR=false, securityContext '
            'allowPrivilegeEscalation false with all capabilities dropped, hostPath volume '
            '/var/lib/kubelet/device-plugins mounted at the same path). Confirm the node then shows '
            'nvidia.com/gpu: 1 allocatable.',
            'Store the API key in a Kubernetes Secret named vllm-api-key (key: api-key) in a new namespace '
            'llm. Never echo the key back in your report.',
            'apply_manifest a Deployment named vllm in namespace llm: 1 replica, image '
            'vllm/vllm-openai:latest, args ["--model", MODEL_ID, "--api-key", "$(VLLM_API_KEY)"] with '
            'VLLM_API_KEY from the vllm-api-key Secret, containerPort 8000, resources.limits '
            'nvidia.com/gpu: 1, a toleration for nvidia.com/gpu, an emptyDir mounted at /dev/shm (medium '
            'Memory) for shared memory, and a readinessProbe on GET /health port 8000 with '
            'initialDelaySeconds 120. Then apply_manifest a ClusterIP Service named vllm on port 8000.',
            'Watch the pod until Ready (the first image pull and model download can take 10+ minutes). If it '
            'stays Pending, check events for an unsatisfied nvidia.com/gpu request; if it crashes, read its '
            'logs and report the exact error.',
            'Report: the in-cluster endpoint (http://vllm.llm.svc.cluster.local:8000/v1), how to test it '
            'from my machine with kubectl port-forward svc/vllm -n llm 8000:8000, what a production rollout '
            'would add (pinned image tag, an Ingress or internal load balancer with TLS, autoscaling on '
            'queue depth, Prometheus scraping of vLLM /metrics), and the teardown: delete the llm namespace, '
            'then delete the gpu-llm node group, which bills hourly until removed.',
        ],
    },
]


# Arbitrary but fixed — must not collide with another advisory lock key.
_SEED_LOCK_KEY = 0x77_4F_52_4B  # "wORK"


def seed_workflow_templates() -> int:
    """Idempotently seed the curated public workflow templates.

    Safe to call on every startup: existing public templates (matched by name)
    are skipped, so it never duplicates. Returns the number of templates added.

    The check-then-insert runs under `seed_lock` because every gunicorn worker
    calls this at import simultaneously — without it they race and each inserts
    the full catalog.
    """
    from models import db, WorkflowTemplate
    from services.seed_lock import seed_lock

    with seed_lock(_SEED_LOCK_KEY):
        existing_names = {
            t.name for t in WorkflowTemplate.query.filter_by(is_public=True).all()
        }
        to_add = [wf for wf in STARTER_WORKFLOWS if wf['name'] not in existing_names]
        for wf in to_add:
            db.session.add(WorkflowTemplate(**wf, is_public=True))

    if to_add:
        logger.info(f"Seeded {len(to_add)} public workflow template(s)")
    return len(to_add)
