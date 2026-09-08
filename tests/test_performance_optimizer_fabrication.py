"""Regression test: PerformanceOptimizer must not fabricate recommendations
for a real (non-sandbox) user.

Found by a scheduled audit (2026-09-08): `_get_user_recommendations()`
unconditionally called `_generate_sample_recommendations()` — hardcoded
"critical" findings against literal resource ids (`i-0abc123def456`, `prod-db`)
identical for every user, with no cloud-credential check and no sandbox_mode
check — the same bug class already fixed once each in drift_detection.py and
predictive_scaling.py (see CLAUDE.md's "every feature runs against a real
cloud account" rule). A real user could even click "Implement" on a fabricated
recommendation and get a fake success with no AWS API call ever made.

Fixed by gating sample generation behind `UserPreferences.sandbox_mode`
(explicit, user-enabled, labelled [Sandbox] — the one documented exception),
so a user with no sandbox mode and no real analysis yet sees an empty,
honest "no recommendations" state instead of canned data.
"""
import pytest


def _get_optimizer():
    from services.performance_optimizer import get_performance_optimizer, PerformanceOptimizer
    import services.performance_optimizer as mod
    # Use a fresh instance per test — the module-level singleton persists
    # fabricated state across tests/users otherwise.
    mod._optimizer = PerformanceOptimizer()
    return get_performance_optimizer()


class TestNoFabricationWithoutSandboxMode:
    def test_real_user_gets_no_fabricated_recommendations(self, app, test_user, db_session):
        optimizer = _get_optimizer()
        recs = optimizer.get_recommendations(test_user.id)
        assert recs == []

    def test_real_user_summary_is_honest_zero_not_fake_data(self, app, test_user, db_session):
        optimizer = _get_optimizer()
        summary = optimizer.get_summary(test_user.id)
        assert summary['total_recommendations'] == 0
        assert summary['critical_count'] == 0
        assert summary['potential_monthly_savings'] == 0.0

    def test_sandbox_mode_user_gets_labelled_sample_data(self, app, test_user, db_session):
        from models import UserPreferences, db
        prefs = UserPreferences(user_id=test_user.id, sandbox_mode=True)
        db.session.add(prefs)
        db.session.commit()

        optimizer = _get_optimizer()
        recs = optimizer.get_recommendations(test_user.id)
        assert len(recs) > 0
        for rec in recs:
            assert rec['title'].startswith('[Sandbox]')
            assert rec['metadata'].get('simulated') is True

    def test_real_analysis_still_populates_recommendations(self, app, test_user, db_session):
        # analyze_resource() is the real-data path (fed by an actual cloud
        # read elsewhere) and must keep working regardless of sandbox_mode.
        from services.performance_optimizer import ResourceType
        optimizer = _get_optimizer()
        optimizer.analyze_resource(test_user.id, ResourceType.EC2_INSTANCE, {
            'instance_id': 'i-real123', 'avg_cpu_percent': 3.0, 'instance_type': 't3.large',
        })
        recs = optimizer.get_recommendations(test_user.id)
        assert any(not r['title'].startswith('[Sandbox]') for r in recs)
