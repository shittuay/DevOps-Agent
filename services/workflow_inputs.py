"""Typed input forms for pre-built workflows.

A workflow declares `inputs` (a list of field specs) and references them in its
step text as `{key}` placeholders. The Run button renders a form from the specs;
`validate_inputs` checks what comes back and `render_steps` fills the placeholders,
so the agent starts with every value it needs instead of asking in chat.

Field spec keys:
    key       identifier used as `{key}` in steps (lowercase, underscores)
    label     form label
    type      text | select | cidr | secret | number
    default   prefilled value (cidr fields with no default prefill the caller's IP)
    required  default True
    help      one-line hint under the field
    options   select only: list of allowed values
    pattern   text only: regex the whole value must match
    max_length  text only: overrides the 200-character default (e.g. SSH public keys)
    min, max  number only
    allow_world  cidr only: permit 0.0.0.0/0 (public web apps); default False
    generate     secret only: blank means generate a random value; default True
"""
import ipaddress
import re
import secrets
from typing import Any, Dict, List, Tuple

INPUT_TYPES = {'text', 'select', 'cidr', 'secret', 'number'}
MAX_TEXT_LENGTH = 200
MIN_SECRET_LENGTH = 16
_KEY_RE = re.compile(r'^[a-z][a-z0-9_]*$')
_PLACEHOLDER_RE = re.compile(r'\{([a-z][a-z0-9_]*)\}')
_WORLD_OPEN = {'*', 'internet', 'any', 'anywhere'}


def _clean_text(value: Any) -> str:
    return str(value if value is not None else '').strip()


def _validate_cidr(raw: str, allow_world: bool) -> Tuple[str, str]:
    if raw.lower() in _WORLD_OPEN:
        raw = '0.0.0.0/0'
    try:
        network = ipaddress.ip_network(raw, strict=False)
    except ValueError:
        return '', 'Enter an IP address or CIDR, e.g. 203.0.113.10/32.'
    if network.prefixlen == 0 and not allow_world:
        return '', 'This would open access to the whole internet. Enter your own IP, e.g. 203.0.113.10/32.'
    return str(network), ''


def validate_inputs(specs: List[Dict[str, Any]], submitted: Dict[str, Any]) -> Tuple[Dict[str, str], Dict[str, str]]:
    """Validate submitted form values against `specs`.

    Returns (values, errors). `values` maps every declared key to its final string;
    `errors` maps a key to a human-readable message. Undeclared submitted keys are
    ignored, so a client cannot inject extra placeholders.
    """
    submitted = submitted if isinstance(submitted, dict) else {}
    values: Dict[str, str] = {}
    errors: Dict[str, str] = {}

    for spec in specs or []:
        key = spec['key']
        kind = spec.get('type', 'text')
        raw = _clean_text(submitted.get(key, ''))
        if not raw and kind != 'secret':
            raw = _clean_text(spec.get('default', ''))

        if kind == 'secret':
            if not raw and spec.get('generate', True):
                values[key] = secrets.token_urlsafe(24)
                continue
            if raw and (len(raw) < MIN_SECRET_LENGTH or not re.fullmatch(r'[A-Za-z0-9_\-.~]+', raw)):
                errors[key] = (f'Use at least {MIN_SECRET_LENGTH} characters from letters, digits and '
                               '- _ . ~ — or leave it blank to generate one.')
                continue

        if not raw:
            if spec.get('required', True):
                errors[key] = 'Required.'
            else:
                values[key] = 'not specified'
            continue

        max_length = spec.get('max_length', MAX_TEXT_LENGTH)
        if len(raw) > max_length or any(c in raw for c in '{}\n\r`'):
            errors[key] = f'Use up to {max_length} characters, without braces, backticks or line breaks.'
            continue

        if kind == 'cidr':
            normalized, error = _validate_cidr(raw, spec.get('allow_world', False))
            if error:
                errors[key] = error
            else:
                values[key] = normalized
            continue

        if kind == 'number':
            try:
                number = int(raw)
            except ValueError:
                errors[key] = 'Enter a whole number.'
                continue
            low, high = spec.get('min'), spec.get('max')
            if (low is not None and number < low) or (high is not None and number > high):
                errors[key] = f'Enter a number from {low} to {high}.'
                continue
            values[key] = str(number)
            continue

        if kind == 'select' and raw not in spec.get('options', []):
            errors[key] = 'Choose one of the listed options.'
            continue

        pattern = spec.get('pattern')
        if kind == 'text' and pattern and not re.fullmatch(pattern, raw):
            errors[key] = spec.get('pattern_hint') or 'That value is not in the expected format.'
            continue

        values[key] = raw

    return values, errors


def render_steps(steps: List[str], values: Dict[str, str]) -> List[str]:
    """Substitute `{key}` placeholders for declared keys only.

    Literal braces elsewhere in a step (e.g. JSON like {"Name": "x"}) are left
    untouched, because only `{identifier}` tokens whose key was declared are replaced.
    """
    def _sub(match: 're.Match[str]') -> str:
        key = match.group(1)
        return values[key] if key in values else match.group(0)

    return [_PLACEHOLDER_RE.sub(_sub, step) for step in steps]


def placeholders_in(steps: List[str]) -> set:
    return {m.group(1) for step in steps for m in _PLACEHOLDER_RE.finditer(step)}


def spec_problems(specs: List[Dict[str, Any]], steps: List[str]) -> List[str]:
    """Static checks for a workflow definition (used by tests)."""
    problems = []
    keys = [s.get('key', '') for s in specs or []]
    if len(keys) != len(set(keys)):
        problems.append('duplicate input keys')
    for spec in specs or []:
        key = spec.get('key', '')
        if not _KEY_RE.match(key):
            problems.append(f'bad key {key!r}')
        if spec.get('type', 'text') not in INPUT_TYPES:
            problems.append(f'{key}: unknown type {spec.get("type")!r}')
        if not spec.get('label'):
            problems.append(f'{key}: missing label')
        if spec.get('type') == 'select' and spec.get('default') not in spec.get('options', []):
            problems.append(f'{key}: default not among options')
    used = placeholders_in(steps)
    for key in set(keys) - used:
        problems.append(f'input {key!r} is never used in the steps')
    for key in used - set(keys):
        problems.append(f'step placeholder {{{key}}} has no matching input')
    return problems
