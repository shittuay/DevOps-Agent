"""Self-hosted LLM workflows (AI/ML category) and the dlami-gpu AMI lookup.

Workflow steps are plain-language prompts dispatched to the agent, so the
guarantees worth pinning are textual: every tool a step names must exist in the
live catalog (a renamed tool would silently turn a step into a guess), the API
port is never opened to the internet, and capacity is checked before launch.
"""
import importlib
import re
from unittest.mock import MagicMock, patch

from services.starter_workflows import STARTER_WORKFLOWS

LLM_WORKFLOWS = [wf for wf in STARTER_WORKFLOWS if wf['category'] == 'AI/ML']
EC2_WF = next(wf for wf in LLM_WORKFLOWS if 'EC2' in wf['name'])
EKS_WF = next(wf for wf in LLM_WORKFLOWS if 'EKS' in wf['name'])

# Tool names the workflow steps instruct the agent to call.
REFERENCED_TOOLS = {
    EC2_WF['name']: {'aws_api_read', 'find_ami', 'create_security_group',
                     'authorize_security_group_ingress', 'create_ec2_instance', 'http_check'},
    EKS_WF['name']: {'aws_api_read', 'create_eks_node_group', 'apply_manifest'},
}


def _catalog_names():
    names = set()
    for mod_name in ('aws_tools', 'kubernetes_tools', 'verification_tools'):
        mod = importlib.import_module('src.tools.' + mod_name)
        names.update(t['name'] for t in mod.get_tools())
    return names


def _text(wf):
    return ' '.join(wf['steps'])


def test_both_llm_workflows_are_in_the_catalog():
    assert len(LLM_WORKFLOWS) == 2
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
    text = _text(EC2_WF)
    # The only mention of 0.0.0.0/0 must be the prohibition itself.
    for match in re.finditer(r'0\.0\.0\.0/0', text):
        assert 'never' in text[max(0, match.start() - 40):match.start()]
    assert 'from my CIDR only' in text


def test_gpu_quota_is_checked_before_launch():
    for wf in LLM_WORKFLOWS:
        steps = wf['steps']
        quota_idx = next(i for i, s in enumerate(steps) if 'L-DB2E81BA' in s)
        launch_idx = next(i for i, s in enumerate(steps)
                          if 'create_ec2_instance' in s or 'create_eks_node_group' in s)
        assert quota_idx < launch_idx, f'{wf["name"]} launches before checking GPU quota'


def test_ec2_workflow_resolves_the_gpu_ami_and_bakes_config_into_user_data():
    text = _text(EC2_WF)
    assert 'find_ami(distro="dlami-gpu"' in text
    # Provision-then-configure in one shot (Execution Integrity): config rides in user_data.
    assert 'user_data' in text and 'vllm/vllm-openai' in text


def test_eks_workflow_installs_the_device_plugin_and_requests_a_gpu():
    text = _text(EKS_WF)
    assert 'AL2023_x86_64_NVIDIA' in text
    assert 'nvcr.io/nvidia/k8s-device-plugin:' in text
    assert 'nvidia.com/gpu: 1' in text


def test_both_workflows_end_with_teardown():
    for wf in LLM_WORKFLOWS:
        assert 'teardown' in wf['steps'][-1].lower()


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
