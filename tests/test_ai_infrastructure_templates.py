"""Tests for the AI Infrastructure Templates feature.

Covers the bugs that made it non-functional scaffolding: create_template wrote a
non-existent `specification` column, api_templates read non-existent attributes
(provider/complexity/estimated_cost), preview_template did not exist, and there
was no public starter catalog.
"""
import pytest

from services.ai_infrastructure import (
    AIInfrastructureService,
    seed_public_templates,
)
from services.starter_templates import STARTER_TEMPLATES


@pytest.fixture(autouse=True)
def _cleanup_templates(app):
    """The test DB is session-scoped and shared; these tests commit rows, so
    delete them (and the seeded system user) after each test — otherwise
    leftover rows/broken session state poison later tests in the suite."""
    yield
    from models import db, InfrastructureTemplate, User
    db.session.rollback()  # clear any failed-transaction state first
    try:
        InfrastructureTemplate.query.delete()
        sysu = User.query.filter_by(email='system@devopsagent.io').first()
        if sysu:
            db.session.delete(sysu)
        db.session.commit()
    except Exception:
        db.session.rollback()


@pytest.fixture
def svc(app):
    return AIInfrastructureService(user_id=1)


def test_seed_public_templates_is_idempotent(app, db_session):
    first = seed_public_templates()
    assert first == len(STARTER_TEMPLATES)
    # A second run adds nothing.
    assert seed_public_templates() == 0
    publics = AIInfrastructureService().get_public_templates()
    assert len(publics) == len(STARTER_TEMPLATES)


def test_create_template_writes_real_columns(app, db_session, svc):
    t = svc.create_template(
        user_id=1, name='My VPC', description='desc',
        category='networking', cloud_provider='aws',
        template_content='provider "aws" {}', variables=[{'name': 'region'}],
        estimated_monthly_cost=12.5,
    )
    assert t.id is not None
    assert t.template_content == 'provider "aws" {}'
    assert t.estimated_monthly_cost == 12.5
    assert t.variables == [{'name': 'region'}]


def test_template_to_dict_canonical_shape(app, db_session, svc):
    t = svc.create_template(user_id=1, name='X', cloud_provider='aws',
                            estimated_monthly_cost=5.0)
    d = AIInfrastructureService.template_to_dict(t)
    assert d['estimated_cost'] == 5.0           # mapped from estimated_monthly_cost
    assert d['cloud_provider'] == 'aws'
    assert set(['id', 'name', 'template_content', 'variables', 'is_public']) <= set(d)


def test_api_templates_returns_public_without_500(authenticated_client, db_session):
    seed_public_templates()
    resp = authenticated_client.get('/ai/api/templates')
    assert resp.status_code == 200
    names = [t['name'] for t in resp.get_json()['templates']]
    assert 'AWS 3-Tier VPC' in names


def test_preview_substitutes_vars_but_not_terraform_interp(app, db_session, svc):
    t = svc.create_template(
        user_id=1, name='P', cloud_provider='aws',
        template_content='region = "${region}"\nidx = ${count.index}',
        variables=[{'name': 'region', 'default': 'us-east-1'}],
    )
    out = svc.preview_template(t.id, {'region': 'eu-west-1'})
    assert 'region = "eu-west-1"' in out['rendered']
    # Terraform's own interpolation must survive untouched.
    assert '${count.index}' in out['rendered']


def test_preview_blocked_for_private_template_of_another_user(app, db_session, svc):
    """Regression: preview_template() must not render another user's private
    template. It called self.get_template(template_id) with no ownership
    check at all (sibling routes template_detail/api_template_clone do check
    `template.is_public or template.user_id == current_user.id`), so any
    logged-in user could POST /ai/api/templates/<guessed_id>/preview and get
    back the fully-rendered template_content of another user's private
    saved infrastructure template -- an IDOR."""
    victim = svc.create_template(
        user_id=999, name='Victim', cloud_provider='aws',
        template_content='secret_host = "internal.example.com"',
        is_public=False,
    )
    out = svc.preview_template(victim.id)
    assert 'error' in out
    assert 'rendered' not in out


def test_clone_creates_private_user_copy(app, db_session, svc):
    src = svc.create_template(user_id=999, name='Src', cloud_provider='aws',
                              template_content='x', is_public=True)
    clone = svc.clone_template(src.id, user_id=1)
    assert clone.user_id == 1
    assert clone.is_public is False
    assert 'copy' in clone.name.lower()
    assert clone.template_content == 'x'
