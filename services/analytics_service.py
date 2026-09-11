"""
Advanced Analytics Service for DevOps Agent.

Provides charts, trends, cost forecasting, and usage analytics — backed by the
user's real cloud account (AWS Cost Explorer / CloudWatch via
`services.cost_explorer`) and this app's own database (`InfrastructureResource`,
`IncidentModel`, `UsageLog`). Per the "every feature runs against a real cloud
account" rule (see CLAUDE.md), nothing here may invent numbers: with no cloud
account connected and no local history, callers get honest empty/zero results
(and, where relevant, an `available: False` flag) instead of fabricated data.
"""

import logging
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from enum import Enum

logger = logging.getLogger(__name__)


class MetricType(Enum):
    """Types of metrics tracked."""
    COST = 'cost'
    RESOURCES = 'resources'
    INCIDENTS = 'incidents'
    DEPLOYMENTS = 'deployments'
    API_CALLS = 'api_calls'
    USERS = 'users'
    ALERTS = 'alerts'


class TimeRange(Enum):
    """Time range options."""
    HOUR = 'hour'
    DAY = 'day'
    WEEK = 'week'
    MONTH = 'month'
    QUARTER = 'quarter'
    YEAR = 'year'


_DAYS_BY_RANGE = {
    TimeRange.HOUR: 1,
    TimeRange.DAY: 1,
    TimeRange.WEEK: 7,
    TimeRange.MONTH: 30,
    TimeRange.QUARTER: 90,
    TimeRange.YEAR: 365,
}


class DataPoint:
    """Single data point in a time series."""

    def __init__(self, timestamp: datetime, value: float, label: Optional[str] = None):
        self.timestamp = timestamp
        self.value = value
        self.label = label
        self.metadata: Dict = {}

    def to_dict(self) -> Dict:
        return {
            'timestamp': self.timestamp.isoformat(),
            'value': self.value,
            'label': self.label or self.timestamp.strftime('%Y-%m-%d %H:%M')
        }


class TimeSeries:
    """Time series data."""

    def __init__(self, name: str, metric_type: MetricType):
        self.name = name
        self.metric_type = metric_type
        self.data_points: List[DataPoint] = []
        self.unit = ''

    def add_point(self, timestamp: datetime, value: float, label: Optional[str] = None):
        self.data_points.append(DataPoint(timestamp, value, label))

    def get_trend(self) -> str:
        """Calculate trend direction."""
        return _trend_from_values([p.value for p in self.data_points])

    def get_summary(self) -> Dict:
        """Get summary statistics."""
        if not self.data_points:
            return {'total': 0, 'avg': 0, 'min': 0, 'max': 0, 'trend': 'stable'}

        values = [p.value for p in self.data_points]
        return {
            'total': sum(values),
            'avg': sum(values) / len(values),
            'min': min(values),
            'max': max(values),
            'count': len(values),
            'trend': self.get_trend()
        }

    def to_dict(self) -> Dict:
        return {
            'name': self.name,
            'metric_type': self.metric_type.value,
            'unit': self.unit,
            'data': [p.to_dict() for p in self.data_points],
            'summary': self.get_summary()
        }


def _trend_from_values(values: List[float]) -> str:
    """Trend direction from a plain list of real values (recent vs. earlier)."""
    if len(values) < 2:
        return 'stable'

    recent = sum(values[-3:]) / min(3, len(values))
    older = sum(values[:3]) / min(3, len(values))
    change = (recent - older) / older if older else 0

    if change > 0.05:
        return 'up'
    elif change < -0.05:
        return 'down'
    return 'stable'


def _trend_from_counts(previous: int, current: int) -> str:
    """Trend direction comparing two real period counts."""
    if previous == 0:
        return 'stable' if current == 0 else 'up'
    change = (current - previous) / previous
    if change > 0.05:
        return 'up'
    elif change < -0.05:
        return 'down'
    return 'stable'


class AnalyticsService:
    """Service for advanced analytics with database persistence."""

    def __init__(self, user_id: Optional[int] = None):
        self.user_id = user_id

    def _get_db(self):
        """Get database session."""
        from models import db
        return db

    def _get_dashboard_model(self):
        """Get AnalyticsDashboard model."""
        from models import AnalyticsDashboard
        return AnalyticsDashboard

    def _get_widget_model(self):
        """Get AnalyticsWidget model."""
        from models import AnalyticsWidget
        return AnalyticsWidget

    # Real data access

    def _current_resource_count(self) -> int:
        """Live count of this user's non-terminated synced resources."""
        if self.user_id is None:
            return 0
        from models import InfrastructureResource
        return InfrastructureResource.query.filter(
            InfrastructureResource.user_id == self.user_id,
            InfrastructureResource.status.notin_(['terminated', 'deleted']),
        ).count()

    def _get_resources(self):
        if self.user_id is None:
            return []
        from models import InfrastructureResource
        return InfrastructureResource.query.filter(
            InfrastructureResource.user_id == self.user_id,
            InfrastructureResource.status.notin_(['terminated', 'deleted']),
        ).all()

    def _get_real_costs(self, days: int = 30) -> Dict:
        """
        Real per-user AWS spend from Cost Explorer. Falls back to a DB
        aggregate of synced resource costs when Cost Explorer can't be
        reached (no credentials linked, no CE permission, API error) —
        same fallback shape as `/api/dashboard/costs` in app.py. Never
        fabricated: an unreachable account reports zero/empty, not noise.
        """
        if self.user_id is None:
            return {'total_cost': 0.0, 'services': [], 'daily_trend': [], 'source': 'unavailable'}

        try:
            from services.cost_explorer import get_actual_costs
            data = get_actual_costs(self.user_id, days=days)
            data['source'] = 'cost_explorer'
            return data
        except Exception:
            db = self._get_db()
            from models import InfrastructureResource
            rows = db.session.query(
                InfrastructureResource.resource_type,
                db.func.sum(InfrastructureResource.monthly_cost)
            ).filter(
                InfrastructureResource.user_id == self.user_id,
                InfrastructureResource.status.notin_(['terminated', 'deleted']),
            ).group_by(InfrastructureResource.resource_type).all()

            services = [
                {'service': (row[0] or 'other'), 'cost': round(float(row[1] or 0), 2)}
                for row in rows
            ]
            services.sort(key=lambda s: s['cost'], reverse=True)
            total = sum(s['cost'] for s in services)
            return {
                'total_cost': round(total, 2),
                'services': services,
                'daily_trend': [],
                'source': 'database',
            }

    def _incidents_in_window(self, since: datetime, before: Optional[datetime] = None) -> List:
        if self.user_id is None:
            return []
        from models import IncidentModel
        query = IncidentModel.query.filter(
            IncidentModel.user_id == self.user_id,
            IncidentModel.triggered_at >= since,
        )
        if before is not None:
            query = query.filter(IncidentModel.triggered_at < before)
        return query.all()

    # Time series

    def get_time_series(self, name: str, time_range: TimeRange = TimeRange.MONTH) -> Optional[TimeSeries]:
        """Get a real time series for one of the known metric names."""
        days = _DAYS_BY_RANGE.get(time_range, 30)

        if name == 'daily_cost':
            return self._cost_time_series(days)
        if name == 'resource_count':
            return self._resource_count_time_series()
        if name == 'incidents':
            return self._incident_time_series(days)
        if name == 'api_calls':
            return self._api_calls_time_series(days, hourly=time_range in (TimeRange.HOUR, TimeRange.DAY))
        if name == 'deployments':
            # No real per-user deployment/CI-CD event log exists yet.
            series = TimeSeries('deployments', MetricType.DEPLOYMENTS)
            series.unit = 'count'
            return series
        return None

    def _cost_time_series(self, days: int) -> TimeSeries:
        series = TimeSeries('daily_cost', MetricType.COST)
        series.unit = 'USD'
        costs = self._get_real_costs(days)
        for point in costs['daily_trend']:
            try:
                ts = datetime.strptime(point['date'], '%Y-%m-%d')
            except (KeyError, ValueError, TypeError):
                continue
            series.add_point(ts, point['cost'])
        return series

    def _resource_count_time_series(self) -> TimeSeries:
        """Only a current snapshot exists (no historical resource-count
        table), so this is a single real data point, not an invented trend."""
        series = TimeSeries('resource_count', MetricType.RESOURCES)
        series.unit = 'count'
        series.add_point(datetime.utcnow(), self._current_resource_count(), label='Current')
        return series

    def _incident_time_series(self, days: int) -> TimeSeries:
        series = TimeSeries('incidents', MetricType.INCIDENTS)
        series.unit = 'count'
        since = datetime.utcnow() - timedelta(days=days)
        buckets: Dict[str, int] = {}
        for incident in self._incidents_in_window(since):
            if not incident.triggered_at:
                continue
            key = incident.triggered_at.strftime('%Y-%m-%d')
            buckets[key] = buckets.get(key, 0) + 1
        for key in sorted(buckets):
            series.add_point(datetime.strptime(key, '%Y-%m-%d'), buckets[key])
        return series

    def _api_calls_time_series(self, days: int, hourly: bool = False) -> TimeSeries:
        series = TimeSeries('api_calls', MetricType.API_CALLS)
        series.unit = 'calls'
        if self.user_id is None:
            return series

        from models import UsageLog
        since = datetime.utcnow() - timedelta(days=days)
        logs = UsageLog.query.filter(
            UsageLog.user_id == self.user_id,
            UsageLog.tool_name.isnot(None),
            UsageLog.created_at >= since,
        ).all()

        fmt = '%Y-%m-%d %H:00' if hourly else '%Y-%m-%d'
        buckets: Dict[str, int] = {}
        for log in logs:
            if not log.created_at:
                continue
            key = log.created_at.strftime(fmt)
            buckets[key] = buckets.get(key, 0) + 1
        for key in sorted(buckets):
            series.add_point(datetime.strptime(key, fmt), buckets[key])
        return series

    # Dashboard / API-facing aggregates

    def get_dashboard_metrics(self, days: int = 30) -> Dict:
        """Get key metrics for dashboard."""
        since = datetime.utcnow() - timedelta(days=days)
        prev_since = since - timedelta(days=days)

        costs = self._get_real_costs(days)
        incidents_current = len(self._incidents_in_window(since))
        incidents_previous = len(self._incidents_in_window(prev_since, before=since))

        return {
            'cost': {
                'current_month': costs['total_cost'],
                'trend': _trend_from_values([p['cost'] for p in costs['daily_trend']]),
                'forecast': self.forecast_costs(30).get('monthly_projection', 0.0),
            },
            'resources': {
                'total': self._current_resource_count(),
                # No historical resource-count series exists to compare against.
                'trend': 'stable',
            },
            'incidents': {
                'this_month': incidents_current,
                'trend': _trend_from_counts(incidents_previous, incidents_current),
            },
            'deployments': {
                'this_month': 0,
                'trend': 'stable',
                'available': False,
            },
        }

    def get_cost_analytics(self, start_date: datetime, end_date: datetime) -> Dict:
        """Get cost analytics for a date range."""
        days = max(1, (end_date - start_date).days)
        costs = self._get_real_costs(days)
        by_service = {s['service']: s['cost'] for s in costs['services']}
        return {
            'by_service': by_service,
            'by_resource': by_service,  # alias for resource view
            'total': costs['total_cost'],
            'trend': costs['daily_trend'],
            'period_days': days,
            'source': costs['source'],
        }

    def forecast_costs(self, days: int = 30) -> Dict:
        """Real AWS Cost Explorer forecast. Unavailable (not fabricated) when
        the account has no credentials or too little billing history."""
        if self.user_id is None:
            return {'monthly_projection': 0.0, 'available': False}

        try:
            from services.cost_explorer import get_cost_forecast
            forecast = get_cost_forecast(self.user_id, forecast_days=days)
        except Exception:
            forecast = {'forecast_total': None, 'error': 'Insufficient data for forecast'}

        total = forecast.get('forecast_total')
        return {
            'monthly_projection': round(total, 2) if total is not None else 0.0,
            'forecast_total': total,
            'forecast_unit': forecast.get('forecast_unit', 'USD'),
            'period': forecast.get('period'),
            'available': total is not None,
            'error': forecast.get('error'),
        }

    def get_resource_utilization(self) -> Dict:
        """Get resource utilization summary from live, currently-synced resources."""
        resources = self._get_resources()
        by_type: Dict[str, int] = {}
        for resource in resources:
            by_type[resource.resource_type] = by_type.get(resource.resource_type, 0) + 1

        return {
            'total_resources': len(resources),
            'trend': 'stable',
            'by_type': by_type,
            # Averaging real per-instance CloudWatch CPU across every running
            # resource on each request is too slow/expensive to do inline
            # here; report honestly-unavailable rather than a fake average.
            # `services.cost_explorer.get_instance_utilization` is the real
            # per-resource source when a specific instance is selected.
            'utilization_avg': None,
        }

    def get_alerts_summary(self, days: int = 7) -> Dict:
        """Get alerts summary for the given number of days, from real incidents."""
        since = datetime.utcnow() - timedelta(days=days)
        prev_since = since - timedelta(days=days)

        incidents = self._incidents_in_window(since)
        total = len(incidents)
        by_severity = {'critical': 0, 'high': 0, 'medium': 0, 'low': 0}
        resolved = 0
        for incident in incidents:
            if incident.severity in by_severity:
                by_severity[incident.severity] += 1
            if incident.status in ('resolved', 'closed'):
                resolved += 1

        previous_total = len(self._incidents_in_window(prev_since, before=since))

        return {
            'total': total,
            'critical': by_severity['critical'],
            'high': by_severity['high'],
            'medium': by_severity['medium'],
            'low': by_severity['low'],
            'resolved': resolved,
            'open': total - resolved,
            'trend': _trend_from_counts(previous_total, total),
        }

    def get_deployment_stats(self, days: int = 30) -> Dict:
        """No real per-user deployment/CI-CD event log exists in this app
        yet — report honestly unavailable rather than inventing figures."""
        return {
            'total': 0,
            'successful': 0,
            'failed': 0,
            'success_rate': None,
            'avg_duration_minutes': None,
            'trend': 'stable',
            'available': False,
        }

    def get_incident_stats(self, days: int = 30) -> Dict:
        """Get incident statistics for the given number of days."""
        return self.get_alerts_summary(days=days)

    # Dashboard Management with Database Persistence

    def create_dashboard(self, user_id: int, name: str, description: str = None) -> Any:
        """Create a custom dashboard."""
        AnalyticsDashboard = self._get_dashboard_model()
        db = self._get_db()

        dashboard = AnalyticsDashboard(
            user_id=user_id,
            name=name,
            description=description,
            layout={},
            is_default=False
        )
        db.session.add(dashboard)
        db.session.commit()
        return dashboard

    def get_dashboard(self, dashboard_id: int) -> Optional[Any]:
        """Get a dashboard by ID (scoped to self.user_id when set)."""
        AnalyticsDashboard = self._get_dashboard_model()
        query = AnalyticsDashboard.query.filter_by(id=dashboard_id)
        if self.user_id is not None:
            query = query.filter_by(user_id=self.user_id)
        return query.first()

    def get_user_dashboards(self, user_id: int) -> List[Any]:
        """Get all dashboards for a user."""
        AnalyticsDashboard = self._get_dashboard_model()
        return AnalyticsDashboard.query.filter_by(user_id=user_id).all()

    def update_dashboard(self, dashboard_id: int, updates: Dict) -> Optional[Any]:
        """Update a dashboard."""
        db = self._get_db()
        dashboard = self.get_dashboard(dashboard_id)
        if not dashboard:
            return None

        if 'name' in updates:
            dashboard.name = updates['name']
        if 'description' in updates:
            dashboard.description = updates['description']
        if 'layout' in updates:
            dashboard.layout = updates['layout']
        if 'is_default' in updates:
            dashboard.is_default = updates['is_default']

        db.session.commit()
        return dashboard

    def delete_dashboard(self, dashboard_id: int) -> bool:
        """Delete a dashboard."""
        db = self._get_db()
        dashboard = self.get_dashboard(dashboard_id)
        if dashboard:
            db.session.delete(dashboard)
            db.session.commit()
            return True
        return False

    # Widget Management

    def add_widget(self, dashboard_id: int, widget_type: str, title: str,
                   config: Dict, position: int = 0) -> Any:
        """Add a widget to a dashboard."""
        AnalyticsWidget = self._get_widget_model()
        db = self._get_db()

        widget = AnalyticsWidget(
            dashboard_id=dashboard_id,
            widget_type=widget_type,
            title=title,
            config=config,
            position=position
        )
        db.session.add(widget)
        db.session.commit()
        return widget

    def get_widget(self, widget_id: int) -> Optional[Any]:
        """Get a widget by ID (scoped to a dashboard owned by self.user_id when set)."""
        AnalyticsWidget = self._get_widget_model()
        widget = AnalyticsWidget.query.get(widget_id)
        if widget is None or self.user_id is None:
            return widget
        if not self.get_dashboard(widget.dashboard_id):
            return None
        return widget

    def get_dashboard_widgets(self, dashboard_id: int) -> List[Any]:
        """Get all widgets for a dashboard."""
        AnalyticsWidget = self._get_widget_model()
        return AnalyticsWidget.query.filter_by(dashboard_id=dashboard_id)\
            .order_by(AnalyticsWidget.position).all()

    def update_widget(self, widget_id: int, updates: Dict) -> Optional[Any]:
        """Update a widget."""
        db = self._get_db()
        widget = self.get_widget(widget_id)
        if not widget:
            return None

        if 'title' in updates:
            widget.title = updates['title']
        if 'config' in updates:
            widget.config = updates['config']
        if 'position' in updates:
            widget.position = updates['position']

        db.session.commit()
        return widget

    def delete_widget(self, widget_id: int) -> bool:
        """Delete a widget."""
        db = self._get_db()
        widget = self.get_widget(widget_id)
        if widget:
            db.session.delete(widget)
            db.session.commit()
            return True
        return False


def get_analytics_service(user_id: Optional[int] = None) -> AnalyticsService:
    """Get analytics service instance."""
    return AnalyticsService(user_id)
