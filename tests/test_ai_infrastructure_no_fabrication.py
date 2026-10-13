from services.ai_infrastructure import AIInfrastructureService


def test_recommendations_are_never_fabricated():
    svc = AIInfrastructureService(1)
    assert svc.get_recommendations(1) == []


def test_apply_never_reports_success():
    result = AIInfrastructureService(1).apply_recommendation('rec_1', 1)
    assert result['success'] is False
    assert 'not yet implemented' in result['error']
