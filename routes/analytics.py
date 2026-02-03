"""
Advanced Analytics Dashboard Routes
"""
from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required, current_user
from datetime import datetime, timedelta

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
    days = int(period.replace('d', ''))

    data = service.get_dashboard_metrics(days=days)
    return jsonify(data)


@analytics_bp.route('/api/costs/summary')
@login_required
def api_cost_summary():
    """Get cost summary"""
    from services.analytics_service import AnalyticsService
    service = AnalyticsService(current_user.id)

    period = request.args.get('period', '30d')
    days = int(period.replace('d', ''))

    start_date = datetime.utcnow() - timedelta(days=days)
    end_date = datetime.utcnow()

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

    return jsonify({
        'forecast': [{
            'date': f.date.isoformat(),
            'predicted_cost': f.predicted_cost,
            'confidence_lower': f.confidence_lower,
            'confidence_upper': f.confidence_upper
        } for f in forecast]
    })


@analytics_bp.route('/api/costs/by-service')
@login_required
def api_costs_by_service():
    """Get costs breakdown by service"""
    from services.analytics_service import AnalyticsService
    service = AnalyticsService(current_user.id)

    period = request.args.get('period', '30d')
    days = int(period.replace('d', ''))

    start_date = datetime.utcnow() - timedelta(days=days)
    end_date = datetime.utcnow()

    data = service.get_cost_analytics(start_date, end_date)
    return jsonify({'by_service': data.get('by_service', {})})


@analytics_bp.route('/api/costs/by-resource')
@login_required
def api_costs_by_resource():
    """Get costs breakdown by resource"""
    from services.analytics_service import AnalyticsService
    service = AnalyticsService(current_user.id)

    period = request.args.get('period', '30d')
    days = int(period.replace('d', ''))

    start_date = datetime.utcnow() - timedelta(days=days)
    end_date = datetime.utcnow()

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

    if period.endswith('h'):
        hours = int(period.replace('h', ''))
        start_date = datetime.utcnow() - timedelta(hours=hours)
    else:
        days = int(period.replace('d', ''))
        start_date = datetime.utcnow() - timedelta(days=days)

    end_date = datetime.utcnow()

    data = service.get_time_series(metric_type, start_date, end_date, resource_id)

    return jsonify({
        'metric': metric_type,
        'data': [{
            'timestamp': d.timestamp.isoformat(),
            'value': d.value,
            'resource_id': d.resource_id
        } for d in data]
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
    days = int(period.replace('d', ''))

    start_date = datetime.utcnow() - timedelta(days=days)
    end_date = datetime.utcnow()

    metrics = ['cpu', 'memory', 'disk', 'network']
    trends = {}

    for metric in metrics:
        data = service.get_time_series(metric, start_date, end_date)
        if data:
            trends[metric] = [{
                'timestamp': d.timestamp.isoformat(),
                'value': d.value
            } for d in data]

    return jsonify({'trends': trends})


@analytics_bp.route('/api/alerts/summary')
@login_required
def api_alerts_summary():
    """Get alerts summary"""
    from services.analytics_service import AnalyticsService
    service = AnalyticsService(current_user.id)

    period = request.args.get('period', '7d')
    days = int(period.replace('d', ''))

    data = service.get_alerts_summary(days=days)
    return jsonify(data)


@analytics_bp.route('/api/deployments/stats')
@login_required
def api_deployment_stats():
    """Get deployment statistics"""
    from services.analytics_service import AnalyticsService
    service = AnalyticsService(current_user.id)

    period = request.args.get('period', '30d')
    days = int(period.replace('d', ''))

    data = service.get_deployment_stats(days=days)
    return jsonify(data)


@analytics_bp.route('/api/incidents/stats')
@login_required
def api_incident_stats():
    """Get incident statistics"""
    from services.analytics_service import AnalyticsService
    service = AnalyticsService(current_user.id)

    period = request.args.get('period', '30d')
    days = int(period.replace('d', ''))

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
    days = int(period.replace('d', ''))

    start_date = datetime.utcnow() - timedelta(days=days)
    end_date = datetime.utcnow()

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
