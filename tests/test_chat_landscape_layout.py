"""The chat page stays usable on a phone turned sideways.

A landscape phone is wide (~740-930px) but short (~320-430px). The mobile rules
matched on width only, so landscape got the desktop layout: a fixed 260px sidebar,
the full welcome banner, and a page sized with 100vh, which on phones is taller than
the visible area once the browser bars are shown. The message box ended up below
the bottom of the screen (reported 2026-10-14).
"""
import re
from pathlib import Path

HTML = (Path(__file__).resolve().parent.parent / 'templates' / 'index.html').read_text()


def _css_block(selector_start: str) -> str:
    start = HTML.index(selector_start)
    return HTML[start:HTML.index('}', start)]


def test_mobile_rules_also_match_short_screens():
    assert HTML.count('@media (max-width: 768px), (max-height: 500px)') == 2, (
        'Both mobile layout blocks (sidebar drawer + chat sizing) must also apply in landscape'
    )


def test_landscape_block_keeps_the_message_box_on_screen():
    m = re.search(r'@media \(max-height: 500px\) \{(.*?)\n        \}', HTML, re.S)
    assert m, 'missing the short-screen (landscape) block'
    block = m.group(1)
    assert '.welcome-icon' in block and 'display: none' in block
    assert '.welcome h2' in block
    assert '.input-wrapper' in block


def test_page_height_uses_the_visible_viewport():
    assert '100dvh' in _css_block('        body {')
    assert '100dvh' in _css_block('        .sidebar {')
