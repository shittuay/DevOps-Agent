"""The npm bridge's version must match server.json and what the server reports.

1.0.7 was drafted in the changelog but never published, while the server still said 1.0.4
and npm had 1.0.6. Keep all four in step so a release can't go out half-bumped.
"""
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_versions_agree():
    pkg = json.loads((ROOT / 'mcp' / 'package.json').read_text())['version']
    server = json.loads((ROOT / 'mcp' / 'server.json').read_text())
    assert server['version'] == pkg
    assert [p['version'] for p in server['packages']] == [pkg]
    route = re.search(r'SERVER_VERSION = "([^"]+)"', (ROOT / 'routes' / 'mcp.py').read_text()).group(1)
    assert route == pkg


def test_changelog_has_an_entry_for_this_version():
    pkg = json.loads((ROOT / 'mcp' / 'package.json').read_text())['version']
    assert f'## [{pkg}]' in (ROOT / 'mcp' / 'CHANGELOG.md').read_text()
