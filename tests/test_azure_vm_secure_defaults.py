"""Regression tests: `create_virtual_machine` (Azure) must not build an
internet-exposed VM.

Before 2026-10-13 it created a Basic, dynamic public IP and a NIC with no network
security group and password-only login. Basic public IPs are open by default, so
every port on the VM was reachable from the whole internet, guarded only by a
password. It is classified low risk (a `create_` tool), so this ran with no
confirmation prompt. Now: the NIC always gets an NSG, the public IP is Standard
(closed by default), inbound rules are scoped to one caller-supplied CIDR, world-open
sources are refused, and an SSH key disables password authentication.
"""
import secrets
from unittest.mock import MagicMock, patch

import pytest

from src.tools import azure_tools

# Generated per run: a literal here trips secret scanners even though it is fake.
TEST_PASSWORD = secrets.token_urlsafe(16)

BASE = dict(resource_group='rg', vm_name='vm1', location='eastus',
            vm_size='Standard_B1s', admin_username='azureuser')


def _clients():
    network, compute = MagicMock(), MagicMock()
    for op in ('virtual_networks', 'subnets', 'network_security_groups',
               'public_ip_addresses', 'network_interfaces'):
        getattr(network, op).begin_create_or_update.return_value.result.return_value = \
            MagicMock(id=f'/id/{op}', ip_address='20.0.0.1')
    vm = MagicMock()
    vm.name = 'vm1'
    vm.location = 'eastus'
    vm.hardware_profile.vm_size = 'Standard_B1s'
    vm.provisioning_state = 'Succeeded'
    compute.virtual_machines.begin_create_or_update.return_value.result.return_value = vm
    return network, compute


def _run(**kwargs):
    network, compute = _clients()
    lookup = {'network': network, 'compute': compute}
    with patch.object(azure_tools, '_get_azure_client', side_effect=lambda kind, *a, **k: lookup[kind]):
        result = azure_tools.create_virtual_machine(**{**BASE, **kwargs})
    return result, network, compute


def _call_body(mock_op):
    return mock_op.begin_create_or_update.call_args.args[-1]


def test_nic_always_gets_an_nsg_and_no_ports_open_by_default():
    result, network, _ = _run(ssh_public_key='ssh-ed25519 AAAA test')
    assert result['success'] is True
    assert _call_body(network.network_security_groups)['security_rules'] == []
    nic = _call_body(network.network_interfaces)
    assert nic['network_security_group'] == {'id': '/id/network_security_groups'}
    assert 'No inbound ports are open' in result['message']


def test_public_ip_is_standard_and_static():
    _, network, _ = _run(ssh_public_key='ssh-ed25519 AAAA test')
    ip = _call_body(network.public_ip_addresses)
    assert ip['sku'] == {'name': 'Standard'}
    assert ip['public_ip_allocation_method'] == 'Static'


def test_rules_are_scoped_to_the_given_cidr():
    result, network, _ = _run(ssh_public_key='ssh-ed25519 AAAA test',
                              allowed_source_cidr='203.0.113.10/32', open_ports=[22, 8000])
    rules = _call_body(network.network_security_groups)['security_rules']
    assert [r['destination_port_range'] for r in rules] == ['22', '8000']
    assert {r['source_address_prefix'] for r in rules} == {'203.0.113.10/32'}
    assert len({r['priority'] for r in rules}) == 2
    assert result['success'] is True


def test_default_port_is_ssh_when_only_a_cidr_is_given():
    _, network, _ = _run(ssh_public_key='ssh-ed25519 AAAA test', allowed_source_cidr='198.51.100.7')
    rules = _call_body(network.network_security_groups)['security_rules']
    assert [r['destination_port_range'] for r in rules] == ['22']


@pytest.mark.parametrize('source', ['0.0.0.0/0', '*', 'Internet', 'any', '::/0', '0.0.0.0/0 '])
def test_world_open_sources_are_refused_before_anything_is_created(source):
    result, network, compute = _run(ssh_public_key='k', allowed_source_cidr=source)
    assert result['success'] is False
    assert 'whole internet' in result['error']
    network.virtual_networks.begin_create_or_update.assert_not_called()
    compute.virtual_machines.begin_create_or_update.assert_not_called()


def test_ports_without_a_cidr_are_refused():
    result, network, _ = _run(ssh_public_key='k', open_ports=[80])
    assert result['success'] is False
    network.virtual_networks.begin_create_or_update.assert_not_called()


def test_invalid_cidr_and_port_are_refused():
    assert _run(ssh_public_key='k', allowed_source_cidr='not-an-ip')[0]['success'] is False
    assert _run(ssh_public_key='k', allowed_source_cidr='1.2.3.4/32', open_ports=[70000])[0]['success'] is False


def test_ssh_key_disables_password_login():
    _, _, compute = _run(ssh_public_key='ssh-ed25519 AAAA test', admin_password=TEST_PASSWORD)
    os_profile = _call_body(compute.virtual_machines)['os_profile']
    assert 'admin_password' not in os_profile
    linux = os_profile['linux_configuration']
    assert linux['disable_password_authentication'] is True
    assert linux['ssh']['public_keys'][0]['path'] == '/home/azureuser/.ssh/authorized_keys'


def test_password_only_still_works_but_behind_the_nsg():
    result, network, compute = _run(admin_password=TEST_PASSWORD)
    assert result['success'] is True
    assert result['authentication'] == 'password'
    assert _call_body(compute.virtual_machines)['os_profile']['admin_password'] == TEST_PASSWORD
    assert _call_body(network.network_security_groups)['security_rules'] == []


def test_requires_a_credential():
    result, network, _ = _run()
    assert result['success'] is False
    network.virtual_networks.begin_create_or_update.assert_not_called()


def test_public_ip_can_be_omitted():
    result, network, _ = _run(ssh_public_key='k', public_ip=False)
    network.public_ip_addresses.begin_create_or_update.assert_not_called()
    assert 'public_ip_address' not in _call_body(network.network_interfaces)['ip_configurations'][0]
    assert result['public_ip_address'] is None


def test_schema_no_longer_requires_a_password_and_documents_the_cidr():
    tool = next(t for t in azure_tools.get_tools() if t['name'] == 'create_virtual_machine')
    schema = tool['input_schema']
    assert 'admin_password' not in schema['required']
    for prop in ('ssh_public_key', 'allowed_source_cidr', 'open_ports', 'public_ip'):
        assert prop in schema['properties']
