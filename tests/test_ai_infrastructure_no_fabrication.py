"""
AI Infrastructure Service — recommendations no longer fabricated.

`AIInfrastructureService.get_recommendations()` used to return four hardcoded
recommendations (EC2 right-sizing, S3 encryption, RDS read replicas, Multi-AZ)
unconditionally, ignoring `user_id` entirely and identical for every user
regardless of what — if anything — was in their account. `apply_recommendation()`
reported `success: True` for any known id with no cloud API call ever made.

Same fabricated-data / fake-Apply bug class as Drift, Predictive Scaling,
Analytics, ChatOps, and Performance Optimizer — see CLAUDE.md's "Non-negotiable"
section and CLAUDE_RUNBOOK.md's 2026-09-26 scheduled-audit entry. Fixed the
same way: fail closed (empty list, honest apply failure) rather than fabricate.
"""

from services.ai_infrastructure import AIInfrastructureService


class TestNoFabricatedRecommendations:
    def test_get_recommendations_empty_for_any_user(self):
        service = AIInfrastructureService(user_id=1)
        assert service.get_recommendations(user_id=1) == []

    def test_two_separate_users_both_start_empty(self):
        assert AIInfrastructureService(user_id=1).get_recommendations(1) == []
        assert AIInfrastructureService(user_id=2).get_recommendations(2) == []

    def test_no_hardcoded_recommendation_ids_remain(self):
        service = AIInfrastructureService(user_id=1)
        recs = service.get_recommendations(user_id=1)
        rec_ids = {r.get('id') for r in recs}
        assert not (rec_ids & {'rec_1', 'rec_2', 'rec_3', 'rec_4'})
        assert recs == []

    def test_apply_recommendation_reports_failure_not_fake_success(self):
        service = AIInfrastructureService(user_id=1)
        result = service.apply_recommendation('rec_1', user_id=1)
        assert result['success'] is False
        assert 'not' in result['error'].lower()

    def test_apply_recommendation_is_not_found_not_generic_501(self):
        """No recommendation exists yet (get_recommendations() is empty), so an
        id that doesn't exist must report 'not found' (-> 404 at the route),
        matching routes/scaling.py's 404-before-501 shape — not the same
        catch-all 'not yet implemented' message a real match would eventually
        get once live data is wired in."""
        service = AIInfrastructureService(user_id=1)
        result = service.apply_recommendation('does-not-exist', user_id=1)
        assert result == {'success': False, 'error': 'Recommendation not found'}

    def test_dismiss_recommendation_has_nothing_real_to_dismiss(self):
        service = AIInfrastructureService(user_id=1)
        assert service.dismiss_recommendation('rec_1') is False

    def test_optimization_suggestions_empty(self):
        service = AIInfrastructureService(user_id=1)
        assert service.get_optimization_suggestions('cost') == []
