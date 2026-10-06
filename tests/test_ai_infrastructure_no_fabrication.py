from services.ai_infrastructure import AIInfrastructureService


def test_recommendations_empty_without_live_data():
    svc = AIInfrastructureService(1)
    assert svc.get_recommendations(1) == []
    assert svc.get_optimization_suggestions('cost') == []


def test_apply_never_reports_success():
    result = AIInfrastructureService(1).apply_recommendation('rec_1', 1)
    assert result['success'] is False
    assert result['not_implemented'] is True
