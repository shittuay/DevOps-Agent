"""Self-hosted LLM workflows (AI/ML category) and the dlami-gpu AMI lookup.

Workflow steps are plain-language prompts dispatched to the agent, so the
guarantees worth pinning are textual: every tool a step names must exist in the
live catalog (a renamed tool would silently turn a step into a guess), the API
port is never opened to the internet, capacity is checked before launch, and
every workflow ends with teardown.
"""
import importlib
import re
import subprocess
from unittest.mock import MagicMock, patch

from services.starter_workflows import STARTER_WORKFLOWS, _VLLM_PIP_SETUP_LINES

LLM_WORKFLOWS = [wf for wf in STARTER_WORKFLOWS if wf['category'] == 'AI/ML']


def _wf(fragment):
    return next(wf for wf in LLM_WORKFLOWS if fragment in wf['name'])


EC2_WF = _wf('AWS GPU (EC2')
EKS_WF = _wf('EKS')
AZURE_WF = _wf('Azure')
GCP_WF = _wf('GCP')
ONPREM_WF = _wf('On-Prem')

# Tool names each workflow instructs the agent to call.
REFERENCED_TOOLS = {
    EC2_WF['name']: {'aws_api_read', 'find_ami', 'create_security_group',
                     'authorize_security_group_ingress', 'create_ec2_instance', 'http_check'},
    EKS_WF['name']: {'aws_api_read', 'create_eks_node_group', 'apply_manifest'},
    AZURE_WF['name']: {'azure_api_read', 'azure_api_write', 'create_resource_group',
                       'create_virtual_machine', 'http_check'},
    GCP_WF['name']: {'gcp_api_read', 'gcp_api_write', 'create_firewall_rule',
                     'delete_compute_instance', 'delete_firewall_rule', 'http_check'},
    ONPREM_WF['name']: {'get_nodes', 'describe_node', 'k8s_api_read', 'apply_manifest',
                        'create_namespace', 'create_k8s_secret', 'get_pod_logs',
                        'delete_namespace'},
}

# Single-VM workflows expose a public port, so ingress must be scoped to one CIDR.
PUBLIC_VM_WORKFLOWS = [EC2_WF, AZURE_WF, GCP_WF]
# Cloud workflows launch billed GPU capacity, so the quota check must come first.
LAUNCH_MARKERS = {
    EC2_WF['name']: 'create_ec2_instance',
    EKS_WF['name']: 'create_eks_node_group',
    AZURE_WF['name']: 'create_virtual_machine',
    GCP_WF['name']: '"instances", "insert"',
}


def _catalog_names():
    names = set()
    for mod_name in ('aws_tools', 'azure_tools', 'gcp_tools', 'kubernetes_tools',
                     'verification_tools'):
        mod = importlib.import_module('src.tools.' + mod_name)
        names.update(t['name'] for t in mod.get_tools())
    return names


def _text(wf):
    return ' '.join(wf['steps'])


def test_all_llm_workflows_are_in_the_catalog():
    assert len(LLM_WORKFLOWS) == 5
    for wf in LLM_WORKFLOWS:
        assert wf['steps'] and wf['estimated_minutes'] > 0


def test_every_referenced_tool_exists():
    catalog = _catalog_names()
    for wf in LLM_WORKFLOWS:
        text = _text(wf)
        for tool in REFERENCED_TOOLS[wf['name']]:
            assert tool in text, f'{tool} no longer referenced in {wf["name"]}; update this test'
            assert tool in catalog, f'{wf["name"]} tells the agent to call {tool}, which does not exist'


def test_api_port_is_never_opened_to_the_internet():
    for wf in PUBLIC_VM_WORKFLOWS:
        text = _text(wf)
        # The only mention of 0.0.0.0/0 must be the prohibition itself.
        for match in re.finditer(r'0\.0\.0\.0/0', text):
            assert 'never' in text[max(0, match.start() - 40):match.start()], wf['name']
        assert 'my CIDR' in text, wf['name']


def test_azure_workflow_uses_the_locked_down_vm_parameters():
    # create_virtual_machine is only safe with a key and a scoped CIDR; see
    # tests/test_azure_vm_secure_defaults.py for the tool-level guarantees.
    text = _text(AZURE_WF)
    assert 'ssh_public_key set to my key' in text
    assert 'allowed_source_cidr set to my CIDR' in text
    assert 'open_ports [8000] (no SSH)' in text


def test_azure_runs_setup_only_after_the_driver_extension():
    steps = AZURE_WF['steps']
    driver = next(i for i, s in enumerate(steps) if 'NvidiaGpuDriverLinux' in s and 'Succeeded' in s)
    setup = next(i for i, s in enumerate(steps) if 'begin_run_command' in s)
    assert driver < setup


def test_gpu_quota_is_checked_before_launch():
    for wf_name, marker in LAUNCH_MARKERS.items():
        wf = next(w for w in LLM_WORKFLOWS if w['name'] == wf_name)
        steps = wf['steps']
        quota_idx = next(i for i, s in enumerate(steps) if 'quota' in s.lower() or 'Quota' in s)
        launch_idx = next(i for i, s in enumerate(steps) if marker in s)
        assert quota_idx < launch_idx, f'{wf_name} launches before checking GPU quota'


def test_onprem_workflow_never_touches_a_cloud_api_or_the_host():
    text = _text(ONPREM_WF)
    for cloud_tool in ('aws_api', 'azure_api', 'gcp_api', 'create_ec2_instance'):
        assert cloud_tool not in text
    assert 'never attempt host-level installs' in text


def test_ec2_workflow_resolves_the_gpu_ami_and_bakes_config_into_user_data():
    text = _text(EC2_WF)
    assert 'find_ami(distro="dlami-gpu"' in text
    # Provision-then-configure in one shot (Execution Integrity): config rides in user_data.
    assert 'user_data' in text and 'vllm/vllm-openai' in text


def test_kubernetes_workflows_install_the_device_plugin_and_request_a_gpu():
    for wf in (EKS_WF, ONPREM_WF):
        text = _text(wf)
        assert 'nvcr.io/nvidia/k8s-device-plugin:' in text
        assert 'nvidia.com/gpu: 1' in text
    assert 'AL2023_x86_64_NVIDIA' in _text(EKS_WF)


def test_all_workflows_end_with_teardown():
    for wf in LLM_WORKFLOWS:
        assert 'teardown' in wf['steps'][-1].lower(), wf['name']


def test_shared_setup_script_is_valid_shell():
    parts = [p.strip() for p in re.split(r'\(\d+\) ', _VLLM_PIP_SETUP_LINES) if p.strip()]
    script = '\n'.join(parts).replace('{model_id}', 'm').replace('{api_key}', 'k').replace('EXTRA_ARGS', '')
    assert script.startswith('#!/bin/bash')
    result = subprocess.run(['bash', '-n'], input=script, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    # Runs as a systemd unit so a driver-install reboot cannot leave vLLM stopped.
    assert 'systemctl daemon-reload && systemctl enable --now vllm' in script


def test_find_ami_dlami_gpu_pins_amazon_owner_and_dlami_name():
    from src.tools import aws_tools
    client = MagicMock()
    client.describe_images.return_value = {'Images': [
        {'ImageId': 'ami-dl-old', 'Name': 'dl-old', 'CreationDate': '2026-01-01T00:00:00Z'},
        {'ImageId': 'ami-dl-new', 'Name': 'dl-new', 'CreationDate': '2026-09-01T00:00:00Z'},
    ]}
    with patch.object(aws_tools, '_get_boto_client', return_value=client), \
         patch.object(aws_tools, '_get_effective_region', return_value='us-east-1'):
        result = aws_tools.find_ami(distro='dlami-gpu', version='24.04')

    assert result['success'] is True
    assert result['ami_id'] == 'ami-dl-new'
    kwargs = client.describe_images.call_args.kwargs
    assert kwargs['Owners'] == ['amazon']
    name_filter = next(f for f in kwargs['Filters'] if f['Name'] == 'name')['Values'][0]
    assert name_filter == 'Deep Learning Base OSS Nvidia Driver GPU AMI (Ubuntu 24.04) *'


def test_find_ami_schema_offers_dlami_gpu():
    from src.tools.aws_tools import get_tools
    tool = next(t for t in get_tools() if t['name'] == 'find_ami')
    assert 'dlami-gpu' in tool['input_schema']['properties']['distro']['enum']


def test_llm_curriculum_phase_exists_with_projects():
    from curriculum.data import CURRICULUM
    phase = next(p for p in CURRICULUM if p['title'].startswith('AI Infrastructure'))
    ids = [m['id'] for m in phase['modules']]
    assert ids == ['llm-serving-fundamentals', 'llm-cloud-gpu-deploy',
                   'llm-kubernetes-onprem', 'llm-production-ops']
    for module in phase['modules']:
        assert module['project'] and len(module['topics']) >= 5


def test_llm_curriculum_phase_renders(authenticated_client):
    body = authenticated_client.get('/curriculum/phase/07').get_data(as_text=True)
    assert 'AI Infrastructure' in body and 'LLMs on Kubernetes' in body
    index = authenticated_client.get('/curriculum/').get_data(as_text=True)
    assert '7 phases' in index
