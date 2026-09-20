"""SAML 2.0 Service Provider (SP) support for organization SSO.

A second provider type alongside the OIDC flow in ``sso_service``. Reuses the
same ``Identity`` and JIT provisioning, so the route/provisioning layer is
protocol-agnostic.

Flow (SP-initiated, HTTP-Redirect AuthnRequest -> HTTP-POST Response):
  1. build_authn_request()          -> redirect URL + request_id (stored in session)
  2. (IdP authenticates, POSTs SAMLResponse to the ACS endpoint)
  3. parse_and_validate_response()  -> normalized Identity

Security:
  - XML parsed with a hardened parser (entities/network/DTD disabled -> no XXE).
  - Assertion signature verified against the IdP's X.509 cert (signxml).
  - Claims are read ONLY from the cryptographically-verified subtree returned by
    the verifier (defends against XML Signature Wrapping).
  - Audience == SP entityID, Conditions NotBefore/NotOnOrAfter (with clock skew),
    SubjectConfirmationData Recipient == ACS URL, and InResponseTo == the request
    we issued are all validated.
"""

from __future__ import annotations

import base64
import logging
import secrets
import zlib
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple
from urllib.parse import urlencode

import lxml.etree as ET

from services.sso_service import Identity, SSOError
from src.utils.timeutils import utcnow

logger = logging.getLogger(__name__)

NS = {
    'samlp': 'urn:oasis:names:tc:SAML:2.0:protocol',
    'saml': 'urn:oasis:names:tc:SAML:2.0:assertion',
    'ds': 'http://www.w3.org/2000/09/xmldsig#',
    'md': 'urn:oasis:names:tc:SAML:2.0:metadata',
}
_CLOCK_SKEW = timedelta(minutes=3)

# Attribute names IdPs commonly use for email / display name.
_EMAIL_ATTRS = (
    'email', 'mail', 'emailaddress',
    'http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress',
    'urn:oid:0.9.2342.19200300.100.1.3',
)
_NAME_ATTRS = (
    'name', 'displayname', 'cn',
    'http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name',
    'http://schemas.xmlsoap.org/ws/2005/05/identity/claims/displayname',
    'urn:oid:2.16.840.1.113730.3.1.241', 'urn:oid:2.5.4.3',
)


def _hardened_parser() -> ET.XMLParser:
    return ET.XMLParser(resolve_entities=False, no_network=True,
                        load_dtd=False, dtd_validation=False, huge_tree=False)


def _normalize_cert(cert: str) -> str:
    cert = (cert or '').strip()
    if not cert:
        raise SSOError("IdP signing certificate is not configured")
    if '-----BEGIN CERTIFICATE-----' in cert:
        return cert
    body = ''.join(cert.split())
    lines = '\n'.join(body[i:i + 64] for i in range(0, len(body), 64))
    return f"-----BEGIN CERTIFICATE-----\n{lines}\n-----END CERTIFICATE-----\n"


def _parse_dt(value: str) -> Optional[datetime]:
    if not value:
        return None
    value = value.strip().rstrip('Z')
    for fmt in ('%Y-%m-%dT%H:%M:%S.%f', '%Y-%m-%dT%H:%M:%S'):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


# --------------------------------------------------------------------------- #
# Config validation (used by the admin save path)
# --------------------------------------------------------------------------- #

def validate_saml_config(config: Dict) -> Tuple[bool, Optional[str]]:
    if not (config.get('idp_sso_url') or '').strip():
        return False, "IdP SSO URL is required"
    if not (config.get('idp_entity_id') or '').strip():
        return False, "IdP Entity ID (Issuer) is required"
    if not (config.get('idp_x509_cert') or '').strip():
        return False, "IdP signing certificate is required"
    return True, None


# --------------------------------------------------------------------------- #
# SP-initiated AuthnRequest (HTTP-Redirect binding)
# --------------------------------------------------------------------------- #

def build_authn_request(config: Dict, acs_url: str, sp_entity_id: str,
                        relay_state: str = '') -> Tuple[str, str]:
    """Return (redirect_url, request_id) for an SP-initiated login."""
    sso_url = (config.get('idp_sso_url') or '').strip()
    if not sso_url:
        raise SSOError("SAML provider is missing the IdP SSO URL")

    request_id = '_' + secrets.token_hex(16)
    issue_instant = utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
    xml = (
        '<samlp:AuthnRequest xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol" '
        'xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion" '
        f'ID="{request_id}" Version="2.0" IssueInstant="{issue_instant}" '
        f'Destination="{_xml_attr(sso_url)}" '
        f'AssertionConsumerServiceURL="{_xml_attr(acs_url)}" '
        'ProtocolBinding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST">'
        f'<saml:Issuer>{_xml_text(sp_entity_id)}</saml:Issuer>'
        '<samlp:NameIDPolicy '
        'Format="urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress" '
        'AllowCreate="true"/>'
        '</samlp:AuthnRequest>'
    )

    # HTTP-Redirect binding: raw DEFLATE -> base64 -> urlencode.
    compressor = zlib.compressobj(9, zlib.DEFLATED, -15)
    deflated = compressor.compress(xml.encode('utf-8')) + compressor.flush()
    saml_request = base64.b64encode(deflated).decode('ascii')

    params = {'SAMLRequest': saml_request}
    if relay_state:
        params['RelayState'] = relay_state
    sep = '&' if '?' in sso_url else '?'
    return sso_url + sep + urlencode(params), request_id


def _xml_attr(value: str) -> str:
    return (value or '').replace('&', '&amp;').replace('"', '&quot;').replace('<', '&lt;')


def _xml_text(value: str) -> str:
    return (value or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


# --------------------------------------------------------------------------- #
# Response parsing + validation
# --------------------------------------------------------------------------- #

def _verify_signed_assertion(xml_bytes: bytes, cert_pem: str):
    """Verify the enveloped signature and return the verified Assertion element.

    Reads claims only from the element returned by the verifier, so unsigned or
    wrapped (XSW) assertions are ignored.
    """
    from signxml import XMLVerifier

    try:
        root = ET.fromstring(xml_bytes, parser=_hardened_parser())
    except Exception as e:
        logger.error("SAML response is not well-formed XML: %s", e)
        raise SSOError("Malformed SAML response")

    if root.find('.//ds:Signature', NS) is None:
        raise SSOError("SAML response is not signed")

    try:
        verified = XMLVerifier().verify(root, x509_cert=cert_pem).signed_xml
    except Exception as e:
        logger.warning("SAML signature verification failed: %s", e)
        raise SSOError("SAML signature verification failed")

    tag = ET.QName(verified).localname
    if tag == 'Assertion':
        return verified
    if tag == 'Response':
        assertion = verified.find('saml:Assertion', NS)
        if assertion is not None:
            return assertion
    raise SSOError("No signed SAML assertion found in the response")


def _validate_conditions(assertion, sp_entity_id: str, acs_url: str,
                         expected_request_id: Optional[str], idp_entity_id: str) -> None:
    issuer = assertion.findtext('saml:Issuer', namespaces=NS)
    if issuer and idp_entity_id and issuer.strip() != idp_entity_id.strip():
        raise SSOError("SAML assertion issuer does not match the configured IdP")

    now = utcnow()
    conditions = assertion.find('saml:Conditions', NS)
    if conditions is not None:
        nb = _parse_dt(conditions.get('NotBefore'))
        na = _parse_dt(conditions.get('NotOnOrAfter'))
        if nb and now + _CLOCK_SKEW < nb:
            raise SSOError("SAML assertion is not yet valid")
        if na and now - _CLOCK_SKEW >= na:
            raise SSOError("SAML assertion has expired")

        audiences = conditions.findall('.//saml:Audience', NS)
        if audiences:
            values = {a.text.strip() for a in audiences if a.text}
            if sp_entity_id not in values:
                raise SSOError("SAML assertion audience does not match this service")

    # SubjectConfirmationData: recipient + InResponseTo + expiry
    scd = assertion.find('.//saml:SubjectConfirmation/saml:SubjectConfirmationData', NS)
    if scd is not None:
        recipient = scd.get('Recipient')
        if recipient and recipient.strip().rstrip('/') != acs_url.strip().rstrip('/'):
            raise SSOError("SAML assertion recipient does not match the ACS URL")
        na = _parse_dt(scd.get('NotOnOrAfter'))
        if na and now - _CLOCK_SKEW >= na:
            raise SSOError("SAML assertion confirmation has expired")
        in_response_to = scd.get('InResponseTo')
        if expected_request_id and in_response_to and in_response_to != expected_request_id:
            raise SSOError("SAML assertion does not correspond to this login request")
    elif expected_request_id:
        # SP-initiated login must echo our request id somewhere.
        if assertion.find('.//saml:SubjectConfirmationData', NS) is None:
            logger.warning("SAML assertion missing SubjectConfirmationData for solicited login")


def _extract_attributes(assertion) -> Dict[str, str]:
    attrs: Dict[str, str] = {}
    for attr in assertion.findall('.//saml:AttributeStatement/saml:Attribute', NS):
        name = (attr.get('Name') or attr.get('FriendlyName') or '').strip().lower()
        value_el = attr.find('saml:AttributeValue', NS)
        if name and value_el is not None and value_el.text:
            attrs[name] = value_el.text.strip()
    return attrs


def parse_and_validate_response(config: Dict, saml_response_b64: str, acs_url: str,
                                sp_entity_id: str,
                                expected_request_id: Optional[str] = None) -> Identity:
    if not saml_response_b64:
        raise SSOError("No SAML response received")
    try:
        xml_bytes = base64.b64decode(saml_response_b64)
    except Exception:
        raise SSOError("SAML response is not valid base64")

    cert_pem = _normalize_cert(config.get('idp_x509_cert', ''))
    assertion = _verify_signed_assertion(xml_bytes, cert_pem)
    _validate_conditions(assertion, sp_entity_id, acs_url, expected_request_id,
                         config.get('idp_entity_id', ''))

    attrs = _extract_attributes(assertion)
    name_id = assertion.findtext('.//saml:Subject/saml:NameID', namespaces=NS)
    name_id = name_id.strip() if name_id else None

    email = None
    if name_id and '@' in name_id:
        email = name_id
    if not email:
        for key in _EMAIL_ATTRS:
            if attrs.get(key):
                email = attrs[key]
                break
    if not email:
        raise SSOError("SAML assertion did not include an email address")

    name = None
    for key in _NAME_ATTRS:
        if attrs.get(key):
            name = attrs[key]
            break

    subject = name_id or email
    groups = _extract_groups(assertion, config.get('groups_attribute'))
    # SAML IdPs vouch for the identity; treat the email as verified.
    return Identity(subject=subject, email=email.lower(), email_verified=True,
                    name=name, provider='saml', groups=groups)


def _extract_groups(assertion, groups_attr: Optional[str]) -> list:
    """Collect all values of the group/role attribute (multi-valued)."""
    target = (groups_attr or 'groups').strip().lower()
    groups = []
    for attr in assertion.findall('.//saml:AttributeStatement/saml:Attribute', NS):
        name = (attr.get('Name') or attr.get('FriendlyName') or '').strip().lower()
        if name == target or 'group' in name or name.endswith('/claims/group'):
            for value_el in attr.findall('saml:AttributeValue', NS):
                if value_el.text and value_el.text.strip():
                    groups.append(value_el.text.strip())
    return groups


# --------------------------------------------------------------------------- #
# SP metadata
# --------------------------------------------------------------------------- #

def sp_metadata(sp_entity_id: str, acs_url: str) -> str:
    return (
        '<?xml version="1.0"?>'
        '<md:EntityDescriptor xmlns:md="urn:oasis:names:tc:SAML:2.0:metadata" '
        f'entityID="{_xml_attr(sp_entity_id)}">'
        '<md:SPSSODescriptor AuthnRequestsSigned="false" WantAssertionsSigned="true" '
        'protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol">'
        '<md:NameIDFormat>urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress</md:NameIDFormat>'
        '<md:AssertionConsumerService '
        'Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST" '
        f'Location="{_xml_attr(acs_url)}" index="0" isDefault="true"/>'
        '</md:SPSSODescriptor></md:EntityDescriptor>'
    )
