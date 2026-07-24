"""Drift guard for two recurring vulnerability classes: SSRF (raw `requests.*`
calls bypassing safe_request()) and duplicate login-timing-unsafe password
checks (direct `.check_password()` calls outside routes/auth.py).

See scripts/check_security_invariants.py for the full rationale — this file
just wires that checker into the pytest suite so it runs on every PR via
ci.yml's `test` job (already a required check), with no separate CI wiring.

If this test fails on a new tool/service you added: either route the call
through safe_request()/`_run_timing_safe_password_check()`, or — only if the
host is genuinely hardcoded/not caller-influenced, or the check is in an
already-authenticated context — add the documented exemption comment. Don't
delete or weaken this test to make it pass.
"""
from scripts.check_security_invariants import find_all_violations


def test_no_ssrf_or_duplicate_auth_check_violations():
    violations = find_all_violations()
    assert not violations, (
        "Found security-invariant violations — see scripts/check_security_invariants.py "
        "for how to fix or (rarely) exempt each one:\n"
        + "\n".join(f"  {v}" for v in violations)
    )
