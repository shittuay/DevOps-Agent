"""Safety validation layer for DevOps Agent."""
import re
from typing import List, Optional, Dict, Any
from dataclasses import dataclass


@dataclass
class ValidationResult:
    """Result of a safety validation check."""

    is_safe: bool
    reason: Optional[str] = None
    requires_confirmation: bool = False
    risk_level: str = 'low'  # low, medium, high, critical


class SafetyValidator:
    """Validates operations for safety before execution."""

    # Destructive operation patterns
    DESTRUCTIVE_PATTERNS = [
        # Delete operations
        r'\bdelete\b.*\b(all|everything|\*)\b',
        r'\bremove\b.*\b(all|everything|\*)\b',
        r'\bdrop\b.*\b(database|table|all)\b',
        r'\btruncate\b.*\btable\b',

        # System commands
        r'\brm\s+-rf\s+/',
        r'\brm\s+-rf\s+\*',
        r'\bmkfs\b',
        r'\bdd\s+if=',
        r'>\s*/dev/sd[a-z]',

        # Kubernetes destructive
        r'\bkubectl\s+delete\b.*\b(all|namespace)\b',
        r'\bkubectl\s+delete\b.*-A\b',
        r'\bkubectl\s+delete\b.*--all\b',

        # AWS destructive
        r'\bterminate-instances\b',
        r'\bdelete-stack\b',
        r'\bdelete-cluster\b',
        r'\bdelete-bucket\b',

        # Format/wipe operations
        r'\bformat\b',
        r'\bwipe\b',
    ]

    # High-risk operation patterns (require confirmation)
    HIGH_RISK_PATTERNS = [
        # Production operations
        r'\bprod(uction)?\b',
        r'\blive\b',

        # Scale operations
        r'\bscale\b.*\b(down|to\s+0)\b',

        # Restart operations
        r'\brestart\b',
        r'\breboot\b',

        # Data operations
        r'\bmigrat(e|ion)\b',
        r'\brollback\b',
    ]

    # Pentest tool patterns (require additional authorization)
    PENTEST_TOOL_PATTERNS = [
        r'\bnmap\b',
        r'\bnikto\b',
        r'\bsqlmap\b',
        r'\bmetasploit\b',
        r'\bburp\b',
        r'\bzap\b',
        r'\bhydra\b',
        r'\bjohn\b',
        r'\bhashcat\b',
        r'\bwpscan\b',
        r'\bwireshark\b',
        r'\btcpdump\b',
    ]

    def __init__(self, dangerous_commands: Optional[List[str]] = None, pentest_config: Optional[Dict[str, Any]] = None):
        """
        Initialize safety validator.

        Args:
            dangerous_commands: List of dangerous command patterns
            pentest_config: Penetration testing configuration
        """
        self.dangerous_commands = dangerous_commands or []
        self.pentest_config = pentest_config or {}

    def validate_command(self, command: str) -> ValidationResult:
        """
        Validate a shell command for safety.

        Args:
            command: Command to validate

        Returns:
            ValidationResult with safety assessment
        """
        command_lower = command.lower()

        # Check against configured dangerous commands
        for dangerous_pattern in self.dangerous_commands:
            if dangerous_pattern.lower() in command_lower:
                return ValidationResult(
                    is_safe=False,
                    reason=f"Command matches dangerous pattern: {dangerous_pattern}",
                    requires_confirmation=False,
                    risk_level='critical'
                )

        # Check destructive patterns
        for pattern in self.DESTRUCTIVE_PATTERNS:
            if re.search(pattern, command_lower):
                return ValidationResult(
                    is_safe=False,
                    reason=f"Command matches destructive pattern: {pattern}",
                    requires_confirmation=False,
                    risk_level='critical'
                )

        # Check pentest tool patterns
        for pattern in self.PENTEST_TOOL_PATTERNS:
            if re.search(pattern, command_lower):
                pentest_enabled = self.pentest_config.get('enabled', False)
                if not pentest_enabled:
                    return ValidationResult(
                        is_safe=False,
                        reason=f"Penetration testing tools disabled in configuration",
                        requires_confirmation=False,
                        risk_level='critical'
                    )

                return ValidationResult(
                    is_safe=True,
                    reason=f"Command uses penetration testing tool - requires authorization",
                    requires_confirmation=True,
                    risk_level='high'
                )

        # Check high-risk patterns
        for pattern in self.HIGH_RISK_PATTERNS:
            if re.search(pattern, command_lower):
                return ValidationResult(
                    is_safe=True,
                    reason=f"Command matches high-risk pattern: {pattern}",
                    requires_confirmation=True,
                    risk_level='high'
                )

        # Command looks safe
        return ValidationResult(
            is_safe=True,
            reason="Command passed safety checks",
            requires_confirmation=False,
            risk_level='low'
        )

    def validate_tool_call(
        self,
        tool_name: str,
        tool_input: Dict[str, Any]
    ) -> ValidationResult:
        """
        Validate a tool call for safety.

        Args:
            tool_name: Name of the tool being called
            tool_input: Input parameters for the tool

        Returns:
            ValidationResult with safety assessment
        """
        # Define penetration testing tools (require explicit authorization)
        pentest_tools = {
            'nmap_port_scan',
            'nmap_service_detection',
            'nikto_web_scan',
            'ssl_scan',
            'sqlmap_scan',
            'xss_scan',
            'zap_spider_scan',
            'quick_vulnerability_scan',
            'aws_security_audit',
            'azure_security_audit',
            'gcp_security_audit',
            'kubernetes_security_audit',
        }

        # Define tool risk levels
        high_risk_tools = {
            'execute_command',
            'delete_resource',
            'terminate_instance',
            'delete_deployment',
            'drop_database',
            'delete_cloudformation_stack',
            'delete_vpc',
            'delete_dynamodb_table',
            'delete_security_group',
            'delete_load_balancer',
            'delete_target_group',
            'delete_eks_cluster',
            'delete_ecr_repository',
            'delete_secret',
            'delete_nat_gateway',
            'delete_elasticache_cluster',
            'delete_efs_file_system',
            'delete_eventbridge_rule',
            'delete_kinesis_stream',
            'ssm_run_command',
            'delete_rds_instance',
            'delete_lambda_function',
            'delete_ecs_cluster',
            'delete_sns_topic',
            'delete_sqs_queue',
            'delete_iam_role',
            'delete_listener',
            'delete_subnet',
            'delete_namespace',
            'delete_service',
            'delete_ingress',
            'delete_job',
            'delete_pod',
            'delete_configmap',
            'delete_k8s_secret',
            'delete_storage_account',
            'delete_sql_server',
            'delete_sql_database',
            'delete_network_security_group',
            'delete_container_instance',
            'delete_managed_disk',
            'delete_public_ip',
            'delete_cloud_sql_instance',
            'delete_pubsub_topic',
            'delete_gcp_secret',
            'delete_cloud_run_service',
            'delete_gke_cluster',
            'delete_firewall_rule',
            'delete_bigquery_dataset',
            'delete_cloud_function',
            'delete_disk_snapshot',
            # Docker destructive
            'docker_manage_container',  # includes remove action
            'docker_remove_image',
            'docker_remove_network',
            'docker_remove_volume',
            'docker_system_prune',
            'docker_compose_down',
            # GitHub destructive
            'github_delete_repo',
            'github_merge_pull_request',
            # Generic write passthroughs (always high-risk — could be anything)
            'aws_api_write',
            'azure_api_write',
            'gcp_api_write',
            'k8s_api_write',
            # CloudWatch destructive
            'delete_cloudwatch_alarm',
            # CI/CD destructive
            'abort_jenkins_build',
            'delete_jenkins_build',
            # Terraform destructive
            'terraform_destroy',
            'terraform_state_rm',
            # SonarQube destructive
            'delete_sonar_project',
            # Nexus destructive
            'nexus_delete_repository',
            'nexus_delete_component',
            'nexus_delete_asset',
            # Git high-risk
            'git_reset_to_commit',
            'git_clean_working_directory',
            'git_force_push_branch',
            # EC2 new destructive and high-impact modifications
            'delete_ec2_keypair',
            'delete_ebs_snapshot',
            'delete_ebs_volume',
            'cleanup_ebs_volume',
            'deregister_ami',
            'resize_ec2_instance',  # Stops/starts instance and changes type — high risk
            # S3 destructive
            'delete_s3_object',
            'delete_s3_objects_batch',
            'delete_s3_bucket_policy',
            'delete_s3_lifecycle_policy',
            'delete_s3_replication',
            'delete_s3_website',
            'delete_s3_bucket_tags',
            # IAM destructive
            'delete_iam_user',
            'delete_iam_group',
            'delete_iam_policy',
            'delete_iam_access_key',
            'delete_iam_inline_policy',
            'delete_iam_login_profile',
            # RDS extended destructive
            'delete_rds_snapshot',
            'delete_db_parameter_group',
            'delete_db_subnet_group',
            'delete_aurora_cluster',
            # VPC extended destructive
            'delete_internet_gateway',
            'delete_route_table',
            'delete_network_acl',
            'delete_vpc_peering',
            'delete_vpc_endpoint',
            'delete_eni',
            'disable_vpc_flow_logs',
            # EKS destructive
            'delete_eks_cluster',
            'delete_eks_node_group',
            'delete_eks_fargate_profile',
            'delete_eks_access_entry',
            'delete_eks_addon',
            # K8s extended destructive
            'delete_statefulset',
            'delete_pvc',
            'delete_hpa',
            'delete_cronjob',
            'delete_service_account',
            'drain_node',
        }

        medium_risk_tools = {
            'restart_deployment',
            'scale_deployment',
            'update_resource',
            'apply_configuration',
            'create_iam_role',
            'create_iam_policy',
            'attach_iam_role_policy',
            'update_auto_scaling_group',
            'update_ecs_service',
            'update_cloudformation_stack',
            'revoke_security_group_ingress',
            'deregister_targets',
            'release_elastic_ip',
            'update_secret',
            'update_lambda_function_config',
            'detach_ebs_volume',
            'delete_pod',
            'delete_configmap',
            'delete_k8s_secret',
            'cordon_node',
            'uncordon_node',
            'update_deployment_image',
            'exec_pod_command',
            'create_nsg_rule',
            'create_sql_firewall_rule',
            'restart_container_instance',
            'regenerate_storage_key',
            'restart_cloud_sql_instance',
            'create_firewall_rule',
            'create_eventbridge_rule',
            'resize_gke_cluster',
            'create_pubsub_subscription',
            # Git medium risk
            'git_clone_repository',
            'git_switch_branch',
            'git_merge_branch',
            'git_rename_branch',
            'git_reset_files',
            'git_amend_commit',
            'git_pull',
            'git_push',
            'git_cherry_pick',
            'git_push_tag',
            'git_stash_drop',
            'git_revert_commit',
            'git_rebase_branch',
            # GitHub PR medium risk
            'github_close_pull_request',
            # Docker medium risk
            'docker_exec',
            'docker_push_image',
            'docker_compose_up',
            'docker_build_image',
            'docker_create_container',
            # GitHub medium risk
            'github_trigger_workflow',
            'github_invite_collaborator',
            'github_close_issue',
            'github_create_release',
            # CI/CD medium risk
            'disable_jenkins_job',
            'cancel_github_workflow_run',
            'rerun_failed_github_jobs',
            'trigger_github_workflow',
            # Terraform medium risk
            'terraform_apply',
            'terraform_state_move',
            'terraform_import',
            # SonarQube medium risk
            'update_sonar_issue',
            'assign_sonar_quality_gate',
            'create_sonar_project',
            # Nexus medium risk
            'nexus_create_repository',
            'nexus_run_cleanup_task',
            # EC2 new medium risk
            'resize_ebs_volume',
            'create_scaling_policy',
            'create_cloudwatch_alarm',
            'disassociate_elastic_ip',
            # S3 medium risk
            'upload_s3_object',
            'set_s3_public_access_block',
            'set_s3_versioning',
            'set_s3_default_encryption',
            'set_s3_notification',
            'set_s3_website',
            'set_s3_cors',
            'set_s3_logging',
            # IAM medium risk
            'create_iam_user',
            'create_iam_group',
            'create_iam_login_profile',
            'create_iam_access_key',
            'update_iam_access_key',
            'update_iam_role_trust_policy',
            'attach_iam_user_policy',
            'attach_iam_group_policy',
            'add_iam_user_to_group',
            'detach_iam_policy',
            'put_iam_inline_policy',
            'assume_iam_role',
            # RDS extended medium risk
            'start_rds_instance',
            'stop_rds_instance',
            'reboot_rds_instance',
            'modify_rds_instance',
            'rotate_rds_master_password',
            'enable_rds_iam_auth',
            'create_rds_snapshot',
            'restore_rds_from_snapshot',
            'restore_rds_to_point_in_time',
            'modify_db_parameter_group',
            'create_rds_read_replica',
            'promote_rds_read_replica',
            'create_aurora_cluster',
            'failover_aurora_cluster',
            # VPC extended medium risk
            'modify_vpc_attribute',
            'enable_vpc_flow_logs',
            'modify_subnet_attribute',
            'detach_internet_gateway',
            'add_route',
            'delete_route',
            'replace_route',
            'associate_route_table',
            'disassociate_route_table',
            'set_main_route_table',
            'authorize_security_group_egress',
            'revoke_security_group_egress',
            'create_nacl_entry',
            'delete_nacl_entry',
            'associate_nacl_with_subnet',
            'accept_vpc_peering',
            'create_vpc_endpoint',
            'attach_eni',
            'detach_eni',
            # EKS medium risk
            'update_eks_cluster_version',
            'update_eks_cluster_config',
            'enable_eks_control_plane_logging',
            'associate_eks_oidc_provider',
            'update_eks_node_group_version',
            'update_eks_node_group_config',
            'create_eks_fargate_profile',
            'create_eks_access_entry',
            'associate_eks_access_policy',
            'create_eks_addon',
            'update_eks_addon',
            # Terraform new medium risk
            'terraform_force_unlock',
            'terraform_state_push',
            'terraform_workspace_delete',
            # GitLab CI medium risk
            'trigger_gitlab_pipeline',
            'retry_gitlab_pipeline',
            'approve_gitlab_deployment',
            'cancel_gitlab_pipeline',
            # Deployment strategy medium risk
            'blue_green_switch',
            'canary_update_weight',
            'auto_rollback_deployment',
            # K8s extended medium risk
            'rollback_deployment',
            'pause_rollout',
            'resume_rollout',
            'scale_statefulset',
            'taint_node',
            'remove_node_taint',
            'label_node',
            'create_cronjob',
            'suspend_cronjob',
            'create_hpa',
            'create_pvc',
            'create_role',
            'create_role_binding',
            'create_service_account',
            'update_configmap',
            'update_k8s_secret',
            'apply_manifest',
        }

        # Check if tool is a pentest tool
        if tool_name in pentest_tools:
            pentest_enabled = self.pentest_config.get('enabled', False)
            if not pentest_enabled:
                return ValidationResult(
                    is_safe=False,
                    reason=f"Penetration testing disabled in configuration",
                    requires_confirmation=False,
                    risk_level='critical'
                )

            # Check if target is provided and validate it
            target = tool_input.get('target') or tool_input.get('target_url', '')

            return ValidationResult(
                is_safe=True,
                reason=f"Penetration testing tool '{tool_name}' - ensure target authorization",
                requires_confirmation=self.pentest_config.get('require_confirmation', True),
                risk_level='high'
            )

        # Check for specific dangerous patterns in input (escalate to critical on production)
        input_str = str(tool_input).lower()
        targets_production = 'production' in input_str or 'prod' in input_str

        # Special case: manage_ec2_instance is action-aware
        if tool_name == 'manage_ec2_instance':
            action = tool_input.get('action', '').lower()
            if action == 'terminate':
                return ValidationResult(
                    is_safe=True,
                    reason=f"High-risk operation: terminating EC2 instance" + (" on production" if targets_production else ""),
                    requires_confirmation=True,
                    risk_level='critical' if targets_production else 'high'
                )
            elif action in ('stop', 'reboot'):
                return ValidationResult(
                    is_safe=True,
                    reason=f"Medium-risk operation: {action} EC2 instance",
                    requires_confirmation=True,
                    risk_level='medium'
                )
            # action='start' falls through to low risk

        # Special case: manage_vm (Azure) is action-aware
        if tool_name == 'manage_vm':
            action = tool_input.get('action', '').lower()
            if action in ('stop', 'restart', 'deallocate'):
                return ValidationResult(
                    is_safe=True,
                    reason=f"Medium-risk operation: {action} Azure VM" + (" on production" if targets_production else ""),
                    requires_confirmation=True,
                    risk_level='medium'
                )
            # action='start' falls through to low risk

        # Special case: manage_compute_instance (GCP) is action-aware
        if tool_name == 'manage_compute_instance':
            action = tool_input.get('action', '').lower()
            if action in ('stop', 'reset'):
                return ValidationResult(
                    is_safe=True,
                    reason=f"Medium-risk operation: {action} GCE instance" + (" on production" if targets_production else ""),
                    requires_confirmation=True,
                    risk_level='medium'
                )
            # action='start' falls through to low risk

        # Priority: explicit sets override auto-detection.
        # A tool in medium_risk_tools stays medium even if its name matches a high-risk pattern.
        if tool_name in high_risk_tools:
            return ValidationResult(
                is_safe=True,
                reason=f"High-risk tool '{tool_name}'" + (" on production" if targets_production else ""),
                requires_confirmation=True,
                risk_level='critical' if targets_production else 'high'
            )

        if tool_name in medium_risk_tools:
            return ValidationResult(
                is_safe=True,
                reason=f"Medium-risk tool '{tool_name}'",
                requires_confirmation=True,
                risk_level='medium'
            )

        # Auto-detect: catch tools not in either explicit set
        if self._matches_high_risk_pattern(tool_name):
            return ValidationResult(
                is_safe=True,
                reason=f"High-risk tool '{tool_name}' (auto-detected)" + (" on production" if targets_production else ""),
                requires_confirmation=True,
                risk_level='critical' if targets_production else 'high'
            )

        if self._matches_medium_risk_pattern(tool_name):
            return ValidationResult(
                is_safe=True,
                reason=f"Medium-risk tool '{tool_name}' (auto-detected)",
                requires_confirmation=True,
                risk_level='medium'
            )

        # Tool is considered low risk
        return ValidationResult(
            is_safe=True,
            reason="Tool is low risk",
            requires_confirmation=False,
            risk_level='low'
        )

    # Auto-detection patterns: catch new tools that weren't added to the static sets
    _HIGH_RISK_NAME_PREFIXES = (
        'delete_', 'terminate_', 'destroy_', 'remove_', 'drop_', 'purge_',
    )
    _HIGH_RISK_NAME_SUBSTRINGS = ('_prune', '_wipe', '_force_remove')

    _MEDIUM_RISK_NAME_PREFIXES = (
        'update_', 'restart_', 'reboot_', 'scale_', 'resize_',
        'modify_', 'revoke_', 'detach_', 'deregister_', 'release_',
        'cordon_', 'uncordon_', 'rollback_', 'migrate_',
    )
    _MEDIUM_RISK_NAME_SUBSTRINGS = ('_exec', '_run_command')

    @classmethod
    def _matches_high_risk_pattern(cls, tool_name: str) -> bool:
        name = tool_name.lower()
        if any(name.startswith(p) for p in cls._HIGH_RISK_NAME_PREFIXES):
            return True
        if any(s in name for s in cls._HIGH_RISK_NAME_SUBSTRINGS):
            return True
        return False

    @classmethod
    def _matches_medium_risk_pattern(cls, tool_name: str) -> bool:
        name = tool_name.lower()
        # Don't escalate to medium if it already matched high
        if cls._matches_high_risk_pattern(tool_name):
            return False
        if any(name.startswith(p) for p in cls._MEDIUM_RISK_NAME_PREFIXES):
            return True
        if any(s in name for s in cls._MEDIUM_RISK_NAME_SUBSTRINGS):
            return True
        return False

    def validate_resource_operation(
        self,
        operation: str,
        resource_type: str,
        environment: Optional[str] = None
    ) -> ValidationResult:
        """
        Validate a resource operation for safety.

        Args:
            operation: Operation being performed (create, delete, update, etc.)
            resource_type: Type of resource (ec2, deployment, database, etc.)
            environment: Environment (production, staging, dev)

        Returns:
            ValidationResult with safety assessment
        """
        destructive_operations = {'delete', 'terminate', 'destroy', 'drop'}
        critical_resources = {'database', 'cluster', 'namespace', 'vpc'}

        risk_level = 'low'
        requires_confirmation = False

        # Check for destructive operations
        if operation.lower() in destructive_operations:
            risk_level = 'high'
            requires_confirmation = True

            # Extra critical if on production
            if environment and environment.lower() in ('production', 'prod', 'live'):
                risk_level = 'critical'

            # Extra critical if critical resource
            if resource_type.lower() in critical_resources:
                risk_level = 'critical'

        # Check for production environment
        if environment and environment.lower() in ('production', 'prod', 'live'):
            if risk_level == 'low':
                risk_level = 'medium'
            requires_confirmation = True

        return ValidationResult(
            is_safe=True,
            reason=f"{operation} on {resource_type} in {environment or 'unknown'} environment",
            requires_confirmation=requires_confirmation,
            risk_level=risk_level
        )

    @staticmethod
    def sanitize_output(output: str, max_length: int = 10000) -> str:
        """
        Sanitize output by removing sensitive data and truncating.

        Args:
            output: Output to sanitize
            max_length: Maximum length of output

        Returns:
            Sanitized output
        """
        # Patterns for sensitive data
        sensitive_patterns = [
            (r'(AKIA[0-9A-Z]{16})', '***AWS_ACCESS_KEY***'),
            (r'([0-9a-f]{40})', '***TOKEN***'),
            (r'(password|passwd|pwd)["\s:=]+([^\s"]+)', r'\1=***MASKED***'),
            (r'(api[_-]?key|token|secret)["\s:=]+([^\s"]+)', r'\1=***MASKED***'),
        ]

        result = output
        for pattern, replacement in sensitive_patterns:
            result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)

        # Truncate if too long
        if len(result) > max_length:
            result = result[:max_length] + f"\n... (truncated, {len(output) - max_length} chars omitted)"

        return result
