"""Curated pre-built workflow templates + idempotent seeding.

Data lives here (not in scripts/) so app.py can seed it at import under gunicorn —
scripts/seed_workflows.py imports app, so importing that from app.py would be circular.
"""
import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# Setup script shared by the Azure and GCP LLM workflows. It needs only the NVIDIA
# driver on the host: vLLM's pip wheels bundle the CUDA runtime and uv fetches the
# Python version vLLM requires, so no Docker/container-toolkit setup is needed
# (install commands follow the vLLM quickstart, docs.vllm.ai). It is idempotent and
# runs vLLM as a systemd unit, so a driver-install reboot or a re-run of the script
# cannot leave the server stopped or duplicated.
_VLLM_PIP_SETUP_LINES = (
    '(1) #!/bin/bash '
    '(2) exec >> /var/log/llm-setup.log 2>&1 '
    '(3) export HOME=/root '
    '(4) for i in $(seq 1 90); do nvidia-smi && break; sleep 20; done '
    '(5) if [ ! -x /opt/vllm/bin/vllm ]; then curl -LsSf https://astral.sh/uv/install.sh | '
    'env UV_INSTALL_DIR=/usr/local/bin sh && uv venv --python 3.12 --seed /opt/vllm && '
    'VIRTUAL_ENV=/opt/vllm uv pip install vllm --torch-backend=auto; fi '
    "(6) printf '[Unit]\\nAfter=network-online.target\\n[Service]\\nEnvironment=HOME=/root\\n"
    'ExecStart=/opt/vllm/bin/vllm serve {model_id} --host 0.0.0.0 --port 8000 --api-key {api_key} EXTRA_ARGS\\n'
    "Restart=always\\nRestartSec=30\\n[Install]\\nWantedBy=multi-user.target\\n' > "
    '/etc/systemd/system/vllm.service '
    '(7) chmod 600 /etc/systemd/system/vllm.service '
    '(8) systemctl daemon-reload && systemctl enable --now vllm'
)

# Reusable form-field specs (see services/workflow_inputs.py).
def _region(default: str = 'us-east-1') -> Dict[str, Any]:
    return {'key': 'region', 'label': 'AWS region', 'type': 'text', 'default': default,
            'pattern': r'[a-z]{2}(-gov)?-[a-z]+-\d', 'pattern_hint': 'An AWS region code, e.g. us-east-1.'}


def _my_cidr(help_text: str = 'Only this address can reach the service. Prefilled with your current IP.',
              allow_world: bool = False) -> Dict[str, Any]:
    return {'key': 'allowed_cidr', 'label': 'Your IP (CIDR)', 'type': 'cidr',
            'allow_world': allow_world, 'help': help_text}


_NAME_PATTERN = r'[a-z][a-z0-9-]{1,30}[a-z0-9]'
_NAME_HINT = '3-32 characters: lowercase letters, digits and hyphens, starting with a letter.'


def _name(key: str, label: str, default: str) -> Dict[str, Any]:
    return {'key': key, 'label': label, 'type': 'text', 'default': default,
            'pattern': _NAME_PATTERN, 'pattern_hint': _NAME_HINT}


_MODEL_INPUT = {'key': 'model_id', 'label': 'Hugging Face model', 'type': 'text',
                'default': 'Qwen/Qwen2.5-1.5B-Instruct',
                'pattern': r'[A-Za-z0-9._-]+/[A-Za-z0-9._-]+',
                'pattern_hint': 'owner/model, e.g. Qwen/Qwen2.5-1.5B-Instruct.',
                'help': 'Small and ungated by default, so no Hugging Face token is needed.'}
_API_KEY_INPUT = {'key': 'api_key', 'label': 'API key for the endpoint', 'type': 'secret',
                  'help': 'Leave blank and a strong key is generated. Clients send it as a Bearer token.'}


STARTER_WORKFLOWS: List[Dict[str, Any]] = [
    {
        'name': 'EC2 + Nginx Web Server Setup',
        'description': 'Launch an EC2 instance, install and configure Nginx, and verify the web server is reachable.',
        'category': 'Compute',
        'estimated_minutes': 8,
        'inputs': [
            _region(),
            {'key': 'instance_type', 'label': 'Instance type', 'type': 'select',
             'default': 't3.micro', 'options': ['t3.micro', 't3.small', 't3.medium']},
            _my_cidr('Who can reach port 80. Your IP keeps it private while you test; enter 0.0.0.0/0 '
                     'to make it public.', allow_world=True),
        ],
        'steps': [
            'Resolve the newest Amazon Linux 2023 AMI with find_ami(distro="amazon-linux", region="{region}").',
            'create_security_group nginx-web-sg in the default VPC and authorize_security_group_ingress TCP '
            '80 from {allowed_cidr} only.',
            'Launch one {instance_type} instance with create_ec2_instance in {region}: the resolved ami_id, '
            'nginx-web-sg, tags {"Name": "nginx-web"}, and user_data so it configures itself on first boot, '
            'one item per line: (1) #!/bin/bash (2) dnf install -y nginx (3) systemctl enable --now nginx.',
            'Wait for the instance to reach running state and retrieve its public IP address.',
            'Verify with http_check http://<public_ip>/ and expected_status 200, retrying every 30 seconds '
            'for up to 5 minutes while the boot script installs Nginx.',
            'Report the public IP and confirm Nginx is serving. Teardown: terminate the nginx-web instance, '
            'then delete nginx-web-sg.',
        ],
    },
    {
        'name': 'Prometheus + Grafana Monitoring Stack',
        'description': 'Deploy Prometheus and Grafana on an EC2 instance for infrastructure monitoring.',
        'category': 'Monitoring',
        'estimated_minutes': 12,
        'inputs': [
            _region(),
            _my_cidr('Only this address can open Prometheus and Grafana. Prefilled with your current IP.'),
            {'key': 'grafana_password', 'label': 'Grafana admin password', 'type': 'secret',
             'help': 'Leave blank and a strong one is generated. Never use the default "admin".'},
        ],
        'steps': [
            'Resolve the newest Amazon Linux 2023 AMI with find_ami(distro="amazon-linux", region="{region}").',
            'create_security_group monitoring-sg in the default VPC and authorize_security_group_ingress TCP '
            '9090 (Prometheus) and TCP 3000 (Grafana) from {allowed_cidr} only.',
            'Launch one t3.small instance with create_ec2_instance in {region}: the resolved ami_id, '
            'monitoring-sg, tags {"Name": "monitoring"}, and user_data so it configures itself on first boot, '
            'one item per line: (1) #!/bin/bash (2) dnf install -y docker (3) systemctl enable --now docker '
            '(4) docker run -d --restart unless-stopped --name prometheus -p 9090:9090 prom/prometheus '
            '(5) docker run -d --restart unless-stopped --name grafana -p 3000:3000 -e '
            'GF_SECURITY_ADMIN_PASSWORD={grafana_password} grafana/grafana',
            'Wait for the instance to reach running state and retrieve its public IP address.',
            'Verify with http_check on http://<public_ip>:9090/-/ready and http://<public_ip>:3000/api/health, '
            'each with expected_status 200, retrying every 30 seconds for up to 8 minutes while the images '
            'download.',
            'Report both URLs and that Grafana logs in as admin with the password I set. Suggest adding '
            'Prometheus as a Grafana data source at http://<private_ip>:9090. Teardown: terminate the '
            'monitoring instance, then delete monitoring-sg.',
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
        'inputs': [_region(), _my_cidr(), dict(_MODEL_INPUT), dict(_API_KEY_INPUT)],
        'steps': [
            'Work in {region} throughout. Before creating anything, warn me that a g5.xlarge is billed '
            'hourly (check current EC2 pricing for {region}) until it is terminated. The API port is only '
            'ever opened to my CIDR ({allowed_cidr}), never 0.0.0.0/0.',
            'Check GPU capacity: call aws_api_read with service "service-quotas", operation '
            '"get_service_quota", params {"ServiceCode": "ec2", "QuotaCode": "L-DB2E81BA"} '
            '(Running On-Demand G and VT instances, measured in vCPUs). A g5.xlarge needs 4. If the value '
            'is below 4, stop and tell me how to request an increase in Service Quotas — do not launch.',
            'Resolve the AMI with find_ami(distro="dlami-gpu", version="24.04"). This is the AWS Deep '
            'Learning Base GPU AMI, which ships with the NVIDIA driver, Docker and the NVIDIA container '
            'toolkit. Use the returned ami_id; never guess one.',
            'Create a security group named llm-gpu-lab in the default VPC with create_security_group, then '
            'add one inbound rule with authorize_security_group_ingress: TCP 8000 from my CIDR ({allowed_cidr}) only. Do not '
            'open SSH; this workflow verifies over HTTP.',
            'Launch ONE instance with create_ec2_instance: the resolved ami_id, instance_type g5.xlarge, '
            'the llm-gpu-lab security group, tags {"Name": "llm-gpu-lab", "Project": "llm-gpu-lab"}, and '
            'a user_data script so the instance configures itself on first boot. Write it as these five '
            'lines, each on its own line: '
            '(1) #!/bin/bash '
            '(2) exec > /var/log/llm-setup.log 2>&1 '
            '(3) for i in $(seq 1 30); do nvidia-smi && break; sleep 10; done '
            '(4) mkdir -p /opt/hf-cache '
            '(5) docker run -d --name vllm --restart unless-stopped --runtime nvidia --gpus all '
            '-v /opt/hf-cache:/root/.cache/huggingface -p 8000:8000 --ipc=host '
            'vllm/vllm-openai:latest --model {model_id} --api-key {api_key}',
            'Wait for the instance to reach running state and report its public IP. The image pull and '
            'model download take roughly 5-15 minutes — say so rather than reporting failure early.',
            'Verify readiness with http_check on http://<public_ip>:8000/health (expected_status 200), '
            'retrying every minute for up to 15 minutes. Then confirm the model is actually served: '
            'http_check http://<public_ip>:8000/v1/models with header Authorization: Bearer {api_key} and '
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
        'inputs': [_region(), _name('cluster_name', 'Existing EKS cluster name', 'dev-cluster'),
                   dict(_MODEL_INPUT), dict(_API_KEY_INPUT)],
        'steps': [
            'Work in {region} throughout. Call list_eks_clusters and confirm {cluster_name} exists. If it '
            'does not, stop and list the clusters that do exist; if there are none, suggest running the '
            '"Create an EKS Cluster (Ready for kubectl)" workflow first.',
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
            'Store the API key {api_key} in a Kubernetes Secret named vllm-api-key (key: api-key) in a new '
            'namespace llm. Never echo the key back in your report.',
            'apply_manifest a Deployment named vllm in namespace llm: 1 replica, image '
            'vllm/vllm-openai:latest, args ["--model", "{model_id}", "--api-key", "$(VLLM_API_KEY)"] with '
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
    {
        'name': 'Self-Hosted LLM on Azure GPU VM (vLLM)',
        'description': (
            'Deploy an open-weight LLM on one Azure NC-series GPU VM (Standard_NC4as_T4_v3, NVIDIA T4) '
            'with vLLM serving an OpenAI-compatible API behind an NSG locked to your IP, then verify it '
            'and report teardown.'
        ),
        'category': 'AI/ML',
        'estimated_minutes': 35,
        'inputs': [
            {'key': 'azure_region', 'label': 'Azure region', 'type': 'text', 'default': 'eastus',
             'pattern': r'[a-z]+[a-z0-9]*', 'pattern_hint': 'An Azure region name, e.g. eastus.'},
            _my_cidr(),
            {'key': 'ssh_public_key', 'label': 'SSH public key', 'type': 'text', 'max_length': 2000,
             'pattern': r'(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp(256|384|521)) [A-Za-z0-9+/=]+( [^\s]+)?',
             'pattern_hint': 'Paste one public key line, e.g. the contents of ~/.ssh/id_ed25519.pub.',
             'help': 'The VM uses key login only, never a password. Never paste a private key.'},
            dict(_MODEL_INPUT),
            dict(_API_KEY_INPUT),
        ],
        'steps': [
            'Work in {azure_region} throughout. Before creating anything, warn me that the VM bills hourly '
            'until it is deleted. The API port is only ever opened to my CIDR ({allowed_cidr}), never '
            '0.0.0.0/0 or *.',
            'Check GPU capacity: call azure_api_read with client_type "compute", operation_path '
            '"usage.list", params {"location": "{azure_region}"}. Find the entry for the NCASv3_T4 family '
            '(Standard_NC4as_T4_v3 needs 4 vCPUs). If limit minus current value is below 4, stop and tell '
            'me how to request a quota increase in the Azure portal — do not create anything.',
            'Resolve the image and GPU driver without guessing: azure_api_read("compute", '
            '"virtual_machine_images.list", {"location": "{azure_region}", "publisher_name": "Canonical", '
            '"offer": "0001-com-ubuntu-server-jammy", "skus": "22_04-lts-gen2"}) and azure_api_read('
            '"compute", "virtual_machine_extension_images.list_versions", {"location": "{azure_region}", '
            '"publisher_name": '
            '"Microsoft.HpcCompute", "type": "NvidiaGpuDriverLinux"}). Use the newest of each. If either '
            'list is empty, stop and report exactly what came back.',
            'create_resource_group named llm-gpu-lab-rg in {azure_region}. Then create the VM with '
            'create_virtual_machine: resource_group llm-gpu-lab-rg, vm_name llm-gpu-lab, location '
            '{azure_region}, vm_size Standard_NC4as_T4_v3, admin_username azureuser, ssh_public_key set to '
            'my key "{ssh_public_key}" (this disables password login), allowed_source_cidr set to my CIDR '
            '{allowed_cidr}, open_ports [8000] (no SSH), '
            'image_publisher Canonical with the image offer and sku resolved above, os_disk_size_gb 128, '
            'and tags {"Project": "llm-gpu-lab"}. The tool builds its own VNet, an NSG allowing only TCP '
            '8000 from my CIDR, and a Standard static public IP.',
            'Install the GPU driver: azure_api_write("compute", "virtual_machine_extensions.'
            'begin_create_or_update", ...) on llm-gpu-lab with publisher Microsoft.HpcCompute, type '
            'NvidiaGpuDriverLinux, the version resolved earlier, and auto_upgrade_minor_version true. Wait '
            'for the call to finish (the extension may reboot the VM) and confirm its provisioning state is '
            'Succeeded before continuing.',
            'Only after the driver is in place, install and start vLLM with azure_api_write("compute", '
            '"virtual_machines.begin_run_command", {"resource_group_name": "llm-gpu-lab-rg", "vm_name": '
            '"llm-gpu-lab", "parameters": {"command_id": "RunShellScript", "script": [...]}}), passing '
            'this script one item per line, replacing EXTRA_ARGS with "--dtype half" (the T4 has no '
            'bfloat16): ' + _VLLM_PIP_SETUP_LINES,
            'Read the public IP back, then verify readiness with http_check on http://<public_ip>:8000/health '
            '(expected_status 200), retrying every 2 minutes for up to 30 minutes — the vLLM download and '
            'first model load are slow. Then http_check http://<public_ip>:8000/v1/models with header '
            'Authorization: Bearer {api_key} and expected_status 200. A refused connection means it is still '
            'installing; a 401 means the key is wrong; report anything else exactly.',
            'Report the API base URL, model name and a sample curl to /v1/chat/completions, and flag the '
            'lab-only shortcuts (plain HTTP, public IP). Finally, give me the teardown: delete the '
            'llm-gpu-lab-rg resource group, which removes the VM, disk, IP, NIC, NSG and VNet together, and '
            'remind me the VM bills until I do.',
        ],
    },
    {
        'name': 'Self-Hosted LLM on GCP GPU VM (vLLM)',
        'description': (
            'Deploy an open-weight LLM on one GCP g2-standard-4 VM (NVIDIA L4) from a Deep Learning VM '
            'image, with vLLM serving an OpenAI-compatible API behind a firewall rule locked to your IP.'
        ),
        'category': 'AI/ML',
        'estimated_minutes': 30,
        'inputs': [
            {'key': 'gcp_project', 'label': 'GCP project ID', 'type': 'text',
             'pattern': r'[a-z][a-z0-9-]{4,28}[a-z0-9]',
             'pattern_hint': 'A GCP project ID: 6-30 lowercase letters, digits and hyphens.'},
            {'key': 'zone', 'label': 'GCP zone', 'type': 'text', 'default': 'us-central1-a',
             'pattern': r'[a-z]+-[a-z]+\d-[a-z]', 'pattern_hint': 'A zone name, e.g. us-central1-a.',
             'help': 'Must be a zone that offers NVIDIA L4 GPUs (g2 machine types).'},
            _my_cidr(),
            dict(_MODEL_INPUT),
            dict(_API_KEY_INPUT),
        ],
        'steps': [
            'Work in project {gcp_project}, zone {zone}; its region is the zone name without the final '
            '"-<letter>" suffix. Before creating anything, warn me the VM bills hourly until it is deleted. '
            'The API port is only ever opened to my CIDR ({allowed_cidr}), never 0.0.0.0/0.',
            'Check GPU capacity: gcp_api_read("compute", "v1", "regions", "get", {"project": '
            '"{gcp_project}", "region": "<region of {zone}>"}) and find the NVIDIA_L4_GPUS quota, and '
            'gcp_api_read("compute", "v1", "projects", "get", {"project": "{gcp_project}"}) for '
            'GPUS_ALL_REGIONS. One g2-standard-4 needs 1 of each. Also confirm the machine type exists in '
            'the zone with gcp_api_read("compute", "v1", "machineTypes", "get", {"project": '
            '"{gcp_project}", "zone": "{zone}", "machineType": "g2-standard-4"}). '
            'If any check fails, stop and explain how to request quota or pick another zone.',
            'Resolve the image without guessing: gcp_api_read("compute", "v1", "images", "list", '
            '{"project": "deeplearning-platform-release"}) and choose the newest non-deprecated image whose '
            'family is a CUDA image (family contains "cu") for Ubuntu or Debian. Report the family you '
            'picked. If none matches, stop and report what was listed.',
            'Open the API port with create_firewall_rule: rule_name llm-gpu-lab-8000, ports ["8000"], '
            'source_ranges ["{allowed_cidr}"] (my CIDR) only, target_tags ["llm-gpu-lab"]. Do not open SSH.',
            'Create the VM with gcp_api_write("compute", "v1", "instances", "insert", {"project": '
            '"{gcp_project}", "zone": "{zone}", "body": ...}): name llm-gpu-lab, machine type '
            'zones/{zone}/machineTypes/'
            'g2-standard-4, scheduling onHostMaintenance TERMINATE (required for GPU VMs), a 150 GB boot '
            'disk from the resolved image, the default network with an external IP (ONE_TO_ONE_NAT), '
            'network tag llm-gpu-lab, labels project=llm-gpu-lab, and metadata items install-nvidia-driver '
            '= True plus startup-script set to this script, each item on its own line, removing '
            'EXTRA_ARGS (it waits for the driver, and is safe to re-run on every boot): '
            + _VLLM_PIP_SETUP_LINES,
            'Read the instance back with gcp_api_read("compute", "v1", "instances", "get", ...) until it '
            'is RUNNING and report its external IP. Then verify with http_check on '
            'http://<external_ip>:8000/health (expected_status 200), retrying every 2 minutes for up to 30 '
            'minutes, and http_check http://<external_ip>:8000/v1/models with header Authorization: Bearer '
            '{api_key} and expected_status 200. Report anything unexpected exactly.',
            'Report the API base URL, model name and a sample curl to /v1/chat/completions, and flag the '
            'lab-only shortcuts (plain HTTP, external IP). Finally, give me the teardown: '
            'delete_compute_instance llm-gpu-lab, then delete_firewall_rule llm-gpu-lab-8000, and remind '
            'me the VM bills until it is deleted.',
        ],
    },
    {
        'name': 'LLM Serving on On-Prem Kubernetes GPUs (vLLM)',
        'description': (
            'Deploy vLLM on your own Kubernetes cluster with NVIDIA GPU nodes: check GPU readiness, '
            'install the NVIDIA device plugin if it is missing, and run vLLM as a Deployment and Service.'
        ),
        'category': 'AI/ML',
        'estimated_minutes': 25,
        'inputs': [
            {'key': 'kube_context', 'label': 'kubeconfig context', 'type': 'text', 'required': False,
             'pattern': r'[A-Za-z0-9@:/._-]{1,120}',
             'pattern_hint': 'A context name from kubectl config get-contexts.',
             'help': 'Leave blank to use the current context.'},
            dict(_MODEL_INPUT),
            dict(_API_KEY_INPUT),
            {'key': 'internet_access', 'label': 'Can the cluster download from Hugging Face?',
             'type': 'select', 'options': ['Yes', 'No (air-gapped)'], 'default': 'Yes'},
        ],
        'steps': [
            'Use kubeconfig context "{kube_context}" for every Kubernetes call ("not specified" means the '
            'current context). Cluster can download model weights from Hugging Face: {internet_access}. If '
            'it is air-gapped, stop after the readiness check and explain that the weights must be '
            'pre-staged on a PersistentVolume first.',
            'Check GPU readiness with get_nodes and describe_node: report which nodes show allocatable '
            'nvidia.com/gpu. GPU nodes must already have the NVIDIA driver and NVIDIA container toolkit '
            'installed on the host by whoever runs the hardware — never attempt host-level installs from '
            'Kubernetes.',
            'If no node reports nvidia.com/gpu, check with k8s_api_read (api_group "apps", method '
            '"list_daemon_set_for_all_namespaces") whether the NVIDIA device plugin or GPU Operator is '
            'already deployed. Only if neither exists, apply_manifest a DaemonSet in kube-system named '
            'nvidia-device-plugin-daemonset (selector label name=nvidia-device-plugin-ds, image '
            'nvcr.io/nvidia/k8s-device-plugin:v0.17.1, toleration nvidia.com/gpu Exists NoSchedule, '
            'priorityClassName system-node-critical, env FAIL_ON_INIT_ERROR=false, securityContext '
            'allowPrivilegeEscalation false with all capabilities dropped, hostPath volume '
            '/var/lib/kubelet/device-plugins mounted at the same path). If nodes still show no '
            'nvidia.com/gpu: 1, stop: the host driver or container toolkit is missing, and say so plainly.',
            'create_namespace llm, then create_k8s_secret vllm-api-key (key: api-key, value {api_key}) in '
            'it. Never echo the key back in your report.',
            'apply_manifest a Deployment named vllm in namespace llm: 1 replica, image '
            'vllm/vllm-openai:latest, args ["--model", "{model_id}", "--api-key", "$(VLLM_API_KEY)"] with '
            'VLLM_API_KEY from the vllm-api-key Secret, containerPort 8000, resources.limits '
            'nvidia.com/gpu: 1, a toleration for nvidia.com/gpu, an emptyDir mounted at /dev/shm (medium '
            'Memory), and a readinessProbe on GET /health port 8000 with initialDelaySeconds 120. Then '
            'apply_manifest a ClusterIP Service named vllm on port 8000.',
            'Watch the pod until Ready. If it stays Pending, read its events for an unsatisfied '
            'nvidia.com/gpu request; if it crashes, read get_pod_logs and report the exact error (an older '
            'GPU without bfloat16 needs "--dtype half" added to args).',
            'Report: the in-cluster endpoint (http://vllm.llm.svc.cluster.local:8000/v1), how to test with '
            'kubectl port-forward svc/vllm -n llm 8000:8000, what production would add (pinned image tag, '
            'an Ingress with TLS, a PersistentVolume for model weights, the NVIDIA GPU Operator to manage '
            'drivers, Prometheus scraping of /metrics), and the teardown: delete_namespace llm, and remove '
            'the device plugin DaemonSet only if this run installed it.',
        ],
    },

    # ---------------------------------------------------------------- App Hosting
    {
        'name': 'Static Website on S3 + CloudFront (HTTPS)',
        'description': (
            'Host a static website from a private S3 bucket behind a CloudFront distribution with '
            'HTTPS, publish a starter page, and verify it loads.'
        ),
        'category': 'App Hosting',
        'estimated_minutes': 20,
        'inputs': [
            _region(),
            {'key': 'bucket_name', 'label': 'Bucket name (globally unique)', 'type': 'text',
             'default': '', 'pattern': r'[a-z0-9][a-z0-9-]{1,61}[a-z0-9]',
             'pattern_hint': '3-63 lowercase letters, digits and hyphens.',
             'help': 'S3 bucket names are shared across all AWS accounts, so pick something unique.'},
            {'key': 'site_title', 'label': 'Starter page headline', 'type': 'text',
             'default': 'Hello from DevOps Agent', 'pattern': r"[A-Za-z0-9 .,!'-]{1,60}",
             'pattern_hint': 'Up to 60 letters, digits, spaces and . , ! \' -'},
        ],
        'steps': [
            'Check the name is free with aws_api_read("s3", "head_bucket", {"Bucket": "{bucket_name}"}): '
            'a 404 means free; a 403 means another account owns it, so stop and tell me to pick another '
            'name. Then create_s3_bucket {bucket_name} in {region} with encryption on and the public access '
            'block ON. The bucket stays private; only CloudFront will read from it.',
            'Upload a starter page with aws_api_write("s3", "put_object", {"Bucket": "{bucket_name}", '
            '"Key": "index.html", "ContentType": "text/html", "Body": "<!doctype html><html><head><meta '
            'charset=utf-8><title>{site_title}</title></head><body><h1>{site_title}</h1><p>Served from S3 '
            'through CloudFront.</p></body></html>"}).',
            'Create an origin access control with aws_api_write("cloudfront", '
            '"create_origin_access_control", {"OriginAccessControlConfig": {"Name": "{bucket_name}-oac", '
            '"SigningProtocol": "sigv4", "SigningBehavior": "always", "OriginAccessControlOriginType": '
            '"s3"}}). Look up the Id of the AWS-managed "CachingOptimized" cache policy with '
            'aws_api_read("cloudfront", "list_cache_policies", {"Type": "managed"}) instead of guessing it.',
            'Create the distribution with aws_api_write("cloudfront", "create_distribution", ...): one '
            'origin with DomainName {bucket_name}.s3.{region}.amazonaws.com, S3OriginConfig with an empty '
            'OriginAccessIdentity, and the OAC id above; DefaultCacheBehavior targeting that origin with '
            'ViewerProtocolPolicy redirect-to-https and the CachingOptimized policy id; DefaultRootObject '
            'index.html; Enabled true; a unique CallerReference; Comment "{bucket_name}".',
            'Allow only this distribution to read the bucket: put_s3_bucket_policy on {bucket_name} with '
            'one statement allowing Principal {"Service": "cloudfront.amazonaws.com"} the s3:GetObject '
            'action on arn:aws:s3:::{bucket_name}/*, with Condition StringEquals AWS:SourceArn set to the '
            'new distribution ARN. Never make the bucket itself public.',
            'Poll aws_api_read("cloudfront", "get_distribution", {"Id": ...}) every minute until Status is '
            'Deployed (often 5-15 minutes), then http_check https://<distribution domain>/ with '
            'expected_status 200 and confirm the body contains "{site_title}". A 403 usually means the bucket '
            'policy or OAC is wrong: re-check them and report exactly what you found.',
            'Report the HTTPS URL, how to publish updates (upload files to {bucket_name}, then '
            'create_cloudfront_invalidation for "/*"), and how to add a custom domain later (ACM certificate '
            'in us-east-1 plus a Route 53 alias). Finally, give me the teardown: disable the distribution, '
            'wait until it is Deployed, delete it and the OAC, empty {bucket_name}, then delete the bucket.',
        ],
    },
    {
        'name': 'Container App on ECS Fargate + Load Balancer',
        'description': (
            'Run any container image on ECS Fargate behind an Application Load Balancer, with logs in '
            'CloudWatch, health checks, and a verified URL.'
        ),
        'category': 'App Hosting',
        'estimated_minutes': 25,
        'inputs': [
            _region(),
            _name('app_name', 'App name', 'my-app'),
            {'key': 'container_image', 'label': 'Container image', 'type': 'text',
             'default': 'nginx:stable', 'pattern': r'[A-Za-z0-9][A-Za-z0-9./:_@-]{0,190}',
             'pattern_hint': 'An image reference such as nginx:stable or <account>.dkr.ecr.<region>.amazonaws.com/app:1.0.',
             'help': 'Any public image, or one in your ECR.'},
            {'key': 'container_port', 'label': 'Container port', 'type': 'number',
             'default': 80, 'min': 1, 'max': 65535},
            {'key': 'desired_count', 'label': 'Number of tasks', 'type': 'number',
             'default': 1, 'min': 1, 'max': 4},
            _my_cidr('Who can reach the load balancer. Your IP keeps it private while you test; '
                     'enter 0.0.0.0/0 to make it public.', allow_world=True),
        ],
        'steps': [
            'Find the default VPC with list_vpcs and at least two of its public subnets in different '
            'Availability Zones with list_subnets in {region}. If there is no default VPC, stop and tell me.',
            'Security groups: create_security_group {app_name}-alb-sg and authorize_security_group_ingress '
            'TCP 80 from {allowed_cidr} only. Then create_security_group {app_name}-task-sg and allow TCP '
            '{container_port} only from {app_name}-alb-sg as the source group (if '
            'authorize_security_group_ingress cannot take a source group, use aws_api_write("ec2", '
            '"authorize_security_group_ingress", ...) with IpPermissions UserIdGroupPairs). Tasks must never '
            'be reachable directly.',
            'Execution role: get_iam_role ecsTaskExecutionRole. If it does not exist, create_iam_role '
            'ecsTaskExecutionRole trusting ecs-tasks.amazonaws.com and attach_iam_role_policy '
            'arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy.',
            'Logs and cluster: aws_api_write("logs", "create_log_group", {"logGroupName": '
            '"/ecs/{app_name}"}), then create_ecs_cluster {app_name}-cluster with capacity provider FARGATE.',
            'Register the task definition with aws_api_write("ecs", "register_task_definition", ...): family '
            '{app_name}, networkMode awsvpc, requiresCompatibilities ["FARGATE"], cpu "256", memory "512", '
            'the execution role ARN, and one essential container named {app_name} using image '
            '{container_image}, portMappings [{"containerPort": {container_port}, "protocol": "tcp"}], and '
            'awslogs logging to /ecs/{app_name} in {region} with stream prefix {app_name}.',
            'Load balancer: create_target_group {app_name}-tg with target_type ip, protocol HTTP, port '
            '{container_port}, the VPC id and health_check_path /. create_load_balancer {app_name}-alb, '
            'internet-facing application type, on the two subnets with {app_name}-alb-sg. Then '
            'aws_api_write("elbv2", "create_listener", ...) on port 80 HTTP forwarding to {app_name}-tg.',
            'Create the service with aws_api_write("ecs", "create_service", ...): cluster '
            '{app_name}-cluster, serviceName {app_name}, the task definition, desiredCount {desired_count}, '
            'launchType FARGATE, awsvpcConfiguration with the two subnets, {app_name}-task-sg and '
            'assignPublicIp ENABLED (needed to pull the image without a NAT gateway), and loadBalancers '
            'pointing at {app_name}-tg, container {app_name}, port {container_port}.',
            'Verify: poll describe_target_health on {app_name}-tg until targets are healthy (up to 10 '
            'minutes), then http_check http://<load balancer DNS name>/ with expected_status 200. If targets '
            'stay unhealthy, read get_cloudwatch_logs for /ecs/{app_name} and report the exact error.',
            'Report the URL, how to deploy a new version (register a new task definition revision, then '
            'update_ecs_service), and that the load balancer bills hourly. Finally, give me the teardown in '
            'order: set the service desired count to 0 and delete it, delete_load_balancer, '
            'delete_target_group, delete_ecs_cluster, delete both security groups and the log group. Keep '
            'ecsTaskExecutionRole; other services may use it.',
        ],
    },

    # ----------------------------------------------------------------- Kubernetes
    {
        'name': 'Create an EKS Cluster (Ready for kubectl)',
        'description': (
            'Create a managed Kubernetes cluster on EKS with a managed node group, IAM roles and '
            'everything needed to start deploying workloads.'
        ),
        'category': 'Kubernetes',
        'estimated_minutes': 30,
        'inputs': [
            _region(),
            _name('cluster_name', 'Cluster name', 'dev-cluster'),
            {'key': 'node_instance_type', 'label': 'Node instance type', 'type': 'select',
             'default': 't3.medium', 'options': ['t3.medium', 't3.large', 'm5.large', 'm5.xlarge']},
            {'key': 'node_count', 'label': 'Number of nodes', 'type': 'number',
             'default': 2, 'min': 1, 'max': 5},
        ],
        'steps': [
            'Warn me first that the EKS control plane and the nodes bill hourly until deleted. Check '
            'list_eks_clusters in {region}: if {cluster_name} already exists, stop and tell me.',
            'Networking: find the default VPC with list_vpcs and its subnets with list_subnets. EKS needs '
            'subnets in at least two Availability Zones; pick two or three. If create_eks_cluster later fails '
            'with UnsupportedAvailabilityZoneException, drop that zone and retry once.',
            'IAM: create_iam_role {cluster_name}-cluster-role trusting eks.amazonaws.com and '
            'attach_iam_role_policy arn:aws:iam::aws:policy/AmazonEKSClusterPolicy. Then create_iam_role '
            '{cluster_name}-node-role trusting ec2.amazonaws.com and attach AmazonEKSWorkerNodePolicy, '
            'AmazonEKS_CNI_Policy and AmazonEC2ContainerRegistryReadOnly (all under '
            'arn:aws:iam::aws:policy/).',
            'create_eks_cluster {cluster_name} in {region} with the cluster role ARN and the chosen subnet ids, '
            'leaving the Kubernetes version at the default. Poll describe_eks_cluster every 2 minutes until '
            'status is ACTIVE (usually 10-20 minutes).',
            'create_eks_node_group {cluster_name}-nodes on the same subnets with the node role ARN, '
            'instance_types ["{node_instance_type}"], ami_type AL2023_x86_64_STANDARD, scaling min 1, max '
            '{node_count}, desired {node_count}. Poll aws_api_read("eks", "describe_nodegroup", '
            '{"clusterName": "{cluster_name}", "nodegroupName": "{cluster_name}-nodes"}) until ACTIVE.',
            'Report the endpoint and Kubernetes version, the command to connect from my machine: aws eks '
            'update-kubeconfig --region {region} --name {cluster_name}, and that if I will use kubectl as a '
            'different IAM identity than DevOps Agent uses, I need an access entry (create_eks_access_entry '
            'plus associate_eks_access_policy with AmazonEKSClusterAdminPolicy). Suggest the "Deploy an App '
            'to Kubernetes" workflow next.',
            'Finally, give me the teardown in order: delete the {cluster_name}-nodes node group and wait for '
            'it to finish, delete_eks_cluster {cluster_name}, then detach the policies from and delete both '
            'IAM roles.',
        ],
    },
    {
        'name': 'Deploy an App to Kubernetes',
        'description': (
            'Deploy a container image to any connected Kubernetes cluster with resource limits, a '
            'Service, and a verified rollout.'
        ),
        'category': 'Kubernetes',
        'estimated_minutes': 10,
        'inputs': [
            _name('namespace', 'Namespace', 'apps'),
            _name('app_name', 'App name', 'my-app'),
            {'key': 'image', 'label': 'Container image', 'type': 'text', 'default': 'nginx:stable',
             'pattern': r'[A-Za-z0-9][A-Za-z0-9./:_@-]{0,190}',
             'pattern_hint': 'An image reference such as nginx:stable.'},
            {'key': 'replicas', 'label': 'Replicas', 'type': 'number', 'default': 2, 'min': 1, 'max': 10},
            {'key': 'container_port', 'label': 'Container port', 'type': 'number',
             'default': 80, 'min': 1, 'max': 65535},
            {'key': 'exposure', 'label': 'Expose as', 'type': 'select', 'default': 'ClusterIP',
             'options': ['ClusterIP', 'LoadBalancer'],
             'help': 'ClusterIP is internal to the cluster; LoadBalancer gets a public address and may cost money.'},
        ],
        'steps': [
            'Confirm which cluster you are connected to (get_nodes) and tell me its name before changing '
            'anything. get_namespaces: create_namespace {namespace} only if it does not exist.',
            'get_deployments in {namespace}: if {app_name} already exists, stop and ask me whether to update '
            'its image with update_deployment_image instead of creating a new one.',
            'create_deployment {app_name} in {namespace} with image {image}, replicas {replicas}, port '
            '{container_port}, labels {"app": "{app_name}"}, cpu_request 100m, memory_request 128Mi, '
            'cpu_limit 500m and memory_limit 256Mi.',
            'create_service {app_name} in {namespace}: port 80, target_port {container_port}, selector '
            '{"app": "{app_name}"}, service_type {exposure}.',
            'Verify: get_deployment_rollout_status until all {replicas} replicas are available (up to 5 '
            'minutes), and get_pods shows them Ready. If not, describe_pod and get_pod_logs the failing pod '
            'and report the exact error instead of retrying blindly.',
            'If exposure is LoadBalancer, poll get_services until the Service has an external address (up to '
            '5 minutes) and http_check http://<address>/ with expected_status 200. If it is ClusterIP, give '
            'me the test command: kubectl port-forward svc/{app_name} -n {namespace} 8080:80.',
            'Report what was created and how to roll out a new version (update_deployment_image, or '
            'rollback_deployment if it misbehaves). Finally, give me the teardown: delete the {app_name} '
            'Service and Deployment, and delete_namespace {namespace} only if this run created it.',
        ],
    },
    {
        'name': 'Troubleshoot Failing Kubernetes Pods',
        'description': (
            'Read-only diagnosis of CrashLoopBackOff, ImagePullBackOff, OOMKilled, Pending and failing '
            'probes, with the root cause and exact fix for each pod.'
        ),
        'category': 'Kubernetes',
        'estimated_minutes': 5,
        'inputs': [
            _name('namespace', 'Namespace', 'default'),
            {'key': 'workload', 'label': 'Pod or Deployment name prefix', 'type': 'text',
             'required': False, 'default': '', 'pattern': r'[a-z0-9][a-z0-9.-]{0,62}',
             'pattern_hint': 'Lowercase letters, digits, dots and hyphens.',
             'help': 'Leave blank to check every pod in the namespace.'},
        ],
        'steps': [
            'This workflow is read-only: do not delete, restart, scale or edit anything without asking me.',
            'get_pods in {namespace}. Focus on pods whose name starts with "{workload}" (if that says "not '
            'specified", check every pod). List each pod that is not Ready, is Pending, or has restarts.',
            'For each problem pod: describe_pod, get_cluster_events for {namespace}, get_previous_container_logs '
            'if it has restarted, and get_pod_logs. For Pending pods, also check get_nodes and describe_node '
            'for allocatable capacity, taints and conditions. Run top_pods to compare usage with limits.',
            'Classify each pod: CrashLoopBackOff (the app exits; quote the last log lines and exit code), '
            'OOMKilled (exit code 137, memory limit too low), ImagePullBackOff/ErrImagePull (wrong image or '
            'tag, or missing registry credentials), Pending (insufficient CPU/memory, taints, nodeSelector, '
            'unbound PersistentVolumeClaim), CreateContainerConfigError (missing ConfigMap or Secret), or '
            'readiness/liveness probe failures (wrong path, port or timing).',
            'Report a table per pod: symptom, evidence (quoted event or log lines), root cause, and the exact '
            'fix, as the DevOps Agent tool call or kubectl command. Then ask me which fixes to apply.',
        ],
    },

    # ---------------------------------------------------------- Incident Response
    {
        'name': 'Investigate High CPU on an EC2 Instance',
        'description': (
            'Find out why an instance is pegged: CPU history, burst credits, the top processes (via SSM '
            'when available), and a recommended fix. Read-only.'
        ),
        'category': 'Incident Response',
        'estimated_minutes': 6,
        'inputs': [
            _region(),
            {'key': 'instance_id', 'label': 'Instance ID', 'type': 'text', 'default': '',
             'pattern': r'i-[0-9a-f]{8,17}', 'pattern_hint': 'An EC2 instance id like i-0123456789abcdef0.'},
            {'key': 'hours', 'label': 'Look back (hours)', 'type': 'number', 'default': 6, 'min': 1, 'max': 72},
        ],
        'steps': [
            'This workflow is read-only: do not stop, reboot, resize or terminate anything without asking me.',
            'get_ec2_instances in {region} for {instance_id}: report the instance type, state, launch time '
            'and whether it is burstable (t2, t3, t3a or t4g).',
            'aws_api_read("cloudwatch", "get_metric_statistics", ...) for AWS/EC2 CPUUtilization on '
            '{instance_id} over the last {hours} hours, Period 300, statistics Average and Maximum. For a '
            'burstable instance also read CPUCreditBalance and CPUSurplusCreditBalance: a balance near zero '
            'means it is being throttled, not just busy. Include NetworkIn/NetworkOut to spot traffic spikes.',
            'If {instance_id} appears in list_ssm_managed_instances, use ssm_run_command with read-only '
            'commands: "uptime", "top -b -n 1 | head -25", "ps -eo pid,user,%cpu,%mem,etime,cmd --sort=-%cpu '
            '| head -15", "free -m", "df -h". If it is not SSM-managed, read get_ec2_console_output instead '
            'and say that you cannot see processes.',
            'Diagnose: runaway or stuck process, traffic spike, burst-credit exhaustion, an undersized '
            'instance, or an unknown process using high CPU. Treat an unrecognized process (for example a '
            'possible crypto miner) as a security concern and say so plainly.',
            'Report the evidence and root cause, then the fix options with trade-offs (fix or restart the '
            'process, enable T-unlimited, resize, add capacity behind a load balancer). Ask me before '
            'applying any of them.',
        ],
    },
    {
        'name': 'Diagnose a Website That Is Down',
        'description': (
            'Trace an unreachable URL from DNS through TLS, the load balancer or CDN, to the instances '
            'behind it, and report exactly where it breaks. Read-only.'
        ),
        'category': 'Incident Response',
        'estimated_minutes': 6,
        'inputs': [
            {'key': 'url', 'label': 'URL that is down', 'type': 'text', 'default': 'https://',
             'pattern': r'https?://[A-Za-z0-9.-]+(:\d{1,5})?(/[^\s]*)?',
             'pattern_hint': 'A full URL such as https://www.example.com/.'},
            _region(),
        ],
        'steps': [
            'This workflow is read-only: do not change DNS, load balancers, security groups or instances '
            'without asking me.',
            'http_check {url} and record the status code, latency and any error. Then tcp_check the host on '
            'port 443 and port 80. This separates DNS, TCP, TLS and application failures.',
            'DNS: list_route53_zones. If the host belongs to one of my hosted zones, read its records with '
            'aws_api_read("route53", "list_resource_record_sets", ...) to find what it points to (a load '
            'balancer, CloudFront, or an IP). If it is not in Route 53, say so and continue from the '
            'reachability results.',
            'Follow the target in {region}: for a load balancer, list_load_balancers and '
            'describe_target_health, quoting the reason for any unhealthy target; for CloudFront, '
            'list_cloudfront_distributions and check it is Enabled and Deployed and what its origin is; for an '
            'IP, get_ec2_instances to check state and status checks and that its security group allows 80/443.',
            'For TLS errors, list_acm_certificates and check the certificate for the host is ISSUED and not '
            'expired.',
            'Report the failing layer (DNS, network, TLS, load balancer, or application), the evidence, the '
            'root cause, and the exact fix. Ask me before changing anything.',
        ],
    },
    {
        'name': 'Investigate an AWS Cost Spike',
        'description': (
            'Find which services and resources drove a jump in your AWS bill, with recommended savings. '
            'Read-only.'
        ),
        'category': 'Incident Response',
        'estimated_minutes': 6,
        'inputs': [
            {'key': 'days', 'label': 'Look back (days)', 'type': 'number', 'default': 14, 'min': 7, 'max': 90},
        ],
        'steps': [
            'This workflow is read-only: do not stop or delete anything without asking me. Note that '
            'Cost Explorer data can lag by up to a day, and each Cost Explorer API request carries a small '
            'per-request charge, so keep queries few.',
            'get_cost_summary with days {days} for the per-service breakdown and daily trend. Compare the '
            'most recent 7 days with the 7 days before them and rank services by the increase.',
            'For the top three movers, aws_api_read("ce", "get_cost_and_usage", ...) with DAILY granularity '
            'over the last {days} days, filtered to that service and grouped by USAGE_TYPE, to see what kind '
            'of usage grew (instance hours, data transfer, NAT gateway hours, storage, requests).',
            'Find the resources likely behind it: list_ec2_all_regions for running instances, '
            'aws_api_read("ec2", "describe_nat_gateways", ...), aws_api_read("ec2", "describe_volumes", ...) '
            'with status available for unattached volumes, list_load_balancers, and list_s3_buckets.',
            'Report a table of each mover: service, increase, usage type, likely resource, and the '
            'recommended action with an estimated monthly saving. Ask me before acting on any of them.',
        ],
    },

    # ------------------------------------------------------------------- Security
    {
        'name': 'AWS Security Baseline (CloudTrail + GuardDuty)',
        'description': (
            'Check and switch on the account-wide basics: a multi-region CloudTrail with log validation, '
            'GuardDuty threat detection, and a review of S3 public access and root MFA.'
        ),
        'category': 'Security',
        'estimated_minutes': 10,
        'inputs': [
            _region(),
            {'key': 'trail_bucket_name', 'label': 'Bucket for CloudTrail logs (globally unique)',
             'type': 'text', 'default': '', 'pattern': r'[a-z0-9][a-z0-9-]{1,61}[a-z0-9]',
             'pattern_hint': '3-63 lowercase letters, digits and hyphens.',
             'help': 'Only used if no multi-region trail exists yet.'},
        ],
        'steps': [
            'Read the current state first and create only what is missing: list_cloudtrail_trails (is there '
            'a multi-region trail that is logging?), aws_api_read("guardduty", "list_detectors", {}) in '
            '{region}, aws_api_read("sts", "get_caller_identity", {}) for the account id, '
            'aws_api_read("s3control", "get_public_access_block", {"AccountId": ...}), and '
            'aws_api_read("iam", "get_account_summary", {}) for AccountMFAEnabled (root MFA).',
            'If no multi-region trail is logging: create_s3_bucket {trail_bucket_name} in {region} with '
            'versioning, encryption and the public access block on. put_s3_bucket_policy allowing Principal '
            '{"Service": "cloudtrail.amazonaws.com"} s3:GetBucketAcl on the bucket and s3:PutObject on '
            'arn:aws:s3:::{trail_bucket_name}/AWSLogs/<account id>/* with s3:x-amz-acl '
            'bucket-owner-full-control, both conditioned on aws:SourceArn '
            'arn:aws:cloudtrail:{region}:<account id>:trail/devops-agent-trail. Then aws_api_write('
            '"cloudtrail", "create_trail", ...) named devops-agent-trail with IsMultiRegionTrail true, '
            'IncludeGlobalServiceEvents true and EnableLogFileValidation true, and aws_api_write('
            '"cloudtrail", "start_logging", {"Name": "devops-agent-trail"}).',
            'If GuardDuty has no detector in {region}: aws_api_write("guardduty", "create_detector", '
            '{"Enable": true}). Tell me GuardDuty is per-region and paid after its free trial, and offer to '
            'enable it in the other regions I use.',
            'Account-level S3 Block Public Access: if any of the four settings is off, do NOT turn it on '
            'automatically. It can break buckets that are meant to be public. List my buckets, tell me which '
            'look intentionally public, and ask me.',
            'Report a before/after table for CloudTrail, GuardDuty, S3 Block Public Access and root MFA. If '
            'root MFA is off, explain how to enable it in the console (it cannot be done through the API). '
            'Finally, give me the rollback: stop_logging and delete the trail, delete the GuardDuty detector, '
            'and keep the log bucket for its audit history.',
        ],
    },

    # ------------------------------------------------------------------------ IaC
    {
        'name': 'Terraform Remote State Backend on S3',
        'description': (
            'Create a versioned, encrypted, private S3 bucket (plus optional DynamoDB lock table) for '
            'Terraform state, and get the backend block to paste into your project.'
        ),
        'category': 'IaC',
        'estimated_minutes': 5,
        'inputs': [
            _region(),
            {'key': 'state_bucket_name', 'label': 'State bucket name (globally unique)', 'type': 'text',
             'default': '', 'pattern': r'[a-z0-9][a-z0-9-]{1,61}[a-z0-9]',
             'pattern_hint': '3-63 lowercase letters, digits and hyphens.'},
            {'key': 'lock_method', 'label': 'State locking', 'type': 'select',
             'default': 'S3 native lockfile', 'options': ['S3 native lockfile', 'DynamoDB table'],
             'help': 'S3 native locking needs a recent Terraform (1.10 or later); DynamoDB works with any version.'},
            _name('lock_table_name', 'DynamoDB lock table name', 'terraform-locks'),
        ],
        'steps': [
            'Check the name is free with aws_api_read("s3", "head_bucket", {"Bucket": "{state_bucket_name}"}): '
            'a 404 means free; a 403 means another account owns it, so stop and ask me for another name.',
            'create_s3_bucket {state_bucket_name} in {region} with versioning_enabled true, '
            'encryption_enabled true and public_access_block true. Then put_s3_lifecycle_policy to expire '
            'noncurrent object versions after 90 days, so old state versions do not pile up forever.',
            'Locking method chosen: {lock_method}. Only if it is "DynamoDB table": create_dynamodb_table '
            '{lock_table_name} with partition key LockID of type String and on-demand (PAY_PER_REQUEST) '
            'billing, and wait until it is ACTIVE. For "S3 native lockfile", create no table.',
            'Verify with get_s3_bucket_info that versioning and encryption are on and public access is '
            'blocked, and that the table (if any) is ACTIVE.',
            'Give me the backend block to paste: terraform { backend "s3" { bucket = "{state_bucket_name}", '
            'key = "envs/dev/terraform.tfstate", region = "{region}", encrypt = true, plus either use_lockfile '
            '= true (S3 native lockfile) or dynamodb_table = "{lock_table_name}" } }, then the commands '
            'terraform init -migrate-state to move existing state. Tell me to confirm the locking argument '
            'against the docs for my Terraform version.',
            'Report the IAM permissions a CI role needs for this backend (s3:ListBucket on the bucket; '
            's3:GetObject, s3:PutObject and s3:DeleteObject on the key path; and the DynamoDB item actions if '
            'using a table). Teardown: warn that deleting this bucket destroys the state history; only empty '
            'and delete it once no Terraform project uses it.',
        ],
    },
]


# Arbitrary but fixed — must not collide with another advisory lock key.
_SEED_LOCK_KEY = 0x77_4F_52_4B  # "wORK"


# Curated fields kept in sync with STARTER_WORKFLOWS on every startup.
_SYNCED_FIELDS = ('description', 'category', 'steps', 'inputs', 'estimated_minutes')


def seed_workflow_templates() -> int:
    """Idempotently seed and refresh the curated public workflow templates.

    Safe to call on every startup. Missing templates (matched by name) are inserted;
    existing curated ones (public, no creator) have their content refreshed from
    STARTER_WORKFLOWS, so an edited workflow reaches production on the next deploy
    instead of being frozen at whatever was seeded first. Run counts and ids are
    kept. Returns the number of templates added.

    The check-then-insert runs under `seed_lock` because every gunicorn worker
    calls this at import simultaneously — without it they race and each inserts
    the full catalog.
    """
    from models import db, WorkflowTemplate
    from services.seed_lock import seed_lock

    updated = 0
    with seed_lock(_SEED_LOCK_KEY):
        curated = {
            t.name: t for t in WorkflowTemplate.query.filter_by(is_public=True).all()
            if t.created_by is None
        }
        public_names = {
            t.name for t in WorkflowTemplate.query.filter_by(is_public=True).all()
        }
        to_add = [wf for wf in STARTER_WORKFLOWS if wf['name'] not in public_names]
        for wf in to_add:
            db.session.add(WorkflowTemplate(**{'inputs': [], **wf}, is_public=True))
        for wf in STARTER_WORKFLOWS:
            row = curated.get(wf['name'])
            if row is None:
                continue
            changed = False
            for field in _SYNCED_FIELDS:
                value = wf.get(field, [] if field == 'inputs' else None)
                if getattr(row, field) != value:
                    setattr(row, field, value)
                    changed = True
            updated += changed

    if to_add or updated:
        logger.info(f"Workflow catalog: added {len(to_add)}, refreshed {updated}")
    return len(to_add)
