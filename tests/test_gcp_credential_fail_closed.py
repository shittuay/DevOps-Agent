"""Regression test: GCP SDK clients must fail closed when the requesting user
has no linked GCP credentials, never fall back to Application Default
Credentials (the app server's own ambient GCP identity).

The 2026-08-08 credential-isolation fix routed ~25 client constructions through
`_get_gcp_credentials_kwargs()`, but that helper returned `{}` when the user had
no credentials linked — so the client was still built with no `credentials=`
argument and still resolved to ADC, which is the exact bug the helper's own
docstring named. Caught in PR review; the helper now raises instead.

These tests pin the fail-closed contract itself, not just the call sites: a
future refactor that reintroduces a `{}`/`None` return here would silently
reopen the fallback across every GCP tool at once.
"""
from unittest.mock import patch

import pytest


class _FakeCredentials:
    """Stand-in for a google.oauth2.service_account.Credentials instance."""


def test_credentials_kwargs_raises_when_user_has_none_linked():
    from src.tools import gcp_tools

    with patch.object(gcp_tools, '_get_user_gcp_credentials', return_value=(None, None)):
        with pytest.raises(Exception) as exc:
            gcp_tools._get_gcp_credentials_kwargs()

    assert 'not configured' in str(exc.value).lower(), (
        "helper must fail closed with an actionable message, not fall through to ADC"
    )


def test_credentials_kwargs_never_returns_empty_dict():
    """An empty dict is the specific regression: `SomeClient(**{})` builds a
    client with no credentials= argument, which resolves to ADC."""
    from src.tools import gcp_tools

    with patch.object(gcp_tools, '_get_user_gcp_credentials', return_value=(None, None)):
        try:
            result = gcp_tools._get_gcp_credentials_kwargs()
        except Exception:
            return  # raising is the correct behavior
    pytest.fail(
        f"_get_gcp_credentials_kwargs() returned {result!r} instead of raising; "
        "an empty/credential-less kwargs dict silently falls back to Application "
        "Default Credentials"
    )


def test_credentials_kwargs_threads_user_credentials_through():
    from src.tools import gcp_tools

    creds = _FakeCredentials()
    with patch.object(gcp_tools, '_get_user_gcp_credentials', return_value=(creds, 'proj-1')):
        kwargs = gcp_tools._get_gcp_credentials_kwargs()

    assert kwargs == {'credentials': creds}


def test_every_gcp_client_construction_passes_credentials():
    """Structural guard over every call site, not just the helper.

    The original bug was not that the helper was wrong — it was that ~25
    client constructions were written without any `credentials=` argument at
    all. A new tool added to this module that constructs a client directly
    would reintroduce the ADC fallback for that one tool with nothing to catch
    it, so assert the property across the whole file.

    This is deliberately source-level rather than behavioral: `_get_gcp_client`
    imports `google.cloud.sql_v1`, which has no installable PyPI distribution
    (see the commented-out `google-cloud-sql` pin in requirements.txt), so the
    real code path raises ImportError before reaching any credential logic in
    every environment including CI.
    """
    import ast
    import inspect
    from src.tools import gcp_tools

    source = inspect.getsource(gcp_tools)
    tree = ast.parse(source)

    # Client constructions are calls whose callee name ends in 'Client', plus
    # the two SDK entry points that don't follow that convention.
    def _is_client_construction(node):
        if not isinstance(node, ast.Call):
            return False
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, 'id', '')
        return name.endswith('Client')

    def _passes_credentials(node):
        if any(kw.arg == 'credentials' for kw in node.keywords):
            return True
        # **creds_kwargs / **_get_gcp_credentials_kwargs()
        for kw in node.keywords:
            if kw.arg is None:
                return True
        return False

    examined, offenders = [], []
    for node in ast.walk(tree):
        if not _is_client_construction(node):
            continue
        callee = node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
        examined.append(callee)
        if not _passes_credentials(node):
            offenders.append(f"{callee} at gcp_tools.py line {node.lineno}")

    # Guard against this test silently becoming vacuous if the detection
    # heuristic stops matching (e.g. a refactor renames the client classes).
    assert len(examined) >= 20, (
        f"only {len(examined)} GCP client construction(s) detected in gcp_tools.py "
        "— the heuristic has drifted and this test is no longer guarding the module"
    )

    assert not offenders, (
        "GCP SDK client(s) constructed without credentials — these silently fall "
        "back to Application Default Credentials (the app server's own ambient "
        "identity) instead of the requesting user's linked credentials:\n  "
        + "\n  ".join(offenders)
    )
