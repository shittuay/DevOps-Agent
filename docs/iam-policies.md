# DevOps Agent — Least-Privilege IAM Policies

Two auditable customer-managed policies you can attach to the IAM role that
DevOps Agent assumes. Both are published verbatim at:

- `https://devopsagent.io/static/iam/devops-agent-readonly.json`
- `https://devopsagent.io/static/iam/devops-agent-management.json`

## Which access level should I use?

You pick one when you create the role (the CloudFormation `PolicyLevel` parameter, or the
choice next to "Create role with CloudFormation" in the app):

| Level | What DevOps Agent may do | How |
|---|---|---|
| **Read** (default, recommended) | See the configuration of every AWS service. Change nothing, never read your data or secret values. | AWS-managed `ViewOnlyAccess` + `SecurityAudit`, the published read-only policy below, and an explicit deny on data reads (`s3:GetObject`, DynamoDB item reads, `lambda:GetFunction`, Kinesis/SQS message reads) and secret values. |
| **Manage** | Also create, change and delete resources in any AWS service. Cannot change IAM; secret values stay blocked. | AWS-managed `PowerUserAccess`, the published management policy below (IAM read, `iam:PassRole` to AWS services only), and an explicit deny on secret values. |
| **ReadOnly** (strict read) | The original hand-picked list of about 45 services, read-only. | `devops-agent-readonly.json` only. |
| **Management** (strict manage) | The original hand-picked list, with changes. | `devops-agent-management.json` only. |

**Why Read and Manage use AWS-managed policies (2026-10-15):** AWS keeps them current as it
adds services, so the agent isn't refused on every service our own list happens to leave out.
With the strict levels, anything outside the list (GuardDuty, for example) is refused, and the
agent has to ask you for each missing permission.

The explicit denies are what keep the Read promise ("metadata, not data") no matter what an
AWS-managed policy allows; AWS evaluates a deny before any allow.

**Existing roles keep the level they were created with.** To move to Read or Manage:

```bash
aws cloudformation update-stack --stack-name YOUR_STACK_NAME \
  --template-url https://devopsagent-cf-templates.s3.amazonaws.com/devops-agent-role.json \
  --parameters ParameterKey=ExternalId,UsePreviousValue=true ParameterKey=PolicyLevel,ParameterValue=Read ParameterKey=RoleName,UsePreviousValue=true \
  --capabilities CAPABILITY_NAMED_IAM
```

(Use `ParameterValue=Manage` for Manage.) For a role you created by hand, attach the AWS-managed
policies listed above and copy the deny statements from `cloudformation/devops-agent-role.json`
(`DevOpsAgentGuardrails`).

Azure and Google Cloud already work this way: the setup script assigns the built-in
**Reader** / **Contributor** role (Azure) or **Viewer** / **Editor** role (Google Cloud).

## The two published policies

| Policy | Use case |
|---|---|
| `devops-agent-readonly.json` | The **ReadOnly** level on its own, and the base of **Read**. Infrastructure discovery, cost analysis, security posture scanning, troubleshooting. |
| `devops-agent-management.json` | The **Management** level on its own, and the base of **Manage**. Start/stop/create/delete resources, deploy, scale, remediate. |

## What the read-only policy deliberately excludes

The guarantee is **metadata, not data**. If this is the only policy on the
role, DevOps Agent cannot read:

- **S3 object contents** — no `s3:GetObject`. Only bucket-level config
  (encryption, versioning, public-access block, lifecycle, tags).
- **Secret values** — `secretsmanager:ListSecrets` / `DescribeSecret` only,
  never `secretsmanager:GetSecretValue`.
- **SSM parameter values** — `ssm:Describe*` only, never `ssm:GetParameter`.
- **DynamoDB / RDS data** — table and instance metadata only, no item reads
  or query access.
- **Lambda function code** — `GetFunctionConfiguration` only, not
  `GetFunction` (which returns a code download URL).

One deliberate inclusion to be aware of: **CloudWatch Logs read**
(`logs:FilterLogEvents`, `logs:Get*`). Log content is application data, but
reading logs is core to the agent's troubleshooting value. Remove the
`ObservabilityCostRead` log actions if your logs are sensitive.

## What the management policy deliberately excludes

- **IAM writes** — read-only IAM (`iam:Get*`, `iam:List*`, plus the
  `iam:GenerateCredentialReport` / `iam:GenerateServiceLastAccessedDetails`
  reporting actions that the security-audit tools need). The agent's IAM
  management tools (create user, attach policy, etc.) will not work unless
  you explicitly grant more; this prevents privilege escalation by default.
  `iam:PassRole` is allowed only when passing to AWS service principals
  (EC2, ECS, Lambda, EKS, EventBridge, Step Functions, Auto Scaling), which
  resource creation flows require.
- **Secret values** — Secrets Manager create/update/delete/tag is allowed,
  but `GetSecretValue` is still excluded. The agent can rotate or manage
  secrets without ever reading them.
- **SSM is scoped, not wildcarded** — `PutParameter`, `SendCommand` (and
  invocation status), but not `ssm:GetParameter`, so SecureString values
  stay unreadable.
- **Account/billing/organizations writes**, KMS administration, and anything
  not on the agent's tool surface.

## Setup

### Fastest: CloudFormation quick-create

The "Create role with CloudFormation" button in Settings → AWS Configuration
(and in the onboarding wizard) opens an AWS console quick-create link that
provisions the role, trust policy, and chosen policy level in one click. The
app pre-fills a random External ID; copy the `RoleArn` stack output back into
the app when the stack completes.

- Template source of truth: `cloudformation/devops-agent-role.json`,
  generated from the policy files by `scripts/build_cf_template.py` (a test
  fails if they drift).
- Hosted publicly at
  `https://devopsagent-cf-templates.s3.amazonaws.com/devops-agent-role.json`
  (S3 bucket `devopsagent-cf-templates` in the platform account; quick-create
  links require an S3 template URL).
- The `PolicyLevel` parameter selects ReadOnly (default) or Management.
- After editing a policy file: re-run the build script, then
  `aws s3 cp cloudformation/devops-agent-role.json s3://devopsagent-cf-templates/devops-agent-role.json --content-type application/json`.

### Updating an existing role (policy freshness check)

Policy versions published before 2026-07-24 carried dead grants (`efs:*` /
`opensearch:*` — not real IAM action prefixes; AWS uses `elasticfilesystem:`
and `es:`), so roles created from them silently fail on the EFS and OpenSearch
tools. The app detects this automatically: `GET /api/aws/policy-check`
(`check_aws_policy_freshness()` in `services/credential_service.py`) assumes
the connected role, reads its inline + customer-managed attached policies via
the role's own `iam:Get*/List*` grant, and flags any action matching
`STALE_ACTION_PREFIXES`. Settings → AWS Configuration shows a warning banner
with fix instructions when the role is outdated (role-ARN mode only;
AWS-managed attached policies are skipped; roles that can't read their own
policies report `outdated: null` rather than failing).

To fix an outdated quick-create stack (preserves External ID, policy level and role
name — leaving `RoleName` out would reset a custom name to the default, replacing the role
and changing its ARN):

```bash
aws cloudformation update-stack --stack-name YOUR_STACK_NAME \
  --template-url https://devopsagent-cf-templates.s3.amazonaws.com/devops-agent-role.json \
  --parameters ParameterKey=ExternalId,UsePreviousValue=true ParameterKey=PolicyLevel,UsePreviousValue=true ParameterKey=RoleName,UsePreviousValue=true \
  --capabilities CAPABILITY_NAMED_IAM
```

This command leaves `AllowSelfGrant` at its default (`No`). If you opted in, add
`ParameterKey=AllowSelfGrant,ParameterValue=Yes` (see below).

Manually created roles: re-paste the current policy JSON from the published
URLs at the top of this document.

### Letting the agent add missing permissions (AllowSelfGrant)

When AWS refuses an action because the role lacks a permission, DevOps Agent shows
you the exact policy it needs (one action, the narrowest resource) and asks yes or
no. On yes, either you add it in AWS yourself (the card shows the console path and
an `aws iam put-role-policy` command) and the agent retries, or, if you opted in,
the agent adds it to its own role and retries.

To opt in, launch or update the stack with `AllowSelfGrant=Yes`, then turn on
"Let DevOps Agent add missing permissions itself" in Settings → AWS Configuration
(it refuses unless the role has a permissions boundary). `Yes` adds:

- `DevOpsAgentSelfGrant`: `iam:PutRolePolicy` / `iam:DeleteRolePolicy` on this role
  only, and a deny on changing its boundary, trust policy or attached policies.
- `DevOpsAgentBoundary`, a managed policy set as the role's permissions boundary:
  every service except IAM writes, `sts`, `organizations`, `account` and SSO; IAM
  read; `iam:PassRole` to AWS services only; and never secret values
  (`secretsmanager:GetSecretValue`, `ssm:GetParameter*`). The role can't edit it.

AWS enforces the boundary, so nothing the agent adds can exceed it. The app also
never adds identity, key or secret-value permissions itself; those are always left
to you. Note that the boundary caps permissions you add by hand too: to give the
role something outside it, edit the boundary policy.

```bash
aws cloudformation update-stack --stack-name YOUR_STACK_NAME \
  --template-url https://devopsagent-cf-templates.s3.amazonaws.com/devops-agent-role.json \
  --parameters ParameterKey=ExternalId,UsePreviousValue=true ParameterKey=PolicyLevel,UsePreviousValue=true ParameterKey=RoleName,UsePreviousValue=true ParameterKey=AllowSelfGrant,ParameterValue=Yes \
  --capabilities CAPABILITY_NAMED_IAM
```

### Manual

1. IAM → Policies → Create policy → JSON → paste the policy file.
2. IAM → Roles → Create role → "Another AWS account" → enter the DevOps
   Agent platform account ID (shown in Settings → AWS Configuration).
3. Check "Require external ID" and set the same External ID you enter in
   the app.
4. Attach the policy from step 1. Copy the Role ARN into the app.

Both files stay within the 6,144-character IAM managed policy limit and are
validated by `tests/test_iam_policies.py`.
