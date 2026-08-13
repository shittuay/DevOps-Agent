"""Minimal fake boto3 clients for drift-detection tests.

Deliberately raise the real botocore ClientError shapes, since the not-found
handling in drift_detection.py keys off specific AWS error codes.
"""
from botocore.exceptions import ClientError


def _not_found(code, op):
    return ClientError({'Error': {'Code': code, 'Message': 'not found'}}, op)


class FakeEc2:
    def __init__(self, instances=None, security_groups=None):
        self.instances = instances or {}
        self.security_groups = security_groups or {}

    def describe_instances(self, InstanceIds):
        found = [self.instances[i] for i in InstanceIds if i in self.instances]
        if not found:
            raise _not_found('InvalidInstanceID.NotFound', 'DescribeInstances')
        return {'Reservations': [{'Instances': found}]}

    def describe_security_groups(self, GroupIds):
        found = [self.security_groups[g] for g in GroupIds if g in self.security_groups]
        if not found:
            raise _not_found('InvalidGroup.NotFound', 'DescribeSecurityGroups')
        return {'SecurityGroups': found}


class FakeRds:
    def __init__(self, instances=None):
        self.instances = instances or {}

    def describe_db_instances(self, DBInstanceIdentifier):
        db = self.instances.get(DBInstanceIdentifier)
        if not db:
            raise _not_found('DBInstanceNotFound', 'DescribeDBInstances')
        return {'DBInstances': [db]}


class FakeS3:
    def __init__(self, buckets=None):
        self.buckets = buckets or {}

    def head_bucket(self, Bucket):
        if Bucket not in self.buckets:
            raise _not_found('404', 'HeadBucket')
        return {}

    def get_bucket_versioning(self, Bucket):
        return {'Status': 'Enabled' if self.buckets[Bucket].get('versioning') else 'Suspended'}

    def get_bucket_encryption(self, Bucket):
        algo = self.buckets[Bucket].get('encryption')
        if not algo:
            raise _not_found('ServerSideEncryptionConfigurationNotFoundError', 'GetBucketEncryption')
        return {'ServerSideEncryptionConfiguration': {'Rules': [
            {'ApplyServerSideEncryptionByDefault': {'SSEAlgorithm': algo}}
        ]}}

    def get_public_access_block(self, Bucket):
        return {'PublicAccessBlockConfiguration': self.buckets[Bucket].get('pab', {})}


def clear_drift_state():
    """Baselines/reports are committed straight to the DB, so they outlive db_session
    rollback and leak between tests. Wipe them between cases."""
    from models import db, DriftBaselineModel, DriftReportModel

    DriftBaselineModel.query.delete()
    DriftReportModel.query.delete()
    db.session.commit()


def patch_boto(monkeypatch, clients_by_service, error=None):
    """Route get_user_boto_client to fakes, or raise `error` to simulate no credentials."""
    import services.credential_service as cs

    def fake_get_client(user_id, service, region=None):
        if error:
            raise error
        if service not in clients_by_service:
            raise AssertionError(f"test did not provide a fake for '{service}'")
        return clients_by_service[service]

    monkeypatch.setattr(cs, 'get_user_boto_client', fake_get_client)
