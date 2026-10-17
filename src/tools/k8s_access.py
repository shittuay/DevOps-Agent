"""Which Kubernetes cluster a tool call reaches, and with whose credentials.

Hosted (the default): the requesting user's own EKS clusters, reached with the AWS
account they connected in Settings. The server's own kubeconfig is never read, because
it would hand every user whatever cluster the server itself can reach.

Self-hosted: set K8S_USE_LOCAL_KUBECONFIG=true to use this machine's kubeconfig instead
(the CLI has no signed-in user, so it needs this too).
"""
import base64
import hashlib
import os
import re
import tempfile
import threading
import time
from typing import Dict, List, Optional, Tuple

from kubernetes import client, config

LOCAL_KUBECONFIG_ENV = 'K8S_USE_LOCAL_KUBECONFIG'
TOKEN_TTL_SECONDS = 600  # EKS accepts a token for 15 minutes; refresh well before that
CONTEXT_DESCRIPTION = (
    "Cluster to use: an EKS cluster name, 'region/name' or the cluster ARN. "
    "Optional when your AWS account has one cluster in its default region. "
    "On self-hosted installs using a local kubeconfig, a kubeconfig context name."
)
VIEW_POLICY_ARN = 'arn:aws:eks::aws:cluster-access-policy/AmazonEKSViewPolicy'

_ARN_RE = re.compile(r'^arn:aws[a-z-]*:eks:([a-z0-9-]+):\d{12}:cluster/([A-Za-z0-9][A-Za-z0-9_-]{0,99})$')
_REGION_RE = re.compile(r'^[a-z]{2}(-[a-z]+)+-\d+$')
_NAME_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_-]{0,99}$')
_EKS_HOST_RE = re.compile(r'^https://[a-z0-9.-]+\.eks\.amazonaws\.com(\.cn)?/?$', re.IGNORECASE)

_cache: Dict[Tuple[int, str, str], Tuple[float, str, str, str]] = {}
_cache_lock = threading.Lock()


class ClusterAccessError(Exception):
    """The request can't be tied to a cluster this user is allowed to reach."""


def local_kubeconfig_enabled() -> bool:
    return os.environ.get(LOCAL_KUBECONFIG_ENV, '').strip().lower() in ('1', 'true', 'yes')


def parse_context(context: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """Return (region, cluster name) from 'name', 'region/name' or an EKS cluster ARN."""
    value = (context or '').strip()
    if not value:
        return None, None
    arn = _ARN_RE.match(value)
    if arn:
        return arn.group(1), arn.group(2)
    if '/' in value:
        region, _, name = value.partition('/')
        if _REGION_RE.match(region) and _NAME_RE.match(name):
            return region, name
    elif _NAME_RE.match(value):
        return None, value
    raise ClusterAccessError(
        f"'{value}' is not an EKS cluster. Use the cluster name, 'region/name' "
        "(for example us-west-2/prod) or the cluster ARN.")


def _user_id() -> Optional[int]:
    from .aws_tools import get_current_user_id
    return get_current_user_id()


def _boto(user_id: int, service: str, region: str, **client_kwargs):
    from services.credential_service import get_user_boto_client
    return get_user_boto_client(user_id, service, region, **client_kwargs)


def _default_region(region: Optional[str]) -> str:
    from .aws_tools import _get_effective_region
    return _get_effective_region(region)


def list_user_clusters(region: Optional[str] = None) -> Tuple[str, List[str]]:
    """EKS cluster names in one region of the signed-in user's AWS account."""
    user_id = _require_user()
    region = _default_region(region)
    eks = _boto(user_id, 'eks', region)
    names: List[str] = []
    for page in eks.get_paginator('list_clusters').paginate():
        names.extend(page.get('clusters', []))
    return region, sorted(names)


def resolve_cluster(context: Optional[str]) -> Tuple[str, str]:
    """Pick the (region, name) a call targets; ask the user to choose when it's ambiguous."""
    region, name = parse_context(context)
    if name:
        return _default_region(region), name
    region, names = list_user_clusters(region)
    if len(names) == 1:
        return region, names[0]
    if not names:
        raise ClusterAccessError(
            f"No EKS clusters found in {region} in your connected AWS account. "
            "For a cluster in another region, pass context='<region>/<cluster-name>'.")
    raise ClusterAccessError(
        f"Your AWS account has {len(names)} EKS clusters in {region}: {', '.join(names)}. "
        "Say which one to use (context='<cluster-name>').")


def eks_token(sts_client, cluster_name: str) -> str:
    """The bearer token EKS accepts: a presigned STS GetCallerIdentity URL naming the cluster."""
    def _add_cluster_header(request, **_kwargs):
        request.headers['x-k8s-aws-id'] = cluster_name

    sts_client.meta.events.register('before-sign.sts.GetCallerIdentity', _add_cluster_header)
    try:
        url = sts_client.generate_presigned_url(
            'get_caller_identity', Params={}, ExpiresIn=60, HttpMethod='GET')
    finally:
        sts_client.meta.events.unregister('before-sign.sts.GetCallerIdentity', _add_cluster_header)
    return 'k8s-aws-v1.' + base64.urlsafe_b64encode(url.encode()).decode().rstrip('=')


def _sts_endpoint(region: str) -> str:
    suffix = 'amazonaws.com.cn' if region.startswith('cn-') else 'amazonaws.com'
    return f'https://sts.{region}.{suffix}'


def _ca_file(ca_b64: str) -> str:
    ca = base64.b64decode(ca_b64)
    folder = os.path.join(tempfile.gettempdir(), 'devops-agent-eks-ca')
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, hashlib.sha256(ca).hexdigest() + '.crt')
    if not os.path.exists(path):
        fd, tmp = tempfile.mkstemp(dir=folder)
        with os.fdopen(fd, 'wb') as handle:
            handle.write(ca)
        os.replace(tmp, path)
    return path


def _eks_connection(user_id: int, region: str, name: str) -> Tuple[str, str, str]:
    key = (user_id, region, name)
    now = time.time()
    with _cache_lock:
        cached = _cache.get(key)
        if cached and cached[0] > now:
            return cached[1], cached[2], cached[3]

    eks = _boto(user_id, 'eks', region)
    try:
        cluster = eks.describe_cluster(name=name)['cluster']
    except Exception as exc:
        if 'ResourceNotFoundException' in str(exc) or 'No cluster found' in str(exc):
            raise ClusterAccessError(f"No EKS cluster named '{name}' in {region}.") from exc
        raise
    status = cluster.get('status')
    if status != 'ACTIVE':
        raise ClusterAccessError(f"EKS cluster '{name}' is {status}, not ACTIVE.")
    if cluster.get('resourcesVpcConfig', {}).get('endpointPublicAccess') is False:
        raise ClusterAccessError(
            f"EKS cluster '{name}' only has a private API endpoint, which DevOps Agent can't reach. "
            "Enable public endpoint access (you can limit it to specific IP ranges) to manage it here.")
    host = (cluster.get('endpoint') or '').rstrip('/')
    if not _EKS_HOST_RE.match(host):
        raise ClusterAccessError(f"EKS returned an unexpected API endpoint for '{name}'.")
    ca_data = cluster.get('certificateAuthority', {}).get('data')
    if not ca_data:
        raise ClusterAccessError(f"EKS cluster '{name}' has no certificate authority yet.")

    sts = _boto(user_id, 'sts', region, endpoint_url=_sts_endpoint(region))
    token = eks_token(sts, name)
    ca_path = _ca_file(ca_data)
    with _cache_lock:
        _cache[key] = (now + TOKEN_TTL_SECONDS, host, ca_path, token)
    return host, ca_path, token


def _require_user() -> int:
    user_id = _user_id()
    if user_id is None:
        raise ClusterAccessError(
            "Kubernetes tools need a signed-in user with a connected AWS account, and reach that "
            "account's EKS clusters. Self-hosted installs can set K8S_USE_LOCAL_KUBECONFIG=true "
            "to use this machine's kubeconfig instead.")
    return user_id


def api_client(context: Optional[str] = None) -> client.ApiClient:
    """A Kubernetes API client for this call only; never touches the process-wide default."""
    if local_kubeconfig_enabled():
        return config.new_client_from_config(context=context or None)
    user_id = _require_user()
    region, name = resolve_cluster(context)
    host, ca_path, token = _eks_connection(user_id, region, name)
    cfg = client.Configuration()
    cfg.host = host
    cfg.ssl_ca_cert = ca_path
    cfg.verify_ssl = True
    cfg.api_key = {'authorization': token}
    cfg.api_key_prefix = {'authorization': 'Bearer'}
    return client.ApiClient(cfg)


def _principal_arn(user_id: int, region: str) -> Optional[str]:
    """The IAM role or user the connected AWS account signs in as, for an access entry."""
    try:
        arn = _boto(user_id, 'sts', region).get_caller_identity()['Arn']
    except Exception:
        return None
    match = re.match(r'^arn:(aws[a-z-]*):sts::(\d{12}):assumed-role/([^/]+)/', arn)
    if match:
        return f'arn:{match.group(1)}:iam::{match.group(2)}:role/{match.group(3)}'
    return arn


def access_hint(status_code: Optional[int], context: Optional[str] = None) -> Optional[str]:
    """Plain next step when EKS refuses DevOps Agent (no access entry, or too little access)."""
    if status_code not in (401, 403) or local_kubeconfig_enabled():
        return None
    user_id = _user_id()
    if user_id is None:
        return None
    try:
        region, name = resolve_cluster(context)
    except Exception:
        region, name = _default_region(None), '<cluster>'
    principal = _principal_arn(user_id, region) or 'the IAM role DevOps Agent uses'
    if status_code == 401:
        return (
            f"EKS cluster '{name}' doesn't let {principal} in yet. Give it access with an EKS access "
            f"entry: create_eks_access_entry (cluster_name='{name}', principal_arn='{principal}'), then "
            f"associate_eks_access_policy with {VIEW_POLICY_ARN} for read-only access, or add the same "
            "entry in the EKS console under Access. The cluster's authentication mode must include API.")
    return (
        f"{principal} can reach EKS cluster '{name}' but isn't allowed to do this. Its access policy "
        "(for example AmazonEKSViewPolicy) doesn't cover this action; associate a broader policy only "
        "if you want DevOps Agent to make this change.")
