"""Fixes from a live EKS-cluster session (2026-10-19).

1. "Cluster creation is now in progress. The state is CREATING" was reported with
   nothing run. The reply was to "This the role : AmazonEKSAutoClusterRole", which has
   no action verb, and the claim wording wasn't recognised either.
2. The app's own "_[Executing tool...]_" markers were replayed in history; the model
   copied them and the strong check replaced real answers with a stock line.
3. The streaming path compared a bool to 'strong'/'weak', so its check never fired.
4. A read-level role meant seven one-at-a-time permission requests for one cluster.
5. The free plan's chat limit showed as "Error: Rate limit exceeded. 10 per 1 hour".
"""
import pytest

from src.agent import core
from services import aws_permissions as ap

LIE = ("Cluster creation is now in progress. The state is CREATING — this typically "
       "takes 10-15 minutes for the control plane to become ACTIVE.")


def _conv(*user_turns):
    msgs = []
    for text in user_turns:
        msgs.append({'role': 'user', 'content': text})
        msgs.append({'role': 'assistant', 'content': 'ok'})
    return msgs[:-1]


# --- 1. in-progress claims and follow-ups -----------------------------------------

def test_in_progress_wording_is_a_create_claim():
    assert core._fabricated_action_claim('create the eks cluster', LIE, [])
    assert core._fabricated_action_claim('create it', 'dev-eks is now provisioning.', [])
    assert not core._fabricated_action_claim('create it', LIE, ['aws_api_write'])


def test_in_progress_denial_is_not_a_claim():
    assert not core._fabricated_action_claim(
        'create the cluster', 'Creation has not started: it is waiting for your approval.', [])


def test_in_progress_delete_claim():
    assert core._fabricated_action_claim('delete the cluster', 'Deletion is now in progress.', [])


def test_followup_without_verb_is_checked_against_earlier_messages():
    msgs = _conv('Now try to create the cluster', 'This the role : AmazonEKSAutoClusterRole')
    assert not core._fabricated_action_claim(core._latest_user_text(msgs), LIE, [])
    assert core._unverified_followup_claim(msgs, LIE, [])
    assert not core._unverified_followup_claim(msgs, LIE, ['create_eks_cluster'])
    assert not core._unverified_followup_claim(msgs, LIE, [], sandbox_mode=True)


@pytest.mark.parametrize('current', ['what is the status?', 'show me the cluster', 'is it ready?'])
def test_followup_questions_are_not_checked(current):
    assert not core._unverified_followup_claim(_conv('create the cluster', current), LIE, [])


def test_followup_with_no_earlier_action_is_not_checked():
    assert not core._unverified_followup_claim(_conv('list my vpcs', 'okay'), LIE, [])


def test_followup_only_looks_back_a_few_turns():
    msgs = _conv('create the cluster', 'a', 'b', 'c', 'okay')
    assert not core._unverified_followup_claim(msgs, LIE, [])


def test_followup_note_is_appended_not_replacing_on_both_kimi_paths():
    with open('src/agent/core.py', encoding='utf-8') as f:
        src = f.read()
    assert src.count('if _unverified_followup_claim(') == 2
    # definition + 2 Kimi sites + 2 Claude sites
    assert src.count('_UNVERIFIED_ACTION_NOTE') == 5


# --- Claude paths (no check at all before 2026-10-19) ---------------------------------

def _claude_conv(*turns):
    """Anthropic-format history: tool results are user messages with no text."""
    msgs = []
    for text in turns:
        msgs.append({'role': 'user', 'content': [{'type': 'text', 'text': text}]})
        msgs.append({'role': 'assistant', 'content': [{'type': 'tool_use', 'id': 't', 'name': 'x', 'input': {}}]})
        msgs.append({'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 't', 'content': '{}'}]})
    return msgs


def test_latest_user_text_skips_tool_results():
    assert core._latest_user_text(_claude_conv('list vpcs', 'create the cluster')) == 'create the cluster'


def test_claude_verdict():
    assert core._action_claim_verdict(_claude_conv('create the cluster'), LIE, []) == 'replace'
    assert core._action_claim_verdict(_claude_conv('create the cluster', 'okay'), LIE, []) == 'note'
    assert core._action_claim_verdict(_claude_conv('create the cluster'), LIE, ['create_eks_cluster']) == ''
    assert core._action_claim_verdict(_claude_conv('create the cluster'), LIE, [], sandbox_mode=True) == ''


def test_claude_paths_are_wired():
    with open('src/agent/core.py', encoding='utf-8') as f:
        src = f.read()
    assert src.count('_action_claim_verdict(') == 3  # definition + non-streaming + streaming


def test_prompt_rules_out_invented_iam_arns():
    assert 'never build one from a policy path' in core.STABLE_SYSTEM_PROMPT
    assert 'never arn:aws:iam::...:cluster/' in core.STABLE_SYSTEM_PROMPT


# --- 2/3. markers in history, streaming check ---------------------------------------

def test_app_markers_are_stripped_from_replayed_history():
    saved = "Checking.\n\n_[Executing tool...]_\n\nCluster is ACTIVE."
    stripped = core._strip_system_markers(saved)
    assert '[Executing tool' not in stripped and 'Cluster is ACTIVE.' in stripped
    assert not any(p.search(stripped) for p in core._STRONG_HALLUCINATION_PATTERNS)


def test_both_history_loaders_strip_markers():
    with open('src/agent/core.py', encoding='utf-8') as f:
        src = f.read()
    assert src.count("_strip_system_markers(msg.get('content', ''))") == 2


def test_streaming_check_uses_severity_not_bool():
    with open('src/agent/core.py', encoding='utf-8') as f:
        src = f.read()
    assert 'severity = _check_hallucination(' not in src


# --- 4. access-level hint -------------------------------------------------------------

@pytest.fixture
def clean_requests(app, db_session):
    from models import ApprovalRequest, db
    yield
    db.session.rollback()
    ApprovalRequest.query.filter_by(tool_name=ap.PERMISSION_TOOL).delete(synchronize_session=False)
    db.session.commit()


def _file(user_id, action):
    from services.approval_service import create_request
    return create_request(tool_name=ap.PERMISSION_TOOL, tool_input={'action': action, 'mode': 'manual'},
                          risk_level='high', risk_reason='x', requester_id=user_id)


def test_no_hint_for_a_single_write_or_reads(test_user, clean_requests):
    _file(test_user.id, 'eks:CreateCluster')
    _file(test_user.id, 'eks:DescribeCluster')
    _file(test_user.id, 'ec2:ListThings')
    assert ap.access_level_hint(test_user.id) is None


def test_hint_after_second_write_names_manage(test_user, clean_requests):
    _file(test_user.id, 'eks:CreateCluster')
    req = _file(test_user.id, 'iam:PassRole')
    hint = ap.access_level_hint(test_user.id)
    assert hint and 'Manage' in hint and 'PolicyLevel' in hint
    assert 'eks:CreateCluster' in hint and 'iam:PassRole' in hint
    assert ap.model_note(req)['access_level_hint'] == hint


# --- 5. chat rate limit ------------------------------------------------------------------

def test_chat_rate_limit_message_is_plain():
    import app as app_module
    msg = app_module._chat_rate_limit_message('10 per 1 hour', 1500)
    assert msg.startswith("You've reached your plan's limit of 10 messages per hour")
    assert 'about 25 minute(s)' in msg
    assert 'later this hour' in app_module._chat_rate_limit_message('10 per 1 hour', None)


def test_chat_page_does_not_prefix_429_with_error():
    with open('templates/index.html', encoding='utf-8') as f:
        page = f.read()
    assert page.count('status === 429 ?') == 2
