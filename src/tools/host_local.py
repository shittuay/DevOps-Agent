"""Gate for tools that act on the DevOps Agent server itself.

command_tools, git_tools, docker_tools, terraform_tools and ansible_tools run
programs and read files on the machine hosting this app, not in the user's
cloud account. On the hosted site that machine holds every customer's data and
the platform's secrets, so these tools are registered only when the operator
opts in for a self-hosted install (DEVOPS_AGENT_HOST_TOOLS=true), the same
shape as K8S_USE_LOCAL_KUBECONFIG. The CLI (main.py) runs on the operator's
own machine and keeps them.
"""
import os

HOST_TOOLS_ENV = 'DEVOPS_AGENT_HOST_TOOLS'

HOST_LOCAL_MODULES = frozenset({
    'command_tools', 'git_tools', 'docker_tools', 'terraform_tools', 'ansible_tools',
})


def host_tools_enabled() -> bool:
    return os.environ.get(HOST_TOOLS_ENV, '').strip().lower() in ('1', 'true', 'yes')


def is_host_local(module) -> bool:
    name = module if isinstance(module, str) else getattr(module, '__name__', '')
    return name.rsplit('.', 1)[-1] in HOST_LOCAL_MODULES
