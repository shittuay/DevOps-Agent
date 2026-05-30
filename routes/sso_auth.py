"""Organization SSO (OIDC) authentication routes.

Public, session-based login flow that sits alongside password login:

  GET/POST /auth/sso/start          -> email entry; resolves org by domain, redirects to IdP
  GET      /auth/sso/login/<slug>   -> org-initiated login (skips email entry)
  GET      /auth/sso/callback       -> IdP redirect target; completes login + JIT provisioning
"""

import logging
import os

from flask import (Blueprint, request, redirect, url_for, render_template,
                   session, flash, Response)
from flask_login import login_user
from urllib.parse import urlparse

from services import sso_service

logger = logging.getLogger(__name__)

sso_auth_bp = Blueprint('sso_auth', __name__, url_prefix='/auth/sso')


def _base_url() -> str:
    return (os.environ.get('BASE_URL') or request.host_url).rstrip('/')


def _callback_uri() -> str:
    """Build the OAuth redirect URI; must match the IdP registration exactly."""
    return _base_url() + url_for('sso_auth.callback')


def _acs_uri() -> str:
    """SAML Assertion Consumer Service URL (must match IdP registration)."""
    return _base_url() + url_for('sso_auth.saml_acs')


def _sp_entity_id() -> str:
    """SAML Service Provider entity ID (the audience IdPs assert to)."""
    return _base_url() + url_for('sso_auth.saml_metadata')


def _safe_next(target: str) -> bool:
    if not target:
        return False
    parsed = urlparse(target)
    return not parsed.netloc and not parsed.scheme and target.startswith('/')


def _begin_login(org, next_url: str = ''):
    """Dispatch to the OIDC or SAML login flow for this organization."""
    provider = org.sso_provider or (org.sso_config or {}).get('provider')
    if provider == 'saml':
        return _begin_saml_login(org, next_url)
    return _begin_oidc_login(org, next_url)


def _begin_oidc_login(org, next_url: str = ''):
    """Store flow state in the session and redirect to the OIDC provider."""
    config = org.sso_config or {}
    state = sso_service.new_state()
    nonce = sso_service.new_nonce()
    redirect_uri = _callback_uri()
    try:
        auth_url = sso_service.build_authorization_url(config, redirect_uri, state, nonce)
    except sso_service.SSOError as e:
        logger.error("SSO start failed for org %s: %s", org.id, e)
        flash("Single sign-on is not configured correctly for your organization.", "error")
        return redirect(url_for('auth.login'))

    session['sso_state'] = state
    session['sso_nonce'] = nonce
    session['sso_org_id'] = org.id
    session['sso_redirect_uri'] = redirect_uri
    session['sso_next'] = next_url if _safe_next(next_url) else ''
    return redirect(auth_url)


@sso_auth_bp.route('/start', methods=['GET', 'POST'])
def start():
    next_url = request.values.get('next', '')

    # Org-initiated shortcut: /auth/sso/start?org=<slug>
    slug = request.values.get('org')
    if slug:
        from models import Organization
        org = Organization.query.filter_by(slug=slug).first()
        if org and org.sso_enabled and org.is_active:
            return _begin_login(org, next_url)
        flash("That organization does not have single sign-on enabled.", "error")
        return render_template('sso_start.html', next=next_url)

    if request.method == 'POST':
        email = (request.form.get('email') or '').strip().lower()
        org = sso_service.resolve_org_for_email(email)
        if not org:
            # Don't disclose which domains are configured.
            flash("Single sign-on isn't set up for that email domain. "
                  "Use password login or contact your administrator.", "error")
            return render_template('sso_start.html', next=next_url, email=email)
        return _begin_login(org, next_url)

    return render_template('sso_start.html', next=next_url)


@sso_auth_bp.route('/login/<slug>')
def login_org(slug):
    from models import Organization
    org = Organization.query.filter_by(slug=slug).first()
    if not org or not org.sso_enabled or not org.is_active:
        flash("That organization does not have single sign-on enabled.", "error")
        return redirect(url_for('auth.login'))
    return _begin_login(org, request.args.get('next', ''))


@sso_auth_bp.route('/callback')
def callback():
    from models import Organization

    err = request.args.get('error')
    if err:
        logger.warning("SSO provider returned error: %s", err)
        flash("Sign-in was cancelled or denied by the identity provider.", "error")
        return redirect(url_for('auth.login'))

    code = request.args.get('code')
    state = request.args.get('state')
    if not code or not state or state != session.get('sso_state'):
        flash("Sign-in session expired or was invalid. Please try again.", "error")
        return redirect(url_for('sso_auth.start'))

    org_id = session.get('sso_org_id')
    nonce = session.get('sso_nonce')
    redirect_uri = session.get('sso_redirect_uri')
    org = Organization.query.get(org_id) if org_id else None
    if not org or not org.sso_enabled:
        flash("Single sign-on is no longer available for this organization.", "error")
        return redirect(url_for('auth.login'))

    try:
        identity = sso_service.handle_callback(org.sso_config or {}, code, redirect_uri, nonce)
        user, created = sso_service.find_or_provision_user(org, identity)
    except sso_service.SSOError as e:
        logger.warning("SSO callback failed for org %s: %s", org_id, e)
        flash(str(e), "error")
        return redirect(url_for('auth.login'))
    except Exception:
        logger.error("Unexpected SSO callback error", exc_info=True)
        flash("Single sign-on failed unexpectedly. Please try again.", "error")
        return redirect(url_for('auth.login'))

    next_url = session.get('sso_next', '')
    for key in ('sso_state', 'sso_nonce', 'sso_org_id', 'sso_redirect_uri', 'sso_next'):
        session.pop(key, None)

    login_user(user, remember=True)
    user.update_last_login(ip_address=request.remote_addr)
    session.permanent = True
    logger.info("SSO login: %s via %s (org=%s, new=%s)",
                user.email, identity.provider, org.id, created)

    if next_url and _safe_next(next_url):
        return redirect(next_url)
    return redirect(url_for('chat'))


# --------------------------------------------------------------------------- #
# SAML 2.0 flow
# --------------------------------------------------------------------------- #

def _begin_saml_login(org, next_url: str = ''):
    """Build a SAML AuthnRequest and redirect to the IdP."""
    from services import saml_service

    acs_url = _acs_uri()
    sp_entity = _sp_entity_id()
    safe_next = next_url if _safe_next(next_url) else ''
    # RelayState carries org id + next so the cross-site ACS POST works even when
    # the session cookie (SameSite=Lax) is not sent by the browser.
    relay_state = f"{org.id}|{safe_next}"

    try:
        redirect_url, request_id = saml_service.build_authn_request(
            org.sso_config or {}, acs_url, sp_entity, relay_state)
    except sso_service.SSOError as e:
        logger.error("SAML start failed for org %s: %s", org.id, e)
        flash("Single sign-on is not configured correctly for your organization.", "error")
        return redirect(url_for('auth.login'))

    # request_id is best-effort (used for InResponseTo when the session is present).
    session['saml_request_id'] = request_id
    return redirect(redirect_url)


@sso_auth_bp.route('/acs', methods=['POST'])
def saml_acs():
    """SAML Assertion Consumer Service — IdP POSTs the signed SAMLResponse here."""
    from models import Organization
    from services import saml_service

    saml_response = request.form.get('SAMLResponse')
    relay_state = request.form.get('RelayState', '') or ''
    org_id, _, next_url = relay_state.partition('|')

    try:
        org = Organization.query.get(int(org_id)) if org_id.strip() else None
    except ValueError:
        org = None
    if not org or not org.sso_enabled or not org.is_active:
        flash("Single sign-on is no longer available for this organization.", "error")
        return redirect(url_for('auth.login'))

    expected_request_id = session.get('saml_request_id')  # best-effort
    try:
        identity = saml_service.parse_and_validate_response(
            org.sso_config or {}, saml_response, _acs_uri(), _sp_entity_id(),
            expected_request_id)
        user, created = sso_service.find_or_provision_user(org, identity)
    except sso_service.SSOError as e:
        logger.warning("SAML ACS failed for org %s: %s", org.id, e)
        flash(str(e), "error")
        return redirect(url_for('auth.login'))
    except Exception:
        logger.error("Unexpected SAML ACS error", exc_info=True)
        flash("Single sign-on failed unexpectedly. Please try again.", "error")
        return redirect(url_for('auth.login'))

    session.pop('saml_request_id', None)
    login_user(user, remember=True)
    user.update_last_login(ip_address=request.remote_addr)
    session.permanent = True
    logger.info("SAML login: %s (org=%s, new=%s)", user.email, org.id, created)

    if next_url and _safe_next(next_url):
        return redirect(next_url)
    return redirect(url_for('chat'))


@sso_auth_bp.route('/saml/metadata')
def saml_metadata():
    """SP metadata document for administrators registering the service in their IdP."""
    from services import saml_service
    xml = saml_service.sp_metadata(_sp_entity_id(), _acs_uri())
    return Response(xml, mimetype='application/xml')
