# /check-tools

Full audit of all DevOps Agent tools — counts, unregistered functions, handler validity, schema completeness, and safety classification gaps.

## Usage

```
/check-tools
```

Or target a specific provider:
```
/check-tools aws
/check-tools k8s
/check-tools azure
/check-tools gcp
```

## What This Skill Does

Runs a comprehensive health check across all 4 tool modules and surfaces every issue that would cause a tool to fail silently or behave incorrectly.

---

### Step 1 — Count all tools

```bash
python -c "
from src.tools.aws_tools import get_tools as aws
from src.tools.kubernetes_tools import get_tools as k8s
from src.tools.azure_tools import get_tools as azure
from src.tools.gcp_tools import get_tools as gcp

counts = {'AWS': len(aws()), 'K8s': len(k8s()), 'Azure': len(azure()), 'GCP': len(gcp())}
total = sum(counts.values())
for k, v in counts.items():
    print(f'{k}: {v}')
print(f'Total: {total}')
"
```

Expected baselines: AWS=154, K8s=28, Azure=36, GCP=40, Total=258. Flag any that are lower than baseline.

---

### Step 2 — Find unregistered functions

Run for each module to find functions defined but not in `get_tools()`:

```bash
python -c "
import re

modules = [
    ('AWS',   'src/tools/aws_tools.py',        'src.tools.aws_tools'),
    ('K8s',   'src/tools/kubernetes_tools.py', 'src.tools.kubernetes_tools'),
    ('Azure', 'src/tools/azure_tools.py',       'src.tools.azure_tools'),
    ('GCP',   'src/tools/gcp_tools.py',         'src.tools.gcp_tools'),
]

for label, path, module_path in modules:
    content = open(path).read()
    defined = set(
        m.group(1) for m in re.finditer(r'^def ([a-z]\w+)\(', content, re.M)
        if not m.group(1).startswith('_') and m.group(1) != 'get_tools'
    )
    import importlib
    mod = importlib.import_module(module_path)
    registered = set(t['name'] for t in mod.get_tools())
    unregistered = defined - registered
    if unregistered:
        print(f'{label} UNREGISTERED ({len(unregistered)}): {sorted(unregistered)}')
    else:
        print(f'{label}: all functions registered')
"
```

---

### Step 3 — Validate all handlers and schemas

```bash
python -c "
from src.tools import aws_tools, kubernetes_tools, azure_tools, gcp_tools

issues = []
for name, mod in [('AWS', aws_tools), ('K8s', kubernetes_tools), ('Azure', azure_tools), ('GCP', gcp_tools)]:
    for t in mod.get_tools():
        if not callable(t.get('handler')):
            issues.append(f'{name}/{t[\"name\"]}: handler not callable')
        if 'input_schema' not in t:
            issues.append(f'{name}/{t[\"name\"]}: missing input_schema')
        if 'description' not in t or not t['description']:
            issues.append(f'{name}/{t[\"name\"]}: missing description')

if issues:
    print('ISSUES FOUND:')
    for i in issues: print(' -', i)
else:
    print('All handlers and schemas valid')
"
```

---

### Step 4 — Check safety classification gaps

Find delete/terminate/update tools that are missing from safety.py risk lists:

```bash
python -c "
from src.tools import aws_tools, kubernetes_tools, azure_tools, gcp_tools
from src.agent.safety import SafetyValidator

sv = SafetyValidator()
high = sv.high_risk_tools
medium = sv.medium_risk_tools

warnings = []
all_tools = []
for mod in [aws_tools, kubernetes_tools, azure_tools, gcp_tools]:
    all_tools.extend(mod.get_tools())

for t in all_tools:
    name = t['name']
    if any(name.startswith(p) for p in ('delete_', 'terminate_', 'remove_', 'destroy_')):
        if name not in high:
            warnings.append(f'HIGH RISK not classified: {name}')
    elif any(name.startswith(p) for p in ('update_', 'restart_', 'stop_', 'start_', 'reboot_')):
        if name not in medium and name not in high:
            warnings.append(f'MEDIUM RISK not classified: {name}')

if warnings:
    print('SAFETY GAPS:')
    for w in warnings: print(' -', w)
else:
    print('Safety classification complete')
"
```

---

### Step 5 — Report

Output a full summary:

```
=== Tool Audit Report ===

Counts:
  AWS:    154  (baseline: 154)  OK / BELOW BASELINE
  K8s:    28   (baseline: 28)   OK / BELOW BASELINE
  Azure:  36   (baseline: 36)   OK / BELOW BASELINE
  GCP:    40   (baseline: 40)   OK / BELOW BASELINE
  Total:  258

Unregistered Functions:
  AWS:   none / [list]
  K8s:   none / [list]
  Azure: none / [list]
  GCP:   none / [list]

Handler/Schema Validity:
  PASS / [list of issues]

Safety Classification:
  PASS / [list of gaps]

=== Overall: PASS / FAIL ===
Issues requiring action: <count>
```

For every issue found, state exactly what file and what change is needed to fix it.

---

## Rules

- Run all 4 steps even if Step 1 finds no issues — gaps can appear in any step
- Never mark overall PASS if there are safety classification gaps for delete/terminate tools
- If unregistered functions are found, check if they were intentionally excluded (helper functions) or genuinely forgotten — only flag non-helper public functions
- After fixing any issue found, re-run `/check-tools` to confirm clean
