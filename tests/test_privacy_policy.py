"""The privacy policy must match what the app does (Apple compares it with the App Store
privacy answers). Rewritten 2026-11-02: the old page claimed AES-256 with key rotation,
GDPR/CCPA compliance and fixed retention periods nothing enforced, and left out most of the
companies that receive data."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HTML = (ROOT / 'templates' / 'privacy-policy.html').read_text()


def test_names_the_operator_and_contact():
    assert 'Urgency LLC' in HTML and 'support@devopsagent.io' in HTML


def test_lists_every_company_the_code_sends_data_to():
    for name in ('Anthropic', 'Moonshot', 'Groq', 'Amazon Web Services', 'Cloudflare', 'Stripe',
                 'Brevo', 'Apple', 'ip-api.com', 'Google Fonts'):
        assert name in HTML, name


def test_no_claims_the_code_does_not_back():
    for phrase in ('AES-256', 'rotated regularly', 'GDPR and CCPA compliant', 'within 90 days',
                   'Regular Security Audits', '90 days for operational purposes'):
        assert phrase not in HTML, phrase


def test_policy_page_loads_and_settings_links_to_it(app):
    resp = app.test_client().get('/privacy-policy')
    assert resp.status_code == 200 and b'Urgency LLC' in resp.data
    assert 'href="/privacy-policy"' in (ROOT / 'templates' / 'settings.html').read_text()
