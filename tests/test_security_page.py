"""The /security trust page must stay public and keep its core claims linked."""


def test_security_page_is_public(client):
    resp = client.get('/security')
    assert resp.status_code == 200


def test_security_page_links_auditable_policies(client):
    html = client.get('/security').data.decode()
    assert '/static/iam/devops-agent-readonly.json' in html
    assert '/static/iam/devops-agent-management.json' in html
    assert 'never need your access keys' in html
    assert 'sandbox' in html.lower()
