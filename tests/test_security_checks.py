"""AWS security checks and the removal of the Compliance area (2026-10-14 audit).

The scanner used to swallow every read error, so an account it could not read looked
clean; it counted each new finding twice (it appended to the list it was iterating);
and it never closed a finding once the problem was fixed. Compliance built SOC 2 /
HIPAA / PCI scores on top of it in which unchecked controls passed automatically, so
an account with no cloud credentials scored 100%.
"""
import importlib

import pytest
from botocore.exceptions import ClientError

import services.security_scanner as scanner


def _denied(op='Op'):
    return ClientError({'Error': {'Code': 'AccessDenied', 'Message': 'denied'}}, op)


class _Pager:
    def __init__(self, pages):
        self.pages = pages

    def paginate(self):
        return iter(self.pages)


class FakeS3:
    def __init__(self, buckets, public=(), unencrypted=(), enc_denied=()):
        self.buckets, self.public, self.unencrypted, self.enc_denied = buckets, set(public), set(unencrypted), set(enc_denied)

    def list_buckets(self):
        return {'Buckets': [{'Name': b} for b in self.buckets]}

    def get_bucket_acl(self, Bucket):
        grants = [{'Grantee': {'Type': 'Group', 'URI': 'http://acs.amazonaws.com/groups/global/AllUsers'}}] \
            if Bucket in self.public else []
        return {'Grants': grants}

    def get_bucket_encryption(self, Bucket):
        if Bucket in self.enc_denied:
            raise _denied('GetBucketEncryption')
        if Bucket in self.unencrypted:
            raise ClientError({'Error': {'Code': 'ServerSideEncryptionConfigurationNotFoundError'}}, 'GetBucketEncryption')
        return {}

    def get_bucket_versioning(self, Bucket):
        return {'Status': 'Enabled'}


class FakeEC2:
    meta = type('M', (), {'region_name': 'us-east-1'})()

    def __init__(self, open_ssh=()):
        self.open_ssh = open_ssh

    def get_paginator(self, name):
        groups = [{'GroupId': g, 'GroupName': g, 'IpPermissions': [
            {'IpProtocol': 'tcp', 'FromPort': 22, 'ToPort': 22, 'IpRanges': [{'CidrIp': '0.0.0.0/0'}]}]}
            for g in self.open_ssh]
        return _Pager([{'SecurityGroups': groups}])


class Empty:
    meta = type('M', (), {'region_name': 'us-east-1'})()

    def get_paginator(self, name):
        key = {'describe_db_instances': 'DBInstances', 'list_users': 'Users'}[name]
        return _Pager([{key: []}])


def _install(monkeypatch, **clients):
    def fake(service, user_id):
        c = clients.get(service)
        if isinstance(c, Exception):
            raise c
        return c if c is not None else Empty()
    monkeypatch.setattr(scanner, '_get_boto_client', fake)
    monkeypatch.setattr(scanner, '_notify_security', lambda *a, **k: None)


def _open(user):
    from models import SecurityFinding
    return SecurityFinding.query.filter_by(user_id=user.id, status='open').all()


def test_unreadable_account_is_an_error_not_a_clean_result(monkeypatch, test_user, db_session):
    _install(monkeypatch, s3=_denied(), ec2=_denied(), rds=_denied(), iam=_denied())
    with pytest.raises(scanner.SecurityScanError):
        scanner.scan_aws_security(test_user.id)


def test_findings_are_counted_once(monkeypatch, test_user, db_session):
    _install(monkeypatch, s3=FakeS3(['logs'], public=['logs']), ec2=FakeEC2(open_ssh=['sg-1']))
    r = scanner.scan_aws_security(test_user.id)
    assert r['total'] == 2
    assert r['critical'] == 1 and r['high'] == 1
    assert len(_open(test_user)) == 2
    assert r['region'] == 'us-east-1'


def test_fixed_problems_close_and_failed_checks_keep_theirs(monkeypatch, test_user, db_session):
    _install(monkeypatch, s3=FakeS3(['logs'], public=['logs']), ec2=FakeEC2(open_ssh=['sg-1']))
    scanner.scan_aws_security(test_user.id)

    # Bucket fixed; EC2 now unreadable: the bucket finding closes, the SG one stays open.
    _install(monkeypatch, s3=FakeS3(['logs']), ec2=_denied())
    r = scanner.scan_aws_security(test_user.id)
    assert r['resolved'] == 1
    assert r['checks']['security_groups']['status'] == 'error'
    assert [f.finding_type for f in _open(test_user)] == ['overly_permissive_security_group']


def test_a_denied_read_is_a_warning_not_a_finding(monkeypatch, test_user, db_session):
    _install(monkeypatch, s3=FakeS3(['secret'], enc_denied=['secret']))
    r = scanner.scan_aws_security(test_user.id)
    assert r['total'] == 0
    assert r['checks']['s3']['warnings'], 'the bucket that could not be read must be reported'


def test_missing_default_encryption_is_a_finding(monkeypatch, test_user, db_session):
    _install(monkeypatch, s3=FakeS3(['raw'], unencrypted=['raw']))
    r = scanner.scan_aws_security(test_user.id)
    assert [f['finding_type'] for f in r['findings']] == ['unencrypted_s3_bucket']


@pytest.fixture
def aws_account(test_user, db_session):
    from models import UserCloudCredential, db
    cred = UserCloudCredential(user_id=test_user.id, cloud_provider='aws',
                               credentials_encrypted='x', is_active=True)
    db.session.add(cred)
    db.session.commit()
    yield cred
    db.session.delete(cred)
    db.session.commit()


def test_scan_without_aws_account_asks_to_connect(authenticated_client, test_user):
    resp = authenticated_client.post('/api/security/scan')
    assert resp.status_code == 400 and resp.get_json()['no_cloud_account'] is True


def test_scan_endpoint_reports_failure(authenticated_client, monkeypatch, test_user, aws_account):
    _install(monkeypatch, s3=_denied(), ec2=_denied(), rds=_denied(), iam=_denied())
    resp = authenticated_client.post('/api/security/scan')
    assert resp.status_code == 502
    assert resp.get_json()['scan_failed'] is True


def test_dismissed_finding_stays_hidden(authenticated_client, monkeypatch, test_user, aws_account):
    _install(monkeypatch, s3=FakeS3(['logs'], public=['logs']))
    assert authenticated_client.post('/api/security/scan').status_code == 200
    [finding] = authenticated_client.get('/api/security/summary').get_json()['findings']
    assert authenticated_client.post(f"/api/security/findings/{finding['id']}/dismiss").status_code == 200
    authenticated_client.post('/api/security/scan')
    assert authenticated_client.get('/api/security/summary').get_json()['findings'] == []


def test_cannot_dismiss_another_users_finding(authenticated_client, test_user, db_session):
    from models import SecurityFinding, User, db
    other = User(username='sec-other', email='sec-other@example.com')
    other.set_password('Another1Password!')
    db.session.add(other)
    db.session.commit()
    f = SecurityFinding(user_id=other.id, finding_type='open_s3_bucket', severity='critical', title='x')
    db.session.add(f)
    db.session.commit()
    assert authenticated_client.post(f'/api/security/findings/{f.id}/dismiss').status_code == 404
    db.session.refresh(f)
    assert f.status == 'open'


def test_compliance_tool_gives_no_score_and_names_unchecked(monkeypatch, test_user, db_session):
    from src.tools import devops_operations_tools as tools
    _install(monkeypatch, s3=FakeS3(['logs'], public=['logs']), iam=_denied())
    monkeypatch.setattr(tools, '_require_user', lambda: (test_user.id, None))
    out = tools.run_compliance_check('soc2')
    assert out['success'] and 'score' not in out
    status = {c['control']: c['status'] for c in out['controls']}
    assert status['CC6.1 Logical access'] == 'issues found'
    assert status['CC6.2 Authentication'] == 'not checked'
    assert 'not a compliance assessment' in out['note']


def test_compliance_tool_fails_when_nothing_could_be_read(monkeypatch, test_user, db_session):
    from src.tools import devops_operations_tools as tools
    _install(monkeypatch, s3=_denied(), ec2=_denied(), rds=_denied(), iam=_denied())
    monkeypatch.setattr(tools, '_require_user', lambda: (test_user.id, None))
    assert tools.run_compliance_check('hipaa')['success'] is False


@pytest.mark.parametrize('path', ['/compliance/', '/compliance/controls', '/compliance/reports',
                                  '/api/compliance/summary', '/api/compliance/report/soc2/pdf'])
def test_compliance_area_is_gone(authenticated_client, path):
    assert authenticated_client.get(path).status_code == 404


@pytest.mark.parametrize('module', ['routes.compliance', 'services.compliance_service',
                                    'services.pdf_service', 'tasks.security_tasks'])
def test_compliance_modules_are_gone(module):
    with pytest.raises(ImportError):
        importlib.import_module(module)
