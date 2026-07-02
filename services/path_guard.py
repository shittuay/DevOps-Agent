"""
Shared filesystem containment guard for tools that accept a user-supplied
working directory / repo path (Terraform working_dir, git repo_path).

Always blocks paths that resolve (after following symlinks/relative
segments) to the application's own source tree or other sensitive system
directories — preventing a prompt-injected tool call from pointing
terraform_destroy/git_reset_to_commit/etc. at the host's own deployment or
OS files. When the corresponding *_WORKSPACE_ROOT env var is set, also
enforces that the path be contained under that root (for stricter
multi-tenant deployments where each tenant's infra-as-code lives under a
dedicated directory).
"""
import os
from typing import Optional

_SENSITIVE_PREFIXES = (
    '/etc', '/root', '/boot', '/sys', '/proc', '/dev', '/var/lib', '/usr/lib', '/usr/bin', '/usr/sbin',
)


def _app_root() -> str:
    # devops-agent repo root: one level up from services/
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def validate_workspace_path(path: str, env_var: Optional[str] = None) -> Optional[str]:
    """Return None if path is safe to operate on, else a human-readable reason it's blocked."""
    if not path:
        return "Path is required"

    resolved = os.path.realpath(path)

    app_root = _app_root()
    if resolved == app_root or resolved.startswith(app_root + os.sep):
        return f"Refusing to operate on the application's own source tree: {resolved}"

    if resolved == os.sep:
        return "Refusing to operate on filesystem root"

    for prefix in _SENSITIVE_PREFIXES:
        if resolved == prefix or resolved.startswith(prefix + os.sep):
            return f"Refusing to operate on sensitive system path: {resolved}"

    root_env = os.environ.get(env_var) if env_var else None
    if root_env:
        allowed_root = os.path.realpath(root_env)
        if resolved != allowed_root and not resolved.startswith(allowed_root + os.sep):
            return f"Path {resolved} is outside the allowed workspace root ({allowed_root})"

    return None
