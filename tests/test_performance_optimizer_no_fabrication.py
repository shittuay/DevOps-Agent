"""The performance-optimization dashboard must never fabricate recommendations.

`PerformanceOptimizer._get_user_recommendations()` used to auto-seed 5 hardcoded
`Recommendation` rows (literal fake resource ids like "i-0abc123def456" and
"prod-db", complete with dollar-figure savings and SLA claims) into every
user's in-memory dict the first time it was accessed — reached live via
`/optimization/` and `/optimization/recommendations` with no cloud query, no DB
read, and no sandbox-mode gate. Found by the 2026-09-10 scheduled audit; same
fabrication-bug shape as the Drift/Predictive-Scaling/Analytics incidents
CLAUDE.md's "every feature runs against a real cloud account" rule documents.

A user with no analyzed resources must see an honest empty list. Recommendations
should only ever appear after `analyze_resource()` runs against real data.
"""
from services.performance_optimizer import (
    PerformanceOptimizer, OptimizationType, ResourceType, Priority, Status,
)


def test_new_user_has_no_recommendations():
    optimizer = PerformanceOptimizer()
    assert optimizer.get_recommendations(user_id=1) == []


def test_new_user_summary_is_empty_not_fabricated():
    optimizer = PerformanceOptimizer()
    summary = optimizer.get_summary(user_id=1)
    assert summary["total_recommendations"] == 0
    assert summary["potential_monthly_savings"] == 0.0
    assert summary["pending_count"] == 0


def test_no_hardcoded_resource_ids_leak_into_any_user():
    """Guards against reintroducing the literal sample resource ids."""
    optimizer = PerformanceOptimizer()
    for uid in (1, 2, 42):
        recs = optimizer.get_recommendations(uid)
        ids = {r["resource_id"] for r in recs}
        assert "i-0abc123def456" not in ids
        assert "prod-db" not in ids
        assert recs == []


def test_recommendations_only_appear_after_real_analysis():
    """analyze_resource() with real data is the only path that should populate rows."""
    optimizer = PerformanceOptimizer()
    assert optimizer.get_recommendations(user_id=1) == []

    result = optimizer.analyze_resource(
        user_id=1,
        resource_type=ResourceType.EC2_INSTANCE,
        resource_data={"instance_id": "i-real123", "avg_cpu_percent": 2.0},
    )
    assert result.recommendations, "a genuinely underutilized instance should produce a finding"

    recs = optimizer.get_recommendations(user_id=1)
    assert len(recs) == 1
    assert recs[0]["resource_id"] == "i-real123"


def test_dismiss_and_get_recommendation_on_empty_user_return_not_found():
    optimizer = PerformanceOptimizer()
    assert optimizer.get_recommendation(user_id=1, rec_id="rec-001") is None
    assert optimizer.dismiss_recommendation(user_id=1, rec_id="rec-001") is False
    assert optimizer.update_recommendation_status(user_id=1, rec_id="rec-001", status=Status.DISMISSED) is False
