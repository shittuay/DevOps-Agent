"""Generate the CloudFormation quick-create template from the published IAM policies.

The template embeds static/iam/devops-agent-readonly.json and
devops-agent-management.json so customers get exactly the audited policies.
Re-run after changing either policy file, then upload:

    python scripts/build_cf_template.py
    aws s3 cp cloudformation/devops-agent-role.json s3://devopsagent-cf-templates/devops-agent-role.json

tests/test_iam_policies.py verifies the committed template matches the policy files.

AllowSelfGrant=Yes (off by default) lets DevOps Agent add a permission the owner has
approved in the app to its own role. It gives the role iam:PutRolePolicy and
iam:DeleteRolePolicy on itself only, and caps the role with a permissions boundary
(a managed policy the role cannot edit): no IAM writes beyond its own inline
policies, no sts/organizations/account/SSO, never secret values. Whatever the agent
adds, AWS grants only what is inside that boundary.
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IAM_DIR = ROOT / 'static' / 'iam'
OUTPUT = ROOT / 'cloudformation' / 'devops-agent-role.json'
PLATFORM_ACCOUNT_ID = os.environ.get('PLATFORM_AWS_ACCOUNT_ID', '188046727805')

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Same list services/aws_permissions.py uses to decide whether a missing permission
# is too sensitive to self-grant without a warning. Importing it (instead of keeping a
# second hand-maintained copy here) is what keeps the actual AWS-enforced boundary and
# the app-level sensitivity check from drifting apart — they drifted once already:
# ec2:GetPasswordData and the redshift credential-vending actions were absent from
# both until the 2026-10-15 scheduled security review caught it (see CLAUDE_RUNBOOK.md).
from services.aws_permissions import SENSITIVE_ACTIONS  # noqa: E402


OWN_ROLE_ARN = {'Fn::Sub': 'arn:aws:iam::${AWS::AccountId}:role/${RoleName}'}

# Prefixes the boundary never allows except for the read and self-manage statements below.
BOUNDARY_EXCLUDED = ['iam:*', 'sts:*', 'organizations:*', 'account:*', 'sso:*', 'identitystore:*']
SECRET_VALUE_ACTIONS = sorted(SENSITIVE_ACTIONS)
SELF_GRANT_ACTIONS = ['iam:PutRolePolicy', 'iam:DeleteRolePolicy']


def build_boundary(management: dict) -> dict:
    """The most the role can ever do, whatever inline policies it gives itself."""
    by_sid = {s['Sid']: s for s in management['Statement']}
    return {
        'Version': '2012-10-17',
        'Statement': [
            {'Sid': 'AllServicesExceptIdentity', 'Effect': 'Allow',
             'NotAction': BOUNDARY_EXCLUDED, 'Resource': '*'},
            {**by_sid['GovernanceRead']},
            {**by_sid['PassRoleToAwsServicesOnly']},
            {'Sid': 'EditOwnInlinePolicies', 'Effect': 'Allow',
             'Action': SELF_GRANT_ACTIONS, 'Resource': OWN_ROLE_ARN},
            {'Sid': 'NeverSecretValues', 'Effect': 'Deny',
             'Action': SECRET_VALUE_ACTIONS, 'Resource': '*'},
        ],
    }


def self_grant_policy() -> dict:
    return {
        'Version': '2012-10-17',
        'Statement': [
            {'Sid': 'EditOwnInlinePolicies', 'Effect': 'Allow',
             'Action': SELF_GRANT_ACTIONS, 'Resource': OWN_ROLE_ARN},
            {'Sid': 'NeverTouchTheBoundaryOrTrust', 'Effect': 'Deny',
             'Action': ['iam:PutRolePermissionsBoundary', 'iam:DeleteRolePermissionsBoundary',
                        'iam:UpdateAssumeRolePolicy', 'iam:AttachRolePolicy', 'iam:DetachRolePolicy'],
             'Resource': OWN_ROLE_ARN},
        ],
    }


def build_template() -> dict:
    readonly = json.loads((IAM_DIR / 'devops-agent-readonly.json').read_text(encoding='utf-8'))
    management = json.loads((IAM_DIR / 'devops-agent-management.json').read_text(encoding='utf-8'))

    return {
        'AWSTemplateFormatVersion': '2010-09-09',
        'Description': (
            'DevOps Agent (devopsagent.io) cross-account access role. Creates an IAM role '
            'that DevOps Agent assumes via STS AssumeRole with an External ID. No access '
            'keys are created or shared; delete the stack to revoke access instantly. '
            'Policy contents are published at https://devopsagent.io/static/iam/'
        ),
        'Parameters': {
            'ExternalId': {
                'Type': 'String',
                'MinLength': 8,
                'MaxLength': 256,
                'AllowedPattern': '[\\w+=,.@:\\/-]+',
                'Description': (
                    'External ID for confused-deputy protection. Must match the External ID '
                    'you enter in DevOps Agent. Pre-filled when launched from the app.'
                ),
            },
            'PolicyLevel': {
                'Type': 'String',
                'AllowedValues': ['ReadOnly', 'Management'],
                'Default': 'ReadOnly',
                'Description': (
                    'ReadOnly: discovery, cost and security scanning - metadata only, never your '
                    'data. Management: the agent can also create/modify/delete resources (IAM '
                    'stays read-only and secret values stay unreadable either way).'
                ),
            },
            'RoleName': {
                'Type': 'String',
                'Default': 'DevOpsAgentRole',
                'Description': 'Name of the IAM role to create.',
            },
            'AllowSelfGrant': {
                'Type': 'String',
                'AllowedValues': ['No', 'Yes'],
                'Default': 'No',
                'Description': (
                    'Yes: when AWS refuses an action and you approve the missing permission in '
                    'DevOps Agent, the agent adds it to this role itself. The role can only edit '
                    'its own inline policies, and a permissions boundary you control caps it: no '
                    'IAM changes, no secret values. No: you add approved permissions yourself.'
                ),
            },
        },
        'Conditions': {
            'IsManagement': {'Fn::Equals': [{'Ref': 'PolicyLevel'}, 'Management']},
            'SelfGrant': {'Fn::Equals': [{'Ref': 'AllowSelfGrant'}, 'Yes']},
        },
        'Resources': {
            'DevOpsAgentBoundary': {
                'Type': 'AWS::IAM::ManagedPolicy',
                'Condition': 'SelfGrant',
                'Properties': {
                    'Description': ('Permissions boundary for the DevOps Agent role: the most it can '
                                    'ever do, whatever permissions it adds to itself.'),
                    'PolicyDocument': build_boundary(management),
                },
            },
            'DevOpsAgentRole': {
                'Type': 'AWS::IAM::Role',
                'Properties': {
                    'RoleName': {'Ref': 'RoleName'},
                    'Description': 'Assumed by DevOps Agent (devopsagent.io) for infrastructure operations.',
                    'MaxSessionDuration': 3600,
                    'PermissionsBoundary': {'Fn::If': ['SelfGrant', {'Ref': 'DevOpsAgentBoundary'},
                                                       {'Ref': 'AWS::NoValue'}]},
                    'AssumeRolePolicyDocument': {
                        'Version': '2012-10-17',
                        'Statement': [
                            {
                                'Effect': 'Allow',
                                'Principal': {'AWS': f'arn:aws:iam::{PLATFORM_ACCOUNT_ID}:root'},
                                'Action': 'sts:AssumeRole',
                                'Condition': {'StringEquals': {'sts:ExternalId': {'Ref': 'ExternalId'}}},
                            }
                        ],
                    },
                    'Policies': [
                        {
                            'PolicyName': 'DevOpsAgentAccess',
                            'PolicyDocument': {'Fn::If': ['IsManagement', management, readonly]},
                        },
                        {'Fn::If': ['SelfGrant',
                                    {'PolicyName': 'DevOpsAgentSelfGrant', 'PolicyDocument': self_grant_policy()},
                                    {'Ref': 'AWS::NoValue'}]},
                    ],
                },
            },
        },
        'Outputs': {
            'RoleArn': {
                'Description': 'Paste this Role ARN into DevOps Agent.',
                'Value': {'Fn::GetAtt': ['DevOpsAgentRole', 'Arn']},
            },
            'ExternalId': {
                'Description': 'Must match the External ID entered in DevOps Agent.',
                'Value': {'Ref': 'ExternalId'},
            },
        },
    }


def main() -> None:
    OUTPUT.parent.mkdir(exist_ok=True)
    OUTPUT.write_text(json.dumps(build_template(), indent=2) + '\n')
    print(f'Wrote {OUTPUT}')


if __name__ == '__main__':
    main()
