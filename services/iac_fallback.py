"""CloudFormation fallback generation for a failed creating tool
(Execution Integrity rule 4 — see docs/execution-integrity.md).

"Never dead-end." When a dedicated create tool (and its generic
``aws_api_write`` fallback) fails, the platform hands the model a ready-to-run
CloudFormation template built from the same intent, so the next step is
"deploy this" — not "go do it in the console."

``generate_cloudformation(tool_name, tool_input)`` returns

  {'format': 'cloudformation',
   'stack_name': <suggested>,
   'template': <compact JSON string>,
   'resource_type': 'AWS::EC2::Instance',
   'apply': 'Call create_cloudformation_stack with template_body set to this ...'}

or ``None`` when the tool isn't supported or the input is too incomplete to
build a valid template (e.g. an EC2 instance with no AMI).

Pure and dependency-free — no boto3, no template is ever applied here.
"""
from __future__ import annotations

import json
from typing import Any, Callable, Dict, Optional, Tuple

_AWS_TEMPLATE_VERSION = "2010-09-09"


def _tags(tag_dict: Any, default_name: Optional[str] = None) -> list:
    out = []
    if isinstance(tag_dict, dict):
        out = [{"Key": str(k), "Value": str(v)} for k, v in tag_dict.items()]
    if default_name and not any(t["Key"] == "Name" for t in out):
        out.append({"Key": "Name", "Value": default_name})
    return out


# --- per-tool: tool_input -> (LogicalId, ResourceType, Properties, Parameters) ---

def _ec2_instance(ti: dict):
    ami = ti.get("ami_id")
    if not ami:
        return None  # CloudFormation needs a concrete ImageId too
    props: Dict[str, Any] = {"ImageId": ami}
    if ti.get("instance_type"):
        props["InstanceType"] = ti["instance_type"]
    if ti.get("key_name"):
        props["KeyName"] = ti["key_name"]
    if ti.get("security_group_ids"):
        props["SecurityGroupIds"] = list(ti["security_group_ids"])
    if ti.get("subnet_id"):
        props["SubnetId"] = ti["subnet_id"]
    tags = _tags(ti.get("tags"))
    if tags:
        props["Tags"] = tags
    return ("Instance", "AWS::EC2::Instance", props, {})


def _security_group(ti: dict):
    if not ti.get("group_name") or not ti.get("description"):
        return None
    props: Dict[str, Any] = {
        "GroupName": ti["group_name"],
        "GroupDescription": ti["description"],
    }
    if ti.get("vpc_id"):
        props["VpcId"] = ti["vpc_id"]
    rules = []
    for r in (ti.get("ingress_rules") or []):
        if not isinstance(r, dict):
            continue
        entry = {"IpProtocol": str(r.get("protocol", r.get("IpProtocol", "tcp")))}
        for src, dst in (("from_port", "FromPort"), ("to_port", "ToPort"),
                         ("FromPort", "FromPort"), ("ToPort", "ToPort")):
            if r.get(src) is not None:
                entry[dst] = r[src]
        cidr = r.get("cidr") or r.get("CidrIp") or r.get("cidr_ip")
        if cidr:
            entry["CidrIp"] = cidr
        rules.append(entry)
    if rules:
        props["SecurityGroupIngress"] = rules
    return ("SecurityGroup", "AWS::EC2::SecurityGroup", props, {})


def _vpc(ti: dict):
    if not ti.get("cidr_block"):
        return None
    props: Dict[str, Any] = {
        "CidrBlock": ti["cidr_block"],
        "EnableDnsSupport": bool(ti.get("enable_dns_support", True)),
        "EnableDnsHostnames": bool(ti.get("enable_dns_hostnames", True)),
    }
    tags = _tags(None, ti.get("name"))
    if tags:
        props["Tags"] = tags
    return ("Vpc", "AWS::EC2::VPC", props, {})


def _s3_bucket(ti: dict):
    name = ti.get("bucket_name")
    if not name:
        return None
    props: Dict[str, Any] = {"BucketName": name}
    if ti.get("versioning_enabled"):
        props["VersioningConfiguration"] = {"Status": "Enabled"}
    if ti.get("encryption_enabled", True):
        props["BucketEncryption"] = {
            "ServerSideEncryptionConfiguration": [
                {"ServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}
            ]
        }
    if ti.get("public_access_block", True):
        props["PublicAccessBlockConfiguration"] = {
            "BlockPublicAcls": True, "BlockPublicPolicy": True,
            "IgnorePublicAcls": True, "RestrictPublicBuckets": True,
        }
    return ("Bucket", "AWS::S3::Bucket", props, {})


_CFN_SPECS: Dict[str, Callable[[dict], Optional[Tuple]]] = {
    "create_ec2_instance": _ec2_instance,
    "run_instances": _ec2_instance,
    "create_security_group": _security_group,
    "create_vpc": _vpc,
    "create_s3_bucket": _s3_bucket,
    # create_rds_instance is intentionally omitted: its MasterUserPassword would
    # have to be embedded or threaded through a NoEcho parameter — deferred.
}

_CAPABILITY_RESOURCES = {"AWS::IAM::Role", "AWS::IAM::Policy", "AWS::IAM::InstanceProfile"}


def is_supported(tool_name: str) -> bool:
    return tool_name in _CFN_SPECS


def _suggested_stack_name(tool_name: str, props: dict) -> str:
    hint = (props.get("BucketName") or props.get("GroupName")
            or (props.get("Tags") or [{}])[0].get("Value") or tool_name)
    slug = "".join(c if c.isalnum() or c == "-" else "-" for c in str(hint)).strip("-")
    return f"devopsagent-{slug or 'fallback'}"[:120]


def generate_cloudformation(tool_name: str, tool_input: dict) -> Optional[Dict[str, Any]]:
    builder = _CFN_SPECS.get(tool_name)
    if builder is None:
        return None
    try:
        built = builder(tool_input or {})
    except Exception:
        return None
    if not built:
        return None
    logical_id, resource_type, props, params = built

    template: Dict[str, Any] = {
        "AWSTemplateFormatVersion": _AWS_TEMPLATE_VERSION,
        "Description": f"DevOpsAgent fallback for {tool_name} (the direct call failed)",
        "Resources": {logical_id: {"Type": resource_type, "Properties": props}},
        "Outputs": {
            f"{logical_id}Ref": {"Value": {"Ref": logical_id}},
        },
    }
    if params:
        template["Parameters"] = params

    caps = ["CAPABILITY_NAMED_IAM"] if resource_type in _CAPABILITY_RESOURCES else []
    stack_name = _suggested_stack_name(tool_name, props)
    return {
        "format": "cloudformation",
        "stack_name": stack_name,
        "template": json.dumps(template, separators=(",", ":")),
        "resource_type": resource_type,
        "apply": (
            f"The direct `{tool_name}` call failed. A CloudFormation template that "
            f"creates the same resource is ready. To apply it, call "
            f"create_cloudformation_stack(stack_name='{stack_name}', "
            f"template_body=<the template string above>"
            + (f", capabilities={caps}" if caps else "") + "). "
            f"Do not tell the user to use the console — offer to run this."
        ),
    }
