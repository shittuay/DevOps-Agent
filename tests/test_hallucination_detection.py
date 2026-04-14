"""
Tests for hallucination detection logic.

Verifies that:
1. Hallucinations are detected when sandbox_mode=False (live mode)
2. Hallucinations are NOT flagged when sandbox_mode=True (sandbox/demo mode)
3. No hallucination is detected when tools were actually called
"""

import pytest
from src.agent.core import _check_hallucination, _HALLUCINATED_TOOL_PATTERNS


class TestHallucinationDetection:
    """Test the _check_hallucination function with various inputs."""

    # Fake AWS resource examples
    FAKE_EC2_INSTANCE = "i-0123456789abcdef0"
    FAKE_VPC = "vpc-12345678"
    FAKE_SUBNET = "subnet-87654321"
    FAKE_SECURITY_GROUP = "sg-fedcba98"
    FAKE_AMI = "ami-12345678"
    FAKE_ARN = "arn:aws:ec2:us-east-1:123456789012:instance/i-0123456789abcdef0"

    # Fake K8s pod names
    FAKE_K8S_POD = "nginx-deploy-a1b2c3d4-5e6f7"

    # Fake Azure subscription
    FAKE_AZURE_SUB = "/subscriptions/12345678-1234-1234-1234-123456789012/"

    # Fake GCP self-link
    FAKE_GCP_LINK = "projects/my-project/zones/us-central1-a/instances/web-server"

    # Fake JSON tool output
    FAKE_JSON_OUTPUT = '{"success": true, "instance_id": "i-xyz"}'

    # Real text (no fake resources)
    REAL_TEXT = "The deployment completed successfully with all services running."

    def test_sandbox_mode_does_not_flag_fake_resources(self):
        """In sandbox mode, fabricated resources should NOT be flagged."""
        text = f"Created instance {self.FAKE_EC2_INSTANCE} with VPC {self.FAKE_VPC}"

        # Sandbox ON: should NOT flag
        is_hallucination = _check_hallucination(text, tools_called_this_turn=False, sandbox_mode=True)
        assert is_hallucination is False, "Sandbox mode should allow fabricated resources"

    def test_live_mode_flags_fake_aws_resources(self):
        """In live mode (sandbox=False), fake AWS resources should be flagged."""
        text = f"Created instance {self.FAKE_EC2_INSTANCE} with VPC {self.FAKE_VPC}"

        # Sandbox OFF (live): should flag
        is_hallucination = _check_hallucination(text, tools_called_this_turn=False, sandbox_mode=False)
        assert is_hallucination is True, "Live mode should flag fake AWS resources"

    def test_live_mode_flags_fake_arn(self):
        """In live mode, fake ARNs should be flagged."""
        text = f"ARN: {self.FAKE_ARN}"

        is_hallucination = _check_hallucination(text, tools_called_this_turn=False, sandbox_mode=False)
        assert is_hallucination is True, "Live mode should flag fake ARNs"

    def test_live_mode_flags_fake_k8s_pod(self):
        """In live mode, fake K8s pod names should be flagged."""
        text = f"Pod: {self.FAKE_K8S_POD}"

        is_hallucination = _check_hallucination(text, tools_called_this_turn=False, sandbox_mode=False)
        assert is_hallucination is True, "Live mode should flag fake K8s pods"

    def test_live_mode_flags_fake_azure_subscription(self):
        """In live mode, fake Azure subscription IDs should be flagged."""
        text = f"Resource: {self.FAKE_AZURE_SUB}resourceGroups/mygroup"

        is_hallucination = _check_hallucination(text, tools_called_this_turn=False, sandbox_mode=False)
        assert is_hallucination is True, "Live mode should flag fake Azure subscriptions"

    def test_live_mode_flags_fake_gcp_self_link(self):
        """In live mode, fake GCP self-links should be flagged."""
        text = f"Instance: {self.FAKE_GCP_LINK}"

        is_hallucination = _check_hallucination(text, tools_called_this_turn=False, sandbox_mode=False)
        assert is_hallucination is True, "Live mode should flag fake GCP self-links"

    def test_live_mode_flags_fake_json_output(self):
        """In live mode, fake JSON tool output blocks should be flagged."""
        text = f"Result: {self.FAKE_JSON_OUTPUT}"

        is_hallucination = _check_hallucination(text, tools_called_this_turn=False, sandbox_mode=False)
        assert is_hallucination is True, "Live mode should flag fake JSON outputs"

    def test_real_text_not_flagged_in_live_mode(self):
        """Real text without fake resources should not be flagged."""
        is_hallucination = _check_hallucination(self.REAL_TEXT, tools_called_this_turn=False, sandbox_mode=False)
        assert is_hallucination is False, "Real text should not be flagged"

    def test_tools_called_prevents_flagging_sandbox_off(self):
        """If tools were called, don't flag even with fake resource patterns (live mode)."""
        text = f"Called describe_instances which returned: {self.FAKE_EC2_INSTANCE}"

        # Even though text has fake resource IDs, tools were called so it's likely a summary
        is_hallucination = _check_hallucination(text, tools_called_this_turn=True, sandbox_mode=False)
        assert is_hallucination is False, "Should not flag when tools were called"

    def test_tools_called_prevents_flagging_sandbox_on(self):
        """If tools were called, don't flag (sandbox mode doesn't matter)."""
        text = f"Found {self.FAKE_EC2_INSTANCE} with details..."

        is_hallucination = _check_hallucination(text, tools_called_this_turn=True, sandbox_mode=True)
        assert is_hallucination is False, "Should not flag when tools were called"

    def test_sandbox_takes_precedence_over_tools_called(self):
        """Sandbox mode should short-circuit even before checking tools_called."""
        text = f"Instance: {self.FAKE_EC2_INSTANCE}"

        # Sandbox ON should prevent flagging regardless of tools_called
        is_hallucination = _check_hallucination(text, tools_called_this_turn=False, sandbox_mode=True)
        assert is_hallucination is False, "Sandbox mode takes precedence"

    def test_multiple_fake_resources_in_one_response(self):
        """Response with multiple fake resource types should be flagged in live mode."""
        text = f"""
        Created VPC {self.FAKE_VPC} with subnet {self.FAKE_SUBNET}.
        Deployed pod {self.FAKE_K8S_POD}.
        Set up ARN: {self.FAKE_ARN}
        """

        is_hallucination = _check_hallucination(text, tools_called_this_turn=False, sandbox_mode=False)
        assert is_hallucination is True, "Should flag multiple fake resources"

    def test_empty_text_not_flagged(self):
        """Empty text should not be flagged."""
        is_hallucination = _check_hallucination("", tools_called_this_turn=False, sandbox_mode=False)
        assert is_hallucination is False, "Empty text should not be flagged"

    def test_default_sandbox_mode_is_false(self):
        """The default for sandbox_mode should be False (live/strict mode)."""
        # This tests backward compatibility — old code calling without sandbox_mode param
        # should default to False (live mode, strict checking)
        text = f"Instance: {self.FAKE_EC2_INSTANCE}"

        # Call without sandbox_mode parameter — should use default False
        is_hallucination = _check_hallucination(text, tools_called_this_turn=False)
        assert is_hallucination is True, "Default sandbox_mode should be False (live mode)"

    def test_ip_address_pattern_detection(self):
        """Multiple IP addresses in response should be flagged as fabrication."""
        # The pattern requires 4+ IPs with minimal separation (.*? non-greedy)
        # Format: IP text IP text IP text IP text (4 IPs with stuff between)
        text = "10.0.0.1 server1 10.0.0.2 server2 10.0.0.3 server3 10.0.0.4 server4"

        is_hallucination = _check_hallucination(text, tools_called_this_turn=False, sandbox_mode=False)
        # 4+ IPs in same response suggests fabricated infrastructure listing
        assert is_hallucination is True, "Should flag multiple IP addresses (fabricated listing)"


class TestHallucinationPatternsCompleteness:
    """Verify that all expected hallucination patterns are compiled."""

    def test_patterns_are_compiled_regexes(self):
        """All patterns should be compiled regex objects."""
        assert len(_HALLUCINATED_TOOL_PATTERNS) > 0, "Should have at least one pattern"

        for pattern in _HALLUCINATED_TOOL_PATTERNS:
            assert hasattr(pattern, 'search'), "Pattern should be a compiled regex"

    def test_aws_credential_pattern_exists(self):
        """Should detect AWS access keys."""
        # AWS access keys start with AKIA and have 16-20 alphanumeric chars
        found = False
        for pattern in _HALLUCINATED_TOOL_PATTERNS:
            if pattern.search("AKIA1234567890ABCD"):
                found = True
                break
        assert found, "Should have pattern for AWS access keys"

    def test_arn_pattern_exists(self):
        """Should detect ARNs."""
        found = False
        for pattern in _HALLUCINATED_TOOL_PATTERNS:
            if pattern.search("arn:aws:ec2:us-east-1:123456789012:instance/i-test"):
                found = True
                break
        assert found, "Should have pattern for ARNs"

    def test_json_success_pattern_exists(self):
        """Should detect fake JSON tool output blocks."""
        found = False
        for pattern in _HALLUCINATED_TOOL_PATTERNS:
            # Pattern requires a comma after "true" (to match {"success": true, ...})
            if pattern.search('{"success": true, "data": "value"}'):
                found = True
                break
        assert found, "Should have pattern for JSON success blocks"
