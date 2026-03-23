# /test-tool

Test a specific DevOps Agent tool by running it in sandbox mode and validating the response shape.

## Usage

```
/test-tool
```

Or with inline args:
```
/test-tool aws list_ec2_instances
/test-tool k8s list_pods namespace=kube-system
/test-tool azure list_virtual_machines
/test-tool gcp list_compute_instances
```

## What This Skill Does

Tests a named tool end-to-end: imports it, calls it with safe/mock inputs, validates the response, and reports pass/fail with details.

---

### Step 1 — Identify the tool

Ask for (or parse from inline args):
1. **Provider** — `aws`, `k8s`, `azure`, `gcp`
2. **Tool name** — exact name as registered in `get_tools()`
3. **Parameters** — any specific inputs to pass (optional, will use safe defaults)

---

### Step 2 — Verify tool is registered

```bash
python -c "
from src.tools.<provider>_tools import get_tools
tools = {t['name']: t for t in get_tools()}
name = '<tool_name>'
if name in tools:
    t = tools[name]
    print('REGISTERED:', name)
    print('Schema:', t['input_schema'])
    print('Handler callable:', callable(t['handler']))
else:
    print('NOT FOUND:', name)
    print('Available:', sorted(tools.keys()))
"
```

If not registered, stop and report — do not proceed.

---

### Step 3 — Enable sandbox mode and call the tool

```bash
python -c "
import os
os.environ['SANDBOX_MODE'] = 'true'

from src.tools.<provider>_tools import get_tools
tools = {t['name']: t for t in get_tools()}
handler = tools['<tool_name>']['handler']

# Call with safe test parameters
result = handler(<test_params>)
print('Result:', result)
"
```

**Safe default parameters by provider:**

| Provider | Safe defaults |
|---|---|
| AWS | `region='us-east-1'` for read tools; skip destructive params |
| K8s | `namespace='default'`, `context=None` |
| Azure | Use non-existent resource names for read; skip delete |
| GCP | `project_id=None` (will use env var or fail gracefully) |

**Never call delete/terminate tools during testing** — use list/describe tools instead.

---

### Step 4 — Validate the response shape

Check all of the following:

```
[ ] result is a dict
[ ] 'success' key is present (bool)
[ ] If success=True: at least one data key present (message, items, data, count, etc.)
[ ] If success=False: 'error' key present with a string value
[ ] No unhandled exceptions (tool should catch and return error dict)
[ ] No raw boto3/k8s/azure/gcp objects in the response (must be serializable)
```

---

### Step 5 — Check safety classification

```bash
python -c "
from src.agent.safety import SafetyValidator
sv = SafetyValidator()
result = sv.validate_tool_call('<tool_name>', {})
print('Risk level:', result.get('risk_level'))
print('Requires confirmation:', result.get('requires_confirmation'))
"
```

Confirm:
- Delete tools → `risk_level: high`
- Update/restart tools → `risk_level: medium`
- Read/list/create tools → `risk_level: low`

Flag if classification looks wrong.

---

### Step 6 — Report

Output a structured result:

```
Tool:        <tool_name>
Provider:    <provider>
Registered:  PASS / FAIL
Handler:     callable / NOT CALLABLE
Response:    VALID / INVALID
  success key: present / missing
  data key:    present / missing
  serializable: yes / no
Safety:      high / medium / low  (expected: <expected>)  PASS / WARN

Overall: PASS / FAIL
```

If FAIL, output the exact error and what needs to be fixed.

---

## Rules

- Never call destructive tools (delete, terminate, stop) during testing
- Sandbox mode (`SANDBOX_MODE=true`) must be set — mock results only
- If the tool raises an unhandled exception, that is a FAIL — all tools must return dicts
- A tool that returns `{'success': False, 'error': '...'}` is PASSING — that is correct error handling
- A tool that returns raw SDK objects is FAILING — responses must be JSON-serializable
