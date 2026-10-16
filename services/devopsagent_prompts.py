"""
DevOps Agent — Mode-Isolated System Prompts & Session Factory

Provides hard-separated system prompts for SANDBOX vs REAL_AGENT modes so Kimi K3
cannot bleed its "simulate freely" sandbox behaviour into live cloud operations.

Also exposes:
  - detect_task_type()  — keyword-based task group detection
  - DevOpsAgentSessionFactory.scope_tools()  — filters tool list to task-relevant subset
    and enforces the per-tier max_tools cap to reduce Kimi hallucination risk.
"""

from __future__ import annotations

import uuid
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class AgentMode(Enum):
    SANDBOX = "sandbox"
    REAL_AGENT = "real_agent"


class CloudProvider(Enum):
    AWS = "aws"
    AZURE = "azure"
    GCP = "gcp"


# ---------------------------------------------------------------------------
# Session dataclass
# ---------------------------------------------------------------------------

@dataclass
class AgentSession:
    mode: AgentMode
    cloud_provider: Optional[CloudProvider]
    session_id: str
    message_history: List[Dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# System Prompts
# ---------------------------------------------------------------------------

SANDBOX_SYSTEM_PROMPT = """
=== SANDBOX / LEARNING MODE ===

You are running in SANDBOX mode. This is a safe learning environment with NO connection
to any real cloud accounts, credentials, or infrastructure.

SANDBOX RULES — follow them exactly:
1. You MAY generate fictional but realistic cloud resources to help the user learn.
   Use plausible-looking IDs (e.g. i-0a1b2c3d4e5f6789a) and realistic names.
2. Every simulated tool result or resource list MUST be prefixed with [SANDBOX SIMULATION].
3. You MUST NOT reference, use, or attempt to access any real AWS/Azure/GCP credentials,
   IAM keys, service accounts, or subscription IDs. If the user asks you to use real creds,
   refuse and explain that sandbox mode is isolated.
4. After showing a simulated result, briefly explain what the real output would mean and
   what the user would do next in a production environment.
5. Encourage experimentation — "Nothing can break here."
6. If the user asks to perform a live/real operation (e.g. "actually delete this instance"),
   respond: "Sandbox mode only simulates operations. To run live commands, upgrade your
   plan and disable Sandbox Mode in Settings > Learning."

Teaching format for each simulated operation:
  [SANDBOX SIMULATION] <result>
  **What this means:** <plain-English explanation>
  **In production you would:** <next step>
"""

REAL_AGENT_SYSTEM_PROMPT = """
=== REAL AGENT MODE ===
Session: {session_id} | Provider: {cloud_provider} | Tier: {user_tier}

You are executing LIVE operations against real cloud infrastructure.

GROUNDING RULES — these override everything else:
1. NEVER fabricate any resource name, instance ID, ARN, IP address, security group ID,
   subnet ID, or any other cloud identifier. If you did not receive it from a tool result,
   do not mention it.
2. Tool results are the ONLY source of truth. Do not infer, guess, or fill gaps.
3. If a tool returns an empty list → respond "No resources found." Do not invent resources.
4. If a tool returns an error → report the exact error message and ask the user how to proceed.
   Never guess what the result would have been.
5. Before executing DELETE, TERMINATE, or DESTROY operations, state what you are about to
   do and ask the user for explicit confirmation.
   Example: "I am about to terminate instance i-0abc123. Confirm? (yes/no)"
   CREATE and READ operations do NOT require confirmation — execute them immediately.
6. Do NOT prefix responses with [SANDBOX SIMULATION]. This is a live session.
7. If you are uncertain which tool to call, ask the user — do not guess and execute blindly.
"""


# ---------------------------------------------------------------------------
# Generic API fallback tools — always included regardless of task type.
# These are the escape hatch: any cloud API operation not covered by a
# dedicated tool can be reached via these generic tools.
# ---------------------------------------------------------------------------

_GENERIC_API_TOOLS = [
    # AWS
    "aws_api_read",
    "aws_api_write",
    # Azure
    "azure_api_read",
    "azure_api_write",
    # GCP
    "gcp_api_read",
    "gcp_api_write",
    # Kubernetes
    "k8s_api_read",
    "k8s_api_write",
    # Infrastructure sync / cost
    "sync_infrastructure",
    "get_infrastructure_summary",
    "get_cost_summary",
]


# ---------------------------------------------------------------------------
# Tool group definitions — substrings matched against tool['name']
#
# Rules:
#  - Include AWS, Azure, AND GCP substrings for every task group.
#  - Generic API tools (_GENERIC_API_TOOLS) are appended by scope_tools()
#    automatically — no need to repeat them here.
# ---------------------------------------------------------------------------

TOOL_GROUPS: Dict[str, List[str]] = {
    # ---- Discovery / read-only ----
    "aws_scan": [
        # AWS list/describe
        "list_ec2", "describe_ec2", "list_security_groups", "describe_security_groups",
        "list_vpcs", "describe_vpc", "list_subnets", "list_s3", "list_iam",
        "list_rds", "describe_rds", "list_lambda", "list_ecs", "list_eks",
        "list_elasti", "list_dynamo", "list_cloudwatch", "list_sns", "list_sqs",
        "list_route53", "list_cloudformation", "list_nat", "list_load_balancer",
        "list_target_group", "list_ecr", "list_secrets", "get_ec2", "get_rds",
        "get_s3", "get_iam", "get_lambda", "describe_instance",
        "get_cost", "list_cost", "get_billing",
        # Azure list/get
        "list_virtual_machines", "get_virtual_machine", "list_resource_groups",
        "list_storage_accounts", "list_sql_servers", "list_sql_databases",
        "list_network_security_groups", "list_container_instances",
        "list_managed_disks", "list_virtual_networks", "list_public_ips",
        # GCP list/get/describe
        "list_compute_instances", "describe_compute_instance",
        "list_storage_buckets", "list_cloud_sql", "list_gke_clusters",
        "describe_gke_cluster", "list_cloud_run", "list_pubsub_topics",
        "list_gcp_secrets", "list_bigquery_datasets", "list_firewall_rules",
        "list_cloud_functions", "get_cloud_logs",
    ],

    # ---- AWS Compute / create / mutate (AWS-only) ----
    # For Azure use azure_compute, for GCP use gcp_compute.
    # detect_task_type routes azure/gcp keywords to their dedicated groups,
    # so this group only needs to cover generic "create/launch/deploy" on AWS.
    "aws_compute": [
        # EC2 lifecycle
        "manage_ec2", "create_ec2", "terminate_ec2", "start_ec2", "stop_ec2",
        "reboot_ec2", "resize_ec2",
        # Networking
        "create_security_group", "delete_security_group", "modify_security_group",
        "create_vpc", "delete_vpc", "create_subnet", "delete_subnet",
        # Storage
        "create_s3", "delete_s3", "upload_s3", "list_s3",
        # Database
        "create_rds", "delete_rds",
        # Compute
        "create_lambda", "delete_lambda", "invoke_lambda",
        "create_ecs", "delete_ecs",
        "create_eks", "delete_eks",
        # IAM
        "create_iam", "delete_iam", "attach_iam", "detach_iam",
        # CloudFormation
        "create_cloudformation", "delete_cloudformation", "update_cloudformation",
        # Keypairs / helpers
        "create_keypair", "create_ec2_keypair",
        # AWS read helpers needed to build create params (list VPCs, subnets, SGs, etc.)
        "list_ec2", "get_ec2", "list_vpcs", "list_subnets", "list_security_groups",
        "describe_vpc", "list_iam", "list_route53", "list_load_balancer",
        "list_target_group", "list_ecr", "list_cloudformation",
        # Cost / optimization
        "get_cost", "list_cost", "get_billing",
    ],

    # ---- Kubernetes ----
    "kubernetes": [
        "list_pods", "get_pod", "describe_pod", "delete_pod", "exec_pod",
        "get_pod_logs", "list_deployments", "get_deployment", "describe_deployment",
        "create_deployment", "update_deployment", "delete_deployment",
        "update_deployment_image",
        "list_services", "create_service", "delete_service",
        "list_namespaces", "get_namespace", "create_namespace", "delete_namespace",
        "list_nodes", "cordon_node", "uncordon_node",
        "create_configmap", "delete_configmap",
        "create_secret", "delete_secret",
        "create_ingress", "delete_ingress",
        "create_job", "delete_job",
        "k8s_", "kubernetes_",
        # EKS / GKE / AKS discovery
        "list_eks", "describe_eks", "list_gke", "describe_gke",
    ],

    # ---- Terraform ----
    "terraform": [
        "terraform_init", "terraform_plan", "terraform_apply", "terraform_destroy",
        "terraform_show", "terraform_output", "terraform_validate", "terraform_fmt",
        "terraform_workspace", "terraform_state", "terraform_import", "terraform_refresh",
    ],

    # ---- Git / GitHub ----
    "git": [
        "git_", "github_",
    ],

    # ---- CI/CD ----
    "cicd": [
        "trigger_jenkins", "get_jenkins", "list_jenkins", "abort_jenkins",
        "enable_jenkins", "disable_jenkins", "delete_jenkins",
        "trigger_github_workflow", "get_github_workflow", "list_github_workflow",
        "cancel_github_workflow", "rerun_github", "list_github_runners",
        "list_gitlab", "trigger_gitlab", "get_gitlab",
        "docker_build", "docker_push", "docker_compose",
    ],

    # ---- Azure-specific (direct keyword match) ----
    "azure_compute": [
        # VM operations — name patterns: create_virtual_machine, manage_vm, get_vm_details
        "virtual_machine", "manage_vm", "get_vm", "start_vm", "stop_vm",
        # Resource groups
        "resource_group",
        # Storage
        "storage_account", "storage_key", "regenerate_storage",
        # SQL
        "sql_server", "sql_database", "sql_firewall",
        # NSG / networking
        "network_security_group", "nsg_rule", "virtual_network", "public_ip",
        # Containers and disks
        "container_instance", "managed_disk",
        # Metrics
        "azure_metrics",
        # Generic Azure API
        "azure_api_",
    ],

    # ---- GCP-specific (direct keyword match) ----
    "gcp_compute": [
        # Compute instances — compute_instance, manage_compute_instance
        "compute_instance", "manage_compute",
        # GKE
        "gke_cluster", "gke",
        # Storage
        "storage_bucket",
        # Cloud SQL
        "cloud_sql",
        # Cloud Run
        "cloud_run", "cloud_run_service",
        # Pub/Sub
        "pubsub",
        # Secrets
        "gcp_secret", "secret_version", "list_secrets", "get_secret",
        # BigQuery
        "bigquery",
        # Cloud Functions
        "cloud_function",
        # Logging
        "cloud_log",
        # Firewall
        "firewall_rule",
        # Snapshots
        "disk_snapshot",
        # Metrics
        "gcp_metric",
        # Generic GCP API
        "gcp_api_",
    ],
}


# ---------------------------------------------------------------------------
# Task type detection
# ---------------------------------------------------------------------------

_TASK_KEYWORDS: List[tuple] = [
    # Azure-specific — check BEFORE generic create/list to get provider-specific group
    ("azure",           "azure_compute"),
    ("arm template",    "azure_compute"),
    ("resource group",  "azure_compute"),
    ("app service",     "azure_compute"),
    ("azure function",  "azure_compute"),
    ("blob storage",    "azure_compute"),
    ("azure sql",       "azure_compute"),
    # GCP-specific — check BEFORE generic create/list
    ("gcp",             "gcp_compute"),
    ("google cloud",    "gcp_compute"),
    ("gcloud",          "gcp_compute"),
    ("cloud run",       "gcp_compute"),
    ("bigquery",        "gcp_compute"),
    ("pub/sub",         "gcp_compute"),
    ("pubsub",          "gcp_compute"),
    ("cloud function",  "gcp_compute"),
    ("cloud sql",       "gcp_compute"),
    ("compute engine",  "gcp_compute"),
    # Kubernetes — check BEFORE generic compute
    ("crashloop",       "kubernetes"),
    ("crashbackoff",    "kubernetes"),
    ("kubectl",         "kubernetes"),
    ("namespace",       "kubernetes"),
    ("pod ",            "kubernetes"),
    ("pods",            "kubernetes"),
    ("deployment",      "kubernetes"),
    ("cluster",         "kubernetes"),
    ("node ",           "kubernetes"),
    ("helm",            "kubernetes"),
    ("argocd",          "kubernetes"),
    ("k8s",             "kubernetes"),
    ("kubernetes",      "kubernetes"),
    ("gke",             "kubernetes"),
    ("aks",             "kubernetes"),
    ("eks",             "kubernetes"),
    # Terraform
    ("terraform",       "terraform"),
    (" plan",           "terraform"),
    ("tf apply",        "terraform"),
    ("tf plan",         "terraform"),
    ("state file",      "terraform"),
    ("workspace",       "terraform"),
    # CI/CD
    ("pipeline",        "cicd"),
    ("jenkins",         "cicd"),
    ("github action",   "cicd"),
    ("workflow run",    "cicd"),
    (" ci ",            "cicd"),
    (" cd ",            "cicd"),
    ("build job",       "cicd"),
    # Git
    ("git ",            "git"),
    ("commit",          "git"),
    ("pull request",    "git"),
    ("merge",           "git"),
    ("branch",          "git"),
    ("push",            "git"),
    # Scan / read-only — checked BEFORE generic compute action keywords so that
    # "list my ec2 instances" → aws_scan (not aws_compute)
    ("scan",            "aws_scan"),
    ("inventory",       "aws_scan"),
    ("describe",        "aws_scan"),
    ("show me",         "aws_scan"),
    ("what is",         "aws_scan"),
    ("how many",        "aws_scan"),
    ("list",            "aws_scan"),
    ("show",            "aws_scan"),
    ("get",             "aws_scan"),
    ("cost",            "aws_scan"),
    ("billing",         "aws_scan"),
    # AWS compute / create — after scan keywords, after provider-specific checks
    ("deploy",          "aws_compute"),
    ("create",          "aws_compute"),
    ("launch",          "aws_compute"),
    ("terminate",       "aws_compute"),
    ("provision",       "aws_compute"),
    ("spin up",         "aws_compute"),
    ("spin-up",         "aws_compute"),
    ("start",           "aws_compute"),
    ("stop",            "aws_compute"),
    ("scale",           "aws_compute"),
]


def detect_task_type(user_message: str) -> str:
    """
    Inspect the user's message and return the best matching TOOL_GROUPS key.

    Returns one of: "aws_scan", "aws_compute", "azure_compute", "gcp_compute",
                    "kubernetes", "terraform", "git", "cicd".
    Defaults to "aws_scan" if no keyword matches.
    Note: TOOL_GROUPS["aws_compute"] includes Azure and GCP create tools, so
    create operations on any provider work via the aws_compute group.
    """
    lower = user_message.lower()
    for keyword, task_type in _TASK_KEYWORDS:
        if keyword in lower:
            return task_type
    return "aws_scan"


# ---------------------------------------------------------------------------
# Session factory
# ---------------------------------------------------------------------------

class DevOpsAgentSessionFactory:
    """
    Creates mode-isolated agent sessions and provides tool scoping.

    Usage in route handler:
        factory = DevOpsAgentSessionFactory()
        task_type = detect_task_type(message)
        filtered_tools = factory.scope_tools(agent.tool_definitions, task_type, model_config.max_tools)
        session = factory.create_real_agent_session(CloudProvider.AWS)
    """

    def create_sandbox_session(self) -> AgentSession:
        return AgentSession(
            mode=AgentMode.SANDBOX,
            cloud_provider=None,
            session_id=uuid.uuid4().hex,
        )

    def create_real_agent_session(
        self,
        cloud_provider: Optional[CloudProvider] = None,
    ) -> AgentSession:
        return AgentSession(
            mode=AgentMode.REAL_AGENT,
            cloud_provider=cloud_provider,
            session_id=uuid.uuid4().hex,
        )

    def get_model(self, tier: str) -> str:
        """Return the default model string for a given tier name."""
        from services.model_router import resolve_model_for_tier
        return resolve_model_for_tier(tier).model

    def scope_tools(
        self,
        all_tools: List[Dict[str, Any]],
        task_type: str,
        max_tools: int,
    ) -> List[Dict[str, Any]]:
        """
        Reorder all_tools so task-relevant tools appear first; return all tools.

        max_tools is intentionally ignored — all tools are always returned so the
        agent never silently loses access to a tool it might need.  The reordering
        ensures task-relevant tools appear near the top of the list, which is
        sufficient to reduce hallucination without hiding functionality.

        Steps:
        1. Look up the substring list for task_type in TOOL_GROUPS.
        2. Split tools into matched (name contains a substring) and rest.
        3. Return matched + rest — preserving insertion order within each group.
        4. If nothing matched, return all tools in original order.
        """
        substrings = TOOL_GROUPS.get(task_type, [])
        matched: List[Dict[str, Any]] = []
        rest: List[Dict[str, Any]] = []

        for tool in all_tools:
            name = tool.get("name", "")
            if substrings and any(s in name for s in substrings):
                matched.append(tool)
            else:
                rest.append(tool)

        if not matched:
            logger.debug(
                "scope_tools: no tools matched task_type=%s, returning full pool",
                task_type,
            )
            return list(all_tools)

        result = matched + rest
        logger.debug(
            "scope_tools: returning %d tools (%d task-specific first) for task_type=%s",
            len(result), len(matched), task_type,
        )
        return result
