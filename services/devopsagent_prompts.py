"""
DevOps Agent — Mode-Isolated System Prompts & Session Factory

Provides hard-separated system prompts for SANDBOX vs REAL_AGENT modes so Kimi K2.5
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
   plan and disable Sandbox Mode in Settings > Preferences."

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
5. Before executing any operation that creates, modifies, deletes, or mutates infrastructure,
   state what you are about to do and ask the user for explicit confirmation.
   Example: "I am about to terminate instance i-0abc123. Confirm? (yes/no)"
6. Do NOT prefix responses with [SANDBOX SIMULATION]. This is a live session.
7. If you are uncertain which tool to call, ask the user — do not guess and execute blindly.
"""


# ---------------------------------------------------------------------------
# Tool group definitions — substrings matched against tool['name']
# ---------------------------------------------------------------------------

TOOL_GROUPS: Dict[str, List[str]] = {
    "aws_scan": [
        "list_ec2", "describe_ec2", "list_security_groups", "describe_security_groups",
        "list_vpcs", "describe_vpc", "list_subnets", "list_s3", "list_iam",
        "list_rds", "describe_rds", "list_lambda", "list_ecs", "list_eks",
        "list_elasti", "list_dynamo", "list_cloudwatch", "list_sns", "list_sqs",
        "list_route53", "list_cloudformation", "list_nat", "list_load_balancer",
        "list_target_group", "list_ecr", "list_secrets", "get_ec2", "get_rds",
        "get_s3", "get_iam", "get_lambda", "describe_instance",
        "get_cost", "list_cost", "get_billing",
    ],
    "aws_compute": [
        "manage_ec2", "create_ec2", "terminate_ec2", "start_ec2", "stop_ec2",
        "reboot_ec2", "resize_ec2", "create_security_group", "delete_security_group",
        "create_vpc", "delete_vpc", "create_subnet", "delete_subnet",
        "create_s3", "delete_s3", "upload_s3", "create_rds", "delete_rds",
        "create_lambda", "delete_lambda", "invoke_lambda",
        "create_ecs", "delete_ecs", "create_eks", "delete_eks",
        "create_iam", "delete_iam", "attach_iam", "detach_iam",
        "create_cloudformation", "delete_cloudformation", "update_cloudformation",
    ],
    "kubernetes": [
        "list_pods", "get_pod", "describe_pod", "delete_pod", "exec_pod",
        "get_pod_logs", "list_deployments", "get_deployment", "describe_deployment",
        "create_deployment", "update_deployment", "delete_deployment",
        "list_services", "create_service", "delete_service",
        "list_namespaces", "create_namespace", "delete_namespace",
        "list_nodes", "cordon_node", "uncordon_node",
        "create_configmap", "delete_configmap",
        "create_secret", "delete_secret",
        "create_ingress", "delete_ingress",
        "create_job", "delete_job",
        "k8s_", "kubernetes_",
    ],
    "terraform": [
        "terraform_init", "terraform_plan", "terraform_apply", "terraform_destroy",
        "terraform_show", "terraform_output", "terraform_validate", "terraform_fmt",
        "terraform_workspace", "terraform_state", "terraform_import", "terraform_refresh",
    ],
    "git": [
        "git_", "github_",
    ],
    "cicd": [
        "trigger_jenkins", "get_jenkins", "list_jenkins", "abort_jenkins",
        "enable_jenkins", "disable_jenkins", "delete_jenkins",
        "trigger_github_workflow", "get_github_workflow", "list_github_workflow",
        "cancel_github_workflow", "rerun_github", "list_github_runners",
        "list_gitlab", "trigger_gitlab", "get_gitlab",
        "docker_build", "docker_push", "docker_compose",
    ],
}


# ---------------------------------------------------------------------------
# Task type detection
# ---------------------------------------------------------------------------

_TASK_KEYWORDS: List[tuple[str, str]] = [
    # (keyword, task_type)  — checked in order; first match wins
    ("scan",            "aws_scan"),
    ("inventory",       "aws_scan"),
    ("security group",  "aws_scan"),
    ("describe",        "aws_scan"),
    ("show me",         "aws_scan"),
    ("what is",         "aws_scan"),
    ("how many",        "aws_scan"),
    ("crashloop",       "kubernetes"),
    ("crashbackoff",    "kubernetes"),
    ("kubectl",         "kubernetes"),
    ("namespace",       "kubernetes"),
    ("pod ",            "kubernetes"),
    ("pods",            "kubernetes"),
    ("deployment",      "kubernetes"),
    ("cluster",         "kubernetes"),
    ("node ",           "kubernetes"),
    ("terraform",       "terraform"),
    (" plan",           "terraform"),
    ("tf apply",        "terraform"),
    ("tf plan",         "terraform"),
    ("state file",      "terraform"),
    ("workspace",       "terraform"),
    ("pipeline",        "cicd"),
    ("jenkins",         "cicd"),
    ("github action",   "cicd"),
    ("workflow run",    "cicd"),
    (" ci ",            "cicd"),
    (" cd ",            "cicd"),
    ("build job",       "cicd"),
    ("git ",            "git"),
    ("commit",          "git"),
    ("pull request",    "git"),
    ("merge",           "git"),
    ("branch",          "git"),
    ("push",            "git"),
    ("deploy",          "aws_compute"),
    ("create",          "aws_compute"),
    ("launch",          "aws_compute"),
    ("terminate",       "aws_compute"),
    ("provision",       "aws_compute"),
    ("start",           "aws_compute"),
    ("stop",            "aws_compute"),
    ("scale",           "aws_compute"),
    ("list",            "aws_scan"),
    ("show",            "aws_scan"),
    ("get",             "aws_scan"),
    ("cost",            "aws_scan"),
    ("billing",         "aws_scan"),
]


def detect_task_type(user_message: str) -> str:
    """
    Inspect the user's message and return the best matching TOOL_GROUPS key.

    Returns one of: "aws_scan", "aws_compute", "kubernetes", "terraform", "git", "cicd".
    Defaults to "aws_scan" if no keyword matches.
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
        Filter all_tools down to those relevant to task_type, then cap at max_tools.

        Steps:
        1. Look up the substring list for task_type in TOOL_GROUPS.
        2. Keep tools whose 'name' contains any listed substring.
        3. Truncate to max_tools if needed.
        4. If nothing matched, fall back to the first max_tools tools from all_tools.
        """
        substrings = TOOL_GROUPS.get(task_type, [])
        filtered: List[Dict[str, Any]] = []

        if substrings:
            for tool in all_tools:
                name = tool.get("name", "")
                if any(s in name for s in substrings):
                    filtered.append(tool)

        if not filtered:
            logger.debug(
                "scope_tools: no tools matched task_type=%s, falling back to first %d tools",
                task_type, max_tools,
            )
            filtered = list(all_tools)

        if len(filtered) > max_tools:
            logger.debug(
                "scope_tools: trimming %d matched tools to max_tools=%d for task_type=%s",
                len(filtered), max_tools, task_type,
            )
            filtered = filtered[:max_tools]

        return filtered
