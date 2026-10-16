"""The sandbox web-server mission ran every step and the teardown in one reply, showed its
heading and table as raw "##" and "|" text, and printed ids AWS never uses (ami-i7lz...).
"""
import json
import pathlib
import re
import shutil
import subprocess
from types import SimpleNamespace

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
CHAT = (ROOT / 'templates' / 'index.html').read_text()


# --- one step per reply -----------------------------------------------------------

def test_sandbox_prompt_asks_for_one_step_per_reply():
    import app as app_module
    text = app_module.SANDBOX_MODE_ADDENDUM
    assert 'ONE STEP PER REPLY' in text
    assert 'Ready for the next step?' in text
    assert 'never clean up, in the same reply' in text


def test_web_server_mission_asks_to_pause_after_each_step():
    mission = re.search(r"title: 'Launch a web server'.*?prompt: \"(.*?)\"\}", CHAT, re.S).group(1)
    assert 'one step at a time' in mission
    assert 'stop and wait for me' in mission


def test_swarm_is_off_in_sandbox():
    import app as app_module
    config = SimpleNamespace(swarm_max_agents=5)
    prefs_on = SimpleNamespace(swarm_enabled=True)
    assert app_module._swarm_agents_for(config, prefs_on, sandbox_active=True) == 0
    assert app_module._swarm_agents_for(config, prefs_on, sandbox_active=False) == 5
    assert app_module._swarm_agents_for(config, None, sandbox_active=False) == 5
    assert app_module._swarm_agents_for(config, SimpleNamespace(swarm_enabled=False), False) == 0


def test_both_chat_routes_use_the_swarm_helper():
    source = (ROOT / 'app.py').read_text()
    assert source.count('_swarm_agents_for(') == 3  # definition + 2 chat routes
    assert "getattr(prefs, 'swarm_enabled', True))\n            else 0" not in source


# --- practice ids look like AWS ids --------------------------------------------------

def test_sandbox_ids_are_hex_like_aws():
    from services import learning_sandbox
    for _ in range(50):
        assert re.fullmatch(r'[0-9a-f]{17}', learning_sandbox._rand_id())
        assert re.fullmatch(r'ami-[0-9a-f]{17}', learning_sandbox._rand_id('ami-'))


# --- chat renders headings, tables and lists ------------------------------------------

def _renderer_source():
    start = CHAT.index('        // Small markdown renderer')
    end = CHAT.index('        function scrollToBottom()')
    return CHAT[start:end]


@pytest.fixture(scope='module')
def render():
    node = shutil.which('node')
    if not node:
        pytest.skip('node is not installed')

    def _render(text):
        script = _renderer_source() + '\nprocess.stdout.write(formatMessage(' + json.dumps(text) + '));'
        out = subprocess.run([node, '-e', script], capture_output=True, text=True, timeout=30)
        assert out.returncode == 0, out.stderr
        return out.stdout
    return _render


REPLY = """[SANDBOX SIMULATION] Teardown complete.

## What you just did

| Step | Action | Result |
|------|--------|--------|
| 1 | Found image | `ami-0a1b2c3d4e5f67890` |
| 2 | Opened port 80 to **one IP** | `sg-0f3a9c2d7e1b45678` |
"""


def test_table_and_heading_render(render):
    html = render(REPLY)
    assert '<h3 class="md-heading">What you just did</h3>' in html
    assert html.count('<tr>') == 3
    assert '<th>Step</th>' in html
    assert '<td><code>ami-0a1b2c3d4e5f67890</code></td>' in html
    assert '<strong>one IP</strong>' in html
    assert '|' not in html.replace('&#124;', '')


def test_lists_rule_and_code_render(render):
    html = render('- a\n- b\n\n1. x\n2. y\n\n---\n```bash\necho | **x**\n```')
    assert '<ul class="md-list"><li>a</li><li>b</li></ul>' in html
    assert '<ol class="md-list"><li>x</li><li>y</li></ol>' in html
    assert '<hr class="md-rule">' in html
    assert '<pre data-lang="code"><code>echo | **x**\n</code></pre>' in html


def test_html_in_a_reply_stays_text(render):
    html = render('<img src=x onerror=alert(1)>\n| <b>a</b> | b |\n|---|---|\n| <script>x</script> | y |')
    assert '<img' not in html and '<script' not in html and '<b>' not in html
    assert '&lt;script&gt;' in html


def test_plain_lines_keep_their_breaks(render):
    assert render('one\ntwo') == 'one<br>two'
