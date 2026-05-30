"""Computes an organization's SSO onboarding progress.

Drives the setup wizard's stepper on the SSO settings page and the compact
checklist on the organization page. Pure read logic over existing models.
"""

from __future__ import annotations

from typing import Dict, Optional

OIDC_PROVIDERS = ('generic_oidc', 'google', 'azure', 'github')


def is_provider_configured(config: Dict) -> bool:
    """True when the stored config has enough to attempt a login."""
    if not config:
        return False
    provider = config.get('provider')
    if provider == 'saml':
        return all(config.get(k) for k in ('idp_entity_id', 'idp_sso_url', 'idp_x509_cert'))
    if provider in OIDC_PROVIDERS:
        if not (config.get('client_id') and config.get('client_secret_encrypted')):
            return False
        if provider == 'generic_oidc' and not config.get('metadata_url'):
            return False
        if provider == 'azure' and not config.get('tenant_id'):
            return False
        return True
    return False


_ACTIONS = {
    'provider': ('Configure your identity provider', '#sso-config'),
    'domain': ('Add your email domain', '#sso-domains'),
    'verify': ('Verify your domain ownership', '#sso-domains'),
    'enable': ('Enable single sign-on', '#sso-config'),
    'login': ('Share the SSO sign-in link with your team', None),
}


def get_onboarding_status(org) -> Dict:
    """Return the org's SSO onboarding state: steps, progress, and next action."""
    from models import OrganizationDomain, User

    config = org.sso_config or {}
    provider_done = is_provider_configured(config)
    domains = OrganizationDomain.query.filter_by(organization_id=org.id).all()
    domain_added = len(domains) > 0
    domain_verified = any(d.verified for d in domains)
    enabled = bool(org.sso_enabled)
    first_login = User.query.filter_by(sso_organization_id=org.id).first() is not None

    steps = [
        {'key': 'provider', 'title': 'Configure identity provider', 'done': provider_done,
         'description': 'Choose your IdP and enter its credentials.', 'anchor': 'sso-config'},
        {'key': 'domain', 'title': 'Add an email domain', 'done': domain_added,
         'description': "Add the email domain your team signs in with.", 'anchor': 'sso-domains'},
        {'key': 'verify', 'title': 'Verify domain ownership', 'done': domain_verified,
         'description': 'Publish the DNS TXT record, then verify.', 'anchor': 'sso-domains'},
        {'key': 'enable', 'title': 'Enable single sign-on', 'done': enabled,
         'description': 'Turn SSO on for your organization.', 'anchor': 'sso-config'},
        {'key': 'login', 'title': 'First member signs in', 'done': first_login,
         'description': 'A teammate completes an SSO sign-in.', 'anchor': None},
    ]

    completed = sum(1 for s in steps if s['done'])
    total = len(steps)
    current = next((s['key'] for s in steps if not s['done']), None)
    for s in steps:
        s['current'] = (s['key'] == current)

    return {
        'steps': steps,
        'completed': completed,
        'total': total,
        'percent': int(round(completed * 100 / total)) if total else 0,
        'all_done': completed == total,
        'current': current,
        'next_action': _next_action(current),
        'configured': provider_done,
    }


def _next_action(current: Optional[str]) -> Optional[Dict]:
    if current is None:
        return None
    label, anchor = _ACTIONS.get(current, (None, None))
    return {'label': label, 'anchor': anchor}
