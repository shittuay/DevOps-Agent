"""Regression test: GCP service-account temp credential file leaked on disk
when Credentials.from_service_account_file() raised.

Found during a scheduled security review: get_user_gcp_credentials_file()
writes a decrypted GCP service-account JSON (including the RSA private key)
to a tempfile.mkstemp() path; every caller (gcp_tools._get_user_gcp_credentials,
infrastructure_sync.sync_gcp_compute_instances/sync_gcp_storage_buckets/
sync_gcp_sql_instances) only removed that file *after* successfully loading
credentials from it, with no try/finally — so a malformed/invalid/revoked key
left the plaintext private key on disk indefinitely. Fixed by wrapping
Credentials.from_service_account_file() in try/finally at each call site.
"""
import os
import tempfile
from unittest.mock import patch

import pytest


def _write_fake_creds_file():
    fd, path = tempfile.mkstemp(suffix='.json', prefix='gcp_creds_test_')
    with os.fdopen(fd, 'w') as f:
        f.write('{"type": "service_account"}')
    return path


def test_gcp_tools_removes_temp_file_when_loading_fails(monkeypatch):
    from src.tools import gcp_tools

    path = _write_fake_creds_file()
    monkeypatch.setattr(gcp_tools, '_get_current_user_id', lambda: 42)

    with patch('services.credential_service.get_user_gcp_credentials_file',
               return_value=(path, 'proj-1', 'us-central1', 'us-central1-a')), \
         patch('google.oauth2.service_account.Credentials.from_service_account_file',
               side_effect=ValueError('stub: invalid key file')):
        credentials, project_id = gcp_tools._get_user_gcp_credentials()

    assert credentials is None
    assert not os.path.exists(path), (
        "temp GCP credentials file (contains a plaintext private key) was not "
        "cleaned up after Credentials.from_service_account_file() raised"
    )


def test_infrastructure_sync_compute_removes_temp_file_when_loading_fails(monkeypatch, app, db_session):
    from services import infrastructure_sync

    path = _write_fake_creds_file()

    with patch('services.credential_service.get_user_gcp_credentials_file',
               return_value=(path, 'proj-1', 'us-central1', 'us-central1-a')), \
         patch('google.oauth2.service_account.Credentials.from_service_account_file',
               side_effect=ValueError('stub: invalid key file')):
        with pytest.raises(ValueError):
            infrastructure_sync.sync_gcp_compute_instances(user_id=1)

    assert not os.path.exists(path), (
        "temp GCP credentials file (contains a plaintext private key) was not "
        "cleaned up after Credentials.from_service_account_file() raised"
    )
