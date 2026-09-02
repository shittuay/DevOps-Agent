"""Regression tests for the 2026-09-02 "agent called list_iam_roles when asked to
create an Ubuntu EC2 instance" production incident.

Three independent defects combined:
  1. No tool could resolve a distro name to an AMI ID, so the request was
     unsatisfiable and the model guessed.
  2. Tool execution tested membership against the FULL registry, so a guessed
     name the model was never offered still hit the user's real cloud account.
  3. search_tools ranked by raw substring match, so the one recovery path
     returned junk ("ami" matched inside "dyn-ami-c").
"""
from unittest.mock import MagicMock, patch

import pytest


def _make_agent():
    from src.agent.core import DevOpsAgent
    cfg = MagicMock()
    cfg.get.return_value = None
    cfg.claude_model = 'claude-sonnet-4-6'
    cfg.claude_max_tokens = 4096
    cfg.claude_temperature = 0.0
    with patch('src.agent.core.anthropic.Anthropic'):
        return DevOpsAgent(cfg)


def _td(name, description=''):
    return {'name': name, 'description': description, 'input_schema': {}}


# --------------------------------------------------------------------------
# 1. find_ami exists, is registered, and is restricted to vendor-owned images
# --------------------------------------------------------------------------

class TestFindAmi:
    def test_registered_in_aws_tools(self):
        from src.tools.aws_tools import get_tools
        assert 'find_ami' in {t['name'] for t in get_tools()}

    def test_selected_for_an_ec2_request(self):
        """The whole point: 'create an ec2 instance using ubuntu' must offer it."""
        from src.agent.tool_selection import classify_tool
        assert classify_tool('find_ami', 'aws') == 'aws.ec2'

    def test_is_low_risk_read_only(self):
        from src.agent.safety import SafetyValidator
        v = SafetyValidator().validate_tool_call('find_ami', {'distro': 'ubuntu'})
        assert v.risk_level == 'low'
        assert not v.requires_confirmation

    def test_restricts_to_vendor_owner_account(self):
        """Never resolve an AMI by name alone — anyone can publish a lookalike."""
        from src.tools import aws_tools
        client = MagicMock()
        client.describe_images.return_value = {'Images': [
            {'ImageId': 'ami-old', 'Name': 'ubuntu-old', 'CreationDate': '2024-01-01T00:00:00Z'},
            {'ImageId': 'ami-new', 'Name': 'ubuntu-new', 'CreationDate': '2026-08-01T00:00:00Z'},
        ]}
        with patch.object(aws_tools, '_get_boto_client', return_value=client), \
             patch.object(aws_tools, '_get_effective_region', return_value='us-east-1'):
            result = aws_tools.find_ami(distro='ubuntu', version='24.04')

        assert result['success'] is True
        # Newest wins regardless of the order the API returned them in.
        assert result['ami_id'] == 'ami-new'
        kwargs = client.describe_images.call_args.kwargs
        assert kwargs['Owners'] == ['099720109477'], "must pin Canonical's owner id"
        names = [f for f in kwargs['Filters'] if f['Name'] == 'name']
        assert '24.04' in names[0]['Values'][0]

    def test_unknown_distro_points_at_the_generic_escape_hatch(self):
        from src.tools import aws_tools
        result = aws_tools.find_ami(distro='plan9')
        assert result['success'] is False
        assert 'aws_api_read' in result['error']

    def test_no_match_is_an_error_not_a_silent_empty(self):
        from src.tools import aws_tools
        client = MagicMock()
        client.describe_images.return_value = {'Images': []}
        with patch.object(aws_tools, '_get_boto_client', return_value=client), \
             patch.object(aws_tools, '_get_effective_region', return_value='eu-west-1'):
            result = aws_tools.find_ami(distro='ubuntu', version='99.99')
        assert result['success'] is False
        assert 'ami_id' not in result

    def test_sandbox_returns_a_usable_ami_id(self):
        """A generic '[Sandbox] executed' fallback would break the launch chain."""
        from services.learning_sandbox import generate_mock_result
        result = generate_mock_result('find_ami', {'distro': 'ubuntu'})
        assert result['simulated'] is True
        assert result['ami_id'].startswith('ami-')


# --------------------------------------------------------------------------
# 2. A tool that was not offered must not execute
# --------------------------------------------------------------------------

class TestOfferedToolEnforcement:
    def test_withheld_tool_is_not_executed(self):
        """The production failure: list_iam_roles was filtered out of the turn
        and ran anyway against the user's real account."""
        agent = _make_agent()
        ran = []
        agent.register_tool('list_iam_roles', 'List IAM roles', {}, lambda **kw: ran.append('iam') or {'ok': True})
        agent.register_tool('find_ami', 'Find an AMI', {}, lambda **kw: {'ok': True})
        agent._tools_override = [_td('find_ami'), _td('search_tools')]

        assert agent._is_tool_offered('find_ami') is True
        assert agent._is_tool_offered('list_iam_roles') is False
        assert ran == []

    def test_rejection_names_search_tools_as_the_recovery_path(self):
        agent = _make_agent()
        agent.register_tool('list_iam_roles', 'List IAM roles', {}, lambda **kw: {'ok': True})
        agent._tools_override = [_td('search_tools')]

        result = agent._not_offered_result('list_iam_roles')
        assert result['success'] is False
        assert 'search_tools' in result['error']
        assert 'not offered' in result['error']

    def test_genuinely_unknown_tool_is_distinguished_from_withheld(self):
        agent = _make_agent()
        agent._tools_override = [_td('search_tools')]
        assert 'Unknown tool' in agent._not_offered_result('no_such_tool_anywhere')['error']

    def test_no_override_means_everything_is_allowed(self):
        """When the full catalog was sent, nothing was withheld."""
        agent = _make_agent()
        agent.register_tool('list_iam_roles', 'List IAM roles', {}, lambda **kw: {'ok': True})
        agent._tools_override = None
        assert agent._is_tool_offered('list_iam_roles') is True

    def test_search_tools_recovery_makes_a_tool_executable_again(self):
        """Rejection must not be a dead end: search_tools is the way back."""
        agent = _make_agent()
        agent.register_tool('list_iam_roles', 'List IAM roles and their policies', {}, lambda **kw: {'ok': True})
        agent._tools_override = [_td('search_tools')]
        assert agent._is_tool_offered('list_iam_roles') is False

        agent._search_tools_handler('list iam roles')
        assert agent._is_tool_offered('list_iam_roles') is True

    def test_unregistered_tool_is_never_offered(self):
        agent = _make_agent()
        agent._tools_override = None
        assert agent._is_tool_offered('totally_made_up') is False


# --------------------------------------------------------------------------
# 3. search_tools ranking
# --------------------------------------------------------------------------

class TestSearchToolsRanking:
    def _agent_with_catalog(self):
        agent = _make_agent()
        for name, desc in [
            ('find_ami', 'Find the newest official AMI ID for a distribution'),
            ('create_ami', 'Create an Amazon Machine Image from an instance'),
            ('list_eks_clusters', 'List EKS clusters, dynamically discovered'),
            ('download_s3_object', 'Download an object from S3'),
        ]:
            agent.register_tool(name, desc, {}, lambda **kw: {'ok': True})
        return agent

    def test_short_term_does_not_match_inside_an_unrelated_word(self):
        """'ami' must not match 'dyn-ami-c', which used to rank an EKS tool top."""
        agent = self._agent_with_catalog()
        names = [m['name'] for m in agent._search_tools_handler('ubuntu ami')['matches']]
        assert names[0] == 'find_ami'
        # The EKS tool only ever matched via "dyn-ami-c" in its description, so
        # with whole-word matching it must not appear at all.
        assert 'list_eks_clusters' not in names

    def test_name_match_outranks_description_match(self):
        agent = self._agent_with_catalog()
        names = [m['name'] for m in agent._search_tools_handler('ami')['matches']]
        assert set(names[:2]) == {'find_ami', 'create_ami'}

    def test_empty_query_rejected(self):
        agent = self._agent_with_catalog()
        assert agent._search_tools_handler('   ')['success'] is False

    def test_no_match_reports_cleanly(self):
        agent = self._agent_with_catalog()
        result = agent._search_tools_handler('zzzz qqqq')
        assert result['success'] is True
        assert result['matches'] == []


# --------------------------------------------------------------------------
# 4. Tool-description discoverability: 2026-09-02 follow-up
#
# find_ami existing and being offered was not enough — Kimi still called
# manage_ec2_instance(action='start') with a guessed instance_id trying to
# "create" an instance, since manage_ec2_instance's description never said
# it can't create one, and create_ec2_instance's description never pointed
# at find_ami as the prerequisite step.
# --------------------------------------------------------------------------

class TestEc2ToolDiscoverability:
    def _tools(self):
        from src.tools.aws_tools import get_tools
        return {t['name']: t for t in get_tools()}

    def test_create_ec2_instance_points_at_find_ami(self):
        desc = self._tools()['create_ec2_instance']['description']
        assert 'find_ami' in desc

    def test_create_ec2_instance_warns_off_manage_ec2_instance(self):
        desc = self._tools()['create_ec2_instance']['description']
        assert 'manage_ec2_instance' in desc

    def test_manage_ec2_instance_states_it_cannot_create(self):
        desc = self._tools()['manage_ec2_instance']['description']
        assert 'create' in desc.lower()
        assert 'create_ec2_instance' in desc

    def test_manage_ec2_instance_points_at_find_ami_too(self):
        """A model that reads only manage_ec2_instance (the one it guessed)
        must still be able to find its way to find_ami from there."""
        desc = self._tools()['manage_ec2_instance']['description']
        assert 'find_ami' in desc


# --------------------------------------------------------------------------
# 5. Runtime self-correction: 2026-09-02 second follow-up
#
# Fixing descriptions (#164) is advisory — an LLM can still ignore them.
# These two guards catch the exact failure mode at the moment it happens,
# in the tool result itself, so the model can self-correct within the same
# turn instead of the mistake reaching AWS with no way back.
# --------------------------------------------------------------------------

class TestEc2RuntimeSelfCorrection:
    def test_create_ec2_instance_missing_ami_id_points_to_find_ami(self):
        from src.tools import aws_tools
        result = aws_tools.create_ec2_instance(instance_type='t2.micro')
        assert result['success'] is False
        assert 'find_ami' in result['message']
        assert 'manage_ec2_instance' in result['message']

    def test_create_ec2_instance_missing_ami_id_never_reaches_boto(self):
        """Must return before touching AWS at all — no client should be built."""
        from src.tools import aws_tools
        with patch.object(aws_tools, '_get_boto_client') as mock_client:
            aws_tools.create_ec2_instance(instance_type='t2.micro')
            mock_client.assert_not_called()

    def test_create_ec2_instance_missing_instance_type(self):
        from src.tools import aws_tools
        result = aws_tools.create_ec2_instance(ami_id='ami-123')
        assert result['success'] is False
        assert 'instance_type' in result['message']

    def test_create_ec2_instance_schema_still_requires_both(self):
        """The runtime guard is defense-in-depth, not a signal to relax the
        schema the model sees — both stay required there."""
        from src.tools.aws_tools import get_tools
        t = {x['name']: x for x in get_tools()}
        assert set(t['create_ec2_instance']['input_schema']['required']) == {'ami_id', 'instance_type'}

    def test_manage_ec2_instance_invalid_instance_id_redirects_to_create(self):
        """The exact production failure: manage_ec2_instance(action='start')
        with a fabricated instance_id, trying to 'create' an instance."""
        from src.tools import aws_tools
        from botocore.exceptions import ClientError
        client = MagicMock()
        client.start_instances.side_effect = ClientError(
            {'Error': {'Code': 'InvalidInstanceID.NotFound', 'Message': 'not found'}},
            'StartInstances',
        )
        with patch.object(aws_tools, '_get_boto_client', return_value=client):
            result = aws_tools.manage_ec2_instance(instance_id='i-fabricated', action='start')

        assert result['success'] is False
        assert 'find_ami' in result['message']
        assert 'create_ec2_instance' in result['message']

    def test_manage_ec2_instance_other_errors_are_not_relabeled(self):
        """Only the InvalidInstanceID family gets the redirect — an unrelated
        AWS error (e.g. permissions) must not be misdiagnosed as 'go create one'."""
        from src.tools import aws_tools
        from botocore.exceptions import ClientError
        client = MagicMock()
        client.start_instances.side_effect = ClientError(
            {'Error': {'Code': 'UnauthorizedOperation', 'Message': 'denied'}},
            'StartInstances',
        )
        with patch.object(aws_tools, '_get_boto_client', return_value=client):
            result = aws_tools.manage_ec2_instance(instance_id='i-real123', action='start')

        assert result['success'] is False
        assert 'message' not in result
