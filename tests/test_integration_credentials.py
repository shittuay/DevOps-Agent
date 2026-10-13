"""Per-user credentials for CI/CD, alerting, monitoring and code-quality tools.

These tools used to fall back to the platform's own env vars (GITHUB_TOKEN, PAGERDUTY_API_KEY,
SONAR_TOKEN, ...), so any user's chat could act through the platform's accounts, and the
URL-taking ones (GitLab, Jenkins, SonarQube, Nexus) would send that platform secret to a URL the
chat chose. Pinned here: no env fallback anywhere, fail closed with a connect-your-account
message, users never see each other's credentials, and a saved secret only goes to the saved
server's origin.
"""
import ast
import pathlib
import secrets
from unittest.mock import MagicMock, patch

import pytest

from services import integration_credentials as ic
from src.tools import (alerting_tools, cicd_tools, github_tools, integration_auth, monitoring_tools,
                       nexus_tools, sonarqube_tools)

ROOT = pathlib.Path(__file__).resolve().parents[1]
# The platform's old env vars, set to sentinel values derived from their names (no literal secrets).
PLATFORM_ENV = {name: f'platform-sentinel-{name.lower()}' for name in (
    'GITHUB_TOKEN', 'GITLAB_TOKEN', 'GITLAB_URL', 'JENKINS_URL', 'JENKINS_USERNAME', 'JENKINS_TOKEN',
    'PAGERDUTY_API_KEY', 'PAGERDUTY_FROM_EMAIL', 'OPSGENIE_API_KEY', 'DATADOG_API_KEY', 'DATADOG_APP_KEY',
    'SONAR_TOKEN', 'NEXUS_USERNAME', 'NEXUS_PASSWORD')}


@pytest.fixture(autouse=True)
def platform_env(monkeypatch):
    for k, v in PLATFORM_ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv('CREDENTIAL_ENCRYPTION_KEY', 'x' * 32)
    integration_auth.clear_user_context()
    yield
    integration_auth.clear_user_context()


@pytest.fixture
def no_dns(monkeypatch):
    """URL safety checks resolve DNS; the hosts here are fictional."""
    monkeypatch.setattr('src.utils.network_safety.assert_safe_url', lambda url: None)
    for mod in (cicd_tools, sonarqube_tools, nexus_tools):
        monkeypatch.setattr(mod, 'assert_safe_url', lambda url: None)


@pytest.fixture
def other_user(app, db_session):
    from models import User, db
    for existing in User.query.filter_by(email='other@example.com').all():
        db.session.delete(existing)
    db.session.commit()
    user = User(email='other@example.com', username='otheruser')
    user.set_password(secrets.token_urlsafe(16))
    db.session.add(user)
    db.session.commit()
    yield user
    db.session.delete(user)
    db.session.commit()


def _ok_response(payload=None):
    resp = MagicMock(status_code=200)
    resp.json.return_value = payload or {}
    resp.raise_for_status.return_value = None
    return resp


# --------------------------------------------------------------- no platform fallback

def test_no_user_context_never_uses_platform_env():
    with patch.object(github_tools, 'Github', create=True) as gh, patch('github.Github') as gh2:
        result = github_tools.github_list_repos()
    assert result['success'] is False
    assert 'Settings > Integrations' in result['error']
    for mock in (gh, gh2):
        for call in mock.call_args_list:
            assert PLATFORM_ENV['GITHUB_TOKEN'] not in str(call)


@pytest.mark.parametrize('call', [
    lambda: cicd_tools.list_github_workflows('o', 'r'),
    lambda: cicd_tools.trigger_github_workflow('o', 'r', 'ci.yml'),
    lambda: cicd_tools.list_gitlab_pipelines('g/p'),
    lambda: cicd_tools.list_jenkins_jobs(),
    lambda: cicd_tools.trigger_jenkins_job('build'),
    lambda: alerting_tools.pagerduty_list_incidents(),
    lambda: alerting_tools.opsgenie_list_alerts(),
    lambda: monitoring_tools.query_datadog_metrics('avg:cpu', 0, 1),
    lambda: sonarqube_tools.get_sonar_projects('https://sonar.acme.io'),
    lambda: nexus_tools.nexus_list_repositories('https://nexus.acme.io'),
], ids=['gh-actions', 'gh-trigger', 'gitlab', 'jenkins', 'jenkins-trigger', 'pagerduty', 'opsgenie',
        'datadog', 'sonarqube', 'nexus'])
def test_every_integration_fails_closed_for_a_user_with_nothing_saved(app, test_user, call):
    integration_auth.set_user_context(test_user.id)
    with patch('src.utils.network_safety.safe_request') as net, \
         patch.object(cicd_tools, 'safe_request') as cicd_net, \
         patch.object(alerting_tools.requests, 'get') as pd_get, \
         patch.object(monitoring_tools.requests, 'get', create=True) as dd_get:
        result = call()
    assert result['success'] is False
    assert 'not connected' in result['error'] and 'Settings > Integrations' in result['error']
    for mock in (net, cicd_net, pd_get, dd_get):
        assert not mock.called


def test_tool_modules_read_no_credential_env_vars():
    names = set(PLATFORM_ENV)
    for mod in ('cicd_tools', 'github_tools', 'git_tools', 'alerting_tools', 'monitoring_tools',
                'sonarqube_tools', 'nexus_tools'):
        tree = ast.parse((ROOT / 'src' / 'tools' / f'{mod}.py').read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and node.value in names:
                parent_src = ast.get_source_segment((ROOT / 'src' / 'tools' / f'{mod}.py').read_text(), node)
                pytest.fail(f'{mod} still references {parent_src}')


# ------------------------------------------------------------ the user's own credentials

def test_saved_credentials_are_used_and_scoped_to_their_owner(app, test_user, other_user):
    assert ic.save(test_user.id, 'github', {'token': 'user-a-token'}) == {}

    integration_auth.set_user_context(test_user.id)
    with patch.object(cicd_tools, 'Github') as gh:
        gh.return_value.get_repo.return_value.get_workflows.return_value = []
        assert cicd_tools.list_github_workflows('o', 'r')['success'] is True
    gh.assert_called_once_with('user-a-token')

    integration_auth.set_user_context(other_user.id)
    with patch.object(cicd_tools, 'Github') as gh:
        result = cicd_tools.list_github_workflows('o', 'r')
    assert result['success'] is False and not gh.called


def test_explicit_token_wins_and_needs_no_saved_row(app, test_user):
    integration_auth.set_user_context(test_user.id)
    with patch.object(cicd_tools, 'Github') as gh:
        gh.return_value.get_repo.return_value.get_workflows.return_value = []
        cicd_tools.list_github_workflows('o', 'r', github_token='pasted-token')
    gh.assert_called_once_with('pasted-token')


def test_saved_secret_is_never_sent_to_another_host(app, test_user, no_dns):
    assert ic.save(test_user.id, 'sonarqube', {'url': 'https://sonar.acme.io', 'token': 'sq-user'}) == {}
    integration_auth.set_user_context(test_user.id)

    with patch.object(sonarqube_tools, 'safe_request') as net:
        result = sonarqube_tools.get_sonar_projects('https://attacker.example.net')
    assert result['success'] is False and 'will not be sent' in result['error']
    assert not net.called

    with patch.object(sonarqube_tools, 'safe_request', return_value=_ok_response({'components': []})) as net:
        assert sonarqube_tools.get_sonar_projects('https://sonar.acme.io/')['success'] is True
    assert net.call_args.args[1].startswith('https://sonar.acme.io/')
    assert net.call_args.kwargs['headers']['Authorization'] == 'Bearer sq-user'


def test_url_tools_default_to_the_saved_server(app, test_user, no_dns):
    assert ic.save(test_user.id, 'gitlab', {'url': 'https://git.acme.io', 'token': 'gl-user'}) == {}
    integration_auth.set_user_context(test_user.id)
    with patch.object(cicd_tools, 'safe_request', return_value=_ok_response([])) as net:
        assert cicd_tools.list_gitlab_pipelines('g/p')['success'] is True
    assert net.call_args.args[1].startswith('https://git.acme.io/api/v4/')
    assert net.call_args.kwargs['headers']['PRIVATE-TOKEN'] == 'gl-user'


def test_pagerduty_write_needs_a_from_email_and_never_invents_one(app, test_user):
    assert ic.save(test_user.id, 'pagerduty', {'api_key': 'pd-user'}) == {}
    integration_auth.set_user_context(test_user.id)
    with patch.object(alerting_tools.requests, 'post') as post:
        result = alerting_tools.pagerduty_create_incident('db down', 'PSVC1')
    assert result['success'] is False and 'from' in result['error']
    assert not post.called


def test_opsgenie_region_comes_from_the_saved_connection(app, test_user):
    assert ic.save(test_user.id, 'opsgenie', {'api_key': 'og-user', 'region': 'EU'}) == {}
    integration_auth.set_user_context(test_user.id)
    headers, base = alerting_tools._opsgenie_auth()
    assert base == 'https://api.eu.opsgenie.com/v2'
    assert headers['Authorization'] == 'GenieKey og-user'


# ------------------------------------------------------------------- storage + API

def test_validation_and_blank_secret_keeps_saved_value(app, test_user, no_dns):
    errors = ic.save(test_user.id, 'jenkins', {'url': 'ftp://x', 'token': 't'})
    assert set(errors) == {'url', 'username'}
    assert ic.save(test_user.id, 'jenkins', {'url': 'https://ci.acme.io/', 'username': 'me', 'token': 'jk1'}) == {}
    assert ic.save(test_user.id, 'jenkins', {'url': 'https://ci.acme.io', 'username': 'me2', 'token': ''}) == {}
    saved = ic.load(test_user.id, 'jenkins')
    assert saved == {'url': 'https://ci.acme.io', 'username': 'me2', 'token': 'jk1'}


def test_credentials_are_encrypted_at_rest(app, test_user):
    from models import UserIntegrationCredential
    ic.save(test_user.id, 'datadog', {'api_key': 'dd-secret-1', 'app_key': 'dd-secret-2'})
    row = UserIntegrationCredential.query.filter_by(user_id=test_user.id, provider='datadog').one()
    assert 'dd-secret' not in row.credentials_encrypted


def test_integrations_are_not_cloud_accounts(app, test_user):
    from services.credential_service import get_user_configured_providers
    ic.save(test_user.id, 'github', {'token': 'x'})
    assert get_user_configured_providers(test_user.id) == {'aws': False, 'azure': False, 'gcp': False}


def test_api_round_trip_never_returns_secrets(authenticated_client, test_user, no_dns):
    resp = authenticated_client.put('/api/integrations/gitlab', json={'url': 'https://git.acme.io', 'token': 'gl-SECRET'})
    assert resp.status_code == 200, resp.get_json()
    listing = authenticated_client.get('/api/integrations')
    assert 'gl-SECRET' not in listing.get_data(as_text=True)
    gitlab = next(i for i in listing.get_json()['integrations'] if i['provider'] == 'gitlab')
    assert gitlab['connected'] is True and gitlab['values'] == {'url': 'https://git.acme.io'}

    bad = authenticated_client.put('/api/integrations/gitlab', json={'url': 'nope'})
    assert bad.status_code == 400 and 'url' in bad.get_json()['fields']
    assert authenticated_client.put('/api/integrations/unknown', json={}).status_code == 404

    assert authenticated_client.delete('/api/integrations/gitlab').status_code == 200
    assert authenticated_client.delete('/api/integrations/gitlab').status_code == 404


def test_api_requires_login(client):
    assert client.get('/api/integrations').status_code in (302, 401)
    assert client.put('/api/integrations/github', json={'token': 'x'}).status_code in (302, 401)


def test_agent_sets_and_clears_the_integration_context():
    from src.agent.core import DevOpsAgent
    fake_agent = MagicMock()
    DevOpsAgent._set_cloud_user_context(fake_agent, 4242)
    assert integration_auth.get_user_id() == 4242
    DevOpsAgent._clear_cloud_user_context(fake_agent)
    assert integration_auth.get_user_id() is None


def test_internal_addresses_are_refused_at_save(app, test_user):
    errors = ic.save(test_user.id, 'sonarqube', {'url': 'http://169.254.169.254', 'token': 't'})
    assert 'url' in errors
