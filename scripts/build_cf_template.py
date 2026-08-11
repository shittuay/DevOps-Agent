"""Generate the CloudFormation quick-create template from the published IAM policies.

The template embeds static/iam/devops-agent-readonly.json and
devops-agent-management.json so customers get exactly the audited policies.
Re-run after changing either policy file, then upload:

    python scripts/build_cf_template.py
    aws s3 cp cloudformation/devops-agent-role.json s3://devopsagent-cf-templates/devops-agent-role.json

tests/test_iam_policies.py verifies the committed template matches the policy files.
"""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IAM_DIR = ROOT / 'static' / 'iam'
OUTPUT = ROOT / 'cloudformation' / 'devops-agent-role.json'
PLATFORM_ACCOUNT_ID = os.environ.get('PLATFORM_AWS_ACCOUNT_ID', '188046727805')


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
        },
        'Conditions': {
            'IsManagement': {'Fn::Equals': [{'Ref': 'PolicyLevel'}, 'Management']},
        },
        'Resources': {
            'DevOpsAgentRole': {
                'Type': 'AWS::IAM::Role',
                'Properties': {
                    'RoleName': {'Ref': 'RoleName'},
                    'Description': 'Assumed by DevOps Agent (devopsagent.io) for infrastructure operations.',
                    'MaxSessionDuration': 3600,
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
                        }
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
