"""
Structural checks for two recurring vulnerability classes in this codebase's
history (see CLAUDE_RUNBOOK.md):

1. SSRF: a raw `requests.get/post/put/patch/delete/request(...)` call in an
   app-reachable module, instead of going through `safe_request()`
   (src/utils/network_safety.py). The guard is opt-in per call site, so
   nothing structurally stops a new integration — or a forgotten spot in an
   old one — from making an outbound HTTP call to a URL that isn't
   hardcoded with zero SSRF protection. This has been the single
   most-recurring vulnerability class in this app's history; several
   independent review passes each found a different subset of unguarded
   call sites rather than the same one twice.

2. Duplicate authentication logic: a direct `.check_password(...)` call
   outside routes/auth.py, which reopens the login-timing side channel
   `_run_timing_safe_password_check()` was built to close. Already happened
   once in routes/mcp.py's independent OAuth login form, which had its own
   inline password check that never went through the shared helper.

Run standalone: `python scripts/check_security_invariants.py`
Also runs as a pytest test (tests/test_security_invariants.py) so it's part
of the same suite that already gates merges via ci.yml's `test` job — no
CI workflow changes needed.

To exempt a genuinely safe call, add a comment on the same line or the line
directly above:
  - `# ssrf-safe: <reason>` — the host is hardcoded (Datadog/PagerDuty/
    GitHub's own API/etc.) or otherwise not caller-influenced.
  - `# check-password-safe: <reason>` — an already-authenticated context
    (e.g. changing your own password), not an anonymous login/account-
    existence surface.
Exemptions are meant to be rare and reviewed — each one is a deliberate,
visible sign-off, not a way to silence the check.
"""
import ast
import sys
from pathlib import Path
from typing import List, NamedTuple, Set

REPO_ROOT = Path(__file__).resolve().parent.parent

# Where outbound HTTP calls / authentication checks have historically shown
# up in this app. Not the whole repo — src/agent, tests, scripts (offline
# CLI tools), templates, etc. are out of scope for both checks.
SCAN_ROOTS = ['src/tools', 'services', 'routes', 'api', 'app.py']

SSRF_HTTP_VERBS = {'get', 'post', 'put', 'patch', 'delete', 'request'}
SSRF_EXEMPT_FILES = {
    # Defines safe_request() itself — its one internal requests.request()
    # call *is* the guard, not a call needing one.
    'src/utils/network_safety.py',
}
SSRF_EXEMPT_MARKER = 'ssrf-safe:'

CHECK_PASSWORD_EXEMPT_FILES = {
    # Defines _run_timing_safe_password_check() and the canonical /login —
    # current_user.check_password() calls here are for an
    # already-authenticated user changing their own password/email, not an
    # anonymous account-existence-revealing surface.
    'routes/auth.py',
}
CHECK_PASSWORD_EXEMPT_MARKER = 'check-password-safe:'


class Violation(NamedTuple):
    rule: str
    file: str
    line: int
    detail: str

    def __str__(self) -> str:
        return f"[{self.rule}] {self.file}:{self.line} — {self.detail}"


def _iter_python_files(roots: List[str]):
    for root in roots:
        p = REPO_ROOT / root
        if p.is_file() and p.suffix == '.py':
            yield p
        elif p.is_dir():
            yield from sorted(p.rglob('*.py'))


def _requests_import_aliases(tree: ast.Module) -> Set[str]:
    """Names in this module that refer to the `requests` package — handles
    both `import requests` and `import requests as X`."""
    aliases = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == 'requests':
                    aliases.add(alias.asname or alias.name)
    return aliases


def _has_exempt_comment(lines: List[str], lineno: int, marker: str) -> bool:
    """An exemption comment on the violating line itself or the line above it."""
    for check_line in (lineno, lineno - 1):
        if 1 <= check_line <= len(lines) and marker in lines[check_line - 1]:
            return True
    return False


def _scan_source_for_ssrf(rel_path: str, source: str) -> List[Violation]:
    """Core detection logic, operating on in-memory source — unit-testable
    with synthetic strings independent of the real repo tree."""
    try:
        tree = ast.parse(source, filename=rel_path)
    except SyntaxError:
        return []
    aliases = _requests_import_aliases(tree)
    if not aliases:
        return []
    lines = source.splitlines()
    violations = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr not in SSRF_HTTP_VERBS:
            continue
        if not isinstance(func.value, ast.Name) or func.value.id not in aliases:
            continue
        if _has_exempt_comment(lines, node.lineno, SSRF_EXEMPT_MARKER):
            continue
        violations.append(Violation(
            rule='ssrf-guard',
            file=rel_path,
            line=node.lineno,
            detail=(
                f"raw requests.{func.attr}(...) call — use safe_request() from "
                f"src.utils.network_safety instead, or add "
                f"'# {SSRF_EXEMPT_MARKER} <reason>' if the host is genuinely "
                f"hardcoded/not caller-influenced"
            ),
        ))
    return violations


def _scan_source_for_check_password(rel_path: str, source: str) -> List[Violation]:
    """Core detection logic, operating on in-memory source — unit-testable
    with synthetic strings independent of the real repo tree."""
    try:
        tree = ast.parse(source, filename=rel_path)
    except SyntaxError:
        return []
    lines = source.splitlines()
    violations = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr != 'check_password':
            continue
        if _has_exempt_comment(lines, node.lineno, CHECK_PASSWORD_EXEMPT_MARKER):
            continue
        violations.append(Violation(
            rule='check-password-duplication',
            file=rel_path,
            line=node.lineno,
            detail=(
                "direct .check_password(...) call outside routes/auth.py — "
                "route through routes.auth._run_timing_safe_password_check() "
                f"instead, or add '# {CHECK_PASSWORD_EXEMPT_MARKER} <reason>' if "
                "this is an already-authenticated context, not an anonymous "
                "login/account-existence surface"
            ),
        ))
    return violations


def check_ssrf_guard_usage() -> List[Violation]:
    violations = []
    for path in _iter_python_files(SCAN_ROOTS):
        rel = str(path.relative_to(REPO_ROOT))
        if rel in SSRF_EXEMPT_FILES:
            continue
        violations.extend(_scan_source_for_ssrf(rel, path.read_text()))
    return violations


def check_password_duplication() -> List[Violation]:
    violations = []
    for path in _iter_python_files(SCAN_ROOTS):
        rel = str(path.relative_to(REPO_ROOT))
        if rel in CHECK_PASSWORD_EXEMPT_FILES:
            continue
        violations.extend(_scan_source_for_check_password(rel, path.read_text()))
    return violations


def find_all_violations() -> List[Violation]:
    return check_ssrf_guard_usage() + check_password_duplication()


def main() -> int:
    violations = find_all_violations()
    if not violations:
        print("No security-invariant violations found.")
        return 0
    print(f"Found {len(violations)} security-invariant violation(s):\n")
    for v in violations:
        print(f"  {v}")
    return 1


if __name__ == '__main__':
    sys.exit(main())
