"""Regression tests: viewing a playbook's edit page must not break toggling it.

edit_playbook() serialized a playbook's actions into dicts and assigned them
back onto the object returned by get_playbook() — the SHARED cached instance.
That corrupted it in place, so any later toggle/save hit
`'dict' object has no attribute 'action_type'` and 500'd until restart.

Two fixes are guarded:
  1. edit_playbook renders on a COPY, never overwriting the cached .actions.
  2. _save_playbook_to_db tolerates dict actions (defensive, the crash site).
"""
from services.incident_response import get_incident_engine, RemediationAction


def test_get_playbook_returns_object_actions(app, test_user):
    """Invariant: get_playbook hands back RemediationAction objects. Runs in the
    engine's in-memory mode (no DB write) and restores the singleton so the
    shared engine state isn't polluted for other tests."""
    eng = get_incident_engine()
    saved_app = eng._app
    try:
        eng._app = None  # in-memory: no DB write-through, no cross-test pollution
        eng._users_loaded.discard(test_user.id)
        eng._user_playbooks.pop(test_user.id, None)
        eng._ensure_user_loaded(test_user.id)
        pb = eng.get_playbook(test_user.id, 'high-cpu-usage')
        assert pb is not None
        assert pb.actions and all(isinstance(a, RemediationAction) for a in pb.actions)
        # toggling flips enabled and comes back cleanly (no dict crash)
        first = eng.toggle_playbook(test_user.id, 'high-cpu-usage')
        assert isinstance(first, bool)
        assert eng.toggle_playbook(test_user.id, 'high-cpu-usage') is (not first)
    finally:
        eng._app = saved_app
        eng._users_loaded.discard(test_user.id)
        eng._user_playbooks.pop(test_user.id, None)


def test_edit_playbook_does_not_mutate_shared_actions():
    """The bug was `playbook.actions = serialized_actions` on the cached object.
    (Negative lookbehind so the fixed `render_playbook.actions = ...` is allowed.)"""
    import re
    src = open('routes/incidents.py').read()
    assert not re.search(r'(?<!_)playbook\.actions = serialized_actions', src), \
        "edit_playbook must not overwrite the shared cached playbook's actions"
    assert 'render_playbook' in src, "edit_playbook should render a copy, not the cached object"


def test_save_playbook_tolerates_dict_actions():
    """_save_playbook_to_db must handle dict-shaped actions, not just objects."""
    src = open('services/incident_response.py').read()
    assert 'isinstance(a, dict)' in src, \
        "_save_playbook_to_db should defensively handle dict actions"
