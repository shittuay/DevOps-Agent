"""Execution Integrity Phase 4 — CloudFormation fallback for a failed create.

services/iac_fallback.py + DevOpsAgent._iac_fallback.
"""
import json
from unittest.mock import MagicMock, patch

import pytest

from services.iac_fallback import generate_cloudformation, is_supported


def _tmpl(fallback):
    return json.loads(fallback['template'])


# --------------------------------------------------------------------------
# module: generate_cloudformation
# --------------------------------------------------------------------------

class TestGenerate:
    def test_ec2_instance(self):
        f = generate_cloudformation('create_ec2_instance', {
            'ami_id': 'ami-0abc123', 'instance_type': 't3.micro', 'key_name': 'kp',
            'security_group_ids': ['sg-1'], 'subnet_id': 'subnet-1',
            'tags': {'Name': 'web', 'env': 'prod'}})
        assert f['format'] == 'cloudformation'
        assert f['resource_type'] == 'AWS::EC2::Instance'
        r = _tmpl(f)['Resources']['Instance']
        assert r['Type'] == 'AWS::EC2::Instance'
        p = r['Properties']
        assert p['ImageId'] == 'ami-0abc123'
        assert p['InstanceType'] == 't3.micro'
        assert p['KeyName'] == 'kp'
        assert p['SecurityGroupIds'] == ['sg-1']
        assert {'Key': 'Name', 'Value': 'web'} in p['Tags']
        assert 'create_cloudformation_stack' in f['apply']

    def test_ec2_without_ami_is_unsupported(self):
        assert generate_cloudformation('create_ec2_instance', {'instance_type': 't3.micro'}) is None

    def test_security_group_with_ingress(self):
        f = generate_cloudformation('create_security_group', {
            'group_name': 'web-sg', 'description': 'web tier', 'vpc_id': 'vpc-1',
            'ingress_rules': [{'protocol': 'tcp', 'from_port': 443, 'to_port': 443,
                              'cidr': '0.0.0.0/0'}]})
        p = _tmpl(f)['Resources']['SecurityGroup']['Properties']
        assert p['GroupName'] == 'web-sg' and p['VpcId'] == 'vpc-1'
        assert p['SecurityGroupIngress'] == [
            {'IpProtocol': 'tcp', 'FromPort': 443, 'ToPort': 443, 'CidrIp': '0.0.0.0/0'}]

    def test_security_group_missing_description_unsupported(self):
        assert generate_cloudformation('create_security_group', {'group_name': 'x'}) is None

    def test_vpc(self):
        f = generate_cloudformation('create_vpc', {'cidr_block': '10.1.0.0/16', 'name': 'main'})
        p = _tmpl(f)['Resources']['Vpc']['Properties']
        assert p['CidrBlock'] == '10.1.0.0/16'
        assert p['EnableDnsSupport'] is True
        assert {'Key': 'Name', 'Value': 'main'} in p['Tags']

    def test_s3_bucket_options(self):
        f = generate_cloudformation('create_s3_bucket', {
            'bucket_name': 'my-bucket', 'versioning_enabled': True,
            'encryption_enabled': True, 'public_access_block': True})
        p = _tmpl(f)['Resources']['Bucket']['Properties']
        assert p['BucketName'] == 'my-bucket'
        assert p['VersioningConfiguration'] == {'Status': 'Enabled'}
        assert p['BucketEncryption']['ServerSideEncryptionConfiguration'][0][
            'ServerSideEncryptionByDefault']['SSEAlgorithm'] == 'AES256'
        assert p['PublicAccessBlockConfiguration']['BlockPublicAcls'] is True

    def test_template_is_valid_cfn_shape(self):
        f = generate_cloudformation('create_vpc', {'cidr_block': '10.0.0.0/16'})
        t = _tmpl(f)
        assert t['AWSTemplateFormatVersion'] == '2010-09-09'
        assert 'Description' in t and 'Resources' in t and 'Outputs' in t

    def test_rds_and_reads_unsupported(self):
        assert not is_supported('create_rds_instance')  # password handling deferred
        assert not is_supported('get_ec2_instances')
        assert not is_supported('delete_vpc')
        assert generate_cloudformation('create_rds_instance', {'db_instance_identifier': 'db'}) is None


# --------------------------------------------------------------------------
# agent: _iac_fallback
# --------------------------------------------------------------------------

def _make_agent(enabled=True):
    from src.agent.core import DevOpsAgent
    cfg = MagicMock()
    cfg.get.side_effect = lambda key, default=None: (
        enabled if key == 'iac_fallback.enabled' else default)
    cfg.claude_model = 'claude-sonnet-4-6'
    cfg.claude_max_tokens = 4096
    cfg.claude_temperature = 0.0
    with patch('src.agent.core.anthropic.Anthropic'):
        return DevOpsAgent(cfg)


_CFN_TD = {'name': 'create_cloudformation_stack', 'description': 'x', 'input_schema': {}}


class TestAgentIacFallback:
    def test_failed_create_gets_iac_fallback_and_tool_becomes_callable(self):
        agent = _make_agent()
        agent.tool_definitions.append(_CFN_TD)
        agent._tools_override = [{'name': 'create_ec2_instance', 'description': '', 'input_schema': {}}]

        out = agent._verify_and_annotate(
            'create_ec2_instance', {'ami_id': 'ami-0abc123', 'instance_type': 't3.micro'},
            {'success': False, 'error': 'InsufficientInstanceCapacity'})

        assert out['success'] is False
        assert out['_iac_fallback']['resource_type'] == 'AWS::EC2::Instance'
        assert any(td['name'] == 'create_cloudformation_stack' for td in agent._tools_override)

    def test_only_one_fallback_per_turn(self):
        agent = _make_agent()
        agent.tool_definitions.append(_CFN_TD)
        agent._tools_override = [{'name': 'create_vpc', 'description': '', 'input_schema': {}}]
        r = {'success': False, 'error': 'x'}
        first = agent._verify_and_annotate('create_vpc', {'cidr_block': '10.0.0.0/16'}, dict(r))
        second = agent._verify_and_annotate('create_vpc', {'cidr_block': '10.1.0.0/16'}, dict(r))
        assert '_iac_fallback' in first
        assert '_iac_fallback' not in second

    def test_unsupported_tool_failure_is_untouched(self):
        agent = _make_agent()
        r = {'success': False, 'error': 'x'}
        assert agent._verify_and_annotate('create_rds_instance', {}, dict(r)) == r

    def test_kill_switch(self):
        agent = _make_agent(enabled=False)
        agent._tools_override = [{'name': 'create_vpc', 'description': '', 'input_schema': {}}]
        out = agent._verify_and_annotate('create_vpc', {'cidr_block': '10.0.0.0/16'},
                                         {'success': False, 'error': 'x'})
        assert '_iac_fallback' not in out

    def test_successful_create_is_not_given_a_fallback(self):
        agent = _make_agent()
        agent.register_tool('get_ec2_instances', 'x', {}, lambda **kw: {
            'success': True, 'instances': [{'instance_id': 'i-0abc123def456789'}]})
        with patch('time.sleep', lambda _s: None):
            out = agent._verify_and_annotate(
                'create_ec2_instance', {'ami_id': 'ami-0abc123'},
                {'success': True, 'details': {'instance_id': 'i-0abc123def456789'}})
        assert '_iac_fallback' not in out
        assert out['_verification']['status'] == 'confirmed'

    def test_sandbox_mode_skips(self):
        agent = _make_agent()
        agent._sandbox_mode = True
        out = agent._verify_and_annotate('create_vpc', {'cidr_block': '10.0.0.0/16'},
                                         {'success': False, 'error': 'x'})
        assert '_iac_fallback' not in out
