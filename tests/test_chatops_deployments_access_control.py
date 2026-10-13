"""Regression test: ChatOps `/deployments` disclosed platform-wide webhook
data to any chat user with no auth check at all.

Found during a scheduled security review (2026-09-24). `WebhookEventRecord`
(models.py) has no `user_id` column — it's a single platform-wide table of
CI/CD webhook events, and every other reader of it
(`routes/webhooks.py`'s `webhooks_dashboard()` and `api_list_events()`) is
gated `@login_required` + `@admin_required`. `services/chatops_service.py`'s
`_cmd_deployments` was the one handler in the file that never called
`_require_app_user()` at all — unlike every sibling per-user command
(`_cmd_status`, `_cmd_incidents`, `_cmd_metrics`, ...) — so any Slack/Teams
user who could message the bot, linked to an app account or not, could read
every tenant's CI/CD deployment history (repository, branch, commit SHA,
actor, status) with zero authentication.

Fixed by requiring a resolved app user AND mirroring the web dashboard's
admin-only gate, since the underlying data was never partitioned per user in
the first place.
"""
import pytest

from services.chatops_service import get_chatops_service, ChatPlatform, _UnresolvedAppUser


def test_deployments_command_refuses_unlinked_identity():
    service = get_chatops_service()
    response = service.process_message(
        'deployments', user_id='slack-U-unlinked-deployments', platform=ChatPlatform.SLACK
    )
    assert 'link' in response.text.lower()


def test_deployments_command_refuses_non_admin_app_user(app, test_user):
    assert test_user.role != 'admin'
    service = get_chatops_service()
    response = service._cmd_deployments([], app_user_id=test_user.id)

    assert 'admin' in response.text.lower()


def test_deployments_command_raises_without_app_user_id():
    service = get_chatops_service()
    with pytest.raises(_UnresolvedAppUser):
        service._cmd_deployments([])


def test_deployments_command_allows_admin_app_user(app, test_user, db_session):
    from models import db

    test_user.role = 'admin'
    db.session.commit()

    service = get_chatops_service()
    response = service._cmd_deployments([], app_user_id=test_user.id)

    # Must not be turned away by the admin gate; content is either the
    # "no deployments" message or a real listing, never the refusal text.
    assert 'admin-only' not in response.text.lower()


def test_requires_auth_is_enforced_before_dispatch(app):
    """A requires_auth command whose handler forgets _require_app_user() must
    still be refused for an unlinked identity, without the handler running."""
    from services.chatops_service import ChatCommand, ChatOpsService

    called = []
    service = ChatOpsService()
    service.register_command(ChatCommand(
        name='forgetful', description='test', usage='/forgetful',
        handler=lambda args, **kw: called.append(kw) or None,
    ))

    response = service.process_message(
        'forgetful', user_id='slack-U-unlinked-forgetful', platform=ChatPlatform.SLACK
    )

    assert called == []
    assert 'link' in response.text.lower()
