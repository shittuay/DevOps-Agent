"""The 2FA code page must fit a phone screen.

On iPhone (WebKit) the centred flex item grew to the code box's intrinsic width (wide
monospace, letter-spaced) and the card ran off the right edge (seen in the iOS app,
2026-11-02). min-width: 0 on the flex item and the input lets them shrink to the screen.
"""
import re
from pathlib import Path

HTML = (Path(__file__).resolve().parent.parent / 'templates' / 'verify_2fa.html').read_text()


def _rule(selector):
    m = re.search(r'^\s*' + re.escape(selector) + r'\s*\{([^}]*)\}', HTML, re.M)
    assert m, selector
    return m.group(1)


def test_container_and_code_box_can_shrink_to_the_screen():
    assert 'min-width: 0' in _rule('.container')
    assert 'min-width: 0' in _rule('input')
