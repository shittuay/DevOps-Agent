"""
Tests for the 4-part anti-hallucination fix.

Covers:
  PART 1 — services/model_router.py   : max_tools + trust_tool_results fields
  PART 2 — services/devopsagent_prompts.py : prompts, enums, session factory,
                                              detect_task_type, scope_tools
  PART 3 — src/agent/core.py          : _validate_tool_result_ids,
                                         tools_override / trust_tool_results params
  PART 4 — app.py wiring              : smoke-checks that the route accepts the
                                         new params without 500-ing
"""

import json
import pytest
from unittest.mock import MagicMock, patch


# ===========================================================================
# PART 1 — model_router.py
# ===========================================================================

class TestModelConfigFields:
    """ModelConfig must expose max_tools and trust_tool_results on every tier."""

    def test_default_tier_models_have_max_tools(self):
        from services.model_router import DEFAULT_TIER_MODELS
        for tier, cfg in DEFAULT_TIER_MODELS.items():
            assert hasattr(cfg, 'max_tools'), f"{tier} missing max_tools"
            assert isinstance(cfg.max_tools, int), f"{tier}.max_tools must be int"
            assert cfg.max_tools > 0, f"{tier}.max_tools must be positive"

    def test_default_tier_models_have_trust_tool_results(self):
        from services.model_router import DEFAULT_TIER_MODELS
        for tier, cfg in DEFAULT_TIER_MODELS.items():
            assert hasattr(cfg, 'trust_tool_results'), f"{tier} missing trust_tool_results"
            assert isinstance(cfg.trust_tool_results, bool)

    def test_free_tier_max_tools_is_6(self):
        from services.model_router import DEFAULT_TIER_MODELS
        assert DEFAULT_TIER_MODELS['free'].max_tools == 6

    def test_starter_tier_max_tools_is_8(self):
        from services.model_router import DEFAULT_TIER_MODELS
        assert DEFAULT_TIER_MODELS['starter'].max_tools == 8

    def test_professional_tier_max_tools_is_15(self):
        from services.model_router import DEFAULT_TIER_MODELS
        assert DEFAULT_TIER_MODELS['professional'].max_tools == 15

    def test_business_tier_max_tools_is_20(self):
        from services.model_router import DEFAULT_TIER_MODELS
        assert DEFAULT_TIER_MODELS['business'].max_tools == 20

    def test_kimi_tiers_do_not_trust_tool_results(self):
        from services.model_router import DEFAULT_TIER_MODELS
        assert DEFAULT_TIER_MODELS['free'].trust_tool_results is False
        assert DEFAULT_TIER_MODELS['starter'].trust_tool_results is False

    def test_claude_tiers_trust_tool_results(self):
        from services.model_router import DEFAULT_TIER_MODELS
        assert DEFAULT_TIER_MODELS['professional'].trust_tool_results is True
        assert DEFAULT_TIER_MODELS['business'].trust_tool_results is True

    def test_claude_override_configs_have_new_fields(self):
        from services.model_router import CLAUDE_OVERRIDE_CONFIGS
        for tier, cfg in CLAUDE_OVERRIDE_CONFIGS.items():
            assert hasattr(cfg, 'max_tools'), f"CLAUDE_OVERRIDE_CONFIGS[{tier}] missing max_tools"
            assert hasattr(cfg, 'trust_tool_results')

    def test_claude_overrides_match_expected_values(self):
        from services.model_router import CLAUDE_OVERRIDE_CONFIGS
        assert CLAUDE_OVERRIDE_CONFIGS['free'].max_tools == 6
        assert CLAUDE_OVERRIDE_CONFIGS['free'].trust_tool_results is False
        assert CLAUDE_OVERRIDE_CONFIGS['professional'].max_tools == 15
        assert CLAUDE_OVERRIDE_CONFIGS['professional'].trust_tool_results is True
        assert CLAUDE_OVERRIDE_CONFIGS['business'].max_tools == 20
        assert CLAUDE_OVERRIDE_CONFIGS['business'].trust_tool_results is True

    def test_kimi_model_config_has_new_fields(self):
        from services.model_router import KIMI_MODEL_CONFIG
        assert KIMI_MODEL_CONFIG.max_tools == 8
        assert KIMI_MODEL_CONFIG.trust_tool_results is False

    def test_resolve_model_with_preference_kimi_inherits_tier_values(self):
        from services.model_router import resolve_model_with_preference
        free_kimi = resolve_model_with_preference('free', 'kimi')
        assert free_kimi.max_tools == 6
        assert free_kimi.trust_tool_results is False

        starter_kimi = resolve_model_with_preference('starter', 'kimi')
        assert starter_kimi.max_tools == 8
        assert starter_kimi.trust_tool_results is False

    def test_resolve_model_with_preference_anthropic_inherits_tier_values(self):
        from services.model_router import resolve_model_with_preference
        pro_claude = resolve_model_with_preference('professional', 'anthropic')
        assert pro_claude.max_tools == 15
        assert pro_claude.trust_tool_results is True

    def test_resolve_model_with_no_preference_uses_tier_defaults(self):
        from services.model_router import resolve_model_with_preference
        cfg = resolve_model_with_preference('business', None)
        assert cfg.max_tools == 20
        assert cfg.trust_tool_results is True

    def test_modelconfig_default_max_tools_is_10(self):
        """Configs constructed without max_tools/trust_tool_results use safe defaults."""
        from services.model_router import ModelConfig
        cfg = ModelConfig(provider='test', model='test', display_name='test', supports_tools=True)
        assert cfg.max_tools == 10
        assert cfg.trust_tool_results is True


# ===========================================================================
# PART 2 — services/devopsagent_prompts.py
# ===========================================================================

class TestEnumsAndDataclass:
    def test_agent_mode_has_sandbox_and_real_agent(self):
        from services.devopsagent_prompts import AgentMode
        assert AgentMode.SANDBOX.value == 'sandbox'
        assert AgentMode.REAL_AGENT.value == 'real_agent'

    def test_cloud_provider_enum_values(self):
        from services.devopsagent_prompts import CloudProvider
        assert CloudProvider.AWS.value == 'aws'
        assert CloudProvider.AZURE.value == 'azure'
        assert CloudProvider.GCP.value == 'gcp'

    def test_agent_session_defaults(self):
        from services.devopsagent_prompts import AgentSession, AgentMode
        s = AgentSession(mode=AgentMode.SANDBOX, cloud_provider=None, session_id='abc123')
        assert s.message_history == []
        assert s.session_id == 'abc123'


class TestSystemPrompts:
    def test_sandbox_prompt_contains_key_directives(self):
        from services.devopsagent_prompts import SANDBOX_SYSTEM_PROMPT
        lower = SANDBOX_SYSTEM_PROMPT.lower()
        assert 'sandbox' in lower
        assert '[sandbox simulation]' in lower
        assert 'real credentials' in lower or 'real cred' in lower

    def test_sandbox_prompt_permits_fiction(self):
        from services.devopsagent_prompts import SANDBOX_SYSTEM_PROMPT
        lower = SANDBOX_SYSTEM_PROMPT.lower()
        # Should explicitly allow generating fictional resources
        assert 'fictional' in lower or 'simulate' in lower or 'fictitious' in lower or 'may generate' in lower

    def test_real_agent_prompt_contains_key_directives(self):
        from services.devopsagent_prompts import REAL_AGENT_SYSTEM_PROMPT
        lower = REAL_AGENT_SYSTEM_PROMPT.lower()
        assert 'never fabricat' in lower or 'do not fabricat' in lower or 'forbid' in lower
        assert 'source of truth' in lower or 'only source' in lower

    def test_real_agent_prompt_has_format_placeholders(self):
        from services.devopsagent_prompts import REAL_AGENT_SYSTEM_PROMPT
        # Must accept {cloud_provider}, {user_tier}, {session_id} substitutions
        rendered = REAL_AGENT_SYSTEM_PROMPT.format(
            cloud_provider='AWS',
            user_tier='free',
            session_id='testsession123'
        )
        assert 'AWS' in rendered
        assert 'free' in rendered
        assert 'testsession123' in rendered

    def test_real_agent_prompt_no_fabrication_on_empty_result(self):
        from services.devopsagent_prompts import REAL_AGENT_SYSTEM_PROMPT
        lower = REAL_AGENT_SYSTEM_PROMPT.lower()
        assert 'no resources found' in lower or 'empty' in lower

    def test_real_agent_prompt_requires_confirmation_for_destructive(self):
        from services.devopsagent_prompts import REAL_AGENT_SYSTEM_PROMPT
        lower = REAL_AGENT_SYSTEM_PROMPT.lower()
        assert 'confirm' in lower


class TestDetectTaskType:
    """detect_task_type() must map user messages to the right TOOL_GROUPS key."""

    def _run(self, msg):
        from services.devopsagent_prompts import detect_task_type
        return detect_task_type(msg)

    # ---- aws_scan ----
    def test_list_maps_to_aws_scan(self):
        assert self._run('list my ec2 instances') == 'aws_scan'

    def test_show_maps_to_aws_scan(self):
        assert self._run('show me the security groups') == 'aws_scan'

    def test_describe_maps_to_aws_scan(self):
        assert self._run('describe my VPCs') == 'aws_scan'

    def test_inventory_maps_to_aws_scan(self):
        assert self._run('give me an inventory of resources') == 'aws_scan'

    def test_billing_maps_to_aws_scan(self):
        assert self._run('show me my billing this month') == 'aws_scan'

    def test_cost_maps_to_aws_scan(self):
        assert self._run('what is my current cost estimate') == 'aws_scan'

    def test_default_fallback_is_aws_scan(self):
        assert self._run('something completely unrelated xyzzy') == 'aws_scan'

    # ---- aws_compute ----
    def test_deploy_maps_to_aws_compute(self):
        assert self._run('deploy a new web server') == 'aws_compute'

    def test_create_maps_to_aws_compute(self):
        assert self._run('create a new EC2 instance') == 'aws_compute'

    def test_launch_maps_to_aws_compute(self):
        assert self._run('launch an RDS instance') == 'aws_compute'

    def test_terminate_maps_to_aws_compute(self):
        assert self._run('terminate the old instance') == 'aws_compute'

    # ---- kubernetes ----
    def test_pod_maps_to_kubernetes(self):
        assert self._run('my pods are not starting') == 'kubernetes'

    def test_deployment_maps_to_kubernetes(self):
        assert self._run('check the deployment status') == 'kubernetes'

    def test_kubectl_maps_to_kubernetes(self):
        assert self._run('run kubectl get nodes') == 'kubernetes'

    def test_crashloop_maps_to_kubernetes(self):
        assert self._run('pod is in crashloopbackoff') == 'kubernetes'

    def test_namespace_maps_to_kubernetes(self):
        assert self._run('list all namespaces') == 'kubernetes'

    # ---- terraform ----
    def test_terraform_maps_to_terraform(self):
        assert self._run('run terraform plan') == 'terraform'

    def test_terraform_apply_maps_to_terraform(self):
        assert self._run('apply my terraform changes') == 'terraform'

    def test_state_file_maps_to_terraform(self):
        assert self._run('inspect the state file') == 'terraform'

    # ---- git ----
    def test_git_maps_to_git(self):
        assert self._run('git push my changes') == 'git'

    def test_commit_maps_to_git(self):
        assert self._run('commit the changes') == 'git'

    def test_pull_request_maps_to_git(self):
        assert self._run('open a pull request') == 'git'

    # ---- cicd ----
    def test_pipeline_maps_to_cicd(self):
        assert self._run('trigger the pipeline') == 'cicd'

    def test_jenkins_maps_to_cicd(self):
        assert self._run('check the jenkins build') == 'cicd'

    def test_github_actions_maps_to_cicd(self):
        assert self._run('run the github action workflow') == 'cicd'

    def test_case_insensitive(self):
        from services.devopsagent_prompts import detect_task_type
        assert detect_task_type('LIST MY EC2 INSTANCES') == 'aws_scan'
        assert detect_task_type('JENKINS BUILD FAILED') == 'cicd'


class TestScopeTools:
    """DevOpsAgentSessionFactory.scope_tools() must filter and cap correctly."""

    def _factory(self):
        from services.devopsagent_prompts import DevOpsAgentSessionFactory
        return DevOpsAgentSessionFactory()

    def _make_tools(self, names):
        return [{'name': n, 'description': '', 'input_schema': {}} for n in names]

    def test_filters_to_matching_group(self):
        f = self._factory()
        tools = self._make_tools([
            'list_ec2_instances', 'list_pods', 'terraform_plan', 'git_commit'
        ])
        result = f.scope_tools(tools, 'kubernetes', max_tools=10)
        names = [t['name'] for t in result]
        assert 'list_pods' in names
        assert 'list_ec2_instances' not in names
        assert 'terraform_plan' not in names

    def test_enforces_max_tools_cap(self):
        f = self._factory()
        tools = self._make_tools([f'list_ec2_{i}' for i in range(20)])
        result = f.scope_tools(tools, 'aws_scan', max_tools=5)
        assert len(result) == 5

    def test_fallback_to_all_tools_when_no_match(self):
        f = self._factory()
        tools = self._make_tools(['tool_alpha', 'tool_beta', 'tool_gamma'])
        # No tool name matches 'kubernetes' group substrings
        result = f.scope_tools(tools, 'kubernetes', max_tools=10)
        assert len(result) == 3  # all returned since nothing matched

    def test_fallback_also_respects_max_tools(self):
        f = self._factory()
        tools = self._make_tools([f'unrelated_tool_{i}' for i in range(15)])
        result = f.scope_tools(tools, 'kubernetes', max_tools=5)
        assert len(result) == 5

    def test_empty_tool_list_returns_empty(self):
        f = self._factory()
        result = f.scope_tools([], 'aws_scan', max_tools=10)
        assert result == []

    def test_returns_list_of_dicts(self):
        f = self._factory()
        tools = self._make_tools(['list_ec2_instances', 'list_pods'])
        result = f.scope_tools(tools, 'aws_scan', max_tools=10)
        assert isinstance(result, list)
        for t in result:
            assert 'name' in t

    def test_terraform_group_matches_terraform_tools(self):
        f = self._factory()
        tools = self._make_tools([
            'terraform_plan', 'terraform_apply', 'terraform_init',
            'list_pods', 'git_push'
        ])
        result = f.scope_tools(tools, 'terraform', max_tools=10)
        names = [t['name'] for t in result]
        assert 'terraform_plan' in names
        assert 'terraform_apply' in names
        assert 'list_pods' not in names

    def test_git_group_matches_git_and_github_tools(self):
        f = self._factory()
        tools = self._make_tools([
            'git_commit', 'git_push', 'github_create_pr',
            'list_ec2_instances', 'terraform_plan'
        ])
        result = f.scope_tools(tools, 'git', max_tools=10)
        names = [t['name'] for t in result]
        assert 'git_commit' in names
        assert 'github_create_pr' in names
        assert 'list_ec2_instances' not in names


class TestSessionFactory:
    def test_create_sandbox_session_mode(self):
        from services.devopsagent_prompts import DevOpsAgentSessionFactory, AgentMode
        s = DevOpsAgentSessionFactory().create_sandbox_session()
        assert s.mode == AgentMode.SANDBOX

    def test_create_sandbox_session_has_session_id(self):
        from services.devopsagent_prompts import DevOpsAgentSessionFactory
        s = DevOpsAgentSessionFactory().create_sandbox_session()
        assert s.session_id and len(s.session_id) > 8

    def test_sandbox_sessions_have_unique_ids(self):
        from services.devopsagent_prompts import DevOpsAgentSessionFactory
        f = DevOpsAgentSessionFactory()
        s1 = f.create_sandbox_session()
        s2 = f.create_sandbox_session()
        assert s1.session_id != s2.session_id

    def test_create_real_agent_session_mode(self):
        from services.devopsagent_prompts import DevOpsAgentSessionFactory, AgentMode, CloudProvider
        s = DevOpsAgentSessionFactory().create_real_agent_session(CloudProvider.AWS)
        assert s.mode == AgentMode.REAL_AGENT
        assert s.cloud_provider == CloudProvider.AWS

    def test_create_real_agent_session_no_provider(self):
        from services.devopsagent_prompts import DevOpsAgentSessionFactory, AgentMode
        s = DevOpsAgentSessionFactory().create_real_agent_session(None)
        assert s.mode == AgentMode.REAL_AGENT
        assert s.cloud_provider is None

    def test_get_model_returns_string(self):
        from services.devopsagent_prompts import DevOpsAgentSessionFactory
        model = DevOpsAgentSessionFactory().get_model('free')
        assert isinstance(model, str)
        assert len(model) > 0

    def test_get_model_free_tier_returns_kimi(self):
        from services.devopsagent_prompts import DevOpsAgentSessionFactory
        model = DevOpsAgentSessionFactory().get_model('free')
        assert 'kimi' in model.lower()

    def test_get_model_professional_returns_claude(self):
        from services.devopsagent_prompts import DevOpsAgentSessionFactory
        model = DevOpsAgentSessionFactory().get_model('professional')
        assert 'claude' in model.lower()


# ===========================================================================
# PART 3 — src/agent/core.py  (_validate_tool_result_ids + process_message_* params)
# ===========================================================================

class TestValidateToolResultIds:
    """_validate_tool_result_ids should reject suspicious fake IDs."""

    def _validate(self, result_dict):
        from src.agent.core import _validate_tool_result_ids
        return _validate_tool_result_ids(json.dumps(result_dict))

    # ---- clean results pass through ----
    def test_real_ec2_id_passes(self):
        result = {'success': True, 'instance_id': 'i-0a1b2c3d4e5f67890'}
        out = self._validate(result)
        assert json.loads(out)['success'] is True

    def test_real_sg_id_passes(self):
        result = {'success': True, 'sg_id': 'sg-0a1b2c3d4e5f67890'}
        out = self._validate(result)
        assert json.loads(out)['success'] is True

    def test_text_only_result_passes(self):
        result = {'success': True, 'message': 'No instances found.'}
        out = self._validate(result)
        assert json.loads(out)['success'] is True

    def test_error_result_passes(self):
        result = {'success': False, 'error': 'AccessDenied'}
        out = self._validate(result)
        assert json.loads(out)['success'] is False

    def test_empty_result_passes(self):
        result = {}
        out = self._validate(result)
        data = json.loads(out)
        assert '_validation' not in data  # no rejection

    # ---- suspicious IDs are rejected ----
    def test_all_zero_instance_id_is_rejected(self):
        result = {'success': True, 'instance_id': 'i-00000000'}
        from src.agent.core import _validate_tool_result_ids
        out = _validate_tool_result_ids(json.dumps(result))
        data = json.loads(out)
        assert data['success'] is False
        assert data.get('_validation') == 'suspicious_ids_rejected'

    def test_sequential_sg_id_is_rejected(self):
        result = {'success': True, 'sg': 'sg-12345678'}
        from src.agent.core import _validate_tool_result_ids
        out = _validate_tool_result_ids(json.dumps(result))
        data = json.loads(out)
        # sequential numeric IDs should fail
        assert data['success'] is False

    def test_rejected_result_contains_error_message(self):
        result = {'success': True, 'instance_id': 'i-00000000'}
        from src.agent.core import _validate_tool_result_ids
        out = _validate_tool_result_ids(json.dumps(result))
        data = json.loads(out)
        assert 'error' in data
        assert len(data['error']) > 10  # non-empty error message

    def test_validator_returns_string(self):
        from src.agent.core import _validate_tool_result_ids
        result = json.dumps({'success': True, 'message': 'ok'})
        out = _validate_tool_result_ids(result)
        assert isinstance(out, str)


class TestProcessMessageIsolatedSignature:
    """process_message_isolated() must accept tools_override and trust_tool_results."""

    def _make_agent(self):
        """Build a DevOpsAgent with minimal config and no real API keys."""
        import inspect
        from src.agent.core import DevOpsAgent
        sig = inspect.signature(DevOpsAgent.__init__)
        params = list(sig.parameters.keys())
        # DevOpsAgent takes a config_manager — create a minimal mock
        cfg = MagicMock()
        cfg.get.return_value = None
        cfg.claude_model = 'claude-sonnet-4-6'
        cfg.claude_max_tokens = 4096
        cfg.claude_temperature = 0.0
        with patch('src.agent.core.anthropic.Anthropic'):
            agent = DevOpsAgent(cfg)
        return agent

    def test_accepts_tools_override_param(self):
        import inspect
        from src.agent.core import DevOpsAgent
        sig = inspect.signature(DevOpsAgent.process_message_isolated)
        assert 'tools_override' in sig.parameters

    def test_accepts_trust_tool_results_param(self):
        import inspect
        from src.agent.core import DevOpsAgent
        sig = inspect.signature(DevOpsAgent.process_message_isolated)
        assert 'trust_tool_results' in sig.parameters

    def test_tools_override_default_is_none(self):
        import inspect
        from src.agent.core import DevOpsAgent
        sig = inspect.signature(DevOpsAgent.process_message_isolated)
        assert sig.parameters['tools_override'].default is None

    def test_trust_tool_results_default_is_true(self):
        import inspect
        from src.agent.core import DevOpsAgent
        sig = inspect.signature(DevOpsAgent.process_message_isolated)
        assert sig.parameters['trust_tool_results'].default is True

    def test_process_message_streaming_also_has_new_params(self):
        import inspect
        from src.agent.core import DevOpsAgent
        sig = inspect.signature(DevOpsAgent.process_message_streaming)
        assert 'tools_override' in sig.parameters
        assert 'trust_tool_results' in sig.parameters


class TestConvertToolListToOpenaiFormat:
    """_convert_tool_list_to_openai_format must convert any list without caching."""

    def test_converts_single_tool(self):
        from src.agent.core import DevOpsAgent
        tool = {
            'name': 'list_ec2',
            'description': 'List EC2 instances',
            'input_schema': {'type': 'object', 'properties': {}}
        }
        result = DevOpsAgent._convert_tool_list_to_openai_format([tool])
        assert len(result) == 1
        assert result[0]['type'] == 'function'
        assert result[0]['function']['name'] == 'list_ec2'

    def test_empty_list_returns_empty(self):
        from src.agent.core import DevOpsAgent
        assert DevOpsAgent._convert_tool_list_to_openai_format([]) == []

    def test_does_not_mutate_input(self):
        from src.agent.core import DevOpsAgent
        tools = [{'name': 'foo', 'description': 'bar', 'input_schema': {}}]
        DevOpsAgent._convert_tool_list_to_openai_format(tools)
        assert tools[0]['name'] == 'foo'

    def test_multiple_tools_all_converted(self):
        from src.agent.core import DevOpsAgent
        tools = [
            {'name': f'tool_{i}', 'description': f'desc {i}', 'input_schema': {}}
            for i in range(5)
        ]
        result = DevOpsAgent._convert_tool_list_to_openai_format(tools)
        assert len(result) == 5
        names = [r['function']['name'] for r in result]
        assert names == [f'tool_{i}' for i in range(5)]


class TestToolsOverrideRespected:
    """When tools_override is set, _call_claude_api and _call_kimi_api must use it."""

    def test_tools_override_stored_during_isolated_call(self):
        """
        Verify that _tools_override is set on the agent instance while
        process_message_isolated is executing (tested by patching the provider calls).
        """
        from src.agent.core import DevOpsAgent
        cfg = MagicMock()
        cfg.get.return_value = None
        cfg.claude_model = 'claude-sonnet-4-6'
        cfg.claude_max_tokens = 4096
        cfg.claude_temperature = 0.0

        captured_override = []

        def fake_call_claude(self_inner, *args, **kwargs):
            captured_override.append(getattr(self_inner, '_tools_override', 'NOT_SET'))
            return "mocked response"

        with patch('src.agent.core.anthropic.Anthropic'), \
             patch.object(DevOpsAgent, '_call_claude_api', fake_call_claude), \
             patch.object(DevOpsAgent, '_set_cloud_user_context'), \
             patch.object(DevOpsAgent, '_clear_cloud_user_context'):

            agent = DevOpsAgent(cfg)
            override_tools = [{'name': 'only_this_tool', 'description': '', 'input_schema': {}}]

            agent.process_message_isolated(
                user_message='test',
                conversation_history=[],
                tools_override=override_tools,
            )

        assert len(captured_override) == 1
        assert captured_override[0] == override_tools

    def test_tools_override_cleared_after_call(self):
        """_tools_override must be None after the call completes (cleanup check)."""
        from src.agent.core import DevOpsAgent
        cfg = MagicMock()
        cfg.get.return_value = None
        cfg.claude_model = 'claude-sonnet-4-6'
        cfg.claude_max_tokens = 4096
        cfg.claude_temperature = 0.0

        with patch('src.agent.core.anthropic.Anthropic'), \
             patch.object(DevOpsAgent, '_call_claude_api', return_value='mocked'), \
             patch.object(DevOpsAgent, '_set_cloud_user_context'), \
             patch.object(DevOpsAgent, '_clear_cloud_user_context'):

            agent = DevOpsAgent(cfg)
            override_tools = [{'name': 'tool_x', 'description': '', 'input_schema': {}}]
            agent.process_message_isolated(
                user_message='test',
                conversation_history=[],
                tools_override=override_tools,
            )

        # After the call, override must be cleared
        assert getattr(agent, '_tools_override', None) is None

    def test_trust_tool_results_cleared_after_call(self):
        """_trust_tool_results must be reset to True after the call completes."""
        from src.agent.core import DevOpsAgent
        cfg = MagicMock()
        cfg.get.return_value = None
        cfg.claude_model = 'claude-sonnet-4-6'
        cfg.claude_max_tokens = 4096
        cfg.claude_temperature = 0.0

        with patch('src.agent.core.anthropic.Anthropic'), \
             patch.object(DevOpsAgent, '_call_claude_api', return_value='mocked'), \
             patch.object(DevOpsAgent, '_set_cloud_user_context'), \
             patch.object(DevOpsAgent, '_clear_cloud_user_context'):

            agent = DevOpsAgent(cfg)
            agent.process_message_isolated(
                user_message='test',
                conversation_history=[],
                trust_tool_results=False,
            )

        assert getattr(agent, '_trust_tool_results', True) is True


# ===========================================================================
# PART 4 — app.py wiring (smoke tests via Flask test client)
# ===========================================================================

class TestAppWiringSmoke:
    """
    Smoke-test that the route-level wiring code (factory, scope_tools, prompt injection)
    behaves correctly.  Tests are pure-unit (no Flask HTTP requests, no DB writes)
    to avoid StaticPool session contamination of the shared in-memory test DB.
    """

    # ---- import sanity ----

    def test_chat_route_imports_factory_without_crash(self):
        """All symbols imported in the route must be importable at module level."""
        from services.devopsagent_prompts import (
            DevOpsAgentSessionFactory, detect_task_type,
            SANDBOX_SYSTEM_PROMPT, REAL_AGENT_SYSTEM_PROMPT,
        )
        assert DevOpsAgentSessionFactory is not None
        assert callable(detect_task_type)
        assert isinstance(SANDBOX_SYSTEM_PROMPT, str)
        assert isinstance(REAL_AGENT_SYSTEM_PROMPT, str)

    # ---- tools_override is non-None and is a subset ----

    def test_scope_tools_returns_non_empty_list_for_aws_message(self):
        """
        Route logic: scope_tools(agent.tool_definitions, detect_task_type(msg), max_tools)
        must return a non-empty list when the agent has at least one matching tool.
        """
        from services.devopsagent_prompts import DevOpsAgentSessionFactory, detect_task_type

        all_tools = [
            {'name': 'list_ec2_instances', 'description': '', 'input_schema': {}},
            {'name': 'list_pods', 'description': '', 'input_schema': {}},
            {'name': 'terraform_plan', 'description': '', 'input_schema': {}},
        ]
        factory = DevOpsAgentSessionFactory()
        task_type = detect_task_type('list my ec2 instances')
        result = factory.scope_tools(all_tools, task_type, max_tools=6)

        assert result is not None
        assert isinstance(result, list)
        assert len(result) > 0
        # ec2 tool should be in aws_scan group
        names = [t['name'] for t in result]
        assert 'list_ec2_instances' in names
        # k8s and terraform should NOT be included for this message
        assert 'list_pods' not in names
        assert 'terraform_plan' not in names

    def test_scope_tools_respects_max_tools_cap(self):
        """The max_tools cap must be enforced — simulates free-tier cap of 6."""
        from services.devopsagent_prompts import DevOpsAgentSessionFactory
        # 20 tools that all match 'aws_scan' group
        tools = [{'name': f'list_ec2_{i}', 'description': '', 'input_schema': {}} for i in range(20)]
        factory = DevOpsAgentSessionFactory()
        result = factory.scope_tools(tools, 'aws_scan', max_tools=6)
        assert len(result) == 6

    # ---- system prompt injection ----

    def test_real_agent_mode_context_contains_real_agent_marker(self):
        """
        Simulate what the /api/chat route does in real-agent mode:
        preferences_context gets the REAL_AGENT_SYSTEM_PROMPT appended.
        The final context must contain the grounding rules.
        """
        from services.devopsagent_prompts import (
            DevOpsAgentSessionFactory, REAL_AGENT_SYSTEM_PROMPT,
        )
        factory = DevOpsAgentSessionFactory()
        session = factory.create_real_agent_session(None)

        base_ctx = "User prefs: verbose mode."
        mode_prompt = REAL_AGENT_SYSTEM_PROMPT.format(
            cloud_provider='configured providers',
            user_tier='free',
            session_id=session.session_id,
        )
        final_ctx = base_ctx + '\n\n' + mode_prompt

        assert 'REAL AGENT MODE' in final_ctx
        assert 'never fabricat' in final_ctx.lower() or 'do not fabricat' in final_ctx.lower() or 'forbid' in final_ctx.lower()
        assert session.session_id in final_ctx

    def test_sandbox_mode_context_contains_sandbox_marker(self):
        """
        Simulate what the route does in sandbox mode:
        preferences_context gets the SANDBOX_SYSTEM_PROMPT appended.
        The final context must contain the sandbox teaching rules.
        """
        from services.devopsagent_prompts import (
            DevOpsAgentSessionFactory, SANDBOX_SYSTEM_PROMPT,
        )
        factory = DevOpsAgentSessionFactory()
        factory.create_sandbox_session()

        base_ctx = "User prefs: sandbox learner."
        final_ctx = base_ctx + '\n\n' + SANDBOX_SYSTEM_PROMPT

        assert 'SANDBOX' in final_ctx.upper()
        assert '[SANDBOX SIMULATION]' in final_ctx

    def test_real_agent_mode_context_has_real_agent_header(self):
        """Real-agent context heading must say REAL AGENT MODE, not SANDBOX."""
        from services.devopsagent_prompts import REAL_AGENT_SYSTEM_PROMPT
        rendered = REAL_AGENT_SYSTEM_PROMPT.format(
            cloud_provider='AWS', user_tier='professional', session_id='sess123'
        )
        # The mode header is REAL AGENT MODE
        assert 'REAL AGENT MODE' in rendered
        # The mode header is NOT SANDBOX / LEARNING MODE
        assert 'SANDBOX / LEARNING MODE' not in rendered

    # ---- trust_tool_results kwarg comes from model_config ----

    def test_free_tier_config_sets_trust_to_false(self):
        """
        Route logic: model_config.trust_tool_results is False for free/starter
        (Kimi tiers) so that the ID validator runs.
        """
        from services.model_router import resolve_model_with_preference
        cfg = resolve_model_with_preference('free', None)
        assert cfg.trust_tool_results is False

    def test_professional_tier_config_sets_trust_to_true(self):
        """Route logic: model_config.trust_tool_results is True for pro/biz (Claude)."""
        from services.model_router import resolve_model_with_preference
        cfg = resolve_model_with_preference('professional', None)
        assert cfg.trust_tool_results is True

    # ---- full round-trip mock (no DB / no HTTP) ----

    def test_route_logic_scope_and_prompt_roundtrip(self):
        """
        Simulate the exact logic the route runs (sans DB), confirming that
        tools_override and preferences_context are built correctly end-to-end.
        """
        from services.devopsagent_prompts import (
            DevOpsAgentSessionFactory, detect_task_type,
            SANDBOX_SYSTEM_PROMPT, REAL_AGENT_SYSTEM_PROMPT,
        )
        from services.model_router import resolve_model_with_preference

        all_tools = [
            {'name': 'list_ec2_instances', 'description': '', 'input_schema': {}},
            {'name': 'list_pods', 'description': '', 'input_schema': {}},
            {'name': 'terraform_plan', 'description': '', 'input_schema': {}},
            {'name': 'git_commit', 'description': '', 'input_schema': {}},
        ]
        message = 'list my ec2 instances'
        tier_name = 'free'
        sandbox_active = False

        model_config = resolve_model_with_preference(tier_name, None)
        factory = DevOpsAgentSessionFactory()
        task_type = detect_task_type(message)
        filtered_tools = factory.scope_tools(all_tools, task_type, model_config.max_tools)

        if sandbox_active:
            session = factory.create_sandbox_session()
            preferences_context = SANDBOX_SYSTEM_PROMPT
        else:
            session = factory.create_real_agent_session(None)
            preferences_context = REAL_AGENT_SYSTEM_PROMPT.format(
                cloud_provider='configured providers',
                user_tier=tier_name,
                session_id=session.session_id,
            )

        # Assert tool scoping
        assert isinstance(filtered_tools, list)
        assert 0 < len(filtered_tools) <= model_config.max_tools
        names = [t['name'] for t in filtered_tools]
        assert 'list_ec2_instances' in names

        # Assert prompt
        assert 'REAL AGENT MODE' in preferences_context
        assert session.session_id in preferences_context

        # Assert trust flag
        assert model_config.trust_tool_results is False  # free = Kimi
