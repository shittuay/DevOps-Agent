"""Single Sign-On (OIDC) service for organization-level federated login.

Supports generic OIDC plus presets for Google, Azure/Entra, and GitHub. Built as
a provider abstraction so SAML can be added later as another provider ``type``
without changing the route layer.

Auth flow (authorization code, confidential client):
  1. resolve_org_for_email() / org-initiated  -> choose org + provider config
  2. build_authorization_url()                 -> redirect to IdP (state+nonce in session)
  3. handle_callback()                          -> exchange code, validate token,
                                                   return normalized Identity
  4. find_or_provision_user()                   -> JIT create/link user + org membership

Security:
  - client_secret is encrypted at rest with the app's Fernet key (same derivation
    as cloud credentials).
  - CSRF via ``state``; replay protection via ``nonce`` on the id_token.
  - id_token signature verified against the IdP JWKS (joserfc); iss/aud/exp checked.
  - userinfo endpoint is used to fill gaps and for OAuth2-only providers (GitHub).
"""

from __future__ import annotations

import logging
import re
import secrets
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlencode

import requests

from src.utils.network_safety import safe_request, UnsafeUrlError

logger = logging.getLogger(__name__)

_HTTP_TIMEOUT = 10
_DISCOVERY_CACHE: Dict[str, Tuple[float, Dict]] = {}
_DISCOVERY_TTL = 3600  # seconds

SUPPORTED_PROVIDERS = ('generic_oidc', 'google', 'azure', 'github', 'saml')


@dataclass
class Identity:
    """Normalized identity returned by any provider."""
    subject: str
    email: str
    email_verified: bool
    name: Optional[str]
    provider: str
    groups: Optional[List[str]] = None


# Roles that may be granted via IdP group mapping (owner is never auto-granted).
_ROLE_PRECEDENCE = ['admin', 'member', 'viewer']


def role_from_groups(config: Dict, groups: Optional[List[str]]) -> Optional[str]:
    """Resolve the most-privileged org role for a user's IdP groups, or None.

    ``config['role_mappings']`` is a dict of {idp_group: org_role}. When a user
    belongs to several mapped groups, the most privileged role wins. 'owner' is
    never assignable via mapping.
    """
    mappings = (config or {}).get('role_mappings') or {}
    if not mappings or not groups:
        return None
    matched = {mappings[g] for g in groups if g in mappings}
    matched.discard('owner')
    for role in _ROLE_PRECEDENCE:
        if role in matched:
            return role
    return next(iter(matched)) if matched else None


class SSOError(Exception):
    """Raised on any recoverable SSO flow failure (shown to the user generically)."""


# --------------------------------------------------------------------------- #
# Secret encryption (reuses the app's Fernet key derivation)
# --------------------------------------------------------------------------- #

def _fernet():
    from cryptography.fernet import Fernet
    from models import UserCloudCredential
    return Fernet(UserCloudCredential._get_encryption_key())


def encrypt_secret(plaintext: str) -> str:
    if not plaintext:
        return ''
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_secret(token: str) -> str:
    if not token:
        return ''
    try:
        return _fernet().decrypt(token.encode()).decode()
    except Exception:
        logger.error("Failed to decrypt SSO client secret", exc_info=True)
        return ''


# --------------------------------------------------------------------------- #
# Provider endpoint resolution
# --------------------------------------------------------------------------- #

def _discover(metadata_url: str) -> Dict:
    """Fetch and cache an OIDC discovery document."""
    now = time.time()
    cached = _DISCOVERY_CACHE.get(metadata_url)
    if cached and (now - cached[0]) < _DISCOVERY_TTL:
        return cached[1]
    try:
        resp = safe_request('GET', metadata_url, timeout=_HTTP_TIMEOUT)
    except UnsafeUrlError as e:
        raise SSOError(f"OIDC discovery URL is not allowed: {e}")
    resp.raise_for_status()
    doc = resp.json()
    _DISCOVERY_CACHE[metadata_url] = (now, doc)
    return doc


def _discovery_url_for(config: Dict) -> Optional[str]:
    provider = config.get('provider')
    if provider == 'google':
        return 'https://accounts.google.com/.well-known/openid-configuration'
    if provider == 'azure':
        tenant = config.get('tenant_id') or 'common'
        return f'https://login.microsoftonline.com/{tenant}/v2.0/.well-known/openid-configuration'
    if provider == 'generic_oidc':
        url = (config.get('metadata_url') or '').strip()
        if not url and config.get('issuer'):
            url = config['issuer'].rstrip('/') + '/.well-known/openid-configuration'
        return url or None
    return None


def get_provider_endpoints(config: Dict) -> Dict:
    """Resolve the concrete OAuth/OIDC endpoints for a stored provider config.

    Returns a dict with: type ('oidc'|'oauth2'), authorization_endpoint,
    token_endpoint, userinfo_endpoint, jwks_uri (oidc), issuer (oidc), scopes,
    client_id, client_secret (decrypted).
    """
    provider = config.get('provider')
    if provider not in SUPPORTED_PROVIDERS:
        raise SSOError(f"Unsupported SSO provider: {provider}")
    if provider == 'saml':
        raise SSOError("SAML is handled by saml_service, not the OIDC endpoint resolver")

    client_id = config.get('client_id')
    client_secret = decrypt_secret(config.get('client_secret_encrypted', ''))
    if not client_id or not client_secret:
        raise SSOError("SSO provider is missing client credentials")

    if provider == 'github':
        return {
            'type': 'oauth2',
            'authorization_endpoint': 'https://github.com/login/oauth/authorize',
            'token_endpoint': 'https://github.com/login/oauth/access_token',
            'userinfo_endpoint': 'https://api.github.com/user',
            'scopes': config.get('scopes') or 'read:user user:email',
            'client_id': client_id,
            'client_secret': client_secret,
        }

    metadata_url = _discovery_url_for(config)
    if not metadata_url:
        raise SSOError("OIDC provider is missing a discovery/metadata URL")
    doc = _discover(metadata_url)
    return {
        'type': 'oidc',
        'authorization_endpoint': doc['authorization_endpoint'],
        'token_endpoint': doc['token_endpoint'],
        'userinfo_endpoint': doc.get('userinfo_endpoint'),
        'jwks_uri': doc['jwks_uri'],
        'issuer': doc['issuer'],
        'scopes': config.get('scopes') or 'openid email profile',
        'client_id': client_id,
        'client_secret': client_secret,
    }


# --------------------------------------------------------------------------- #
# Authorization request
# --------------------------------------------------------------------------- #

def new_state() -> str:
    return secrets.token_urlsafe(24)


def new_nonce() -> str:
    return secrets.token_urlsafe(24)


def build_authorization_url(config: Dict, redirect_uri: str, state: str, nonce: str) -> str:
    ep = get_provider_endpoints(config)
    params = {
        'response_type': 'code',
        'client_id': ep['client_id'],
        'redirect_uri': redirect_uri,
        'scope': ep['scopes'],
        'state': state,
    }
    if ep['type'] == 'oidc':
        params['nonce'] = nonce
    return ep['authorization_endpoint'] + '?' + urlencode(params)


# --------------------------------------------------------------------------- #
# Token exchange + identity extraction
# --------------------------------------------------------------------------- #

def _exchange_code(ep: Dict, code: str, redirect_uri: str) -> Dict:
    data = {
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': redirect_uri,
        'client_id': ep['client_id'],
        'client_secret': ep['client_secret'],
    }
    headers = {'Accept': 'application/json'}
    try:
        resp = safe_request('POST', ep['token_endpoint'], data=data, headers=headers, timeout=_HTTP_TIMEOUT)
    except UnsafeUrlError as e:
        raise SSOError(f"OIDC token endpoint is not allowed: {e}")
    if resp.status_code != 200:
        logger.error("SSO token exchange failed: %s %s", resp.status_code, resp.text[:300])
        raise SSOError("Token exchange with identity provider failed")
    token = resp.json()
    if token.get('error'):
        logger.error("SSO token endpoint returned error: %s", token.get('error'))
        raise SSOError("Identity provider rejected the authorization code")
    return token


def _validate_id_token(ep: Dict, id_token: str, nonce: str) -> Dict:
    """Verify the id_token signature against JWKS and validate core claims."""
    from joserfc import jwt
    from joserfc.jwk import KeySet

    try:
        jwks = safe_request('GET', ep['jwks_uri'], timeout=_HTTP_TIMEOUT).json()
    except UnsafeUrlError as e:
        raise SSOError(f"OIDC jwks_uri is not allowed: {e}")
    key_set = KeySet.import_key_set(jwks)
    try:
        token = jwt.decode(id_token, key_set)
    except Exception as e:
        logger.error("id_token signature validation failed: %s", e)
        raise SSOError("Invalid identity token signature")

    claims = token.claims
    registry = jwt.JWTClaimsRegistry(
        iss={'essential': True, 'value': ep['issuer']},
        aud={'essential': True, 'value': ep['client_id']},
        exp={'essential': True},
    )
    try:
        registry.validate(claims)
    except Exception as e:
        logger.error("id_token claim validation failed: %s", e)
        raise SSOError("Identity token claims are invalid")

    if claims.get('nonce') != nonce:
        raise SSOError("Identity token nonce mismatch (possible replay)")
    return claims


def _fetch_userinfo(ep: Dict, access_token: str) -> Dict:
    if not ep.get('userinfo_endpoint'):
        return {}
    try:
        resp = safe_request(
            'GET',
            ep['userinfo_endpoint'],
            headers={'Authorization': f"Bearer {access_token}", 'Accept': 'application/json'},
            timeout=_HTTP_TIMEOUT,
        )
    except UnsafeUrlError as e:
        raise SSOError(f"OIDC userinfo endpoint is not allowed: {e}")
    if resp.status_code != 200:
        return {}
    return resp.json()


def _github_identity(ep: Dict, access_token: str) -> Identity:
    info = _fetch_userinfo(ep, access_token)
    if not info or not info.get('id'):
        raise SSOError("Could not read GitHub profile")
    # Primary verified email comes from the dedicated emails endpoint.
    email, verified = info.get('email'), False
    try:
        # ssrf-safe: hardcoded api.github.com (GitHub OAuth email lookup) — distinct from the org-configurable OIDC endpoints, which already go through safe_request()
        er = requests.get(
            'https://api.github.com/user/emails',
            headers={'Authorization': f"Bearer {access_token}", 'Accept': 'application/json'},
            timeout=_HTTP_TIMEOUT,
        )
        if er.status_code == 200:
            for e in er.json():
                if e.get('primary') and e.get('verified'):
                    email, verified = e.get('email'), True
                    break
    except requests.RequestException:
        pass
    if not email:
        raise SSOError("No verified primary email on the GitHub account")
    return Identity(subject=str(info['id']), email=email.lower(), email_verified=verified,
                    name=info.get('name') or info.get('login'), provider='github')


def handle_callback(config: Dict, code: str, redirect_uri: str, nonce: str) -> Identity:
    """Complete the auth-code flow and return a normalized Identity."""
    ep = get_provider_endpoints(config)
    token = _exchange_code(ep, code, redirect_uri)

    if ep['type'] == 'oauth2':  # GitHub
        access_token = token.get('access_token')
        if not access_token:
            raise SSOError("Identity provider did not return an access token")
        return _github_identity(ep, access_token)

    # OIDC: prefer validated id_token claims, backfill from userinfo.
    id_token = token.get('id_token')
    if not id_token:
        raise SSOError("OIDC provider did not return an id_token")
    claims = _validate_id_token(ep, id_token, nonce)

    email = claims.get('email')
    verified = bool(claims.get('email_verified', False))
    name = claims.get('name')
    if (not email or not name) and token.get('access_token'):
        info = _fetch_userinfo(ep, token['access_token'])
        email = email or info.get('email')
        name = name or info.get('name')
        if 'email_verified' in info:
            verified = verified or bool(info['email_verified'])

    if not email:
        raise SSOError("Identity provider did not supply an email address")

    groups_claim = config.get('groups_claim') or 'groups'
    raw_groups = claims.get(groups_claim)
    if raw_groups is None and token.get('access_token'):
        raw_groups = _fetch_userinfo(ep, token['access_token']).get(groups_claim)
    groups = [raw_groups] if isinstance(raw_groups, str) else (list(raw_groups) if raw_groups else [])

    return Identity(subject=str(claims['sub']), email=email.lower(),
                    email_verified=verified, name=name, provider=config.get('provider'),
                    groups=[str(g) for g in groups])


# --------------------------------------------------------------------------- #
# Org resolution + JIT provisioning
# --------------------------------------------------------------------------- #

def resolve_org_for_email(email: str):
    """Find the organization whose IdP should handle this email, by domain."""
    from models import Organization, OrganizationDomain
    if not email or '@' not in email:
        return None
    domain = email.split('@', 1)[1].strip().lower()
    if not domain:
        return None
    # Only verified domains may route logins (prevents claiming a domain you
    # don't control, e.g. a public provider like gmail.com).
    od = OrganizationDomain.query.filter_by(domain=domain, verified=True).first()
    if not od:
        return None
    org = Organization.query.get(od.organization_id)
    if org and org.sso_enabled and org.is_active:
        return org
    return None


def sso_login_required(user) -> Optional[object]:
    """Return the org that mandates SSO for ``user`` (blocking password login), else None.

    Safety valves: only enforces when SSO is enabled AND the IdP is fully
    configured, and never for an org owner (so admins can't lock themselves out).
    """
    from models import Organization, OrganizationDomain, OrganizationMember
    from services.sso_onboarding import is_provider_configured

    if not user or not getattr(user, 'email', None) or '@' not in user.email:
        return None
    domain = user.email.split('@', 1)[1].strip().lower()
    od = OrganizationDomain.query.filter_by(domain=domain, verified=True).first()
    if not od:
        return None
    org = Organization.query.get(od.organization_id)
    if not org or not org.sso_enabled or not org.is_active:
        return None
    config = org.sso_config or {}
    if not config.get('enforce_sso') or not is_provider_configured(config):
        return None
    if org.owner_id == user.id:
        return None
    member = OrganizationMember.query.filter_by(organization_id=org.id, user_id=user.id).first()
    if member and member.role == 'owner':
        return None
    return org


def _unique_username(base: str) -> str:
    from models import User
    base = ''.join(c for c in (base or 'user') if c.isalnum() or c in ('-', '_', '.')) or 'user'
    base = base[:60]
    candidate = base
    i = 1
    while User.query.filter_by(username=candidate).first() is not None:
        candidate = f"{base}{i}"
        i += 1
    return candidate


def find_or_provision_user(org, identity: Identity):
    """JIT-create or link a user for an SSO identity and ensure org membership.

    Returns (user, created: bool). Raises SSOError if the email is unverified.
    """
    from models import db, User, OrganizationMember

    if not identity.email_verified:
        raise SSOError("Your identity provider has not verified this email address")

    config = org.sso_config or {}
    default_role = config.get('default_role', 'member')
    mapped_role = role_from_groups(config, identity.groups)

    user = User.query.filter_by(email=identity.email).first()
    created = False
    if user is None:
        user = User(
            email=identity.email,
            username=_unique_username(identity.email.split('@', 1)[0]),
            full_name=identity.name or identity.email.split('@', 1)[0],
            email_verified=True,
            role='user',
            sso_provider=identity.provider,
            sso_subject=identity.subject,
            sso_organization_id=org.id,
        )
        user.set_password(secrets.token_urlsafe(32))  # unusable; SSO-only login
        db.session.add(user)
        db.session.flush()  # assign id
        created = True
    else:
        # Link SSO identity on first federated login without clobbering existing data.
        if not user.sso_provider:
            user.sso_provider = identity.provider
            user.sso_subject = identity.subject
            user.sso_organization_id = org.id
        if not user.email_verified:
            user.email_verified = True

    membership = OrganizationMember.query.filter_by(
        organization_id=org.id, user_id=user.id).first()
    if membership is None:
        membership = OrganizationMember(
            organization_id=org.id, user_id=user.id, role=(mapped_role or default_role))
        db.session.add(membership)
    elif mapped_role and membership.role != 'owner':
        # Keep role in sync with IdP groups on each login (never demote an owner).
        membership.role = mapped_role

    db.session.commit()
    return user, created


# --------------------------------------------------------------------------- #
# Admin configuration (save / read)
# --------------------------------------------------------------------------- #

_DOMAIN_RE = re.compile(r'^(?=.{1,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$')


def add_domain(org_id: int, raw: str) -> Tuple[bool, Optional[str]]:
    """Claim an email domain for an org (unverified). Returns (ok, error)."""
    from models import db, OrganizationDomain

    domain = (raw or '').strip().lower().lstrip('@')
    if not domain or not _DOMAIN_RE.match(domain):
        return False, "Enter a valid domain, e.g. acme.com"

    existing = OrganizationDomain.query.filter_by(domain=domain).first()
    if existing:
        if existing.organization_id == org_id:
            return False, "That domain is already added."
        return False, "That domain is already claimed by another organization."

    from services.domain_verification import generate_token
    db.session.add(OrganizationDomain(organization_id=org_id, domain=domain,
                                      verified=False, verification_token=generate_token()))
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error("Failed to add domain %s for org %s: %s", domain, org_id, e)
        return False, "Failed to add domain."
    return True, None


def remove_domain(org_id: int, domain_id: int) -> bool:
    from models import db, OrganizationDomain
    row = OrganizationDomain.query.filter_by(id=domain_id, organization_id=org_id).first()
    if not row:
        return False
    db.session.delete(row)
    db.session.commit()
    return True


def save_config(org_id: int, form: Dict) -> Tuple[bool, Optional[str]]:
    """Persist SSO config from the admin form. Encrypts the secret, syncs domains.

    ``form`` keys: provider, client_id, client_secret, metadata_url, tenant_id,
    scopes, default_role, domains (comma/space separated), enabled.
    Returns (ok, error_message).
    """
    from models import db, Organization

    org = Organization.query.get(org_id)
    if not org:
        return False, "Organization not found"

    provider = (form.get('provider') or '').strip()
    if provider not in SUPPORTED_PROVIDERS:
        return False, f"Unsupported provider '{provider}'"

    config = dict(org.sso_config or {})
    config['provider'] = provider

    if provider == 'saml':
        config['idp_entity_id'] = (form.get('idp_entity_id') or '').strip()
        config['idp_sso_url'] = (form.get('idp_sso_url') or '').strip()
        # Keep the existing cert if the field is left blank on edit.
        new_cert = (form.get('idp_x509_cert') or '').strip()
        if new_cert:
            config['idp_x509_cert'] = new_cert
        from services import saml_service
        ok, err = saml_service.validate_saml_config(config)
        if not ok:
            return False, err
    else:
        client_id = (form.get('client_id') or '').strip()
        if not client_id:
            return False, "Client ID is required"
        config['client_id'] = client_id

        # Only replace the stored secret when a new one is submitted.
        new_secret = (form.get('client_secret') or '').strip()
        if new_secret:
            config['client_secret_encrypted'] = encrypt_secret(new_secret)
        if not config.get('client_secret_encrypted'):
            return False, "Client secret is required"

        config['metadata_url'] = (form.get('metadata_url') or '').strip()
        config['tenant_id'] = (form.get('tenant_id') or '').strip()
        config['scopes'] = (form.get('scopes') or '').strip()

    config['default_role'] = (form.get('default_role') or 'member').strip()

    # Group -> role mapping (optional). Claim/attribute name + "group=role" lines.
    config['groups_claim'] = (form.get('groups_claim') or '').strip()
    config['groups_attribute'] = (form.get('groups_attribute') or '').strip()
    mappings = {}
    for line in (form.get('role_mappings') or '').replace(',', '\n').splitlines():
        line = line.strip()
        sep = '=' if '=' in line else (':' if ':' in line else None)
        if not sep:
            continue
        group, role = (p.strip() for p in line.split(sep, 1))
        if group and role.lower() in ('admin', 'member', 'viewer'):
            mappings[group] = role.lower()
    config['role_mappings'] = mappings
    config['enforce_sso'] = str(form.get('enforce_sso', '')).lower() in ('on', 'true', '1', 'yes')

    enabled = str(form.get('enabled', '')).lower() in ('on', 'true', '1', 'yes')

    org.sso_provider = provider
    org.sso_enabled = enabled
    org.sso_config = config

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error("Failed to save SSO config for org %s: %s", org_id, e, exc_info=True)
        return False, "Failed to save configuration"
    return True, None


def get_admin_config(org) -> Dict:
    """Return the stored config for display, never exposing the secret."""
    config = dict(org.sso_config or {})
    config.pop('client_secret_encrypted', None)
    config['has_secret'] = bool((org.sso_config or {}).get('client_secret_encrypted'))
    config['enabled'] = bool(org.sso_enabled)
    config.setdefault('provider', org.sso_provider or '')
    config.setdefault('allowed_domains', [])
    return config
