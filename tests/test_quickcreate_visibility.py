
def test_settings_shows_quickcreate(authenticated_client):
    html = authenticated_client.get('/settings').data.decode()
    assert 'openCfQuickCreate' in html, 'quick-create JS missing'
    assert 'Create role with CloudFormation' in html, 'button missing'
    assert html.count('Create role with CloudFormation') == 1
    assert 'modeRoleArn' in html

def test_onboarding_shows_quickcreate(authenticated_client):
    html = authenticated_client.get('/onboarding').data.decode()
    assert 'Create role with CloudFormation' in html
    assert 'Start in sandbox' in html
