"""
Root Cause Analysis Routes for DevOps Agent.

Provides API and web UI endpoints for AI-powered root cause analysis.
"""

from flask import Blueprint, render_template, jsonify, request
from flask_login import login_required, current_user
import logging

from services.root_cause_analyzer import get_root_cause_analyzer
from services.incident_response import get_incident_engine

logger = logging.getLogger(__name__)

analysis_bp = Blueprint('analysis', __name__, url_prefix='/analysis')


def json_response(data: dict, status: int = 200):
    """Create a JSON response."""
    return jsonify(data), status


@analysis_bp.route('/')
@login_required
def analysis_dashboard():
    """Render the analysis dashboard."""
    analyzer = get_root_cause_analyzer()
    return render_template(
        'analysis/dashboard.html',
        analyses=analyzer.get_all_analyses()
    )


@analysis_bp.route('/<analysis_id>')
@login_required
def view_analysis(analysis_id: str):
    """View a specific analysis."""
    analyzer = get_root_cause_analyzer()
    analysis = analyzer.get_analysis(analysis_id)

    if not analysis:
        return "Analysis not found", 404

    return render_template(
        'analysis/detail.html',
        analysis=analysis.to_dict()
    )


# API Endpoints

@analysis_bp.route('/api/analyze', methods=['POST'])
@login_required
def api_analyze_incident():
    """Trigger root cause analysis for an incident."""
    data = request.get_json()

    if not data:
        return json_response({"error": "No data provided"}, 400)

    incident_id = data.get('incident_id')

    # If incident_id provided, fetch incident data
    if incident_id:
        incident_engine = get_incident_engine()
        incident = incident_engine.get_incident(incident_id)
        if not incident:
            return json_response({"error": "Incident not found"}, 404)

        incident_data = {
            'id': incident.id,
            'title': incident.title,
            'description': incident.description,
            'severity': incident.severity.value,
            'status': incident.status.value,
            'source': incident.source,
            'triggered_at': incident.triggered_at.isoformat(),
            'timeline': incident.timeline,
            'actions_taken': [
                {
                    'action': a.get('action'),
                    'type': a.get('type'),
                    'result': a.get('result', {})
                }
                for a in incident.actions_taken
            ]
        }
    else:
        # Use provided incident data
        incident_data = data.get('incident_data', {})
        if not incident_data:
            return json_response({"error": "Either incident_id or incident_data required"}, 400)

    # Get optional additional data
    logs = data.get('logs', [])
    metrics = data.get('metrics', {})
    related_events = data.get('related_events', [])

    # Perform analysis
    analyzer = get_root_cause_analyzer()
    result = analyzer.analyze_incident(
        incident_data=incident_data,
        logs=logs,
        metrics=metrics,
        related_events=related_events
    )

    return json_response({
        "success": True,
        "analysis_id": result.id,
        "analysis": result.to_dict()
    })


@analysis_bp.route('/api/analyses', methods=['GET'])
@login_required
def api_list_analyses():
    """List all analyses."""
    analyzer = get_root_cause_analyzer()
    incident_id = request.args.get('incident_id')

    if incident_id:
        analyses = [a.to_dict() for a in analyzer.get_analyses_for_incident(incident_id)]
    else:
        analyses = analyzer.get_all_analyses()

    return json_response({"analyses": analyses})


@analysis_bp.route('/api/analyses/<analysis_id>', methods=['GET'])
@login_required
def api_get_analysis(analysis_id: str):
    """Get a specific analysis."""
    analyzer = get_root_cause_analyzer()
    analysis = analyzer.get_analysis(analysis_id)

    if not analysis:
        return json_response({"error": "Analysis not found"}, 404)

    return json_response({"analysis": analysis.to_dict()})


@analysis_bp.route('/api/incident/<incident_id>/analyze', methods=['POST'])
@login_required
def api_analyze_incident_by_id(incident_id: str):
    """Trigger analysis for a specific incident by ID."""
    incident_engine = get_incident_engine()
    incident = incident_engine.get_incident(incident_id)

    if not incident:
        return json_response({"error": "Incident not found"}, 404)

    incident_data = {
        'id': incident.id,
        'title': incident.title,
        'description': incident.description,
        'severity': incident.severity.value,
        'status': incident.status.value,
        'source': incident.source,
        'triggered_at': incident.triggered_at.isoformat(),
        'timeline': incident.timeline,
        'actions_taken': [
            {
                'action': a.get('action'),
                'type': a.get('type'),
                'result': a.get('result', {})
            }
            for a in incident.actions_taken
        ]
    }

    # Get additional context from request
    data = request.get_json() or {}
    logs = data.get('logs', [])
    metrics = data.get('metrics', {})
    related_events = data.get('related_events', [])

    analyzer = get_root_cause_analyzer()
    result = analyzer.analyze_incident(
        incident_data=incident_data,
        logs=logs,
        metrics=metrics,
        related_events=related_events
    )

    return json_response({
        "success": True,
        "analysis_id": result.id,
        "analysis": result.to_dict()
    })
