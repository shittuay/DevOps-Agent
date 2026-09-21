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
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

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
    'aws.common': ('resource', 'inventory', 'tagged', 'tagging', 'everything i have'),
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
    'verification': ('reachable', 'responding', 'serving', 'web server', 'website',
                     'port 80', 'port 443', 'smoke test', 'health check', 'healthcheck',
                     'health endpoint', 'is it up', 'is it live', 'is it serving',
                     'verify the deployment', 'confirm it works'),
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
    if name in _VERIFICATION_TOOL_NAMES:
        return 'verification'
    if module_category == 'aws':
        name_l = (name or '').lower()
        for token, category in AWS_SERVICE_TOKENS:
            if token in name_l:
                return category
        return 'aws.other'
    return module_category


# Tools whose home module doesn't match their job: run_smoke_test lives in
# cicd_tools but is a generic HTTP health check, needed on any "is it serving"
# task, not just pipeline work.
_VERIFICATION_TOOL_NAMES = frozenset({'run_smoke_test', 'http_check', 'tcp_check'})


# Meta-tools callable on every turn unconditionally: search_tools is the
# universal tool-recovery path; record_state_override lets the model honour a
# user's console evidence against a stale verification result on any turn (the
# dispute can be about something verified turns ago); http_check / tcp_check are
# cheap read-only SSRF-guarded probes the model needs to verify anything it just
# built ("is nginx serving on port 80") regardless of what the turn is about.
ALWAYS_TOOL_NAMES = frozenset({SEARCH_TOOL_NAME, 'record_state_override', 'http_check', 'tcp_check'})

# The provider-generic API tools the system prompt tells the model to fall
# back on ("NEVER say 'I don't have a tool'"), keyed by the provider they
# belong to. Offered only for providers this turn's matched categories
# actually implicate (see _hatch_providers_for) — NOT unconditionally on
# every turn. An earlier version of this fix made all eight always-present
# regardless of relevance, which meant a plain "create an ec2 instance"
# request always carried GCP/Azure/Kubernetes escape hatches too; a model
# struggling to find the right AWS tool reached for whichever generic hatch
# was easiest to grab instead. Confirmed live 2026-09-02: k8s_api_read
# executed for a "create an ec2 instance using ubuntu" request purely
# because it was always offered, though nothing about the request implicated
# Kubernetes. See CLAUDE_RUNBOOK.md.
HATCH_PAIRS_BY_PROVIDER: Dict[str, Tuple[str, str]] = {
    'aws': ('aws_api_read', 'aws_api_write'),
    'azure': ('azure_api_read', 'azure_api_write'),
    'gcp': ('gcp_api_read', 'gcp_api_write'),
    'kubernetes': ('k8s_api_read', 'k8s_api_write'),
}

# Provider-agnostic nouns -> categories that could satisfy them, in preference
# order. Weaker than CATEGORY_KEYWORDS (ranked below explicit matches) and, when
# the caller knows which cloud accounts are connected, filtered to those
# providers. Explicit keyword matches are never filtered by connected providers.
GENERIC_NOUNS: Dict[str, Tuple[str, ...]] = {
    'server': ('aws.ec2', 'azure', 'gcp'),
    'vm': ('aws.ec2', 'azure', 'gcp'),
    'virtual machine': ('aws.ec2', 'azure', 'gcp'),
    'database': ('aws.rds', 'aws.dynamodb', 'azure', 'gcp'),
    'db': ('aws.rds', 'aws.dynamodb', 'azure', 'gcp'),
    'container': ('kubernetes', 'aws.ecs', 'aws.eks', 'azure', 'gcp', 'docker'),
    'cluster': ('kubernetes', 'aws.eks', 'aws.ecs', 'gcp', 'azure'),
    'log': ('aws.cloudwatch', 'kubernetes', 'gcp', 'azure'),
    'storage': ('aws.s3', 'aws.efs', 'azure', 'gcp'),
    'firewall': ('aws.vpc', 'azure', 'gcp'),
}

# How many prior user messages inform selection. Follow-ups ("yes go ahead",
# "now delete it") carry no keywords of their own; without this they fell back
# to the full catalog on every turn.
HISTORY_WINDOW = 6

_AWS_SEED_CATEGORIES = ('aws.ec2', 'aws.s3', 'aws.iam', 'aws.vpc')

# "list everything in us-east-1" names no service but is unambiguously an AWS
# query. Without this it matched nothing and fell back to the full catalog.
_AWS_REGION_RE = re.compile(
    r'\b(?:us|eu|ap|sa|ca|me|af|il)-(?:east|west|north|south|central|northeast|'
    r'southeast|northwest|southwest)-\d\b'
)


def _mentions_aws(message: str) -> bool:
    return 'aws' in message or bool(_AWS_REGION_RE.search(message))


def _category_score(category: str, message: str) -> int:
    """Number of the category's keywords present in the message."""
    return sum(1 for kw in CATEGORY_KEYWORDS.get(category, ()) if kw in message)


def _explicit_matches(message: str) -> Dict[str, int]:
    """Categories explicitly named in ``message`` (lowercased) -> keyword score."""
    matched = {}
    for cat in CATEGORY_KEYWORDS:
        score = _category_score(cat, message)
        if score:
            matched[cat] = score
    return matched


def _generic_matches(message: str) -> List[str]:
    """Categories implied by provider-agnostic nouns, in preference order."""
    out: List[str] = []
    for noun, cats in GENERIC_NOUNS.items():
        if re.search(r'\b' + re.escape(noun) + r's?\b', message):
            for cat in cats:
                if cat not in out:
                    out.append(cat)
    return out


def provider_of_category(category: str) -> Optional[str]:
    """``aws.ec2`` -> ``aws``; ``azure``/``gcp`` -> themselves; else ``None``."""
    if category.startswith('aws.'):
        return 'aws'
    if category in ('azure', 'gcp'):
        return category
    return None


def _hatch_provider_of(category: str) -> Optional[str]:
    """Like ``provider_of_category`` but also resolves ``kubernetes``.

    Kept separate from ``provider_of_category`` deliberately: that function
    also drives the connected-providers filter for generic nouns, and
    ``connected_providers`` (from ``get_user_configured_providers``) has no
    notion of a "connected" Kubernetes cluster — making it kubernetes-aware
    there would silently drop Kubernetes from noun matches for every
    non-sandbox user.
    """
    if category == 'kubernetes':
        return 'kubernetes'
    return provider_of_category(category)


def _hatch_providers_for(categories: Iterable[str]) -> set:
    """Which providers' generic API escape hatches this turn should carry,
    given every category matched by the current message, generic nouns, and
    history."""
    return {p for c in categories if (p := _hatch_provider_of(c)) is not None}


def select_tool_definitions(
    tool_definitions: List[Dict[str, Any]],
    tool_categories: Dict[str, str],
    user_message: str,
    max_tools: Optional[int] = None,
    history_messages: Optional[List[str]] = None,
    connected_providers: Optional[Dict[str, bool]] = None,
) -> Optional[List[Dict[str, Any]]]:
    """Select a relevant subset of tool definitions for a message.

    Signals, strongest first:
      1. categories whose keywords appear in ``user_message``;
      2. categories implied by provider-agnostic nouns ("server", "database"),
         filtered to ``connected_providers`` when given;
      3. categories matched by the last ``HISTORY_WINDOW`` ``history_messages``
         (prior user turns), so follow-ups keep the working tool set.

    Returns ``None`` when no signal matches (caller should then use the full
    tool list). Otherwise returns a filtered list (original order preserved) that
    always includes ALWAYS_CATEGORIES, ``search_tools``, and the provider-generic
    API escape hatches for whichever providers this turn actually implicates
    (see HATCH_PAIRS_BY_PROVIDER) — not unconditionally for every provider.

    ``max_tools`` is honored greedily, with one exception: every category tied
    for the top explicit score is always kept. When the message names two
    things equally ("pods in my eks cluster" -> kubernetes + aws.eks) dropping
    either hides exactly the tool the user asked for.
    """
    message = (user_message or '').lower()

    current = _explicit_matches(message)

    generic = _generic_matches(message)
    # General AWS mention (or a bare region) with no specific service named:
    # seed the common services. This is a guess, so it rides in the greedy tier
    # rather than the cap-exempt one — four seeded categories tied for "top"
    # would otherwise push a plain "what is my aws bill" past max_tools.
    if _mentions_aws(message) and not any(
        c.startswith('aws.') and c != AWS_COMMON_CATEGORY for c in current
    ):
        for cat in _AWS_SEED_CATEGORIES:
            if cat not in generic:
                generic.append(cat)
    generic = [c for c in generic if c not in current]
    if connected_providers is not None:
        generic = [
            c for c in generic
            if provider_of_category(c) is None or connected_providers.get(provider_of_category(c))
        ]

    history: List[str] = []
    for prior in (history_messages or [])[-HISTORY_WINDOW:]:
        for cat in _explicit_matches((prior or '').lower()):
            if cat not in current and cat not in generic and cat not in history:
                history.append(cat)

    if not current and not generic and not history:
        return None

    base = set(ALWAYS_CATEGORIES)
    all_matched = [*current, *generic, *history]
    if any(c.startswith('aws.') for c in all_matched):
        base.add(AWS_COMMON_CATEGORY)

    # Scope the provider-generic escape hatches to providers this turn's
    # matched categories actually implicate — see HATCH_PAIRS_BY_PROVIDER.
    always_tool_names = set(ALWAYS_TOOL_NAMES)
    for provider in _hatch_providers_for(all_matched):
        always_tool_names.update(HATCH_PAIRS_BY_PROVIDER[provider])

    def _subset_for(cats: set) -> List[Dict[str, Any]]:
        return [
            td for td in tool_definitions
            if tool_categories.get(td['name']) in cats or td['name'] in always_tool_names
        ]

    ranked_current = sorted(current, key=lambda c: current[c], reverse=True)
    top_score = current[ranked_current[0]] if ranked_current else 0
    keep = set(base) | {c for c in ranked_current if current[c] == top_score}
    ordered = [c for c in ranked_current if c not in keep] + generic + history
    for cat in ordered:
        candidate = keep | {cat}
        if not max_tools or len(_subset_for(candidate)) <= max_tools:
            keep = candidate

    return _subset_for(keep)
