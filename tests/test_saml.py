"""Tests for SAML 2.0 SP support — services/saml_service.py.

Builds real signed SAML assertions with signxml + a self-signed cert and drives
them through the SP validation path, including the security checks.
"""

import base64
from datetime import datetime, timedelta

import lxml.etree as ET
import pytest

from services import saml_service
from services.sso_service import SSOError
from src.utils.timeutils import utcnow

SAML = 'urn:oasis:names:tc:SAML:2.0:assertion'
SAMLP = 'urn:oasis:names:tc:SAML:2.0:protocol'

ISSUER = 'https://idp.example.com/saml/metadata'
AUDIENCE = 'https://app.test/auth/sso/saml/metadata'
ACS = 'https://app.test/auth/sso/acs'
REQUEST_ID = '_req-12345'


@pytest.fixture(scope='module')
def certkey():
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization, hashes
    from cryptography import x509
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subj = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, u"test-idp")])
    cert = (x509.CertificateBuilder().subject_name(subj).issuer_name(subj)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(utcnow() - timedelta(days=1))
            .not_valid_after(utcnow() + timedelta(days=365))
            .sign(key, hashes.SHA256()))
    cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode()
    key_pem = key.private_bytes(serialization.Encoding.PEM,
                                serialization.PrivateFormat.TraditionalOpenSSL,
                                serialization.NoEncryption()).decode()
    return cert_pem, key_pem


def _fmt(dt):
    return dt.strftime('%Y-%m-%dT%H:%M:%SZ')


def _build_response(cert_pem, key_pem, *, audience=AUDIENCE, recipient=ACS,
                    request_id=REQUEST_ID, nameid='alice@acme.com',
                    email_attr=None, name='Alice', groups=None,
                    not_before=None, not_on_or_after=None, sign=True, tamper=False):
    from signxml import XMLSigner

    now = utcnow()
    nb = _fmt(not_before or now - timedelta(minutes=1))
    noa = _fmt(not_on_or_after or now + timedelta(minutes=5))
    aid = '_assertion-1'

    attrs = ''
    if email_attr:
        attrs += f'<saml:Attribute Name="email"><saml:AttributeValue>{email_attr}</saml:AttributeValue></saml:Attribute>'
    if name:
        attrs += f'<saml:Attribute Name="name"><saml:AttributeValue>{name}</saml:AttributeValue></saml:Attribute>'
    if groups:
        vals = ''.join(f'<saml:AttributeValue>{g}</saml:AttributeValue>' for g in groups)
        attrs += f'<saml:Attribute Name="groups">{vals}</saml:Attribute>'

    # Build the full Response with the assertion inside, then sign the assertion
    # in place — this mirrors how an IdP produces the document and keeps the
    # canonicalization context identical at sign and verify time.
    resp_str = (
        f'<samlp:Response xmlns:samlp="{SAMLP}" xmlns:saml="{SAML}" '
        f'ID="_resp-1" Version="2.0" IssueInstant="{_fmt(now)}" Destination="{recipient}">'
        f'<saml:Issuer>{ISSUER}</saml:Issuer>'
        f'<samlp:Status><samlp:StatusCode Value="urn:oasis:names:tc:SAML:2.0:status:Success"/></samlp:Status>'
        f'<saml:Assertion ID="{aid}" Version="2.0" IssueInstant="{_fmt(now)}">'
        f'<saml:Issuer>{ISSUER}</saml:Issuer>'
        f'<saml:Subject>'
        f'<saml:NameID Format="urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress">{nameid}</saml:NameID>'
        f'<saml:SubjectConfirmation Method="urn:oasis:names:tc:SAML:2.0:cm:bearer">'
        f'<saml:SubjectConfirmationData Recipient="{recipient}" NotOnOrAfter="{noa}" InResponseTo="{request_id}"/>'
        f'</saml:SubjectConfirmation></saml:Subject>'
        f'<saml:Conditions NotBefore="{nb}" NotOnOrAfter="{noa}">'
        f'<saml:AudienceRestriction><saml:Audience>{audience}</saml:Audience></saml:AudienceRestriction>'
        f'</saml:Conditions>'
        f'<saml:AttributeStatement>{attrs}</saml:AttributeStatement>'
        f'</saml:Assertion>'
        f'</samlp:Response>'
    )
    root = ET.fromstring(resp_str.encode())
    assertion = root.find(f'{{{SAML}}}Assertion')

    if sign:
        signed = XMLSigner().sign(assertion, key=key_pem.encode(),
                                  cert=cert_pem.encode(), reference_uri=aid)
        root.replace(assertion, signed)
    if tamper:
        root.find(f'.//{{{SAML}}}NameID').text = 'attacker@evil.com'

    return base64.b64encode(ET.tostring(root)).decode()


def _config(cert_pem):
    return {'provider': 'saml', 'idp_entity_id': ISSUER, 'idp_sso_url': 'https://idp.example.com/sso',
            'idp_x509_cert': cert_pem}


# --------------------------------------------------------------------------- #
# AuthnRequest + config validation
# --------------------------------------------------------------------------- #

def test_build_authn_request():
    cfg = {'provider': 'saml', 'idp_sso_url': 'https://idp.example.com/sso'}
    url, request_id = saml_service.build_authn_request(cfg, ACS, AUDIENCE, 'relay123')
    assert url.startswith('https://idp.example.com/sso?')
    assert 'SAMLRequest=' in url
    assert 'RelayState=relay123' in url
    assert request_id.startswith('_')


def test_build_authn_request_missing_url():
    with pytest.raises(SSOError):
        saml_service.build_authn_request({'provider': 'saml'}, ACS, AUDIENCE)


def test_validate_saml_config():
    ok, _ = saml_service.validate_saml_config(
        {'idp_sso_url': 'x', 'idp_entity_id': 'y', 'idp_x509_cert': 'z'})
    assert ok
    ok, err = saml_service.validate_saml_config({'idp_sso_url': 'x', 'idp_entity_id': 'y'})
    assert not ok and 'certificate' in err.lower()


# --------------------------------------------------------------------------- #
# Response validation — happy paths
# --------------------------------------------------------------------------- #

def test_valid_response_returns_identity(certkey):
    cert_pem, key_pem = certkey
    resp = _build_response(cert_pem, key_pem)
    identity = saml_service.parse_and_validate_response(
        _config(cert_pem), resp, ACS, AUDIENCE, REQUEST_ID)
    assert identity.provider == 'saml'
    assert identity.email == 'alice@acme.com'
    assert identity.email_verified is True
    assert identity.name == 'Alice'
    assert identity.subject == 'alice@acme.com'


def test_groups_extracted_from_assertion(certkey):
    cert_pem, key_pem = certkey
    resp = _build_response(cert_pem, key_pem, groups=['admins', 'engineering'])
    identity = saml_service.parse_and_validate_response(
        _config(cert_pem), resp, ACS, AUDIENCE, REQUEST_ID)
    assert identity.groups == ['admins', 'engineering']


def test_email_from_attribute_when_nameid_opaque(certkey):
    cert_pem, key_pem = certkey
    resp = _build_response(cert_pem, key_pem, nameid='opaque-id-123',
                           email_attr='bob@acme.com')
    identity = saml_service.parse_and_validate_response(
        _config(cert_pem), resp, ACS, AUDIENCE, REQUEST_ID)
    assert identity.email == 'bob@acme.com'
    assert identity.subject == 'opaque-id-123'


def test_works_without_request_id_when_session_absent(certkey):
    cert_pem, key_pem = certkey
    resp = _build_response(cert_pem, key_pem)
    identity = saml_service.parse_and_validate_response(
        _config(cert_pem), resp, ACS, AUDIENCE, expected_request_id=None)
    assert identity.email == 'alice@acme.com'


# --------------------------------------------------------------------------- #
# Response validation — security checks
# --------------------------------------------------------------------------- #

def test_tampered_assertion_rejected(certkey):
    cert_pem, key_pem = certkey
    resp = _build_response(cert_pem, key_pem, tamper=True)
    with pytest.raises(SSOError):
        saml_service.parse_and_validate_response(_config(cert_pem), resp, ACS, AUDIENCE, REQUEST_ID)


def test_unsigned_response_rejected(certkey):
    cert_pem, key_pem = certkey
    resp = _build_response(cert_pem, key_pem, sign=False)
    with pytest.raises(SSOError) as ei:
        saml_service.parse_and_validate_response(_config(cert_pem), resp, ACS, AUDIENCE, REQUEST_ID)
    assert 'signed' in str(ei.value).lower()


def test_wrong_audience_rejected(certkey):
    cert_pem, key_pem = certkey
    resp = _build_response(cert_pem, key_pem, audience='https://evil.test/sp')
    with pytest.raises(SSOError) as ei:
        saml_service.parse_and_validate_response(_config(cert_pem), resp, ACS, AUDIENCE, REQUEST_ID)
    assert 'audience' in str(ei.value).lower()


def test_expired_assertion_rejected(certkey):
    cert_pem, key_pem = certkey
    past = utcnow() - timedelta(hours=1)
    resp = _build_response(cert_pem, key_pem, not_on_or_after=past)
    with pytest.raises(SSOError) as ei:
        saml_service.parse_and_validate_response(_config(cert_pem), resp, ACS, AUDIENCE, REQUEST_ID)
    assert 'expired' in str(ei.value).lower()


def test_recipient_mismatch_rejected(certkey):
    cert_pem, key_pem = certkey
    resp = _build_response(cert_pem, key_pem, recipient='https://evil.test/acs')
    with pytest.raises(SSOError) as ei:
        saml_service.parse_and_validate_response(_config(cert_pem), resp, ACS, AUDIENCE, REQUEST_ID)
    assert 'recipient' in str(ei.value).lower()


def test_wrong_signing_cert_rejected(certkey):
    cert_pem, key_pem = certkey
    resp = _build_response(cert_pem, key_pem)
    # Validate against a different cert than signed with.
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization, hashes
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subj = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, u"other")])
    other_cert = (x509.CertificateBuilder().subject_name(subj).issuer_name(subj)
                  .public_key(other.public_key()).serial_number(x509.random_serial_number())
                  .not_valid_before(utcnow() - timedelta(days=1))
                  .not_valid_after(utcnow() + timedelta(days=365))
                  .sign(other, hashes.SHA256()))
    bad_pem = other_cert.public_bytes(serialization.Encoding.PEM).decode()
    with pytest.raises(SSOError):
        saml_service.parse_and_validate_response(
            {'provider': 'saml', 'idp_entity_id': ISSUER, 'idp_x509_cert': bad_pem},
            resp, ACS, AUDIENCE, REQUEST_ID)


def test_sp_metadata_contains_acs():
    xml = saml_service.sp_metadata(AUDIENCE, ACS)
    assert AUDIENCE in xml
    assert ACS in xml
    assert 'AssertionConsumerService' in xml
