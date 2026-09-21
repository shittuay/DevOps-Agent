"""
Performance Optimizer Service Tests

Guards against the service ever fabricating recommendations again — see
CLAUDE.md's "every feature runs against a real cloud account" rule. The
service previously seeded five hardcoded fake resources (byte-identical for
every user, e.g. resource_id="i-0abc123def456") via an auto-triggered
_generate_sample_recommendations(); fixed by removing the fabrication
entirely and requiring recommendations to come from analyze_resource() with
real resource data.
"""

from services.performance_optimizer import (
    PerformanceOptimizer, OptimizationType, ResourceType,
)


class TestNoFabricatedData:
    """A fresh service instance must never invent recommendations."""

    def test_get_recommendations_empty_for_unknown_user(self):
        optimizer = PerformanceOptimizer()
        assert optimizer.get_recommendations(user_id=1) == []

    def test_get_summary_reports_zero_for_unknown_user(self):
        optimizer = PerformanceOptimizer()
        summary = optimizer.get_summary(user_id=1)
        assert summary['total_recommendations'] == 0
        assert summary['pending_count'] == 0
        assert summary['critical_count'] == 0
        assert summary['potential_monthly_savings'] == 0.0

    def test_no_sample_data_method_remains(self):
        optimizer = PerformanceOptimizer()
        assert not hasattr(optimizer, '_generate_sample_recommendations')

    def test_no_hardcoded_fake_resource_ids_leak_into_a_fresh_users_recommendations(self):
        optimizer = PerformanceOptimizer()
        # Regression guard for the specific fabricated ids this bug shipped.
        recs = optimizer.get_recommendations(user_id=1)
        resource_ids = {r.get('resource_id') for r in recs}
        fabricated_ids = {
            'i-0abc123def456', 'prod-db', 'default/api-service',
            'vol-0xyz789', 'data-archive',
        }
        assert not (resource_ids & fabricated_ids)
        assert recs == []

    def test_two_separate_users_both_start_empty(self):
        optimizer = PerformanceOptimizer()
        assert optimizer.get_recommendations(user_id=1) == []
        assert optimizer.get_recommendations(user_id=2) == []


class TestRealDataStillProducesRecommendations:
    """Once analyze_resource() is fed real data, recommendations work."""

    def test_analyze_resource_with_real_underutilized_ec2_produces_a_recommendation(self):
        optimizer = PerformanceOptimizer()
        result = optimizer.analyze_resource(
            user_id=7,
            resource_type=ResourceType.EC2_INSTANCE,
            resource_data={
                'instance_id': 'i-real0001',
                'instance_type': 't3.large',
                'avg_cpu_percent': 2.0,
            },
        )
        assert len(result.recommendations) == 1
        assert result.recommendations[0].resource_id == 'i-real0001'
        assert result.recommendations[0].optimization_type == OptimizationType.COST

        # And it's now visible in this user's (only this user's) recommendations.
        recs = optimizer.get_recommendations(user_id=7)
        assert len(recs) == 1
        assert recs[0]['resource_id'] == 'i-real0001'
        assert optimizer.get_recommendations(user_id=8) == []
