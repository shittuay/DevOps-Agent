"""2026-11-21 scheduled review: generic read escape hatches can't read secrets unconfirmed,
and a wrong password doesn't reveal that the account exists."""
import pytest

from src.agent.safety import SafetyValidator, generic_read_secret_operation


@pytest.fixture
def sv():
    return SafetyValidator()


@pytest.mark.parametrize('tool,args', [
    ('aws_api_read', {'service': 'secretsmanager', 'operation': 'get_secret_value',
                      'params': {'SecretId': 'db'}}),
    ('aws_api_read', {'service': 'SecretsManager', 'operation': 'batch_get_secret_value'}),
    ('aws_api_read', {'service': 'ecr', 'operation': 'get_authorization_token'}),
    ('aws_api_read', {'service': 'sts', 'operation': 'get_session_token'}),
    ('aws_api_read', {'service': 'lambda', 'operation': 'get_function',
                      'params': {'FunctionName': 'f'}}),
    ('aws_api_read', {'service': 'ssm', 'operation': 'get_parameter',
                      'params': {'Name': '/db/pw', 'WithDecryption': True}}),
    ('aws_api_read', {'service': 'apigateway', 'operation': 'get_api_keys',
                      'params': {'includeValues': True}}),
    ('azure_api_read', {'client_type': 'storage', 'operation_path': 'storage_accounts.list_keys',
                        'params': {}}),
    ('azure_api_read', {'client_type': 'container', 'operation_path': 'registries.list_credentials'}),
    ('azure_api_read', {'client_type': 'web', 'operation_path': 'web_apps.list_application_settings'}),
    ('azure_api_read', {'client_type': 'web', 'operation_path': 'web_apps.list_connection_strings'}),
    ('k8s_api_read', {'api_group': 'core', 'method': 'read_namespaced_secret',
                      'params': {'name': 'x', 'namespace': 'default'}}),
    ('k8s_api_read', {'api_group': 'core', 'method': 'list_secret_for_all_namespaces'}),
])
def test_secret_reads_need_confirmation(sv, tool, args):
    assert generic_read_secret_operation(tool, args)
    result = sv.validate_tool_call(tool, args)
    assert result.requires_confirmation
    assert result.risk_level in ('high', 'critical')


@pytest.mark.parametrize('tool,args', [
    ('aws_api_read', {'service': 'ec2', 'operation': 'describe_instances'}),
    ('aws_api_read', {'service': 'secretsmanager', 'operation': 'list_secrets'}),
    ('aws_api_read', {'service': 'ssm', 'operation': 'get_parameter', 'params': {'Name': '/cfg'}}),
    ('aws_api_read', {'service': 'apigateway', 'operation': 'get_api_keys'}),
    ('aws_api_read', {'service': 'lambda', 'operation': 'list_functions'}),
    ('azure_api_read', {'client_type': 'compute', 'operation_path': 'virtual_machines.list_all'}),
    ('azure_api_read', {'client_type': 'network',
                        'operation_path': 'private_endpoint_connections.list'}),
    ('k8s_api_read', {'api_group': 'apps', 'method': 'list_namespaced_deployment'}),
    ('gcp_api_read', {'api_name': 'compute', 'method': 'list'}),
])
def test_ordinary_reads_stay_low_risk(sv, tool, args):
    assert generic_read_secret_operation(tool, args) is None
    result = sv.validate_tool_call(tool, args)
    assert not result.requires_confirmation
    assert result.risk_level == 'low'


def test_malformed_params_do_not_crash(sv):
    assert generic_read_secret_operation('aws_api_read', {'service': None, 'params': 'x'}) is None
    assert generic_read_secret_operation('aws_api_read', None) is None


def _login(client, ident, password):
    return client.post('/login', data={'email': ident, 'password': password})


def test_wrong_password_message_matches_unknown_account(client, db_session):
    from models import User
    user = User(email='known@example.com', username='knownuser', email_verified=True)
    user.set_password('Correct-horse-9!')
    db_session.add(user)
    db_session.commit()

    unknown = _login(client, 'nobody@example.com', 'whatever').get_data(as_text=True)
    wrong = _login(client, 'known@example.com', 'wrong-password').get_data(as_text=True)
    assert 'Invalid email/username or password' in wrong
    assert 'attempts remaining' not in wrong
    assert 'attempts remaining' not in unknown


def test_sso_hint_only_after_correct_password(client, db_session, monkeypatch):
    from models import User
    from services import sso_service
    user = User(email='sso@example.com', username='ssouser', email_verified=True)
    user.set_password('Correct-horse-9!')
    db_session.add(user)
    db_session.commit()
    monkeypatch.setattr(sso_service, 'sso_login_required', lambda u: True)

    wrong = _login(client, 'sso@example.com', 'wrong-password').get_data(as_text=True)
    assert 'single sign-on' not in wrong
    right = _login(client, 'sso@example.com', 'Correct-horse-9!').get_data(as_text=True)
    assert 'single sign-on' in right
