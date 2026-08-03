"""Regression tests for Azure error-message translation in azure_tools.py.

A correctly-configured, correctly-scoped (Contributor) Azure service principal
can still fail to create resources for subscription-level reasons that have
nothing to do with the credentials: an unregistered resource provider, quota,
or region/SKU availability. Before this fix, every azure_tools.py create/
delete/manage function returned Azure's raw SDK exception text verbatim,
which names the ARM error code but gives no indication of what to do about
it — someone hitting AuthorizationFailed or MissingSubscriptionRegistration
would reasonably (but wrongly) assume their saved credentials were broken.

_friendly_azure_error() recognizes the handful of common ARM error codes and
appends actionable guidance while preserving the original error text.
"""
from unittest.mock import MagicMock, patch

from src.tools.azure_tools import _friendly_azure_error, create_resource_group


def test_authorization_failed_points_to_contributor_access():
    e = Exception(
        "(AuthorizationFailed) The client 'xxx' does not have authorization to "
        "perform action 'Microsoft.Compute/virtualMachines/write' over scope '...'"
    )
    msg = _friendly_azure_error(e)
    assert 'Contributor' in msg
    assert 'Settings > Cloud Credentials' in msg
    assert 'AuthorizationFailed' in msg  # original error preserved


def test_missing_subscription_registration_extracts_namespace():
    e = Exception(
        "The subscription is not registered to use namespace 'Microsoft.Compute'. "
        "See https://aka.ms/rps-not-found for how to register subscriptions."
    )
    msg = _friendly_azure_error(e)
    assert 'az provider register --namespace Microsoft.Compute --wait' in msg
    assert 'MissingSubscriptionRegistration' in msg


def test_quota_exceeded_points_to_portal():
    e = Exception(
        "(QuotaExceeded) Operation could not be completed as it results in "
        "exceeding approved Total Regional Cores quota."
    )
    msg = _friendly_azure_error(e)
    assert 'Usage + quotas' in msg
    assert 'QuotaExceeded' in msg


def test_sku_not_available_suggests_alternatives():
    e = Exception(
        "(SkuNotAvailable) The requested VM size for resource 'foo' is currently "
        "not available in location 'eastus'."
    )
    msg = _friendly_azure_error(e)
    assert 'different VM size or a different region' in msg


def test_unrecognized_error_passes_through_unchanged():
    e = Exception("(SomeOtherError) totally novel failure mode")
    assert _friendly_azure_error(e) == str(e)


def test_create_resource_group_surfaces_friendly_authorization_error():
    """End-to-end: a write tool function's except block actually calls the
    translator, not just the standalone helper."""
    mock_client = MagicMock()
    mock_client.resource_groups.create_or_update.side_effect = Exception(
        "(AuthorizationFailed) does not have authorization to perform action "
        "'Microsoft.Resources/subscriptions/resourceGroups/write'"
    )

    with patch('src.tools.azure_tools._get_azure_client', return_value=mock_client):
        result = create_resource_group('my-rg', 'eastus')

    assert result['success'] is False
    assert 'Contributor' in result['error']
    assert 'AuthorizationFailed' in result['error']
