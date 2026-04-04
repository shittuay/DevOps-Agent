"""
Chat Artifacts API routes — create, version, and export structured documents
generated during chat conversations (runbooks, incident reports, specs, etc.).
"""

from flask import Blueprint, request, jsonify, make_response
from flask_login import login_required, current_user
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

artifacts_bp = Blueprint('artifacts', __name__, url_prefix='/api/chat/artifacts')


@artifacts_bp.route('', methods=['GET'])
@login_required
def list_artifacts():
    """List artifacts for the current user, optionally filtered by conversation_id."""
    from models import db, ChatArtifact
    conversation_id = request.args.get('conversation_id')
    q = ChatArtifact.query.filter_by(user_id=current_user.id, is_latest=True)
    if conversation_id:
        q = q.filter_by(conversation_id=conversation_id)
    artifacts = q.order_by(ChatArtifact.created_at.desc()).limit(100).all()
    return jsonify([a.to_dict() for a in artifacts])


@artifacts_bp.route('', methods=['POST'])
@login_required
def create_artifact():
    """Create a new artifact."""
    from models import db, ChatArtifact
    data = request.get_json() or {}
    artifact_type = data.get('artifact_type', 'runbook')
    title = data.get('title', 'Untitled')
    content = data.get('content', '')
    conversation_id = data.get('conversation_id')
    message_id = data.get('message_id')

    if not content:
        return jsonify({'error': 'content is required'}), 400

    artifact = ChatArtifact(
        user_id=current_user.id,
        conversation_id=conversation_id,
        message_id=message_id,
        artifact_type=artifact_type,
        title=title,
        content=content,
        version=1,
        is_latest=True,
    )
    db.session.add(artifact)
    db.session.commit()
    return jsonify(artifact.to_dict()), 201


@artifacts_bp.route('/<int:artifact_id>', methods=['GET'])
@login_required
def get_artifact(artifact_id):
    """Get a single artifact by ID."""
    from models import ChatArtifact
    artifact = ChatArtifact.query.filter_by(id=artifact_id, user_id=current_user.id).first()
    if not artifact:
        return jsonify({'error': 'Artifact not found'}), 404
    return jsonify(artifact.to_dict())


@artifacts_bp.route('/<int:artifact_id>', methods=['PUT'])
@login_required
def update_artifact(artifact_id):
    """Create a new version of an artifact (increments version, flips is_latest)."""
    from models import db, ChatArtifact
    existing = ChatArtifact.query.filter_by(id=artifact_id, user_id=current_user.id).first()
    if not existing:
        return jsonify({'error': 'Artifact not found'}), 404

    data = request.get_json() or {}
    content = data.get('content', existing.content)
    title = data.get('title', existing.title)

    # Mark old version as not latest
    existing.is_latest = False

    new_version = ChatArtifact(
        user_id=current_user.id,
        conversation_id=existing.conversation_id,
        artifact_type=existing.artifact_type,
        title=title,
        content=content,
        version=existing.version + 1,
        parent_id=existing.id,
        is_latest=True,
    )
    db.session.add(new_version)
    db.session.commit()
    return jsonify(new_version.to_dict())


@artifacts_bp.route('/<int:artifact_id>', methods=['DELETE'])
@login_required
def delete_artifact(artifact_id):
    """Soft-delete an artifact by marking is_latest=False."""
    from models import db, ChatArtifact
    artifact = ChatArtifact.query.filter_by(id=artifact_id, user_id=current_user.id).first()
    if not artifact:
        return jsonify({'error': 'Artifact not found'}), 404
    artifact.is_latest = False
    db.session.commit()
    return jsonify({'success': True})


@artifacts_bp.route('/<int:artifact_id>/export', methods=['GET'])
@login_required
def export_artifact(artifact_id):
    """Download artifact as a markdown file."""
    from models import ChatArtifact
    artifact = ChatArtifact.query.filter_by(id=artifact_id, user_id=current_user.id).first()
    if not artifact:
        return jsonify({'error': 'Artifact not found'}), 404

    safe_title = ''.join(c if c.isalnum() or c in '-_ ' else '_' for c in artifact.title)[:50]
    filename = f"{safe_title.replace(' ', '_')}_v{artifact.version}.md"
    response = make_response(artifact.content)
    response.headers['Content-Type'] = 'text/markdown; charset=utf-8'
    response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response
