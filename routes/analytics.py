"""
Advanced Analytics Dashboard Routes
"""
from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required, current_user
from datetime import datetime, timedelta
from src.utils.timeutils import utcnow

analytics_bp = Blueprint('analytics', __name__, url_prefix='/analytics')


@analytics_bp.route('/')
@login_required
def dashboard():
    """Main analytics dashboard"""
    return render_template('analytics/dashboard.html')


@analytics_bp.route('/costs')
@login_required
def cost_analytics():
    """Cost analytics and forecasting"""
    return render_template('analytics/costs.html')


@analytics_bp.route('/performance')
@login_required
def performance_analytics():
    """Performance metrics and trends"""
    return render_template('analytics/performance.html')


@analytics_bp.route('/resources')
@login_required
def resource_analytics():
    """Resource utilization analytics"""
    return render_template('analytics/resources.html')


# API Endpoints
@analytics_bp.route('/api/dashboard')
@login_required
def api_dashboard_data():
    """Get dashboard summary data"""
    from services.analytics_service import AnalyticsService
    service = AnalyticsService(current_user.id)

    period = request.args.get('period', '30d')
    days = int(period.rstrip('dh')) if period[-1] in ('d', 'h') else 30

    data = service.get_dashboard_metrics(days=days)
    return jsonify(data)


@analytics_bp.route('/api/costs/summary')
@login_required
def api_cost_summary():
    """Get cost summary"""
    from services.analytics_service import AnalyticsService
    service = AnalyticsService(current_user.id)

    period = request.args.get('period', '30d')
    days = int(period.rstrip('dh'))

    start_date = utcnow() - timedelta(days=days)
    end_date = utcnow()

    data = service.get_cost_analytics(start_date, end_date)
    return jsonify(data)


@analytics_bp.route('/api/costs/forecast')
@login_required
def api_cost_forecast():
    """Get cost forecast"""
    from services.analytics_service import AnalyticsService
    service = AnalyticsService(current_user.id)

    days = int(request.args.get('days', 30))
    forecast = service.forecast_costs(days)
    return jsonify(forecast)


@analytics_bp.route('/api/costs/by-service')
@login_required
def api_costs_by_service():
    """Get costs breakdown by service"""
    from services.analytics_service import AnalyticsService
    service = AnalyticsService(current_user.id)

    period = request.args.get('period', '30d')
    days = int(period.rstrip('dh'))

    start_date = utcnow() - timedelta(days=days)
    end_date = utcnow()

    data = service.get_cost_analytics(start_date, end_date)
    return jsonify({'by_service': data.get('by_service', {})})


@analytics_bp.route('/api/costs/by-resource')
@login_required
def api_costs_by_resource():
    """Get costs breakdown by resource"""
    from services.analytics_service import AnalyticsService
    service = AnalyticsService(current_user.id)

    period = request.args.get('period', '30d')
    days = int(period.rstrip('dh'))

    start_date = utcnow() - timedelta(days=days)
    end_date = utcnow()

    data = service.get_cost_analytics(start_date, end_date)
    return jsonify({'by_resource': data.get('by_resource', {})})


@analytics_bp.route('/api/performance/metrics')
@login_required
def api_performance_metrics():
    """Get performance metrics time series"""
    from services.analytics_service import AnalyticsService
    service = AnalyticsService(current_user.id)

    metric_type = request.args.get('metric', 'cpu')
    resource_id = request.args.get('resource_id')
    period = request.args.get('period', '24h')

    from services.analytics_service import TimeRange
    if period.endswith('h'):
        time_range = TimeRange.HOUR if period == '1h' else TimeRange.DAY
    elif period.endswith('d'):
        days = int(period[:-1])
        time_range = TimeRange.WEEK if days <= 7 else TimeRange.MONTH
    else:
        time_range = TimeRange.MONTH

    # Map metric alias to cached series names
    metric_map = {'cpu': 'resource_count', 'memory': 'resource_count', 'cost': 'daily_cost'}
    series_name = metric_map.get(metric_type, metric_type)
    series = service.get_time_series(series_name, time_range)

    return jsonify({
        'metric': metric_type,
        'data': [p.to_dict() for p in series.data_points] if series else []
    })


@analytics_bp.route('/api/resources/utilization')
@login_required
def api_resource_utilization():
    """Get resource utilization summary"""
    from services.analytics_service import AnalyticsService
    service = AnalyticsService(current_user.id)

    data = service.get_resource_utilization()
    return jsonify(data)


@analytics_bp.route('/api/resources/trends')
@login_required
def api_resource_trends():
    """Get resource trends"""
    from services.analytics_service import AnalyticsService
    service = AnalyticsService(current_user.id)

    period = request.args.get('period', '30d')
    days = int(period.rstrip('dh'))

    start_date = utcnow() - timedelta(days=days)
    end_date = utcnow()

    from services.analytics_service import TimeRange
    time_range = TimeRange.WEEK if days <= 7 else TimeRange.MONTH
    metric_map = {'cpu': 'resource_count', 'memory': 'resource_count', 'disk': 'resource_count', 'network': 'api_calls'}
    trends = {}

    for metric in ['cpu', 'memory', 'disk', 'network']:
        series = service.get_time_series(metric_map[metric], time_range)
        if series:
            trends[metric] = [p.to_dict() for p in series.data_points]

    return jsonify({'trends': trends})


@analytics_bp.route('/api/alerts/summary')
@login_required
def api_alerts_summary():
    """Get alerts summary"""
    from services.analytics_service import AnalyticsService
    service = AnalyticsService(current_user.id)

    period = request.args.get('period', '7d')
    days = int(period.rstrip('dh'))

    data = service.get_alerts_summary(days=days)
    return jsonify(data)


@analytics_bp.route('/api/deployments/stats')
@login_required
def api_deployment_stats():
    """Get deployment statistics"""
    from services.analytics_service import AnalyticsService
    service = AnalyticsService(current_user.id)

    period = request.args.get('period', '30d')
    days = int(period.rstrip('dh'))

    data = service.get_deployment_stats(days=days)
    return jsonify(data)


@analytics_bp.route('/api/incidents/stats')
@login_required
def api_incident_stats():
    """Get incident statistics"""
    from services.analytics_service import AnalyticsService
    service = AnalyticsService(current_user.id)

    period = request.args.get('period', '30d')
    days = int(period.rstrip('dh'))

    data = service.get_incident_stats(days=days)
    return jsonify(data)


@analytics_bp.route('/api/export')
@login_required
def api_export_data():
    """Export analytics data"""
    from services.analytics_service import AnalyticsService
    from flask import Response
    import json

    service = AnalyticsService(current_user.id)

    export_type = request.args.get('type', 'costs')
    format_type = request.args.get('format', 'json')
    period = request.args.get('period', '30d')
    days = int(period.rstrip('dh'))

    start_date = utcnow() - timedelta(days=days)
    end_date = utcnow()

    if export_type == 'costs':
        data = service.get_cost_analytics(start_date, end_date)
    elif export_type == 'performance':
        data = service.get_resource_utilization()
    else:
        data = service.get_dashboard_metrics(days=days)

    if format_type == 'csv':
        import csv
        import io

        output = io.StringIO()
        if isinstance(data, dict) and 'daily_costs' in data:
            writer = csv.DictWriter(output, fieldnames=['date', 'cost'])
            writer.writeheader()
            for item in data.get('daily_costs', []):
                writer.writerow(item)
        else:
            writer = csv.writer(output)
            writer.writerow(['metric', 'value'])
            for key, value in data.items():
                writer.writerow([key, value])

        return Response(
            output.getvalue(),
            mimetype='text/csv',
            headers={'Content-Disposition': f'attachment; filename=analytics_{export_type}.csv'}
        )

    return Response(
        json.dumps(data, indent=2, default=str),
        mimetype='application/json',
        headers={'Content-Disposition': f'attachment; filename=analytics_{export_type}.json'}
    )


@analytics_bp.route('/api/widgets')
@login_required
def api_widgets():
    """Get available dashboard widgets"""
    widgets = [
        {'id': 'cost_trend', 'name': 'Cost Trend', 'type': 'line_chart', 'size': 'large'},
        {'id': 'cost_forecast', 'name': 'Cost Forecast', 'type': 'area_chart', 'size': 'large'},
        {'id': 'resource_utilization', 'name': 'Resource Utilization', 'type': 'gauge', 'size': 'medium'},
        {'id': 'top_resources', 'name': 'Top Resources by Cost', 'type': 'bar_chart', 'size': 'medium'},
        {'id': 'alerts_summary', 'name': 'Alerts Summary', 'type': 'stat_card', 'size': 'small'},
        {'id': 'deployment_status', 'name': 'Deployment Status', 'type': 'pie_chart', 'size': 'medium'},
        {'id': 'incident_trend', 'name': 'Incident Trend', 'type': 'line_chart', 'size': 'medium'},
        {'id': 'savings_opportunities', 'name': 'Savings Opportunities', 'type': 'list', 'size': 'medium'},
    ]
    return jsonify({'widgets': widgets})



@analytics_bp.route('/api/tool-usage')
@login_required
def api_tool_usage():
    """
    Return tool usage statistics for the current user.

    Query params:
      period   - number of days to look back (default 30)
      limit    - max tools to return (default 20)
    """
    from models import db, UsageLog
    from sqlalchemy import func

    try:
        period = int(request.args.get('period', '30').rstrip('dh'))
    except ValueError:
        period = 30
    period = max(1, min(period, 365))
    limit = max(1, min(int(request.args.get('limit', 20)), 100))

    since = utcnow() - timedelta(days=period)

    # Top tools by call count
    rows = (
        db.session.query(
            UsageLog.tool_name,
            func.count(UsageLog.id).label('call_count'),
            func.sum(func.cast(UsageLog.success, db.Integer)).label('success_count'),
        )
        .filter(
            UsageLog.user_id == current_user.id,
            UsageLog.tool_name.isnot(None),
            UsageLog.created_at >= since,
        )
        .group_by(UsageLog.tool_name)
        .order_by(func.count(UsageLog.id).desc())
        .limit(limit)
        .all()
    )

    tools = [
        {
            'tool_name': r.tool_name,
            'call_count': r.call_count,
            'success_count': int(r.success_count or 0),
            'success_rate': round((r.success_count or 0) / r.call_count * 100, 1),
        }
        for r in rows
    ]

    # Daily call volume
    daily = (
        db.session.query(
            func.date(UsageLog.created_at).label('date'),
            func.count(UsageLog.id).label('calls'),
        )
        .filter(
            UsageLog.user_id == current_user.id,
            UsageLog.tool_name.isnot(None),
            UsageLog.created_at >= since,
        )
        .group_by(func.date(UsageLog.created_at))
        .order_by(func.date(UsageLog.created_at))
        .all()
    )

    return jsonify({
        'period_days': period,
        'top_tools': tools,
        'daily_volume': [{'date': str(r.date), 'calls': r.calls} for r in daily],
    })


@analytics_bp.route('/api/conversion-funnel')
@login_required
def api_conversion_funnel():
    """Return conversion funnel data (admin view for your own account)."""
    from models import db, ConversionEvent
    from sqlalchemy import func

    try:
        period = int(request.args.get('period', '30').rstrip('dh'))
    except ValueError:
        period = 30
    period = max(1, min(period, 365))
    since = utcnow() - timedelta(days=period)

    rows = (
        db.session.query(
            ConversionEvent.event_type,
            func.count(ConversionEvent.id).label('count'),
        )
        .filter(
            ConversionEvent.created_at >= since,
            ConversionEvent.user_id == current_user.id,
        )
        .group_by(ConversionEvent.event_type)
        .all()
    )

    funnel = {r.event_type: r.count for r in rows}
    ordered = [
        {'step': 'trial_start',       'count': funnel.get('trial_start', 0)},
        {'step': 'first_tool_use',    'count': funnel.get('first_tool_use', 0)},
        {'step': 'upgrade_cta_shown', 'count': funnel.get('upgrade_cta_shown', 0)},
        {'step': 'upgrade_completed', 'count': funnel.get('upgrade_completed', 0)},
    ]

    return jsonify({'period_days': period, 'funnel': ordered})
