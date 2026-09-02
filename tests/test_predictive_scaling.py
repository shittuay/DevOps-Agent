"""
Predictive Scaling Service Tests

Guards against the service ever fabricating resources or metrics again — see
CLAUDE.md's "every feature runs against a real cloud account" rule. The
service previously seeded three hardcoded fake resources (byte-identical for
every user) via an auto-triggered _ensure_sample_data()/_load_sample_data();
fixed by removing the fabrication entirely and requiring resources/metrics to
be registered explicitly via register_resource()/add_metric().
"""

from services.predictive_scaling import (
    PredictiveScalingService, ResourceCategory, ScalingDirection,
)


class TestNoFabricatedData:
    """A fresh service instance must never invent resources or predictions."""

    def test_generate_all_predictions_empty_for_unknown_user(self):
        service = PredictiveScalingService()
        assert service.generate_all_predictions(user_id=1) == []

    def test_get_summary_reports_zero_for_unknown_user(self):
        service = PredictiveScalingService()
        summary = service.get_summary(user_id=1)
        assert summary['total_predictions'] == 0
        assert summary['resources_analyzed'] == 0

    def test_analyze_patterns_returns_none_with_no_real_data(self):
        service = PredictiveScalingService()
        assert service.analyze_patterns(user_id=1, resource_id='anything') is None

    def test_no_sample_data_methods_remain(self):
        service = PredictiveScalingService()
        assert not hasattr(service, '_ensure_sample_data')
        assert not hasattr(service, '_load_sample_data')

    def test_no_hardcoded_fake_resource_ids_leak_into_a_fresh_users_metrics(self):
        service = PredictiveScalingService()
        # Regression guard for the specific fabricated ids this bug shipped:
        # 'web-server-1', 'prod-database', 'api-deployment'.
        assert service.metrics[1] == {}


class TestRealDataStillProducesPredictions:
    """Once a real metrics source registers a resource, predictions work."""

    def test_scale_up_recommended_for_sustained_high_utilization(self):
        service = PredictiveScalingService()
        service.register_resource(
            user_id=7, resource_id='i-real123', name='real-web-server',
            resource_type='EC2 Instance', category=ResourceCategory.COMPUTE,
            current_capacity=2, max_capacity=8,
        )
        from datetime import datetime, timedelta
        now = datetime.utcnow()
        for i in range(200):
            service.add_metric(7, 'i-real123', 90.0, now - timedelta(hours=200 - i))

        predictions = service.generate_all_predictions(7)
        assert len(predictions) == 1
        assert predictions[0].resource_name == 'real-web-server'
        assert predictions[0].direction == ScalingDirection.SCALE_UP

    def test_predictions_are_isolated_per_user(self):
        service = PredictiveScalingService()
        service.register_resource(
            user_id=1, resource_id='r1', name='user-1-resource',
            resource_type='EC2 Instance', category=ResourceCategory.COMPUTE,
            current_capacity=1, max_capacity=4,
        )
        from datetime import datetime, timedelta
        now = datetime.utcnow()
        for i in range(200):
            service.add_metric(1, 'r1', 90.0, now - timedelta(hours=200 - i))

        # A different user with no registered resources gets nothing.
        assert service.generate_all_predictions(2) == []
        assert len(service.generate_all_predictions(1)) == 1
