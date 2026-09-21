"""Upload database backups to S3, pinned to the bucket owner we expect.

A backup bucket is named by an env var. If that name is mistyped, or the bucket
is deleted and its (globally unique) name re-registered by someone else, a plain
upload_file() writes a full database dump into a stranger's account. Passing
ExpectedBucketOwner makes S3 reject the write with 403 instead.
"""

import os
from typing import Optional


def expected_bucket_owner(session=None) -> str:
    """Account id that must own the backup bucket.

    BACKUP_S3_BUCKET_OWNER wins when set (bucket in another account); otherwise
    the account of the credentials doing the upload.
    """
    owner = os.environ.get('BACKUP_S3_BUCKET_OWNER', '').strip()
    if owner:
        return owner
    import boto3
    sts = (session or boto3).client('sts')
    return sts.get_caller_identity()['Account']


def upload_backup_to_s3(local_path: str, bucket: str, key: str,
                        owner: Optional[str] = None) -> None:
    """Upload a backup file, failing if the bucket is not owned by `owner`."""
    import boto3
    boto3.client('s3').upload_file(
        str(local_path), bucket, key,
        ExtraArgs={'ExpectedBucketOwner': owner or expected_bucket_owner()},
    )
