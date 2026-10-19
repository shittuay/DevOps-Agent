"""Turn an AWS "access denied" into a permission request the account owner approves.

When an AWS tool fails because the customer's IAM role (or user) lacks a permission,
the agent works out the missing action, writes the smallest policy that allows it,
and files an approval request ("To do this I need ec2:RunInstances. Add it?"). On a
yes it is applied one of two ways (owner decision, 2026-10-15):

- **manual** (always available): the owner adds the policy themselves (console steps
  or one AWS CLI command shown on the card), then confirms; the agent retries.
- **self** (opt-in, role ARN only): the customer launched the CloudFormation template
  with AllowSelfGrant=Yes, which lets the role edit only its own inline policy and
  caps it with a permissions boundary they control. The agent adds the policy and
  retries. AWS enforces the boundary, so the agent can never grant itself more.

The request is an ordinary ApprovalRequest with tool_name PERMISSION_TOOL, which is
never registered as an agent tool: the model cannot ask for a permission directly;
only a real AccessDenied from AWS creates one.
"""
import json
import logging
import re
import time
from datetime import timedelta
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

PERMISSION_TOOL = 'grant_aws_permission'
GRANTED_POLICY_NAME = 'DevOpsAgentGrantedPermissions'

DENIED_CODES = {
    'AccessDenied', 'AccessDeniedException', 'UnauthorizedOperation',
    'UnauthorizedAccess', 'AuthorizationError', 'AuthorizationErrorException',
    'Forbidden', 'NotAuthorized',
}

_NOT_AUTHORIZED = re.compile(
    r'(?:User|Principal):\s*(arn:aws[\w-]*:(?:sts|iam)::\d{12}:\S+?)\s+is not authorized to perform:\s*'
    r'([a-z0-9-]+:[A-Za-z0-9]+)(?:\s+on resource:\s*"?(arn:[^\s"]+|\*)"?)?',
    re.IGNORECASE,
)
_OPERATION = re.compile(r'when calling the (\w+) operation')
_CODE = re.compile(r'An error occurred \((\w+)\)')

# Actions the agent never grants itself (option B), however the request reads. The
# owner can still add them by hand (option A) after seeing a warning.
SENSITIVE_PREFIXES = ('iam:', 'organizations:', 'sts:', 'account:', 'kms:', 'billing:',
                      'aws-portal:', 'sso:', 'identitystore:')
SENSITIVE_ACTIONS = {'secretsmanager:GetSecretValue', 'ssm:GetParameter', 'ssm:GetParameters',
                     'ssm:GetParametersByPath', 'lambda:GetFunction', 's3:GetObject'}

# Tool category (src/agent/tool_selection.py) -> IAM service prefix, used only when
# AWS's message doesn't name the action itself.
_CATEGORY_PREFIX = {
    'aws.rds': 'rds', 'aws.dynamodb': 'dynamodb', 'aws.route53': 'route53', 'aws.vpc': 'ec2',
    'aws.ec2': 'ec2', 'aws.elb': 'elasticloadbalancing', 'aws.eks': 'eks', 'aws.ecs': 'ecs',
    'aws.ecr': 'ecr', 'aws.lambda': 'lambda', 'aws.stepfunctions': 'states',
    'aws.apigateway': 'apigateway', 'aws.s3': 's3', 'aws.iam': 'iam',
}
# boto3 client name -> IAM prefix where they differ (for aws_api_read / aws_api_write).
_CLIENT_PREFIX = {'elbv2': 'elasticloadbalancing', 'elb': 'elasticloadbalancing',
                  'stepfunctions': 'states', 'logs': 'logs', 'events': 'events',
                  'apigatewayv2': 'apigateway', 'es': 'es', 'opensearch': 'es'}
# S3 API operations whose IAM action has a different name.
_S3_ACTION = {'HeadBucket': 'ListBucket', 'ListObjects': 'ListBucket', 'ListObjectsV2': 'ListBucket',
              'ListBuckets': 'ListAllMyBuckets', 'HeadObject': 'GetObject',
              'DeleteObjects': 'DeleteObject', 'GetBucketEncryption': 'GetEncryptionConfiguration',
              'PutBucketEncryption': 'PutEncryptionConfiguration',
              'GetPublicAccessBlock': 'GetBucketPublicAccessBlock',
              'PutPublicAccessBlock': 'PutBucketPublicAccessBlock',
              'DeleteBucketPolicy': 'DeleteBucketPolicy', 'ListObjectVersions': 'ListBucketVersions'}
_AUTOSCALING_HINTS = ('AutoScaling', 'ScalingPolicy', 'LaunchConfiguration', 'ScheduledAction')
_NARROW_VERBS = ('Delete', 'Terminate', 'Modify', 'Update', 'Put', 'Stop', 'Start', 'Reboot',
                 'Attach', 'Detach', 'Associate', 'Disassociate', 'Revoke', 'Authorize')


def _pascal(snake: str) -> str:
    return ''.join(p[:1].upper() + p[1:] for p in (snake or '').split('_') if p)


def is_access_denied(result: Any) -> bool:
    if not isinstance(result, dict) or result.get('success') is not False:
        return False
    code = str(result.get('error_code') or '')
    text = str(result.get('error') or '')
    if code in DENIED_CODES:
        return True
    m = _CODE.search(text)
    if m and m.group(1) in DENIED_CODES:
        return True
    return 'is not authorized to perform' in text


def parse_denial(tool_name: str, tool_input: Dict, result: Dict,
                 category: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """What was denied: {'action', 'resource', 'principal_arn', 'explicit_deny'}, or None."""
    if not is_access_denied(result):
        return None
    text = str(result.get('error') or '')
    explicit = 'explicit deny' in text.lower()
    m = _NOT_AUTHORIZED.search(text)
    if m:
        return {'principal_arn': m.group(1), 'action': m.group(2), 'resource': m.group(3) or '*',
                'explicit_deny': explicit}

    op = _OPERATION.search(text)
    operation = op.group(1) if op else None
    prefix = None
    if tool_name in ('aws_api_read', 'aws_api_write'):
        client = str((tool_input or {}).get('service') or '').lower()
        prefix = _CLIENT_PREFIX.get(client, client) or None
        operation = operation or _pascal(str((tool_input or {}).get('operation') or '')) or None
    elif category in _CATEGORY_PREFIX:
        prefix = _CATEGORY_PREFIX[category]
        if prefix == 'ec2' and operation and any(h in operation for h in _AUTOSCALING_HINTS):
            prefix = 'autoscaling'
    if not prefix or not operation:
        return None
    if prefix == 's3':
        operation = _S3_ACTION.get(operation, operation)
    return {'principal_arn': None, 'action': f'{prefix}:{operation}', 'resource': '*',
            'explicit_deny': explicit}


_READ_VERBS = ('List', 'Describe', 'Get', 'BatchGet')
# Wildcards that only ever list or describe configuration. Asked for alongside a refused
# read, so one yes covers the service's reads instead of one request per call.
_READ_WILDCARDS = ('List*', 'Describe*')


def build_policy(action: str, resource: str = '*') -> Dict[str, Any]:
    """Smallest policy that allows `action`. A specific resource ARN is kept only for
    actions that change one existing resource; creates and lists need '*' because AWS
    checks several related resources in turn (subnet, security group, image...).

    A refused read also asks for the same service's List*/Describe* (metadata only), so
    "check my GuardDuty" needs one yes, not one per API call (owner feedback, 2026-10-15).
    """
    svc, _, verb = action.partition(':')
    narrow = resource and resource != '*' and verb.startswith(_NARROW_VERBS)
    actions = [action]
    if verb.startswith(_READ_VERBS) and not action.startswith(SENSITIVE_PREFIXES):
        actions += [f'{svc}:{w}' for w in _READ_WILDCARDS if f'{svc}:{w}' != action]
    sid = re.sub(r'[^A-Za-z0-9]', '', 'DevOpsAgent' + action.title())[:100]
    return {'Version': '2012-10-17',
            'Statement': [{'Sid': sid, 'Effect': 'Allow', 'Action': actions,
                           'Resource': resource if narrow else '*'}]}


def policy_actions(policy: Dict[str, Any]) -> list:
    return [a for st in (policy or {}).get('Statement', []) for a in
            ([st['Action']] if isinstance(st.get('Action'), str) else st.get('Action', []))]


def is_sensitive(action: str) -> bool:
    if action.startswith(SENSITIVE_PREFIXES) or action in SENSITIVE_ACTIONS:
        return True
    if '*' in action:
        return action.partition(':')[2] not in _READ_WILDCARDS
    return False


def _principal(user_id: int, principal_arn: Optional[str]) -> Dict[str, Optional[str]]:
    """Which IAM role or user to attach the policy to, from the saved credentials."""
    from services.credential_service import get_user_aws_credentials
    creds = get_user_aws_credentials(user_id) or {}
    if creds.get('auth_mode') == 'role_arn':
        role_arn = creds['role_arn']
        return {'type': 'role', 'name': role_arn.rsplit('/', 1)[-1], 'arn': role_arn,
                'self_grant': bool(creds.get('self_grant'))}
    arn = principal_arn or ''
    if ':user/' in arn:
        return {'type': 'user', 'name': arn.rsplit('/', 1)[-1], 'arn': arn, 'self_grant': False}
    return {'type': None, 'name': None, 'arn': arn or None, 'self_grant': False}


def manual_steps(principal: Dict, policy: Dict) -> Dict[str, str]:
    """Console steps and one CLI command that add the policy by hand."""
    doc = json.dumps(policy, separators=(',', ':'))
    if principal.get('type') == 'role':
        cli = (f"aws iam put-role-policy --role-name {principal['name']} "
               f"--policy-name {GRANTED_POLICY_NAME}-{int(time.time())} --policy-document '{doc}'")
        where = f"IAM > Roles > {principal['name']} > Add permissions > Create inline policy > JSON"
    elif principal.get('type') == 'user':
        cli = (f"aws iam put-user-policy --user-name {principal['name']} "
               f"--policy-name {GRANTED_POLICY_NAME}-{int(time.time())} --policy-document '{doc}'")
        where = f"IAM > Users > {principal['name']} > Add permissions > Create inline policy > JSON"
    else:
        cli = ''
        where = 'IAM > the role or user DevOps Agent signs in as > Create inline policy > JSON'
    return {'console': where, 'cli': cli}


def build_request(user_id: int, tool_name: str, tool_input: Dict, result: Dict,
                  category: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Everything a permission request needs, or None when there is nothing to propose."""
    denial = parse_denial(tool_name, tool_input, result, category)
    if not denial or denial['explicit_deny']:
        return None  # an explicit deny (SCP, boundary, deny statement) can't be fixed by adding an allow
    action = denial['action']
    policy = build_policy(action, denial['resource'])
    principal = _principal(user_id, denial.get('principal_arn'))
    sensitive = any(is_sensitive(a) for a in policy_actions(policy))
    mode = 'self' if principal['self_grant'] and principal['type'] == 'role' and not sensitive else 'manual'
    return {
        'action': action, 'resource': policy['Statement'][0]['Resource'], 'policy': policy,
        'mode': mode, 'sensitive': sensitive, 'principal': principal,
        'manual': manual_steps(principal, policy),
        'original_tool': tool_name, 'original_input': tool_input,
    }


def describe(req_input: Dict) -> str:
    """One paragraph for the approval card and the approvals pages."""
    action, tool = req_input['action'], req_input['original_tool']
    how = ('On yes, DevOps Agent adds it to its own role (within the limit you set) and retries.'
           if req_input['mode'] == 'self' else
           'Add it in AWS (steps below), then confirm here and DevOps Agent retries.')
    warn = (' This is a sensitive permission (identity, keys or secret values); add it only if you '
            'mean the agent to have it.' if req_input['sensitive'] else '')
    extra = [a for a in policy_actions(req_input.get('policy')) if a != action]
    also = (f" It also covers this service's other list and describe reads ({', '.join(extra)}), "
            "so you aren't asked again for each one." if extra else '')
    level = (" Tip: with the CloudFormation access level 'Read' or 'Manage', DevOps Agent can "
             "already read or manage every AWS service, so this rarely comes up.")
    return (f"AWS refused {tool}: the account is missing {action}. To finish what was asked, "
            f"allow {action} on {req_input['resource']}.{also} {how}{warn}{level}")


def file_request(user_id: int, conversation_id: Optional[str], tool_name: str,
                 tool_input: Dict, result: Dict, category: Optional[str] = None):
    """Create (or reuse) the pending approval for this missing permission. Returns it or None."""
    from models import ApprovalRequest
    from services.approval_service import create_request
    req_input = build_request(user_id, tool_name, tool_input, result, category)
    if not req_input:
        return None
    for existing in ApprovalRequest.query.filter_by(requester_id=user_id, tool_name=PERMISSION_TOOL,
                                                    status='pending').all():
        if (existing.tool_input or {}).get('action') == req_input['action']:
            return existing
    return create_request(tool_name=PERMISSION_TOOL, tool_input=req_input, risk_level='high',
                          risk_reason=describe(req_input), requester_id=user_id,
                          conversation_id=conversation_id)


_READ_VERBS = ('List', 'Describe', 'Get', 'BatchGet')
HINT_AFTER_WRITE_DENIALS = 2
HINT_WINDOW = timedelta(hours=6)

MANAGE_ACCESS_HINT = (
    "The account owner has now been asked for {count} separate write permissions ({actions}). "
    "Stop the one-at-a-time requests and tell them the one-step fix: their DevOps Agent role is "
    "on a read-only access level. Switching the CloudFormation stack to the 'Manage' access level "
    "lets DevOps Agent create, change and delete resources in every AWS service, including "
    "iam:PassRole to AWS services (IAM itself stays read-only, so creating a new IAM role still "
    "needs its own permission). Console: CloudFormation > the DevOps Agent stack > Update > "
    "Replace current template with "
    "https://devopsagent-cf-templates.s3.amazonaws.com/devops-agent-role.json > set PolicyLevel "
    "to Manage > Submit. CLI: aws cloudformation update-stack --stack-name YOUR_STACK_NAME "
    "--template-url https://devopsagent-cf-templates.s3.amazonaws.com/devops-agent-role.json "
    "--parameters ParameterKey=ExternalId,UsePreviousValue=true "
    "ParameterKey=PolicyLevel,ParameterValue=Manage ParameterKey=RoleName,UsePreviousValue=true "
    "--capabilities CAPABILITY_NAMED_IAM. Never write IAM policies yourself with guessed resource "
    "ARNs; use the policy in the permission request."
)


def _is_write_action(action: Optional[str]) -> bool:
    verb = (action or '').split(':', 1)[-1]
    return bool(verb) and not verb.startswith(_READ_VERBS)


def access_level_hint(user_id: int) -> Optional[str]:
    """The Manage-access suggestion once a user has hit several missing write permissions.

    A read-level role refuses every create, so one task (an EKS cluster) became seven
    separate requests in a row, each needing the owner to edit IAM by hand (2026-10-19).
    """
    from models import ApprovalRequest
    from src.utils.timeutils import utcnow
    rows = ApprovalRequest.query.filter(
        ApprovalRequest.requester_id == user_id,
        ApprovalRequest.tool_name == PERMISSION_TOOL,
        ApprovalRequest.created_at >= utcnow() - HINT_WINDOW,
    ).all()
    actions = sorted({a for a in ((r.tool_input or {}).get('action') for r in rows) if _is_write_action(a)})
    if len(actions) < HINT_AFTER_WRITE_DENIALS:
        return None
    return MANAGE_ACCESS_HINT.format(count=len(actions), actions=', '.join(actions))


def model_note(req) -> Dict[str, Any]:
    """What the agent sees in place of the bare AccessDenied."""
    ti = req.tool_input or {}
    note = {
        'permission_request_id': req.id,
        'missing_permission': ti.get('action'),
        'policy': ti.get('policy'),
        'how': ti.get('mode'),
        'next_step': (
            f"Tell the user AWS refused this because the account lacks {ti.get('action')}, that you "
            f"filed permission request #{req.id} with the exact policy, and that once it is approved "
            "you will retry automatically. Do not try other tools to get around the missing permission."
        ),
    }
    hint = access_level_hint(req.requester_id)
    if hint:
        note['access_level_hint'] = hint
    return note


def _put_self_policy(user_id: int, principal: Dict, policy: Dict) -> None:
    """Merge the statement into the role's own granted-permissions inline policy."""
    from services.credential_service import get_user_boto_client
    iam = get_user_boto_client(user_id, 'iam')
    existing = {'Version': '2012-10-17', 'Statement': []}
    try:
        doc = iam.get_role_policy(RoleName=principal['name'], PolicyName=GRANTED_POLICY_NAME)['PolicyDocument']
        existing = json.loads(doc) if isinstance(doc, str) else doc
    except Exception as e:
        if 'NoSuchEntity' not in str(e):
            raise
    new = policy['Statement'][0]
    stmts = [s for s in existing.get('Statement', []) if s.get('Sid') != new['Sid']] + [new]
    iam.put_role_policy(RoleName=principal['name'], PolicyName=GRANTED_POLICY_NAME,
                        PolicyDocument=json.dumps({'Version': '2012-10-17', 'Statement': stmts}))


RETRY_DELAYS = (0, 5, 10)  # IAM changes take a few seconds to reach every region


def execute_grant(req, run_tool) -> Dict[str, Any]:
    """Apply (self mode) or assume applied (manual mode), then retry the original call.

    `run_tool(tool_name, tool_input)` runs a tool with the requester's context and the
    usual verification and audit (approval_service._execute_tool provides it).
    """
    ti = req.tool_input or {}
    granted = False
    # The setting is read again now: the owner may have turned self-grant off since
    # the request was filed. Then it's a manual request: just retry.
    current = _principal(req.requester_id, None) if ti.get('mode') == 'self' else {}
    if current.get('self_grant') and current.get('type') == 'role':
        if any(is_sensitive(a) for a in [ti.get('action', '')] + policy_actions(ti.get('policy'))):
            return {'success': False, 'error': 'Refused: DevOps Agent never grants itself identity, '
                    'key or secret-value permissions. Add it by hand if you want it.'}
        try:
            _put_self_policy(req.requester_id, current, ti['policy'])
            granted = True
        except Exception as e:
            logger.warning(f"Self-grant failed for request {req.id}: {e}")
            return {'success': False, 'error': f"Couldn't add the permission to the role: {e}. "
                    "Check that the CloudFormation stack was launched with AllowSelfGrant=Yes, or "
                    "add it by hand.", 'manual': ti.get('manual')}

    retry = None
    for delay in RETRY_DELAYS:
        if delay:
            time.sleep(delay)
        retry = run_tool(ti['original_tool'], ti.get('original_input') or {})
        if not is_access_denied(retry):
            break
    still_denied = is_access_denied(retry)
    follow_up = None
    if still_denied:
        nxt = parse_denial(ti['original_tool'], ti.get('original_input') or {}, retry,
                           category_of(ti['original_tool']))
        if nxt and nxt['action'] != ti.get('action'):
            # The first permission worked; AWS now needs another one for the same task.
            new_req = file_request(req.requester_id, req.conversation_id, ti['original_tool'],
                                   ti.get('original_input') or {}, retry, category_of(ti['original_tool']))
            if new_req is not None:
                follow_up = {'permission_request_id': new_req.id, 'missing_permission': nxt['action']}
                hint = access_level_hint(req.requester_id)
                if hint:
                    follow_up['access_level_hint'] = hint
    return {
        'success': not still_denied and bool(isinstance(retry, dict) and retry.get('success', True)),
        'permission': ti.get('action'),
        'granted_by': 'DevOps Agent (within your permissions boundary)' if granted else 'you',
        'retried': ti.get('original_tool'),
        'retry_result': retry,
        **({'next_permission_request': follow_up,
            'error': f"{ti.get('action')} is in place, but AWS now also needs "
                     f"{follow_up['missing_permission']} for this task: approve request "
                     f"#{follow_up['permission_request_id']} to continue."} if follow_up else
           {'error': f"AWS still refuses {ti.get('action')}. It may not be added yet, or another "
                     "policy (an SCP or permissions boundary) denies it."} if still_denied else {}),
    }


def category_of(tool_name: str) -> Optional[str]:
    try:
        from app import agent
        return getattr(agent, 'tool_categories', {}).get(tool_name)
    except Exception:
        return None
