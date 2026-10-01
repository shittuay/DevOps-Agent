"""
Marketing agent routes: admin-only prospect discovery, draft generation and
the human approval queue, plus the public unsubscribe link.
"""

import logging

from flask import Blueprint, jsonify, render_template, request
from flask_login import current_user, login_required

from models import db, MarketingDraft, MarketingProspect
from services import marketing_agent as ma
from services.rbac import admin_required
from src.utils.timeutils import utcnow

logger = logging.getLogger(__name__)

marketing_bp = Blueprint('marketing', __name__, url_prefix='/marketing')


@marketing_bp.route('/')
@login_required
@admin_required
def dashboard():
    return render_template('admin/marketing.html', channels=ma.CHANNELS,
                           default_queries=ma.DEFAULT_QUERIES, facts=ma.PRODUCT_FACTS)


@marketing_bp.route('/api/stats')
@login_required
@admin_required
def api_stats():
    def count(model, **kw):
        return model.query.filter_by(**kw).count()
    return jsonify({
        'prospects_new': count(MarketingProspect, status='new'),
        'prospects_total': MarketingProspect.query.count(),
        'drafts_pending': count(MarketingDraft, status='pending'),
        'drafts_approved': count(MarketingDraft, status='approved'),
        'emails_sent': count(MarketingDraft, status='sent'),
        'daily_email_cap': ma.daily_email_cap(),
    })


@marketing_bp.route('/api/discover', methods=['POST'])
@login_required
@admin_required
def api_discover():
    data = request.get_json(silent=True) or {}
    queries = data.get('queries')
    if isinstance(queries, str):
        queries = [q for q in queries.splitlines()]
    try:
        min_score = int(data.get('min_score', 5))
    except (TypeError, ValueError):
        min_score = 5
    result = ma.discover_prospects(queries=queries, sources=data.get('sources'), min_score=min_score)
    return jsonify(result)


@marketing_bp.route('/api/prospects')
@login_required
@admin_required
def api_prospects():
    status = request.args.get('status')
    q = MarketingProspect.query
    if status:
        q = q.filter_by(status=status)
    rows = q.order_by(MarketingProspect.score.desc(), MarketingProspect.created_at.desc()).limit(200).all()
    return jsonify({'prospects': [p.to_dict() for p in rows]})


@marketing_bp.route('/api/prospects/<int:prospect_id>/status', methods=['PUT'])
@login_required
@admin_required
def api_prospect_status(prospect_id):
    prospect = MarketingProspect.query.get_or_404(prospect_id)
    status = (request.get_json(silent=True) or {}).get('status')
    if status not in ('new', 'drafted', 'contacted', 'ignored'):
        return jsonify({'error': 'Invalid status'}), 400
    prospect.status = status
    db.session.commit()
    return jsonify(prospect.to_dict())


@marketing_bp.route('/api/drafts', methods=['GET'])
@login_required
@admin_required
def api_drafts():
    status = request.args.get('status')
    q = MarketingDraft.query
    if status:
        q = q.filter_by(status=status)
    rows = q.order_by(MarketingDraft.created_at.desc()).limit(200).all()
    return jsonify({'drafts': [d.to_dict() for d in rows]})


@marketing_bp.route('/api/drafts', methods=['POST'])
@login_required
@admin_required
def api_generate_draft():
    data = request.get_json(silent=True) or {}
    try:
        draft = ma.generate_draft(
            channel=data.get('channel', ''),
            created_by=current_user.id,
            topic=data.get('topic'),
            prospect_id=data.get('prospect_id'),
            recipient_email=data.get('recipient_email') or None,
        )
    except ma.MarketingAgentError as e:
        return jsonify({'error': str(e)}), 400
    return jsonify(draft.to_dict()), 201


@marketing_bp.route('/api/drafts/<int:draft_id>', methods=['PUT'])
@login_required
@admin_required
def api_edit_draft(draft_id):
    draft = MarketingDraft.query.get_or_404(draft_id)
    if draft.status == 'sent':
        return jsonify({'error': 'Sent drafts cannot be edited'}), 400
    data = request.get_json(silent=True) or {}
    if 'body' in data:
        draft.body = str(data['body'])
    if 'subject' in data:
        draft.subject = str(data['subject'])[:300] or None
    if 'recipient_email' in data:
        try:
            draft.recipient_email = ma.normalize_email(data['recipient_email']) if data['recipient_email'] else None
        except ma.MarketingAgentError as e:
            return jsonify({'error': str(e)}), 400
    draft.compliance_issues = ma.check_compliance(draft.channel, draft.body)
    draft.status = 'pending'  # any edit needs a fresh review
    db.session.commit()
    return jsonify(draft.to_dict())


@marketing_bp.route('/api/drafts/<int:draft_id>/review', methods=['POST'])
@login_required
@admin_required
def api_review_draft(draft_id):
    draft = MarketingDraft.query.get_or_404(draft_id)
    data = request.get_json(silent=True) or {}
    decision = data.get('decision')
    if decision not in ('approve', 'reject'):
        return jsonify({'error': "decision must be 'approve' or 'reject'"}), 400
    if draft.status not in ('pending', 'approved', 'rejected'):
        return jsonify({'error': f'Cannot review a {draft.status} draft'}), 400
    if decision == 'approve' and draft.compliance_issues and not data.get('acknowledge_issues'):
        return jsonify({'error': 'Draft has compliance issues; fix them or acknowledge them explicitly',
                        'compliance_issues': draft.compliance_issues}), 409
    draft.status = 'approved' if decision == 'approve' else 'rejected'
    draft.reviewed_by = current_user.id
    draft.reviewed_at = utcnow()
    db.session.commit()
    return jsonify(draft.to_dict())


@marketing_bp.route('/api/drafts/<int:draft_id>/send', methods=['POST'])
@login_required
@admin_required
def api_send_draft(draft_id):
    draft = MarketingDraft.query.get_or_404(draft_id)
    try:
        ma.send_approved_email(draft, sender_id=current_user.id)
    except ma.MarketingAgentError as e:
        return jsonify({'error': str(e), 'draft': draft.to_dict()}), 400
    return jsonify(draft.to_dict())


@marketing_bp.route('/api/drafts/<int:draft_id>/mark-posted', methods=['POST'])
@login_required
@admin_required
def api_mark_posted(draft_id):
    """Record that a person posted an approved non-email draft by hand."""
    draft = MarketingDraft.query.get_or_404(draft_id)
    if draft.status != 'approved':
        return jsonify({'error': 'Draft must be approved first'}), 400
    draft.status = 'sent'
    draft.sent_at = utcnow()
    if draft.prospect_id:
        prospect = MarketingProspect.query.get(draft.prospect_id)
        if prospect:
            prospect.status = 'contacted'
    db.session.commit()
    return jsonify(draft.to_dict())


@marketing_bp.route('/unsubscribe/<token>')
def unsubscribe(token):
    email = ma.read_unsubscribe_token(token)
    if email:
        ma.suppress_email(email)
    return render_template('marketing_unsubscribe.html', ok=bool(email)), (200 if email else 400)
