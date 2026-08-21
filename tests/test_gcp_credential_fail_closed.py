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


def test_get_gcp_client_fails_closed_even_with_explicit_project_id():
    """An explicit project_id skips the project-resolution branch, which was
    once the only path that could raise — so this is the case where a caller
    could otherwise still reach an ADC-backed client.

    This is reachable to test only because _get_gcp_client now resolves
    credentials *before* importing any SDK; it previously imported five SDKs
    up front (one of which, sql_v1, has no PyPI distribution) and so raised
    ImportError before any credential logic ran, on every platform.
    """
    from src.tools import gcp_tools

    with patch.object(gcp_tools, '_get_user_gcp_credentials', return_value=(None, None)):
        with pytest.raises(Exception) as exc:
            gcp_tools._get_gcp_client('compute', project_id='some-explicit-project')

    assert 'not configured' in str(exc.value).lower(), (
        f"expected a fail-closed credentials error, got: {exc.value}"
    )


def test_get_gcp_client_resolves_credentials_only_once():
    """_get_user_gcp_credentials() writes a plaintext service-account private
    key to a temp file, loads it, then deletes it. Resolving twice per client
    construction doubles both the DB round-trip and the window that key is on
    disk, so the resolution must be hoisted and reused."""
    from src.tools import gcp_tools

    calls = []

    def _counting_resolver():
        calls.append(1)
        return (None, None)

    with patch.object(gcp_tools, '_get_user_gcp_credentials', _counting_resolver):
        with pytest.raises(Exception):
            gcp_tools._get_gcp_client('compute')

    assert len(calls) == 1, (
        f"_get_user_gcp_credentials() called {len(calls)}x for a single "
        "_get_gcp_client() call; resolve once and reuse the result"
    )


def test_get_gcp_client_does_not_serve_cloud_sql():
    """Cloud SQL has no google-cloud-* client library (`google-cloud-sql` does
    not exist on PyPI), so it must be reached via _get_sqladmin_client()'s REST
    discovery client. Asking _get_gcp_client for it previously returned a
    client built from `sql_v1` — an import that always failed — and that single
    unsatisfiable import in the shared import line took down compute, storage,
    container and monitoring along with it."""
    from src.tools import gcp_tools

    creds = _FakeCredentials()
    with patch.object(gcp_tools, '_get_user_gcp_credentials', return_value=(creds, 'proj-1')):
        with pytest.raises(Exception) as exc:
            gcp_tools._get_gcp_client('sql')

    message = str(exc.value).lower()
    assert 'unknown gcp service type' in message, (
        f"expected Cloud SQL to be rejected by _get_gcp_client, got: {exc.value}"
    )
    assert 'sql_v1' not in message


def test_sqladmin_client_fails_closed():
    from src.tools import gcp_tools

    with patch.object(gcp_tools, '_get_user_gcp_credentials', return_value=(None, None)):
        with pytest.raises(Exception) as exc:
            gcp_tools._get_sqladmin_client()

    assert 'not configured' in str(exc.value).lower()


def test_no_module_imports_the_nonexistent_cloud_sql_package():
    """`google-cloud-sql` is commented out of requirements.txt as nonexistent
    on PyPI. Any live `sql_v1` import is therefore guaranteed to raise at
    runtime — guard against one being reintroduced."""
    import ast
    import inspect
    from src.tools import gcp_tools

    # AST, not a text scan: this module's own comments and docstrings discuss
    # sql_v1 by name to explain why it must not be imported, and a substring
    # match cannot tell those apart from a real import.
    tree = ast.parse(inspect.getsource(gcp_tools))

    offending = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if 'sql_v1' in alias.name:
                    offending.append(f"line {node.lineno}: import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ''
            names = [a.name for a in node.names]
            if 'sql_v1' in module or any('sql_v1' in n for n in names):
                offending.append(f"line {node.lineno}: from {module} import {', '.join(names)}")

    assert not offending, (
        "live import(s) of google.cloud.sql_v1, which has no installable "
        "distribution — use _get_sqladmin_client() instead:\n  "
        + "\n  ".join(offending)
    )


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


# `gcp_api_read`/`gcp_api_write` (the generic "call any GCP REST API" escape
# hatch) build their client via `googleapiclient.discovery.build(...)`, not a
# `*Client(...)` constructor, so they're invisible to the AST heuristic above.
# They called `_get_user_gcp_credentials()` directly instead of routing through
# `_get_gcp_credentials_kwargs()`, and passed the result straight through as
# `credentials=credentials` with no None-check — `discovery.build()` treats an
# explicit `credentials=None` exactly like an omitted argument and falls
# through to Application Default Credentials. Found in a 2026-08-21 scheduled
# audit; fixed by returning a fail-closed error before `discovery.build()` is
# ever reached. These tests pin the behavioral contract directly since the
# syntactic AST check can't: `credentials=credentials` is present either way,
# the bug was that the variable could be `None`.


def test_gcp_api_read_fails_closed_with_no_credentials():
    from src.tools import gcp_tools

    with patch.object(gcp_tools, '_get_user_gcp_credentials', return_value=(None, None)):
        with patch('googleapiclient.discovery.build') as mock_build:
            result = gcp_tools.gcp_api_read('compute', 'v1', 'instances', 'list', {'zone': 'us-central1-a'})

    assert result['success'] is False
    assert 'not configured' in result['error'].lower()
    mock_build.assert_not_called()


def test_gcp_api_write_fails_closed_with_no_credentials():
    from src.tools import gcp_tools

    with patch.object(gcp_tools, '_get_user_gcp_credentials', return_value=(None, None)):
        with patch('googleapiclient.discovery.build') as mock_build:
            result = gcp_tools.gcp_api_write(
                'compute', 'v1', 'instances', 'delete', {'zone': 'us-central1-a', 'instance': 'x'}
            )

    assert result['success'] is False
    assert 'not configured' in result['error'].lower()
    mock_build.assert_not_called()
