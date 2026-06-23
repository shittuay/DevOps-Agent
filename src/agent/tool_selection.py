"""
Progressive tool loading (the "ToolSearch" pattern).

The agent registers ~745 tools. Sending every schema on every request wastes
tokens and degrades tool selection. These pure functions classify each tool into
a category and select a relevant subset based on the user's message, honoring the
per-tier ``max_tools`` cap. The logic is intentionally side-effect free so it can
be unit-tested without instantiating the agent or mocking an LLM client.

Safety contract:
- When the message matches no category, ``select_tool_definitions`` returns
  ``None`` — the caller then uses the full tool list (never hide tools when
  unsure).
- ``search_tools`` is always retained so the model can recover any tool at runtime.
"""
from typing import Any, Dict, List, Optional, Tuple

# Always available regardless of message content.
ALWAYS_CATEGORIES = ('command', 'devops_operations')
SEARCH_TOOL_NAME = 'search_tools'

# AWS service tokens checked (in order) against the tool NAME. Tool names carry
# the service token (e.g. ``terminate_ec2_instance`` -> ``aws.ec2``). First match
# wins, so order matters: database/networking tokens precede compute so shared
# words (e.g. "snapshot") resolve to the more specific service.
AWS_SERVICE_TOKENS: Tuple[Tuple[str, str], ...] = (
    # cross-cutting utilities — travel with any AWS query (see select logic)
    ('aws_api', 'aws.common'),
    ('resource_inventory', 'aws.common'),
    ('resources_by_tag', 'aws.common'),
    ('resource_group', 'aws.common'),
    ('add_tags', 'aws.common'),
    ('remove_tags', 'aws.common'),
    ('_tags', 'aws.common'),
    # identity
    ('iam', 'aws.iam'),
    ('access_key', 'aws.iam'),
    # databases (before compute so "snapshot"/"cluster" resolve here first)
    ('aurora', 'aws.rds'),
    ('db_parameter', 'aws.rds'),
    ('rds', 'aws.rds'),
    ('dynamodb', 'aws.dynamodb'),
    # networking (VPC family) — before generic compute
    ('route53', 'aws.route53'),
    ('nat_gateway', 'aws.vpc'),
    ('internet_gateway', 'aws.vpc'),
    ('route_table', 'aws.vpc'),
    ('replace_route', 'aws.vpc'),
    ('add_route', 'aws.vpc'),
    ('delete_route', 'aws.vpc'),
    ('network_acl', 'aws.vpc'),
    ('nacl', 'aws.vpc'),
    ('subnet', 'aws.vpc'),
    ('security_group', 'aws.vpc'),
    ('elastic_ip', 'aws.vpc'),
    ('eni', 'aws.vpc'),
    ('vpc', 'aws.vpc'),
    # load balancing
    ('load_balancer', 'aws.elb'),
    ('target_group', 'aws.elb'),
    ('target', 'aws.elb'),
    ('listener', 'aws.elb'),
    ('_elb', 'aws.elb'),
    ('_alb', 'aws.elb'),
    # compute (EC2 family)
    ('ebs', 'aws.ec2'),
    ('volume', 'aws.ec2'),
    ('snapshot', 'aws.ec2'),
    ('ami', 'aws.ec2'),
    ('launch_template', 'aws.ec2'),
    ('auto_scaling', 'aws.ec2'),
    ('autoscaling', 'aws.ec2'),
    ('scaling_policy', 'aws.ec2'),
    ('spot', 'aws.ec2'),
    ('keypair', 'aws.ec2'),
    ('ec2', 'aws.ec2'),
    # containers / registry
    ('eks', 'aws.eks'),
    ('ecs', 'aws.ecs'),
    ('ecr', 'aws.ecr'),
    # serverless / app
    ('lambda', 'aws.lambda'),
    ('step_function', 'aws.stepfunctions'),
    ('api_gateway', 'aws.apigateway'),
    # storage
    ('s3', 'aws.s3'),
    ('efs', 'aws.efs'),
    # messaging
    ('sns', 'aws.messaging'),
    ('sqs', 'aws.messaging'),
    # observability
    ('cloudwatch', 'aws.cloudwatch'),
    ('cloudtrail', 'aws.cloudtrail'),
    ('xray', 'aws.cloudwatch'),
    # iac / delivery / caching / streaming
    ('cloudformation', 'aws.cloudformation'),
    ('cloudfront', 'aws.cloudfront'),
    ('elasticache', 'aws.elasticache'),
    ('eventbridge', 'aws.events'),
    ('kinesis', 'aws.kinesis'),
    ('secret', 'aws.secrets'),
    ('ssm', 'aws.ssm'),
    ('service_quota', 'aws.quota'),
)

# AWS utility categories that should accompany any AWS-service query (generic
# API access, tagging, inventory) rather than being matched on their own.
AWS_COMMON_CATEGORY = 'aws.common'

# Message keyword -> category. Categories must match what ``classify_tool``
# produces. Generous overlap is intentional: over-including a category is safe,
# hiding a needed tool is not. Seeded from the proven signals in
# ``core._compute_swarm_agents`` and ``core._TOOL_SIGNAL_RE``.
CATEGORY_KEYWORDS: Dict[str, Tuple[str, ...]] = {
    'aws.ec2': ('ec2', 'instance', 'ami', 'keypair', 'key pair', 'ebs', 'volume',
                'snapshot', 'autoscaling', 'auto scaling', 'launch template', 'spot'),
    'aws.vpc': ('vpc', 'subnet', 'security group', 'nat gateway', 'route table',
                'network acl', 'elastic ip', 'internet gateway', 'eni'),
    'aws.s3': ('s3', 'bucket', 'object storage'),
    'aws.iam': ('iam', 'role', 'policy', 'policies', 'permission', 'least privilege'),
    'aws.rds': ('rds', 'database', 'aurora', 'postgres', 'mysql'),
    'aws.lambda': ('lambda', 'function', 'serverless'),
    'aws.eks': ('eks',),
    'aws.ecs': ('ecs', 'fargate', 'task definition'),
    'aws.ecr': ('ecr', 'container registry'),
    'aws.dynamodb': ('dynamodb', 'dynamo'),
    'aws.cloudwatch': ('cloudwatch', 'metric', 'log group', 'alarm'),
    'aws.cloudformation': ('cloudformation', 'cfn', 'stack'),
    'aws.elasticache': ('elasticache', 'redis', 'memcached'),
    'aws.efs': ('efs', 'elastic file'),
    'aws.events': ('eventbridge', 'event rule'),
    'aws.kinesis': ('kinesis', 'stream'),
    'aws.secrets': ('secret', 'secrets manager'),
    'aws.ssm': ('ssm', 'parameter store', 'systems manager'),
    'aws.messaging': ('sns', 'sqs', 'queue', 'topic', 'notification'),
    'aws.route53': ('route53', 'route 53', 'dns', 'hosted zone'),
    'aws.elb': ('load balancer', 'elb', 'alb', 'nlb', 'target group', 'listener'),
    'aws.cloudfront': ('cloudfront', 'cdn', 'distribution'),
    'aws.cloudtrail': ('cloudtrail', 'audit trail'),
    'aws.apigateway': ('api gateway', 'apigateway'),
    'aws.stepfunctions': ('step function', 'state machine'),
    'aws.quota': ('service quota', 'quota', 'limit increase'),
    'kubernetes': ('pod', 'kubectl', 'namespace', 'deployment', 'k8s', 'kubernetes',
                   'node', 'ingress', 'configmap', 'cordon', 'crashloop'),
    'azure': ('azure', 'blob', 'cosmos', 'nsg', 'vnet', 'az vm', 'resource group'),
    'gcp': ('gcp', 'gke', 'gcs', 'bigquery', 'cloud run', 'pub/sub', 'pubsub',
            'firestore', 'compute instance', 'google cloud'),
    'terraform': ('terraform', 'tfstate', 'tf plan', 'tf apply', 'hcl', 'workspace', 'tfvars'),
    'docker': ('docker', 'container', 'image', 'compose', 'dockerfile'),
    'git': ('git ', 'commit', 'branch', 'merge', 'rebase', 'stash', 'cherry-pick', 'clone'),
    'github': ('github', 'pull request', ' pr ', 'workflow', 'github actions', 'issue'),
    'cicd': ('jenkins', 'pipeline', 'build job'),
    'sonarqube': ('sonar', 'quality gate', 'code smell'),
    'nexus': ('nexus', 'artifact repo', 'repository manager'),
    'ansible': ('ansible', 'playbook', 'inventory', 'galaxy'),
    'monitoring': ('prometheus', 'datadog', 'grafana', 'dashboard'),
    'alerting': ('pagerduty', 'opsgenie', 'on-call', 'oncall', 'alert', 'incident'),
    'pentest': ('nmap', 'nikto', 'sqlmap', 'zap', 'pentest', 'vulnerability', 'security scan'),
}


def module_category_from_name(module_name: str) -> str:
    """Derive a base category from a tools module's ``__name__``.

    ``src.tools.aws_tools`` -> ``aws``; ``kubernetes_tools`` -> ``kubernetes``.
    """
    base = (module_name or '').rsplit('.', 1)[-1]
    if base.endswith('_tools'):
        base = base[: -len('_tools')]
    return base or 'other'


def classify_tool(name: str, module_category: str) -> str:
    """Classify a tool into a selection category.

    AWS tools are classified at the service level (``aws.ec2``, ``aws.s3``, ...)
    so a single-service query selects a tight subset instead of all ~351 AWS
    tools. Non-AWS tools fall back to their module category.
    """
    if module_category == 'aws':
        name_l = (name or '').lower()
        for token, category in AWS_SERVICE_TOKENS:
            if token in name_l:
                return category
        return 'aws.other'
    return module_category


def _category_score(category: str, message: str) -> int:
    """Number of the category's keywords present in the message."""
    return sum(1 for kw in CATEGORY_KEYWORDS.get(category, ()) if kw in message)


def select_tool_definitions(
    tool_definitions: List[Dict[str, Any]],
    tool_categories: Dict[str, str],
    user_message: str,
    max_tools: Optional[int] = None,
) -> Optional[List[Dict[str, Any]]]:
    """Select a relevant subset of tool definitions for a message.

    Returns ``None`` when the message matches no category (caller should then use
    the full tool list). Otherwise returns a filtered list (original order
    preserved) that always includes the ALWAYS_CATEGORIES and ``search_tools``.
    """
    message = (user_message or '').lower()

    matched = {cat for cat in CATEGORY_KEYWORDS if _category_score(cat, message) > 0}

    # General AWS mention with no specific service -> seed the common services.
    if 'aws' in message and not any(c.startswith('aws.') for c in matched):
        matched.update({'aws.ec2', 'aws.s3', 'aws.iam', 'aws.vpc'})

    if not matched:
        return None

    # Generic AWS utilities (api/tags/inventory) ride along with any AWS query.
    base = set(ALWAYS_CATEGORIES)
    if any(c.startswith('aws.') for c in matched):
        base.add(AWS_COMMON_CATEGORY)

    keep = base | matched

    def _subset_for(cats: set) -> List[Dict[str, Any]]:
        return [
            td for td in tool_definitions
            if tool_categories.get(td['name']) in cats or td['name'] == SEARCH_TOOL_NAME
        ]

    subset = _subset_for(keep)

    # Enforce the max_tools cap. Always keep the base categories + the top-scored
    # matched category (so the user's primary target is never dropped), then
    # greedily add the rest while staying under the cap.
    if max_tools and len(subset) > max_tools:
        ranked = sorted(matched, key=lambda c: _category_score(c, message), reverse=True)
        keep = set(base)
        if ranked:
            keep.add(ranked[0])
        for cat in ranked[1:]:
            if len(_subset_for(keep | {cat})) <= max_tools:
                keep.add(cat)
        subset = _subset_for(keep)

    return subset
