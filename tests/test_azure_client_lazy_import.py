"""Regression test: `_get_azure_client()` must import and construct only the
requested service's SDK client, never all seven up front.

Before this fix, `_get_azure_client()` imported all seven azure-mgmt-* SDKs
(compute/storage/network/resource/monitor/container/sql) inside one `try` and
eagerly constructed all seven client objects on every call, discarding six of
them. A single broken/missing azure-mgmt-* package, or a failed construction
of any of the six unused clients, took down every Azure tool at once — the
exact bug already found and fixed in gcp_tools.py's `_get_gcp_client()`
(2026-08-11) but never ported to its Azure sibling.

These tests pin the lazy-import contract itself: a future refactor that goes
back to importing/constructing every client up front would fail these.
"""
from unittest.mock import MagicMock, patch

import pytest


def test_compute_client_construction_does_not_import_other_sdks():
    """Requesting 'compute' must never touch the sql/storage/etc. SDKs, so a
    broken azure-mgmt-sql install can't break compute operations."""
    from src.tools import azure_tools

    fake_credential = MagicMock()
    with patch.object(
        azure_tools, 'get_user_azure_credential',
        create=True, return_value=(fake_credential, 'sub-1', 'eastus'),
    ), patch(
        'services.credential_service.get_user_azure_credential',
        return_value=(fake_credential, 'sub-1', 'eastus'),
    ), patch.dict(
        'sys.modules',
        {
            'azure.mgmt.sql': None,
            'azure.mgmt.storage': None,
            'azure.mgmt.network': None,
            'azure.mgmt.resource': None,
            'azure.mgmt.monitor': None,
            'azure.mgmt.containerinstance': None,
        },
    ):
        client = azure_tools._get_azure_client('compute', user_id=1)

    assert client is not None
    assert type(client).__name__ == 'ComputeManagementClient'


def test_unknown_service_type_raises_instead_of_returning_none():
    """The old dict.get(service_type) shape silently returned None for a typo
    or an unhandled service_type; callers would then AttributeError deep
    inside their own logic instead of getting an actionable error."""
    from src.tools import azure_tools

    fake_credential = MagicMock()
    with patch(
        'services.credential_service.get_user_azure_credential',
        return_value=(fake_credential, 'sub-1', 'eastus'),
    ):
        with pytest.raises(Exception) as exc:
            azure_tools._get_azure_client('not-a-real-service', user_id=1)

    assert 'unknown azure service type' in str(exc.value).lower()


def test_only_requested_client_is_constructed():
    """Guards against reintroducing eager construction of all seven clients —
    constructing e.g. a SqlManagementClient with bad/incomplete credentials
    should never be able to break a 'storage' request."""
    from src.tools import azure_tools

    fake_credential = MagicMock()
    with patch(
        'services.credential_service.get_user_azure_credential',
        return_value=(fake_credential, 'sub-1', 'eastus'),
    ), patch(
        'azure.mgmt.sql.SqlManagementClient',
        side_effect=Exception('sql client should never be constructed for a storage request'),
    ):
        client = azure_tools._get_azure_client('storage', user_id=1)

    assert type(client).__name__ == 'StorageManagementClient'
