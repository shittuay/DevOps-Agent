from unittest.mock import MagicMock, patch

from services.backup_upload import expected_bucket_owner, upload_backup_to_s3


def test_owner_env_override_skips_sts(monkeypatch):
    monkeypatch.setenv('BACKUP_S3_BUCKET_OWNER', '111122223333')
    with patch('boto3.client') as client:
        assert expected_bucket_owner() == '111122223333'
    client.assert_not_called()


def test_owner_defaults_to_caller_account(monkeypatch):
    monkeypatch.delenv('BACKUP_S3_BUCKET_OWNER', raising=False)
    sts = MagicMock()
    sts.get_caller_identity.return_value = {'Account': '444455556666'}
    with patch('boto3.client', return_value=sts) as client:
        assert expected_bucket_owner() == '444455556666'
    client.assert_called_once_with('sts')


def test_upload_pins_expected_bucket_owner(monkeypatch):
    monkeypatch.setenv('BACKUP_S3_BUCKET_OWNER', '111122223333')
    s3 = MagicMock()
    with patch('boto3.client', return_value=s3):
        upload_backup_to_s3('/tmp/b.gz', 'my-bucket', 'database-backups/b.gz')
    s3.upload_file.assert_called_once_with(
        '/tmp/b.gz', 'my-bucket', 'database-backups/b.gz',
        ExtraArgs={'ExpectedBucketOwner': '111122223333'},
    )
