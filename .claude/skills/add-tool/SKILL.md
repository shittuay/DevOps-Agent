# /add-tool

Scaffold a new tool for the DevOps Agent — creates the handler function, registers it in `get_tools()`, and adds safety classification in `safety.py`.

## Usage

```
/add-tool
```

You may also specify inline:
```
/add-tool aws ec2 describe_spot_prices
/add-tool k8s list_daemon_sets
/add-tool azure list_load_balancers
/add-tool gcp list_cloud_functions
```

## What This Skill Does

When invoked, gather the following from the user (or from inline args):

1. **Provider** — `aws`, `k8s`, `azure`, or `gcp`
2. **Tool name** — snake_case function name (e.g. `describe_spot_prices`)
3. **Description** — one sentence describing what the tool does
4. **Operation type** — `read`, `create`, `update`, `delete` (determines safety classification)
5. **Key parameters** — names and types of the required inputs

Then execute these steps in order:

---

### Step 1 — Read the target tool file

Read the full relevant tool file before making any changes:
- AWS → `src/tools/aws_tools.py`
- Kubernetes → `src/tools/kubernetes_tools.py`
- Azure → `src/tools/azure_tools.py`
- GCP → `src/tools/gcp_tools.py`

---

### Step 2 — Write the handler function

Insert the new function **before** the `get_tools()` function at the bottom of the file.

Follow the exact pattern for the provider:

**AWS pattern:**
```python
def tool_name(param: str, region: Optional[str] = None) -> Dict[str, Any]:
    try:
        client = _get_boto_client('service_name', region)
        response = client.api_call(Param=param)
        return {'success': True, 'message': f'...', 'data': response}
    except ClientError as e:
        logger.error(f"AWS API error: {str(e)}")
        return {'success': False, 'error': str(e), 'error_code': e.response['Error']['Code']}
    except Exception as e:
        logger.error(f"Error in tool_name: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}
```

**Kubernetes pattern:**
```python
def tool_name(namespace: str = 'default', context: Optional[str] = None) -> Dict[str, Any]:
    try:
        v1, apps_v1 = _get_k8s_client(context)
        result = v1.list_namespaced_resource(namespace=namespace)
        items = [{'name': i.metadata.name, 'namespace': i.metadata.namespace} for i in result.items]
        return {'success': True, 'items': items, 'count': len(items)}
    except ApiException as e:
        logger.error(f"Kubernetes API error: {str(e)}")
        return {'success': False, 'error': str(e), 'status_code': e.status}
    except Exception as e:
        logger.error(f"Error in tool_name: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}
```

**Azure pattern:**
```python
def tool_name(param: str) -> Dict[str, Any]:
    try:
        client = _get_azure_client('compute')  # or storage|network|resource|sql|container
        result = client.resource_type.begin_operation(param).result()
        return {'success': True, 'message': f'...'}
    except Exception as e:
        logger.error(f"Azure API error: {str(e)}")
        return {'success': False, 'error': str(e)}
```

**GCP pattern:**
```python
def tool_name(param: str, project_id: Optional[str] = None) -> Dict[str, Any]:
    try:
        from google.cloud import specific_service_v1
        project = _resolve_project_id(project_id)
        client = specific_service_v1.ServiceClient()
        result = client.api_call(request={'project': project, 'param': param})
        return {'success': True, 'message': f'...'}
    except Exception as e:
        logger.error(f"GCP API error: {str(e)}")
        return {'success': False, 'error': str(e)}
```

---

### Step 3 — Register in `get_tools()`

Add an entry to the list returned by `get_tools()` at the bottom of the file:

```python
{
    'name': 'tool_name',
    'description': 'One sentence description of what this tool does.',
    'input_schema': {
        'type': 'object',
        'properties': {
            'param_name': {
                'type': 'string',
                'description': 'What this parameter controls.'
            },
            # add all parameters here
        },
        'required': ['param_name']  # list only truly required params
    },
    'handler': tool_name
},
```

---

### Step 4 — Update `safety.py`

Read `src/agent/safety.py` and add the tool name to the correct risk list:

| Operation type | Risk list | Location in safety.py |
|---|---|---|
| `delete` / `terminate` | `high_risk_tools` | Large set near top of `validate_tool_call()` |
| `update` / `restart` / `create_rule` / IAM | `medium_risk_tools` | Set below `high_risk_tools` |
| `read` / `list` / `describe` / `create` (non-rule) | No change needed | — |

**CRITICAL: Never skip this step for delete or update tools.**

---

### Step 5 — Verify

Run the verification command for the affected module:

```bash
# AWS
python -c "from src.tools.aws_tools import get_tools; print(f'AWS: {len(get_tools())}')"

# Kubernetes
python -c "from src.tools.kubernetes_tools import get_tools; print(f'K8s: {len(get_tools())}')"

# Azure
python -c "from src.tools.azure_tools import get_tools; print(f'Azure: {len(get_tools())}')"

# GCP
python -c "from src.tools.gcp_tools import get_tools; print(f'GCP: {len(get_tools())}')"
```

Confirm the count increased by exactly 1. If it didn't, find and fix the registration error before continuing.

---

### Step 6 — Report

Output a summary:

```
Tool added: <tool_name>
Provider:   <aws|k8s|azure|gcp>
File:       src/tools/<provider>_tools.py
Safety:     <high_risk | medium_risk | low_risk (default)>
Tool count: <old> → <new>
```

---

## Rules

- NEVER create boto3 clients directly in AWS tools — always use `_get_boto_client()`
- NEVER hardcode project IDs in GCP tools — always use `_resolve_project_id(project_id)`
- ALWAYS call `.result()` on Azure async operations (`begin_*()` methods)
- For K8s tools needing `NetworkingV1Api` or `BatchV1Api`, create them inline after `_get_k8s_client()`
- NEVER skip safety.py for delete/update tools — it silently defaults to low risk
- ALWAYS read the file before editing it
