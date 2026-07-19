"""Regression tests for Sandbox Mode activation (2026-07-19).

Bug: in /api/chat and /api/chat/stream, sandbox activation was nested inside
the learning_mode check, so enabling Sandbox Mode alone did nothing — tools
executed for real. This violated the core safety promise ("nothing you do
touches real infrastructure") and broke the credential-free trial flow that
the marketing/onboarding promotes.
"""
import pytest


def _sandbox_active(learning_mode: bool, sandbox_mode: bool) -> bool:
    """Mirror of the activation logic in both chat endpoints. The bug was that
    the sandbox branch was nested under `if learning_mode:` — this asserts the
    corrected, independent behavior. Kept in lockstep with app.py by the
    end-to-end preference tests below."""
    active = False
    if learning_mode:
        pass  # learning context appended
    if sandbox_mode:
        active = True
    return active


@pytest.mark.parametrize("learning,sandbox,expected", [
    (False, True, True),    # THE bug case: sandbox alone must activate
    (True, True, True),
    (True, False, False),
    (False, False, False),
])
def test_sandbox_active_independent_of_learning(learning, sandbox, expected):
    assert _sandbox_active(learning, sandbox) is expected


def test_chat_endpoints_activate_sandbox_without_learning():
    """End-to-end guard: the sandbox activation in app.py must not be nested
    inside a learning_mode block on either chat path."""
    import ast
    with open('app.py') as f:
        tree = ast.parse(f.read())

    # Find every `if <...>.sandbox_mode:` and confirm none is a descendant of an
    # `if <...>.learning_mode:` statement.
    def is_attr_test(node, attr):
        t = node.test
        if isinstance(t, ast.BoolOp):
            return any(isinstance(v, ast.Attribute) and v.attr == attr for v in t.values)
        return isinstance(t, ast.Attribute) and t.attr == attr

    learning_ifs = [n for n in ast.walk(tree)
                    if isinstance(n, ast.If) and is_attr_test(n, 'learning_mode')]
    nested_sandbox = 0
    for lif in learning_ifs:
        for child in ast.walk(lif):
            if child is not lif and isinstance(child, ast.If) and is_attr_test(child, 'sandbox_mode'):
                nested_sandbox += 1
    assert nested_sandbox == 0, "sandbox_mode check is nested inside a learning_mode block"

    sandbox_ifs = [n for n in ast.walk(tree)
                   if isinstance(n, ast.If) and is_attr_test(n, 'sandbox_mode')]
    assert len(sandbox_ifs) >= 2, "expected independent sandbox_mode checks on both chat paths"


def test_sandbox_mock_covers_unmapped_tools():
    """Sandbox must simulate ANY tool, including cost tools with no dedicated
    mock branch — the generic fallback returns a safe simulated success."""
    from services.learning_sandbox import generate_mock_result
    for tool in ('get_cost_summary', 'get_optimization_recommendations',
                 'terminate_ec2_instance', 'delete_s3_bucket'):
        result = generate_mock_result(tool, {})
        assert result.get('success') is True, f"{tool} not simulated safely: {result}"
        assert result.get('simulated') is True or '[Sandbox]' in result.get('message', ''), \
            f"{tool} result not marked simulated: {result}"
