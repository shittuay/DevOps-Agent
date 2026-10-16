"""Contact us lives in the chat profile menu, not as a floating button.

The floating envelope sat fixed at the bottom-right and covered the Send
button on desktop (and was hidden on phones, leaving no way to reach it).
"""
from pathlib import Path

HTML = (Path(__file__).resolve().parent.parent / 'templates' / 'index.html').read_text()


def test_no_floating_contact_button_over_send():
    assert 'class="contact-widget"' not in HTML
    assert '.contact-widget' not in HTML


def test_contact_us_is_in_profile_menu():
    menu = HTML[HTML.index('id="mainMenu"'):]
    menu = menu[:menu.index('</div>\n                    </div>')]
    assert 'openContactModal()' in menu
    assert 'Contact us' in menu


def test_contact_modal_still_present():
    assert 'id="contactModalOverlay"' in HTML
    assert 'function openContactModal' in HTML
