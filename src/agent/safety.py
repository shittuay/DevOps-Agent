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
        }

        medium_risk_tools = {
            'restart_deployment',
            'scale_deployment',
            'update_resource',
            'apply_configuration',
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

        # Check if tool is high risk
        if tool_name in high_risk_tools:
            # Check for specific dangerous patterns in input
            input_str = str(tool_input).lower()

            if 'production' in input_str or 'prod' in input_str:
                return ValidationResult(
                    is_safe=True,
                    reason=f"High-risk tool '{tool_name}' on production",
                    requires_confirmation=True,
                    risk_level='critical'
                )

            return ValidationResult(
                is_safe=True,
                reason=f"High-risk tool '{tool_name}'",
                requires_confirmation=True,
                risk_level='high'
            )

        # Check if tool is medium risk
        if tool_name in medium_risk_tools:
            return ValidationResult(
                is_safe=True,
                reason=f"Medium-risk tool '{tool_name}'",
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
