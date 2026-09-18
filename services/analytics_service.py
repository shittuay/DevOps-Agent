"""
Advanced Analytics Service for DevOps Agent.

Provides charts, trends, cost forecasting, and usage analytics.
Uses database persistence for dashboards and widgets.

All metrics are derived from the user's real synced data (InfrastructureResource,
IncidentModel, UsageLog) or real cloud credentials — never fabricated. A metric with
no real data source backing it yet (e.g. deployments, CPU/memory utilization) reports
an empty/zero result rather than inventing one. See CLAUDE.md's "every feature runs
against a real cloud account" rule.
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


class AggregationType(Enum):
    """Aggregation types."""
    SUM = 'sum'
    AVG = 'avg'
    MIN = 'min'
    MAX = 'max'
    COUNT = 'count'


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
        if len(self.data_points) < 2:
            return 'stable'

        recent = sum(p.value for p in self.data_points[-3:]) / min(3, len(self.data_points))
        older = sum(p.value for p in self.data_points[:3]) / min(3, len(self.data_points))

        change = (recent - older) / older if older != 0 else 0

        if change > 0.05:
            return 'up'
        elif change < -0.05:
            return 'down'
        return 'stable'

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


class CostForecast:
    """Cost forecasting model."""

    def __init__(self, historical_data: List[DataPoint]):
        self.historical = historical_data
        self.forecast: List[DataPoint] = []
        self.confidence = 0.0

    def generate_forecast(self, days_ahead: int = 30):
        """Generate cost forecast using simple linear regression."""
        if len(self.historical) < 7:
            return

        n = len(self.historical)
        x_vals = list(range(n))
        y_vals = [p.value for p in self.historical]

        x_mean = sum(x_vals) / n
        y_mean = sum(y_vals) / n

        numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_vals, y_vals))
        denominator = sum((x - x_mean) ** 2 for x in x_vals)

        slope = numerator / denominator if denominator != 0 else 0
        intercept = y_mean - slope * x_mean

        last_date = self.historical[-1].timestamp
        for i in range(1, days_ahead + 1):
            forecast_date = last_date + timedelta(days=i)
            forecast_value = max(0, intercept + slope * (n + i - 1))
            self.forecast.append(DataPoint(
                forecast_date,
                round(forecast_value, 2),
                f"Forecast Day {i}"
            ))

        y_pred = [intercept + slope * x for x in x_vals]
        ss_res = sum((y - yp) ** 2 for y, yp in zip(y_vals, y_pred))
        ss_tot = sum((y - y_mean) ** 2 for y in y_vals)
        self.confidence = 1 - (ss_res / ss_tot) if ss_tot != 0 else 0

    def get_monthly_projection(self) -> float:
        """Get projected cost for next 30 days."""
        if not self.forecast:
            self.generate_forecast(30)
        return sum(p.value for p in self.forecast[:30])

    def to_dict(self) -> Dict:
        return {
            'historical': [p.to_dict() for p in self.historical],
            'forecast': [p.to_dict() for p in self.forecast],
            'confidence': round(self.confidence * 100, 1),
            'monthly_projection': round(self.get_monthly_projection(), 2)
        }


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

    def _get_infra_model(self):
        from models import InfrastructureResource
        return InfrastructureResource

    def _get_incident_model(self):
        from models import IncidentModel
        return IncidentModel

    def _get_usage_log_model(self):
        from models import UsageLog
        return UsageLog

    def _has_connected_account(self) -> bool:
        """Whether this user has at least one active cloud credential connected."""
        if self.user_id is None:
            return False
        from models import UserCloudCredential
        return UserCloudCredential.query.filter_by(
            user_id=self.user_id, is_active=True
        ).first() is not None

    @staticmethod
    def _coerce_day(value) -> datetime:
        """Normalize a SQL date/func.date() result (str on SQLite, date on Postgres) to datetime."""
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            return datetime.strptime(value[:10], '%Y-%m-%d')
        return datetime(value.year, value.month, value.day)

    def _daily_count_series(self, series_name: str, metric_type: 'MetricType', unit: str,
                             model, timestamp_column, lookback_days: int) -> TimeSeries:
        """Build a real per-day count series for a user-scoped model over the lookback window."""
        series = TimeSeries(series_name, metric_type)
        series.unit = unit
        if self.user_id is None:
            return series

        from sqlalchemy import func
        db = self._get_db()
        since = datetime.utcnow() - timedelta(days=lookback_days)
        rows = (
            db.session.query(
                func.date(timestamp_column).label('day'),
                func.count(model.id).label('count'),
            )
            .filter(model.user_id == self.user_id, timestamp_column >= since)
            .group_by(func.date(timestamp_column))
            .order_by(func.date(timestamp_column))
            .all()
        )
        for row in rows:
            series.add_point(self._coerce_day(row.day), row.count)
        return series

    def _cost_time_series(self) -> TimeSeries:
        """Current total monthly cost as a single real data point.

        There is no persisted daily cost history yet, so this reports the real
        current snapshot rather than fabricating a 90-day trend.
        """
        series = TimeSeries('daily_cost', MetricType.COST)
        series.unit = 'USD'
        if not self._has_connected_account() or self.user_id is None:
            return series

        InfrastructureResource = self._get_infra_model()
        resources = InfrastructureResource.query.filter(
            InfrastructureResource.user_id == self.user_id,
            InfrastructureResource.status != 'terminated',
        ).all()
        total = sum(r.monthly_cost or 0.0 for r in resources)
        series.add_point(datetime.utcnow(), round(total, 2), 'Current')
        return series

    def _resource_count_time_series(self) -> TimeSeries:
        """Current resource count as a single real data point (no historical count is tracked)."""
        series = TimeSeries('resource_count', MetricType.RESOURCES)
        series.unit = 'count'
        if self.user_id is None:
            return series

        InfrastructureResource = self._get_infra_model()
        count = InfrastructureResource.query.filter(
            InfrastructureResource.user_id == self.user_id,
            InfrastructureResource.status != 'terminated',
        ).count()
        series.add_point(datetime.utcnow(), count, 'Current')
        return series

    def _incidents_time_series(self) -> TimeSeries:
        """Real per-day incident counts from IncidentModel.triggered_at."""
        IncidentModel = self._get_incident_model()
        return self._daily_count_series(
            'incidents', MetricType.INCIDENTS, 'count',
            IncidentModel, IncidentModel.triggered_at, lookback_days=90,
        )

    def _api_calls_time_series(self) -> TimeSeries:
        """Real per-day tool/API call counts from UsageLog."""
        UsageLog = self._get_usage_log_model()
        return self._daily_count_series(
            'api_calls', MetricType.API_CALLS, 'calls',
            UsageLog, UsageLog.created_at, lookback_days=30,
        )

    def _deployments_time_series(self) -> TimeSeries:
        """No deployment record model exists yet — report empty rather than infer/fabricate."""
        series = TimeSeries('deployments', MetricType.DEPLOYMENTS)
        series.unit = 'count'
        return series

    _SERIES_BUILDERS = {
        'daily_cost': '_cost_time_series',
        'resource_count': '_resource_count_time_series',
        'incidents': '_incidents_time_series',
        'deployments': '_deployments_time_series',
        'api_calls': '_api_calls_time_series',
    }

    def get_time_series(self, name: str, time_range: TimeRange = TimeRange.MONTH) -> Optional[TimeSeries]:
        """Get real time series data for a known metric name, filtered to the requested range."""
        builder_name = self._SERIES_BUILDERS.get(name)
        if not builder_name:
            return None
        series = getattr(self, builder_name)()

        now = datetime.utcnow()
        if time_range == TimeRange.HOUR:
            cutoff = now - timedelta(hours=1)
        elif time_range == TimeRange.DAY:
            cutoff = now - timedelta(days=1)
        elif time_range == TimeRange.WEEK:
            cutoff = now - timedelta(weeks=1)
        elif time_range == TimeRange.MONTH:
            cutoff = now - timedelta(days=30)
        elif time_range == TimeRange.QUARTER:
            cutoff = now - timedelta(days=90)
        else:
            cutoff = now - timedelta(days=365)

        filtered = TimeSeries(series.name, series.metric_type)
        filtered.unit = series.unit
        filtered.data_points = [p for p in series.data_points if p.timestamp >= cutoff]
        return filtered

    def get_cost_forecast(self, days_ahead: int = 30) -> CostForecast:
        """Get cost forecast from real cost history.

        No daily cost history is persisted yet (only a current snapshot), so this
        currently always returns an empty forecast (CostForecast requires 7+ real
        historical points before it will project) rather than fabricating one.
        """
        cost_series = self._cost_time_series()
        if not cost_series.data_points:
            return CostForecast([])

        forecast = CostForecast(cost_series.data_points)
        forecast.generate_forecast(days_ahead)
        return forecast

    def get_cost_breakdown(self) -> Dict:
        """Get real cost breakdown by resource type, from the user's synced infrastructure."""
        by_service: Dict[str, float] = {}
        if self._has_connected_account() and self.user_id is not None:
            InfrastructureResource = self._get_infra_model()
            resources = InfrastructureResource.query.filter(
                InfrastructureResource.user_id == self.user_id,
                InfrastructureResource.status != 'terminated',
            ).all()
            for r in resources:
                key = (r.resource_type or 'other').upper()
                by_service[key] = round(by_service.get(key, 0.0) + (r.monthly_cost or 0.0), 2)

        return {
            'by_service': by_service,
            # No team/cost-center attribution exists on InfrastructureResource yet.
            'by_team': {},
            'total': round(sum(by_service.values()), 2),
        }

    def get_trend_analysis(self, metric: str) -> Dict:
        """Analyze trends for a metric using real data."""
        series = self.get_time_series(metric, TimeRange.QUARTER)
        if not series or len(series.data_points) < 7:
            return {'error': 'Insufficient data'}

        values = [p.value for p in series.data_points]

        ma_7 = []
        ma_30 = []
        for i in range(len(values)):
            if i >= 6:
                ma_7.append(sum(values[i-6:i+1]) / 7)
            if i >= 29:
                ma_30.append(sum(values[i-29:i+1]) / 30)

        current_value = values[-1]
        week_ago = values[-8] if len(values) > 7 else values[0]
        month_ago = values[-31] if len(values) > 30 else values[0]

        week_change = ((current_value - week_ago) / week_ago * 100) if week_ago != 0 else 0
        month_change = ((current_value - month_ago) / month_ago * 100) if month_ago != 0 else 0

        return {
            'current': current_value,
            'week_change': round(week_change, 1),
            'month_change': round(month_change, 1),
            'trend': series.get_trend(),
            'summary': series.get_summary()
        }

    def get_dashboard_metrics(self, days: int = 30) -> Dict:
        """Get key metrics for dashboard."""
        cost_series = self.get_time_series('daily_cost', TimeRange.MONTH)
        resource_series = self.get_time_series('resource_count', TimeRange.MONTH)
        incident_series = self.get_time_series('incidents', TimeRange.MONTH)
        deploy_series = self.get_time_series('deployments', TimeRange.MONTH)

        return {
            'cost': {
                'current_month': sum(p.value for p in cost_series.data_points) if cost_series else 0,
                'trend': cost_series.get_trend() if cost_series else 'stable',
                'forecast': self.get_cost_forecast().get_monthly_projection()
            },
            'resources': {
                'total': resource_series.data_points[-1].value if resource_series and resource_series.data_points else 0,
                'trend': resource_series.get_trend() if resource_series else 'stable'
            },
            'incidents': {
                'this_month': sum(p.value for p in incident_series.data_points) if incident_series else 0,
                'trend': incident_series.get_trend() if incident_series else 'stable'
            },
            'deployments': {
                'this_month': sum(p.value for p in deploy_series.data_points) if deploy_series else 0,
                'trend': deploy_series.get_trend() if deploy_series else 'stable'
            }
        }

    def get_chart_data(self, metric: str, time_range: TimeRange, aggregation: AggregationType = AggregationType.SUM) -> Dict:
        """Get formatted chart data."""
        series = self.get_time_series(metric, time_range)
        if not series:
            return {'labels': [], 'data': [], 'unit': ''}

        if time_range in [TimeRange.HOUR, TimeRange.DAY]:
            labels = [p.timestamp.strftime('%H:%M') for p in series.data_points]
            data = [p.value for p in series.data_points]
        elif time_range == TimeRange.WEEK:
            labels = [p.timestamp.strftime('%a %d') for p in series.data_points]
            data = [p.value for p in series.data_points]
        else:
            daily_data: Dict[str, List[float]] = {}
            for p in series.data_points:
                key = p.timestamp.strftime('%Y-%m-%d')
                if key not in daily_data:
                    daily_data[key] = []
                daily_data[key].append(p.value)

            labels = list(daily_data.keys())
            if aggregation == AggregationType.SUM:
                data = [sum(v) for v in daily_data.values()]
            elif aggregation == AggregationType.AVG:
                data = [sum(v)/len(v) for v in daily_data.values()]
            elif aggregation == AggregationType.MAX:
                data = [max(v) for v in daily_data.values()]
            elif aggregation == AggregationType.MIN:
                data = [min(v) for v in daily_data.values()]
            else:
                data = [len(v) for v in daily_data.values()]

        return {
            'labels': labels[-60:],
            'data': [round(d, 2) for d in data[-60:]],
            'unit': series.unit,
            'summary': series.get_summary()
        }

    def get_cost_analytics(self, start_date: datetime, end_date: datetime) -> Dict:
        """Get cost analytics for a date range."""
        breakdown = self.get_cost_breakdown()
        days = max(1, (end_date - start_date).days)
        time_range = TimeRange.MONTH if days >= 28 else TimeRange.WEEK if days >= 7 else TimeRange.DAY
        cost_series = self.get_time_series('daily_cost', time_range)
        trend_data = []
        if cost_series:
            trend_data = [p.to_dict() for p in cost_series.data_points]
        return {
            'by_service': breakdown['by_service'],
            'by_team': breakdown['by_team'],
            'by_resource': breakdown['by_service'],  # alias for resource view
            'total': breakdown['total'],
            'trend': trend_data,
            'period_days': days,
        }

    def forecast_costs(self, days: int = 30) -> Dict:
        """Get cost forecast. Returns to_dict() of CostForecast."""
        return self.get_cost_forecast(days_ahead=days).to_dict()

    def get_resource_utilization(self) -> Dict:
        """Get real resource utilization summary from synced infrastructure."""
        by_type: Dict[str, int] = {}
        if self.user_id is not None:
            from sqlalchemy import func
            db = self._get_db()
            InfrastructureResource = self._get_infra_model()
            rows = (
                db.session.query(InfrastructureResource.resource_type, func.count(InfrastructureResource.id))
                .filter(
                    InfrastructureResource.user_id == self.user_id,
                    InfrastructureResource.status != 'terminated',
                )
                .group_by(InfrastructureResource.resource_type)
                .all()
            )
            by_type = {rtype: count for rtype, count in rows}

        resource_series = self.get_time_series('resource_count', TimeRange.MONTH)
        trend = resource_series.get_trend() if resource_series else 'stable'
        return {
            'total_resources': sum(by_type.values()),
            'trend': trend,
            'by_type': by_type,
            # No CPU/memory monitoring source (e.g. CloudWatch) is wired in yet.
            'utilization_avg': None,
        }

    def get_alerts_summary(self, days: int = 7) -> Dict:
        """Get real alerts/incidents summary for the given number of days."""
        empty = {'total': 0, 'critical': 0, 'high': 0, 'medium': 0, 'low': 0,
                  'resolved': 0, 'open': 0, 'trend': 'stable'}
        if self.user_id is None:
            return empty

        IncidentModel = self._get_incident_model()
        since = datetime.utcnow() - timedelta(days=days)
        incidents = IncidentModel.query.filter(
            IncidentModel.user_id == self.user_id,
            IncidentModel.triggered_at >= since,
        ).all()

        total = len(incidents)
        by_severity = {'critical': 0, 'high': 0, 'medium': 0, 'low': 0}
        resolved = 0
        for incident in incidents:
            severity = (incident.severity or '').lower()
            if severity in by_severity:
                by_severity[severity] += 1
            if incident.status in ('resolved', 'closed'):
                resolved += 1

        incident_series = self.get_time_series('incidents', TimeRange.WEEK if days <= 7 else TimeRange.MONTH)
        return {
            'total': total,
            'critical': by_severity['critical'],
            'high': by_severity['high'],
            'medium': by_severity['medium'],
            'low': by_severity['low'],
            'resolved': resolved,
            'open': total - resolved,
            'trend': incident_series.get_trend() if incident_series else 'stable',
        }

    def get_deployment_stats(self, days: int = 30) -> Dict:
        """Get deployment statistics for the given number of days.

        No deployment-record model exists in this app yet (CI/CD tool calls are chat
        actions, not deployment records) — report zeros/unavailable rather than infer
        or fabricate one.
        """
        return {
            'total': 0,
            'successful': 0,
            'failed': 0,
            'success_rate': None,
            'avg_duration_minutes': None,
            'trend': 'stable',
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
