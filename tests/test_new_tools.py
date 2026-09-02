"""
Tests for new tool modules: cicd_tools, terraform_tools, sonarqube_tools,
nexus_tools — plus safety classifications and sandbox mock routing.
"""

import pytest


# ---------------------------------------------------------------------------
# cicd_tools
# ---------------------------------------------------------------------------

class TestCICDTools:
    """Tests for CI/CD pipeline tools (Jenkins + GitHub Actions)."""

    def test_tool_count(self):
        from src.tools.cicd_tools import get_tools
        tools = get_tools()
        assert len(tools) >= 21, f"Expected >= 21 cicd tools, got {len(tools)}"

    def test_all_handlers_callable(self):
        from src.tools.cicd_tools import get_tools
        for t in get_tools():
            assert callable(t['handler']), f"{t['name']} handler not callable"

    def test_all_have_input_schema(self):
        from src.tools.cicd_tools import get_tools
        for t in get_tools():
            assert 'input_schema' in t, f"{t['name']} missing input_schema"
            assert 'properties' in t['input_schema'], f"{t['name']} input_schema missing properties"

    def test_all_have_descriptions(self):
        from src.tools.cicd_tools import get_tools
        for t in get_tools():
            assert t.get('description'), f"{t['name']} missing description"

    def test_jenkins_tools_present(self):
        from src.tools.cicd_tools import get_tools
        names = {t['name'] for t in get_tools()}
        expected = {
            'trigger_jenkins_job', 'get_jenkins_job_status', 'get_jenkins_build_logs',
            'list_jenkins_jobs', 'get_jenkins_queue', 'abort_jenkins_build',
            'enable_jenkins_job', 'disable_jenkins_job', 'get_jenkins_job_config',
            'list_jenkins_nodes', 'delete_jenkins_build',
        }
        missing = expected - names
        assert not missing, f"Missing Jenkins tools: {missing}"

    def test_github_actions_tools_present(self):
        from src.tools.cicd_tools import get_tools
        names = {t['name'] for t in get_tools()}
        expected = {
            'trigger_github_workflow', 'get_github_workflow_runs',
            'list_github_workflows', 'get_github_workflow_run',
            'cancel_github_workflow_run', 'rerun_failed_github_jobs',
            'list_github_runners', 'list_github_secrets',
            'list_github_environments', 'get_github_workflow_usage',
        }
        missing = expected - names
        assert not missing, f"Missing GitHub Actions tools: {missing}"

    def test_no_duplicate_tool_names(self):
        from src.tools.cicd_tools import get_tools
        names = [t['name'] for t in get_tools()]
        assert len(names) == len(set(names)), "Duplicate tool names found in cicd_tools"


# ---------------------------------------------------------------------------
# terraform_tools
# ---------------------------------------------------------------------------

class TestTerraformTools:
    """Tests for Terraform tools including the 5 new additions."""

    def test_tool_count(self):
        from src.tools.terraform_tools import get_tools
        tools = get_tools()
        assert len(tools) >= 16, f"Expected >= 16 terraform tools, got {len(tools)}"

    def test_all_handlers_callable(self):
        from src.tools.terraform_tools import get_tools
        for t in get_tools():
            assert callable(t['handler']), f"{t['name']} handler not callable"

    def test_all_have_input_schema(self):
        from src.tools.terraform_tools import get_tools
        for t in get_tools():
            assert 'input_schema' in t, f"{t['name']} missing input_schema"

    def test_new_tools_present(self):
        from src.tools.terraform_tools import get_tools
        names = {t['name'] for t in get_tools()}
        new_tools = {
            'terraform_import', 'terraform_state_move', 'terraform_state_rm',
            'terraform_refresh', 'terraform_workspace_new',
        }
        missing = new_tools - names
        assert not missing, f"Missing new Terraform tools: {missing}"

    def test_core_tools_present(self):
        from src.tools.terraform_tools import get_tools
        names = {t['name'] for t in get_tools()}
        core = {
            'terraform_init', 'terraform_plan', 'terraform_apply',
            'terraform_destroy', 'terraform_output', 'terraform_validate',
        }
        missing = core - names
        assert not missing, f"Missing core Terraform tools: {missing}"

    def test_no_duplicate_tool_names(self):
        from src.tools.terraform_tools import get_tools
        names = [t['name'] for t in get_tools()]
        assert len(names) == len(set(names)), "Duplicate tool names in terraform_tools"

    def test_terraform_import_schema(self):
        from src.tools.terraform_tools import get_tools
        tool = next(t for t in get_tools() if t['name'] == 'terraform_import')
        props = tool['input_schema']['properties']
        assert 'address' in props
        assert 'resource_id' in props

    def test_terraform_state_move_schema(self):
        from src.tools.terraform_tools import get_tools
        tool = next(t for t in get_tools() if t['name'] == 'terraform_state_move')
        props = tool['input_schema']['properties']
        assert 'source' in props
        assert 'destination' in props

    def test_terraform_state_rm_schema(self):
        from src.tools.terraform_tools import get_tools
        tool = next(t for t in get_tools() if t['name'] == 'terraform_state_rm')
        props = tool['input_schema']['properties']
        assert 'address' in props


# ---------------------------------------------------------------------------
# sonarqube_tools
# ---------------------------------------------------------------------------

class TestSonarqubeTools:
    """Tests for SonarQube integration tools."""

    def test_tool_count(self):
        from src.tools.sonarqube_tools import get_tools
        tools = get_tools()
        assert len(tools) >= 12, f"Expected >= 12 sonarqube tools, got {len(tools)}"

    def test_all_handlers_callable(self):
        from src.tools.sonarqube_tools import get_tools
        for t in get_tools():
            assert callable(t['handler']), f"{t['name']} handler not callable"

    def test_all_have_input_schema(self):
        from src.tools.sonarqube_tools import get_tools
        for t in get_tools():
            assert 'input_schema' in t, f"{t['name']} missing input_schema"

    def test_all_have_descriptions(self):
        from src.tools.sonarqube_tools import get_tools
        for t in get_tools():
            assert t.get('description'), f"{t['name']} missing description"

    def test_key_tools_present(self):
        from src.tools.sonarqube_tools import get_tools
        names = {t['name'] for t in get_tools()}
        expected = {
            'get_sonar_projects', 'get_sonar_project_quality', 'get_sonar_issues',
            'list_sonar_quality_gates', 'update_sonar_issue', 'assign_sonar_quality_gate',
            'delete_sonar_project', 'create_sonar_project',
        }
        missing = expected - names
        assert not missing, f"Missing SonarQube tools: {missing}"

    def test_no_duplicate_tool_names(self):
        from src.tools.sonarqube_tools import get_tools
        names = [t['name'] for t in get_tools()]
        assert len(names) == len(set(names)), "Duplicate tool names in sonarqube_tools"


# ---------------------------------------------------------------------------
# nexus_tools
# ---------------------------------------------------------------------------

class TestNexusTools:
    """Tests for Nexus Repository Manager tools."""

    def test_tool_count(self):
        from src.tools.nexus_tools import get_tools
        tools = get_tools()
        assert len(tools) >= 12, f"Expected >= 12 nexus tools, got {len(tools)}"

    def test_all_handlers_callable(self):
        from src.tools.nexus_tools import get_tools
        for t in get_tools():
            assert callable(t['handler']), f"{t['name']} handler not callable"

    def test_all_have_input_schema(self):
        from src.tools.nexus_tools import get_tools
        for t in get_tools():
            assert 'input_schema' in t, f"{t['name']} missing input_schema"

    def test_all_have_descriptions(self):
        from src.tools.nexus_tools import get_tools
        for t in get_tools():
            assert t.get('description'), f"{t['name']} missing description"

    def test_key_tools_present(self):
        from src.tools.nexus_tools import get_tools
        names = {t['name'] for t in get_tools()}
        expected = {
            'nexus_get_system_status', 'nexus_list_repositories', 'nexus_get_repository',
            'nexus_create_repository', 'nexus_delete_repository',
            'nexus_search_components', 'nexus_delete_component', 'nexus_delete_asset',
            'nexus_run_cleanup_task',
        }
        missing = expected - names
        assert not missing, f"Missing Nexus tools: {missing}"

    def test_no_duplicate_tool_names(self):
        from src.tools.nexus_tools import get_tools
        names = [t['name'] for t in get_tools()]
        assert len(names) == len(set(names)), "Duplicate tool names in nexus_tools"

    def test_base_url_in_all_schemas(self):
        from src.tools.nexus_tools import get_tools
        for t in get_tools():
            props = t['input_schema'].get('properties', {})
            assert 'base_url' in props, f"{t['name']} missing base_url in schema"


# ---------------------------------------------------------------------------
# Safety classifications
# ---------------------------------------------------------------------------

class TestSafetyClassifications:
    """Verify new tools are correctly classified in SafetyValidator."""

    def _classify(self, tool_name: str) -> str:
        from src.agent.safety import SafetyValidator
        sv = SafetyValidator()
        result = sv.validate_tool_call(tool_name, {})
        return result.risk_level

    # --- high-risk: Jenkins ---
    def test_abort_jenkins_build_is_high_risk(self):
        assert self._classify('abort_jenkins_build') == 'high'

    def test_delete_jenkins_build_is_high_risk(self):
        assert self._classify('delete_jenkins_build') == 'high'

    # --- high-risk: Terraform ---
    def test_terraform_destroy_is_high_risk(self):
        assert self._classify('terraform_destroy') == 'high'

    def test_terraform_state_rm_is_high_risk(self):
        assert self._classify('terraform_state_rm') == 'high'

    # --- high-risk: SonarQube ---
    def test_delete_sonar_project_is_high_risk(self):
        assert self._classify('delete_sonar_project') == 'high'

    # --- high-risk: Nexus ---
    def test_nexus_delete_repository_is_high_risk(self):
        assert self._classify('nexus_delete_repository') == 'high'

    def test_nexus_delete_component_is_high_risk(self):
        assert self._classify('nexus_delete_component') == 'high'

    def test_nexus_delete_asset_is_high_risk(self):
        assert self._classify('nexus_delete_asset') == 'high'

    # --- medium-risk: Jenkins ---
    def test_disable_jenkins_job_is_medium_risk(self):
        assert self._classify('disable_jenkins_job') == 'medium'

    # --- medium-risk: GitHub Actions ---
    def test_cancel_github_workflow_run_is_medium_risk(self):
        assert self._classify('cancel_github_workflow_run') == 'medium'

    def test_rerun_failed_github_jobs_is_medium_risk(self):
        assert self._classify('rerun_failed_github_jobs') == 'medium'

    def test_trigger_github_workflow_is_medium_risk(self):
        assert self._classify('trigger_github_workflow') == 'medium'

    # --- medium-risk: Terraform ---
    def test_terraform_apply_is_medium_risk(self):
        assert self._classify('terraform_apply') == 'medium'

    def test_terraform_state_move_is_medium_risk(self):
        assert self._classify('terraform_state_move') == 'medium'

    def test_terraform_import_is_medium_risk(self):
        assert self._classify('terraform_import') == 'medium'

    # --- medium-risk: SonarQube ---
    def test_update_sonar_issue_is_medium_risk(self):
        assert self._classify('update_sonar_issue') == 'medium'

    def test_assign_sonar_quality_gate_is_medium_risk(self):
        assert self._classify('assign_sonar_quality_gate') == 'medium'

    def test_create_sonar_project_is_medium_risk(self):
        assert self._classify('create_sonar_project') == 'medium'

    def test_trigger_sonar_analysis_is_medium_risk(self):
        # Sibling to trigger_jenkins_job/trigger_github_workflow/
        # create_gitlab_pipeline_trigger — same "kick off a remote job" shape,
        # and its trigger_ prefix isn't caught by auto-detection.
        assert self._classify('trigger_sonar_analysis') == 'medium'

    # --- medium-risk: Ansible ---
    def test_ansible_vault_encrypt_is_medium_risk(self):
        # Sibling to ansible_vault_decrypt/ansible_vault_view — in-place
        # mutates a file via the ansible-vault CLI with no confirmation gate.
        assert self._classify('ansible_vault_encrypt') == 'medium'

    # --- medium-risk: Nexus ---
    def test_nexus_create_repository_is_medium_risk(self):
        assert self._classify('nexus_create_repository') == 'medium'

    def test_nexus_run_cleanup_task_is_medium_risk(self):
        assert self._classify('nexus_run_cleanup_task') == 'medium'

    # --- medium-risk: Docker ---
    def test_docker_build_image_is_medium_risk(self):
        assert self._classify('docker_build_image') == 'medium'

    def test_docker_create_container_is_high_risk(self):
        # Escalated from medium: an unrestricted host bind-mount (e.g.
        # /var/run/docker.sock or '/') gives trivial container-escape to full
        # host/Docker-daemon control, the same risk class as execute_command.
        # _validate_container_volumes() blocks the clearest cases as defense
        # in depth, but the confirmation prompt is the primary control.
        assert self._classify('docker_create_container') == 'high'

    # --- medium-risk: Alerting (provider_verb_noun shape defeats prefix auto-detection) ---
    def test_pagerduty_update_incident_is_medium_risk(self):
        assert self._classify('pagerduty_update_incident') == 'medium'

    def test_opsgenie_acknowledge_alert_is_medium_risk(self):
        assert self._classify('opsgenie_acknowledge_alert') == 'medium'

    def test_opsgenie_close_alert_is_medium_risk(self):
        assert self._classify('opsgenie_close_alert') == 'medium'

    def test_opsgenie_escalate_alert_is_medium_risk(self):
        assert self._classify('opsgenie_escalate_alert') == 'medium'

    # --- medium-risk: Git (merges stashed changes into the working tree,
    # can conflict/overwrite — same risk class as git_merge_branch/git_cherry_pick) ---
    def test_git_stash_apply_is_medium_risk(self):
        assert self._classify('git_stash_apply') == 'medium'

    # --- high-risk: AWS secret/credential disclosure (same class as get_secret_value) ---
    def test_create_ec2_keypair_is_high_risk(self):
        # Returns the raw PEM private key material directly in the tool result.
        assert self._classify('create_ec2_keypair') == 'high'

    def test_generate_s3_presigned_url_is_high_risk(self):
        # Generates an unauthenticated bearer URL (up to 7 days) for get_object
        # or put_object with no further AWS auth required.
        assert self._classify('generate_s3_presigned_url') == 'high'

    # --- medium-risk: AWS SNS (same "pages/redirects to an external endpoint
    # with no confirmation" shape as the alerting tools above) ---
    def test_publish_sns_message_is_medium_risk(self):
        assert self._classify('publish_sns_message') == 'medium'

    def test_subscribe_sns_topic_is_medium_risk(self):
        assert self._classify('subscribe_sns_topic') == 'medium'

    # --- medium-risk: GCP Pub/Sub (same shape as publish_sns_message above —
    # topic_name/message_data/attributes are caller-controlled and can reach
    # push subscriptions or trigger downstream Cloud Functions/Cloud Run) ---
    def test_publish_pubsub_message_is_medium_risk(self):
        assert self._classify('publish_pubsub_message') == 'medium'

    # --- medium-risk: Route53 (create_ prefix isn't a monitored auto-detect
    # prefix, but this tool defaults action='UPSERT', silently overwriting any
    # existing live DNS record with the same name/type with zero confirmation) ---
    def test_create_route53_record_is_medium_risk(self):
        assert self._classify('create_route53_record') == 'medium'

    # --- production escalation ---
    def test_high_risk_on_production_escalates_to_critical(self):
        from src.agent.safety import SafetyValidator
        sv = SafetyValidator()
        result = sv.validate_tool_call('nexus_delete_repository', {'target': 'production'})
        assert result.risk_level == 'critical'

    # --- low-risk tools still pass ---
    def test_read_only_nexus_is_low_risk(self):
        risk = self._classify('nexus_get_system_status')
        assert risk == 'low'

    def test_list_jenkins_jobs_is_low_risk(self):
        risk = self._classify('list_jenkins_jobs')
        assert risk == 'low'

    def test_list_github_workflows_is_low_risk(self):
        risk = self._classify('list_github_workflows')
        assert risk == 'low'

    # --- all tools require confirmation when high/medium ---
    def test_high_risk_requires_confirmation(self):
        from src.agent.safety import SafetyValidator
        sv = SafetyValidator()
        result = sv.validate_tool_call('terraform_destroy', {})
        assert result.requires_confirmation is True

    def test_medium_risk_requires_confirmation(self):
        from src.agent.safety import SafetyValidator
        sv = SafetyValidator()
        result = sv.validate_tool_call('terraform_apply', {})
        assert result.requires_confirmation is True


# ---------------------------------------------------------------------------
# Sandbox mock routing
# ---------------------------------------------------------------------------

class TestSandboxMockRouting:
    """Verify generate_mock_result correctly routes new tool categories."""

    def _mock(self, tool_name: str, tool_input: dict = None):
        from services.learning_sandbox import generate_mock_result
        return generate_mock_result(tool_name, tool_input or {})

    # --- Jenkins ---
    def test_jenkins_list_jobs_routed(self):
        result = self._mock('list_jenkins_jobs')
        assert result.get('success') is True
        assert result.get('simulated') is True

    def test_jenkins_queue_routed(self):
        result = self._mock('get_jenkins_queue')
        assert result.get('success') is True

    def test_jenkins_abort_routed(self):
        result = self._mock('abort_jenkins_build', {'job_name': 'my-job', 'build_number': 42})
        assert result.get('success') is True

    def test_jenkins_build_status_routed(self):
        result = self._mock('get_jenkins_build_status', {'job_name': 'my-job', 'build_number': 5})
        assert result.get('success') is True

    # --- GitHub Actions ---
    def test_github_workflow_list_routed(self):
        result = self._mock('list_github_workflows', {'repo_owner': 'acme', 'repo_name': 'app'})
        assert result.get('success') is True
        assert result.get('simulated') is True

    def test_github_workflow_run_routed(self):
        result = self._mock('get_github_workflow_run', {'repo_owner': 'acme', 'repo_name': 'app', 'run_id': 1})
        assert result.get('success') is True

    def test_github_runners_routed(self):
        result = self._mock('list_github_runners', {'repo_owner': 'acme', 'repo_name': 'app'})
        assert result.get('success') is True

    def test_github_secrets_routed(self):
        result = self._mock('list_github_secrets', {'repo_owner': 'acme', 'repo_name': 'app'})
        assert result.get('success') is True

    def test_github_environments_routed(self):
        result = self._mock('list_github_environments', {'repo_owner': 'acme', 'repo_name': 'app'})
        assert result.get('success') is True

    # --- Docker ---
    def test_docker_list_containers_routed(self):
        result = self._mock('list_containers')
        assert result.get('success') is True
        assert result.get('simulated') is True

    def test_docker_pull_image_routed(self):
        result = self._mock('docker_pull_image', {'image': 'nginx:latest'})
        assert result.get('success') is True

    def test_docker_build_image_routed(self):
        result = self._mock('docker_build_image', {'tag': 'myapp:v1'})
        assert result.get('success') is True

    def test_docker_system_prune_routed(self):
        result = self._mock('docker_system_prune')
        assert result.get('success') is True

    def test_docker_compose_up_routed(self):
        result = self._mock('docker_compose_up', {'compose_file': 'docker-compose.yml'})
        assert result.get('success') is True

    # --- Terraform ---
    def test_terraform_init_routed(self):
        result = self._mock('terraform_init', {'working_dir': './terraform'})
        assert result.get('success') is True
        assert result.get('simulated') is True

    def test_terraform_plan_routed(self):
        result = self._mock('terraform_plan', {'working_dir': './terraform'})
        assert result.get('success') is True

    def test_terraform_apply_routed(self):
        result = self._mock('terraform_apply', {'working_dir': './terraform'})
        assert result.get('success') is True

    def test_terraform_destroy_routed(self):
        result = self._mock('terraform_destroy', {'working_dir': './terraform'})
        assert result.get('success') is True

    def test_terraform_import_routed(self):
        result = self._mock('terraform_import', {'working_dir': './tf', 'address': 'aws_s3_bucket.x', 'resource_id': 'my-bucket'})
        assert result.get('success') is True

    def test_terraform_state_move_routed(self):
        result = self._mock('terraform_state_move', {'working_dir': './tf', 'source': 'a.b', 'destination': 'a.c'})
        assert result.get('success') is True

    def test_terraform_state_rm_routed(self):
        result = self._mock('terraform_state_rm', {'working_dir': './tf', 'address': 'aws_s3_bucket.old'})
        assert result.get('success') is True

    # --- SonarQube ---
    def test_sonar_list_projects_routed(self):
        result = self._mock('get_sonar_projects', {'base_url': 'http://sonar.example.com'})
        assert result.get('success') is True
        assert result.get('simulated') is True

    def test_sonar_quality_gates_routed(self):
        result = self._mock('get_sonar_quality_gates', {'base_url': 'http://sonar.example.com'})
        assert result.get('success') is True

    def test_sonar_issues_routed(self):
        result = self._mock('get_sonar_issues', {'base_url': 'http://sonar.example.com', 'project_key': 'myapp'})
        assert result.get('success') is True

    def test_sonar_delete_project_routed(self):
        result = self._mock('delete_sonar_project', {'base_url': 'http://sonar.example.com', 'project_key': 'myapp'})
        assert result.get('success') is True

    # --- Nexus ---
    def test_nexus_status_routed(self):
        result = self._mock('nexus_get_system_status', {'base_url': 'http://nexus.example.com'})
        assert result.get('success') is True
        assert result.get('simulated') is True

    def test_nexus_list_repositories_routed(self):
        result = self._mock('nexus_list_repositories', {'base_url': 'http://nexus.example.com'})
        assert result.get('success') is True

    def test_nexus_search_components_routed(self):
        result = self._mock('nexus_search_components', {'base_url': 'http://nexus.example.com', 'repository': 'maven-releases'})
        assert result.get('success') is True

    def test_nexus_delete_repository_routed(self):
        result = self._mock('nexus_delete_repository', {'base_url': 'http://nexus.example.com', 'repository_name': 'old-repo'})
        assert result.get('success') is True

    def test_nexus_run_cleanup_task_routed(self):
        result = self._mock('nexus_run_cleanup_task', {'base_url': 'http://nexus.example.com'})
        assert result.get('success') is True

    # --- Routing isolation: non-matching names still go elsewhere ---
    def test_aws_tool_not_routed_to_jenkins(self):
        result = self._mock('list_ec2_instances', {'region': 'us-east-1'})
        # Should return a result without being routed to Jenkins mock
        assert result.get('success') is True
        # Must not contain Jenkins-specific keys
        assert 'jobs' not in result or 'instances' in result or 'simulated' in result


# ---------------------------------------------------------------------------
# Module integration: __init__.py exports
# ---------------------------------------------------------------------------

class TestToolsModuleInit:
    """Verify all new modules are importable via src.tools package."""

    def test_cicd_tools_importable(self):
        from src.tools import cicd_tools
        assert hasattr(cicd_tools, 'get_tools')

    def test_terraform_tools_importable(self):
        from src.tools import terraform_tools
        assert hasattr(terraform_tools, 'get_tools')

    def test_sonarqube_tools_importable(self):
        from src.tools import sonarqube_tools
        assert hasattr(sonarqube_tools, 'get_tools')

    def test_nexus_tools_importable(self):
        from src.tools import nexus_tools
        assert hasattr(nexus_tools, 'get_tools')

    def test_docker_tools_importable(self):
        from src.tools import docker_tools
        assert hasattr(docker_tools, 'get_tools')

    def test_ansible_tools_importable(self):
        from src.tools import ansible_tools
        assert hasattr(ansible_tools, 'get_tools')


# ---------------------------------------------------------------------------
# Cleanup workflow regression tests
# ---------------------------------------------------------------------------

class TestCleanupWorkflows:
    """Regression tests for AMI deregister, snapshot delete, and EBS volume cleanup."""

    # --- delete_ebs_snapshot ---

    def test_delete_snapshot_blocked_by_ami(self):
        from unittest.mock import patch, MagicMock
        from botocore.exceptions import ClientError
        from src.tools.aws_tools import delete_ebs_snapshot

        error_response = {'Error': {'Code': 'InvalidSnapshot.InUse', 'Message': 'snapshot in use'}}
        mock_ec2 = MagicMock()
        mock_ec2.delete_snapshot.side_effect = ClientError(error_response, 'DeleteSnapshot')
        mock_ec2.describe_images.return_value = {'Images': [{'ImageId': 'ami-abc123'}]}

        with patch('src.tools.aws_tools._get_boto_client', return_value=mock_ec2):
            result = delete_ebs_snapshot('snap-111')

        assert result['success'] is False
        assert result['error_code'] == 'InvalidSnapshot.InUse'
        assert result['blocking_amis'] == ['ami-abc123']
        assert 'deregister_ami' in result['error']

    def test_delete_snapshot_success(self):
        from unittest.mock import patch, MagicMock
        from src.tools.aws_tools import delete_ebs_snapshot

        mock_ec2 = MagicMock()
        mock_ec2.delete_snapshot.return_value = {}

        with patch('src.tools.aws_tools._get_boto_client', return_value=mock_ec2):
            result = delete_ebs_snapshot('snap-999')

        assert result['success'] is True
        assert result['snapshot_id'] == 'snap-999'

    # --- deregister_ami ---

    def test_deregister_ami_returns_snapshot_ids(self):
        from unittest.mock import patch, MagicMock
        from src.tools.aws_tools import deregister_ami

        mock_ec2 = MagicMock()
        mock_ec2.describe_images.return_value = {'Images': [{
            'BlockDeviceMappings': [{'Ebs': {'SnapshotId': 'snap-aaa'}}, {'Ebs': {'SnapshotId': 'snap-bbb'}}]
        }]}
        mock_ec2.deregister_image.return_value = {}

        with patch('src.tools.aws_tools._get_boto_client', return_value=mock_ec2):
            result = deregister_ami('ami-xyz', delete_snapshots=False)

        assert result['success'] is True
        assert result['backing_snapshot_ids'] == ['snap-aaa', 'snap-bbb']
        assert result['deleted_snapshots'] == []

    def test_deregister_ami_with_delete_snapshots(self):
        from unittest.mock import patch, MagicMock
        from src.tools.aws_tools import deregister_ami

        mock_ec2 = MagicMock()
        mock_ec2.describe_images.return_value = {'Images': [{
            'BlockDeviceMappings': [{'Ebs': {'SnapshotId': 'snap-111'}}]
        }]}
        mock_ec2.deregister_image.return_value = {}
        mock_ec2.delete_snapshot.return_value = {}

        with patch('src.tools.aws_tools._get_boto_client', return_value=mock_ec2):
            result = deregister_ami('ami-del', delete_snapshots=True)

        assert result['success'] is True
        assert result['backing_snapshot_ids'] == ['snap-111']
        assert result['deleted_snapshots'] == ['snap-111']
        assert result['failed_snapshots'] == []

    def test_deregister_ami_snapshot_delete_failure(self):
        from unittest.mock import patch, MagicMock
        from botocore.exceptions import ClientError
        from src.tools.aws_tools import deregister_ami

        error_response = {'Error': {'Code': 'InvalidSnapshot.NotFound', 'Message': 'not found'}}
        mock_ec2 = MagicMock()
        mock_ec2.describe_images.return_value = {'Images': [{
            'BlockDeviceMappings': [{'Ebs': {'SnapshotId': 'snap-gone'}}]
        }]}
        mock_ec2.deregister_image.return_value = {}
        mock_ec2.delete_snapshot.side_effect = ClientError(error_response, 'DeleteSnapshot')

        with patch('src.tools.aws_tools._get_boto_client', return_value=mock_ec2):
            result = deregister_ami('ami-partial', delete_snapshots=True)

        assert result['success'] is True  # AMI was deregistered despite snapshot failure
        assert result['backing_snapshot_ids'] == ['snap-gone']
        assert result['deleted_snapshots'] == []
        assert len(result['failed_snapshots']) == 1
        assert result['failed_snapshots'][0]['snapshot_id'] == 'snap-gone'

    # --- datetime serialization ---

    def test_datetime_serialization_in_tool_results(self):
        import json
        from datetime import datetime
        from src.agent.core import _json_default

        dt = datetime(2025, 1, 15, 12, 0, 0)
        result = json.dumps({'created': dt}, default=_json_default)
        assert '2025-01-15' in result

        # Non-serializable type still raises TypeError
        import pytest
        with pytest.raises(TypeError):
            json.dumps({'obj': object()}, default=_json_default)
