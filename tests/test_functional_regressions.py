"""Regression tests from the 2026-07-16 functional audit.

Covers two production bugs:
1. CostOptimization attribute mismatches (estimated_savings/detected_at vs the
   real columns potential_monthly_savings/created_at) crashed
   /api/dashboard/health-score, /api/onboarding/scan, and two scheduler tasks.
2. Built-in skills were only loaded in app.py's __main__ block (gunicorn never
   runs it) and the engine was never given the app handle, so every
   list/context method returned empty — the Skills feature was inert in prod.
"""
import pytest


def test_builtin_skills_loaded_at_import(app):
    """Skills must load when the app module is imported, not just under
    `python app.py` — production runs `gunicorn app:app`."""
    from services.skills_engine import get_skills_engine
    engine = get_skills_engine()
    assert len(type(engine)._builtin_skills) >= 5, (
        "built-in skills/*.md were not loaded at import time"
    )


def test_skills_engine_has_app_handle(app):
    """Without an app handle every engine method silently returns empty."""
    from services.skills_engine import get_skills_engine
    assert get_skills_engine()._app is not None


def test_skills_api_lists_builtin_skills(authenticated_client):
    resp = authenticated_client.get('/api/skills')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['total'] >= 5, f"expected built-in skills, got {data}"
    ids = {s['id'] for s in data['skills']}
    assert 'kubernetes-troubleshooting' in ids


def test_health_score_endpoint_returns_200(app, authenticated_client, test_user):
    """The savings sum used CostOptimization.estimated_savings (nonexistent
    column) and 500'd for every user, with or without data."""
    from models import db, CostOptimization
    with app.app_context():
        db.session.add(CostOptimization(
            user_id=test_user.id,
            recommendation_type='idle_resource',
            title='Idle test instance',
            potential_monthly_savings=120.0,
            status='pending',
        ))
        db.session.commit()

    try:
        resp = authenticated_client.get('/api/dashboard/health-score')
        assert resp.status_code == 200, resp.get_data(as_text=True)
        data = resp.get_json()
        assert 'score' in data and 'grade' in data
    finally:
        # user deletion in the test_user teardown NULLs the FK otherwise
        with app.app_context():
            CostOptimization.query.filter_by(user_id=test_user.id).delete()
            db.session.commit()


def test_cost_optimization_attribute_names():
    """Guard against the invalid attribute names creeping back in queries."""
    from models import CostOptimization
    assert hasattr(CostOptimization, 'potential_monthly_savings')
    assert hasattr(CostOptimization, 'created_at')
    assert not hasattr(CostOptimization, 'estimated_savings')
    assert not hasattr(CostOptimization, 'detected_at')
