# DevOps Agent — Least-Privilege IAM Policies

Two auditable customer-managed policies you can attach to the IAM role that
DevOps Agent assumes. Both are published verbatim at:

- `https://devopsagent.io/static/iam/devops-agent-readonly.json`
- `https://devopsagent.io/static/iam/devops-agent-management.json`

## Which one should I use?

| Policy | Use case |
|---|---|
| `devops-agent-readonly.json` | **Recommended starting point.** Infrastructure discovery, cost analysis, security posture scanning, troubleshooting. The agent can see configuration and metrics but cannot change anything. |
| `devops-agent-management.json` | Full agent capability — start/stop/create/delete resources, deploy, scale, remediate. Attach when you trust the agent to act, not just observe. |

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

### Manual

1. IAM → Policies → Create policy → JSON → paste the policy file.
2. IAM → Roles → Create role → "Another AWS account" → enter the DevOps
   Agent platform account ID (shown in Settings → AWS Configuration).
3. Check "Require external ID" and set the same External ID you enter in
   the app.
4. Attach the policy from step 1. Copy the Role ARN into the app.

Both files stay within the 6,144-character IAM managed policy limit and are
validated by `tests/test_iam_policies.py`.
