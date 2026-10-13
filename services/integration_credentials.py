"""Per-user credentials for non-cloud integrations (CI/CD, alerting, monitoring, code quality).

Tools in this family used to fall back to the platform's own environment variables
(GITHUB_TOKEN, PAGERDUTY_API_KEY, SONAR_TOKEN, ...) whenever a chat didn't pass a token,
so any user's chat could act through the platform's accounts. Credentials now come only
from the requesting user's own saved row (or a value they pass explicitly); with neither,
the tool fails closed. See CLAUDE.md "Integration credentials".
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse


@dataclass(frozen=True)
class IntegrationSpec:
    label: str
    secret_fields: Tuple[str, ...]
    plain_fields: Tuple[str, ...] = ()
    required: Tuple[str, ...] = ()
    url_field: Optional[str] = None
    defaults: Dict[str, str] = field(default_factory=dict)
    choices: Dict[str, Tuple[str, ...]] = field(default_factory=dict)
    help: str = ''


INTEGRATIONS: Dict[str, IntegrationSpec] = {
    'github': IntegrationSpec(
        'GitHub', ('token',), required=('token',),
        help='Fine-grained personal access token scoped to the repos you want managed.'),
    'gitlab': IntegrationSpec(
        'GitLab', ('token',), ('url',), required=('token', 'url'), url_field='url',
        defaults={'url': 'https://gitlab.com'},
        help='Personal or project access token with the api scope.'),
    'jenkins': IntegrationSpec(
        'Jenkins', ('token',), ('url', 'username'), required=('token', 'url', 'username'),
        url_field='url', help='Jenkins user API token (People > you > Configure > API Token).'),
    'pagerduty': IntegrationSpec(
        'PagerDuty', ('api_key',), ('from_email',), required=('api_key',),
        help='REST API key. Creating or updating incidents also needs the email of a PagerDuty user.'),
    'opsgenie': IntegrationSpec(
        'OpsGenie', ('api_key',), ('region',), required=('api_key',),
        defaults={'region': 'us'}, choices={'region': ('us', 'eu')},
        help='API integration key.'),
    'datadog': IntegrationSpec(
        'Datadog', ('api_key', 'app_key'), required=('api_key', 'app_key'),
        help='API key plus an application key.'),
    'sonarqube': IntegrationSpec(
        'SonarQube', ('token',), ('url',), required=('token', 'url'), url_field='url',
        help='User token from My Account > Security.'),
    'nexus': IntegrationSpec(
        'Nexus', ('password',), ('url', 'username'), required=('password', 'url', 'username'),
        url_field='url', help='A Nexus user with only the privileges you want the agent to have.'),
}

MAX_FIELD_LENGTH = 4096


class IntegrationNotConnected(Exception):
    """The requesting user has no usable credentials for this integration."""


def _spec(provider: str) -> IntegrationSpec:
    spec = INTEGRATIONS.get(provider)
    if spec is None:
        raise ValueError(f'Unknown integration: {provider}')
    return spec


def _origin(url: str) -> Tuple[str, str, int]:
    parsed = urlparse(url.strip())
    port = parsed.port or (443 if parsed.scheme == 'https' else 80)
    return parsed.scheme.lower(), (parsed.hostname or '').lower(), port


def same_origin(a: str, b: str) -> bool:
    return _origin(a) == _origin(b)


def validate_fields(provider: str, values: Dict[str, str]) -> Tuple[Dict[str, str], Dict[str, str]]:
    """Return (clean values, per-field errors). Unknown keys are dropped."""
    spec = _spec(provider)
    clean: Dict[str, str] = dict(spec.defaults)
    errors: Dict[str, str] = {}
    for name in spec.secret_fields + spec.plain_fields:
        raw = values.get(name)
        if raw is None or str(raw).strip() == '':
            continue
        value = str(raw).strip()
        if len(value) > MAX_FIELD_LENGTH or any(c in value for c in '\r\n'):
            errors[name] = 'Invalid value.'
            continue
        clean[name] = value
    for name in spec.required:
        if not clean.get(name):
            errors.setdefault(name, 'Required.')
    for name, allowed in spec.choices.items():
        if clean.get(name) and clean[name].lower() not in allowed:
            errors[name] = f"Must be one of: {', '.join(allowed)}."
        elif clean.get(name):
            clean[name] = clean[name].lower()
    if spec.url_field and clean.get(spec.url_field):
        url = clean[spec.url_field].rstrip('/')
        parsed = urlparse(url)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname:
            errors[spec.url_field] = 'Must be a full http(s) URL.'
        else:
            from src.utils.network_safety import UnsafeUrlError, assert_safe_url
            try:
                assert_safe_url(url)
            except UnsafeUrlError as exc:
                errors[spec.url_field] = str(exc)
        clean[spec.url_field] = url
    return clean, errors


def _row(user_id: int, provider: str):
    from models import UserIntegrationCredential
    return UserIntegrationCredential.query.filter_by(user_id=user_id, provider=provider).first()


def save(user_id: int, provider: str, values: Dict[str, str]) -> Dict[str, str]:
    """Validate and store. A blank secret on update keeps the saved one. Returns field errors."""
    from models import UserIntegrationCredential, db
    spec = _spec(provider)
    row = _row(user_id, provider)
    merged = dict(values)
    if row is not None:
        existing = row.get_credentials()
        for name in spec.secret_fields:
            if not str(merged.get(name) or '').strip() and existing.get(name):
                merged[name] = existing[name]
    clean, errors = validate_fields(provider, merged)
    if errors:
        return errors
    if row is None:
        row = UserIntegrationCredential(user_id=user_id, provider=provider)
        db.session.add(row)
    row.set_credentials(clean)
    db.session.commit()
    return {}


def delete(user_id: int, provider: str) -> bool:
    from models import db
    _spec(provider)
    row = _row(user_id, provider)
    if row is None:
        return False
    db.session.delete(row)
    db.session.commit()
    return True


def load(user_id: int, provider: str) -> Optional[Dict[str, str]]:
    _spec(provider)
    row = _row(user_id, provider)
    return row.get_credentials() if row is not None else None


def status(user_id: int) -> List[Dict[str, object]]:
    """Connection state per integration; never includes secret values."""
    from models import UserIntegrationCredential
    rows = {r.provider: r for r in UserIntegrationCredential.query.filter_by(user_id=user_id).all()}
    out = []
    for provider, spec in INTEGRATIONS.items():
        row = rows.get(provider)
        saved: Dict[str, str] = {}
        broken = False
        if row is not None:
            try:
                saved = row.get_credentials()
            except Exception:
                broken = True
        out.append({
            'provider': provider,
            'label': spec.label,
            'help': spec.help,
            'connected': row is not None and not broken,
            'needs_reconnect': broken,
            'secret_fields': list(spec.secret_fields),
            'plain_fields': list(spec.plain_fields),
            'required': list(spec.required),
            'choices': {k: list(v) for k, v in spec.choices.items()},
            'values': {k: saved.get(k, spec.defaults.get(k, '')) for k in spec.plain_fields},
            'updated_at': row.updated_at.isoformat() if row is not None and row.updated_at else None,
        })
    return out


def resolve(provider: str, user_id: Optional[int], explicit: Optional[Dict[str, Optional[str]]] = None,
            caller_url: Optional[str] = None) -> Dict[str, str]:
    """Credentials a tool call may use, or raise IntegrationNotConnected.

    - Every secret passed explicitly by the caller: use the caller's values only.
    - Otherwise the requesting user's saved credentials, and nothing else. Never env vars.
    - A saved secret is only ever sent to the saved URL's origin: a caller-supplied URL on
      another host is refused, so a chat cannot redirect the user's token elsewhere.
    """
    spec = _spec(provider)
    explicit = {k: v for k, v in (explicit or {}).items() if v not in (None, '')}
    if caller_url and spec.url_field:
        explicit.setdefault(spec.url_field, caller_url)

    if all(explicit.get(name) for name in spec.secret_fields):
        values = {**spec.defaults, **explicit}
        missing = [n for n in spec.required if not values.get(n)]
        if missing:
            raise IntegrationNotConnected(f"{spec.label}: missing {', '.join(missing)}.")
        return values

    connect_hint = (f"Connect {spec.label} in Settings > Integrations "
                    f"(the platform does not lend its own {spec.label} credentials).")
    if user_id is None:
        raise IntegrationNotConnected(f"No signed-in user for this {spec.label} call. {connect_hint}")
    saved = load(user_id, provider)
    if not saved:
        raise IntegrationNotConnected(f"{spec.label} is not connected for your account. {connect_hint}")

    values = {**spec.defaults, **saved}
    if spec.url_field:
        requested = explicit.get(spec.url_field)
        stored = saved.get(spec.url_field, '')
        if requested and stored and not same_origin(requested, stored):
            raise IntegrationNotConnected(
                f"Your saved {spec.label} credentials are for {stored}; they will not be sent to "
                f"{requested}. Update the URL in Settings > Integrations if it changed.")
        if requested:
            values[spec.url_field] = requested.rstrip('/')
    for name in spec.plain_fields:
        if name != spec.url_field and explicit.get(name) and not saved.get(name):
            values[name] = explicit[name]
    return values
