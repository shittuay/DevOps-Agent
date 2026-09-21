"""
Advanced Analytics Service for DevOps Agent.

Provides charts, trends, cost forecasting, and usage analytics — all sourced from
the user's real connected cloud account (AWS Cost Explorer / CloudWatch via
services/cost_explorer.py) and this app's own per-user tables
(InfrastructureResource, IncidentModel, UsageLog). No metric here may be
fabricated: a user with no cloud account connected and no synced resources sees
zeros/empty series, never invented numbers. See CLAUDE.md's "every feature runs
against a real cloud account" rule.
"""

import logging
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from enum import Enum

logger = logging.getLogger(__name__)

# Tool names that represent an actual deployment/pipeline action taken by the
# user. Used to derive real "deployment" activity from UsageLog rather than
# inventing one — this app has no dedicated Deployment model.
_DEPLOYMENT_TOOL_NAMES = {
    'trigger_jenkins_job', 'trigger_github_workflow', 'trigger_gitlab_pipeline',
    'rerun_failed_github_jobs', 'deploy_cloud_run_service', 'docker_compose_up',
    'terraform_apply',
}


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


_RANGE_DAYS = {
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
    """Cost forecasting model — simple linear regression over REAL historical
    daily costs. No random noise: the previous implementation added
    ``random.uniform()`` variance on top of already-fabricated history, which
    made every projection fiction twice over."""

    def __init__(self, historical_data: List[DataPoint]):
        self.historical = historical_data
        self.forecast: List[DataPoint] = []
        self.confidence = 0.0

    def generate_forecast(self, days_ahead: int = 30):
        """Generate cost forecast using simple linear regression over real history."""
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
            'monthly_projection': round(self.get_monthly_projection(), 2),
            'source': 'linear_regression',
        }


class AnalyticsService:
    """Service for advanced analytics with database persistence.

    Every read method below is scoped to ``self.user_id`` and sources data from
    the user's real cloud account or this app's own per-user tables — never
    hardcoded or randomly-generated values. A user with no cloud account
    connected and nothing synced yet sees empty/zeroed results, not fiction.
    """

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

    def _resource_query(self):
        """Real, non-terminated infrastructure resources synced for this user."""
        from models import InfrastructureResource
        excluded_statuses = ['terminated', 'deleted', 'deleting', 'shutting-down']
        query = InfrastructureResource.query
        if self.user_id is not None:
            query = query.filter_by(user_id=self.user_id)
        return query.filter(~InfrastructureResource.status.in_(excluded_statuses))

    # ---- Cost ------------------------------------------------------------

    def _real_cost_breakdown(self, days: int) -> Dict:
        """By-service cost breakdown: AWS Cost Explorer first, real synced
        resource costs as fallback. Never fabricated — matches the pattern
        already used by app.py's /api/dashboard/costs."""
        if self.user_id is None:
            return {'by_service': {}, 'total': 0.0, 'daily_trend': [], 'source': 'no_user'}

        try:
            from services.cost_explorer import get_actual_costs
            costs = get_actual_costs(self.user_id, days=days)
            by_service = {s['service']: s['cost'] for s in costs.get('services', [])}
            return {
                'by_service': by_service,
                'total': costs.get('total_cost', 0.0),
                'daily_trend': costs.get('daily_trend', []),
                'source': 'cost_explorer',
            }
        except Exception as e:
            logger.info(
                "Cost Explorer unavailable for user %s, falling back to synced resource costs: %s",
                self.user_id, e,
            )

        from models import InfrastructureResource
        db = self._get_db()
        rows = db.session.query(
            InfrastructureResource.resource_type,
            db.func.sum(InfrastructureResource.monthly_cost)
        ).filter_by(user_id=self.user_id).group_by(InfrastructureResource.resource_type).all()
        by_service = {(r[0] or 'other'): round(float(r[1] or 0), 2) for r in rows}
        return {
            'by_service': by_service,
            'total': round(sum(by_service.values()), 2),
            'daily_trend': [],
            'source': 'database',
        }

    def get_cost_breakdown(self) -> Dict:
        """Get cost breakdown by service. ``by_team`` has no real backing data
        in this schema (no per-team cost attribution exists), so it is left
        empty rather than invented."""
        breakdown = self._real_cost_breakdown(days=30)
        return {
            'by_service': breakdown['by_service'],
            'by_team': {},
            'total': breakdown['total'],
            'source': breakdown['source'],
        }

    def get_cost_forecast(self, days_ahead: int = 30) -> CostForecast:
        """Get cost forecast built from real historical daily costs."""
        breakdown = self._real_cost_breakdown(days=max(days_ahead, 30))
        historical = [
            DataPoint(datetime.strptime(d['date'], '%Y-%m-%d'), d['cost'])
            for d in breakdown.get('daily_trend', [])
        ]
        forecast = CostForecast(historical)
        forecast.generate_forecast(days_ahead)
        return forecast

    def get_cost_analytics(self, start_date: datetime, end_date: datetime) -> Dict:
        """Get cost analytics for a date range."""
        days = max(1, (end_date - start_date).days)
        breakdown = self._real_cost_breakdown(days=days)
        trend_data = [
            {'timestamp': d['date'], 'value': d['cost'], 'label': d['date']}
            for d in breakdown.get('daily_trend', [])
        ]
        return {
            'by_service': breakdown['by_service'],
            'by_team': {},
            'by_resource': breakdown['by_service'],  # alias for resource view
            'total': breakdown['total'],
            'trend': trend_data,
            'period_days': days,
            'source': breakdown['source'],
        }

    def forecast_costs(self, days: int = 30) -> Dict:
        """Get cost forecast. Returns to_dict() of CostForecast."""
        return self.get_cost_forecast(days_ahead=days).to_dict()

    # ---- Time series / trends ---------------------------------------------

    def get_time_series(self, name: str, time_range: TimeRange = TimeRange.MONTH) -> Optional[TimeSeries]:
        """Get a real time series for one of the known metric names, bucketed
        daily over the requested range. Returns None for an unknown name."""
        days = _RANGE_DAYS.get(time_range, 30)
        builders = {
            'daily_cost': self._series_daily_cost,
            'resource_count': self._series_resource_count,
            'incidents': self._series_incidents,
            'deployments': self._series_deployments,
            'api_calls': self._series_api_calls,
        }
        builder = builders.get(name)
        if builder is None:
            return None
        return builder(days)

    def _series_daily_cost(self, days: int) -> TimeSeries:
        series = TimeSeries('daily_cost', MetricType.COST)
        series.unit = 'USD'
        breakdown = self._real_cost_breakdown(days=days)
        for d in breakdown.get('daily_trend', []):
            series.add_point(datetime.strptime(d['date'], '%Y-%m-%d'), d['cost'])
        return series

    def _series_resource_count(self, days: int) -> TimeSeries:
        """Cumulative count of currently-tracked resources by the date each was
        first synced. This only reflects resources still on record (removed
        ones drop out of the running total), which is an honest limitation of
        not keeping a historical resource-count table — never randomly
        generated."""
        series = TimeSeries('resource_count', MetricType.RESOURCES)
        series.unit = 'count'
        if self.user_id is None:
            return series

        from models import InfrastructureResource
        cutoff = datetime.utcnow() - timedelta(days=days)
        resources = self._resource_query().order_by(InfrastructureResource.created_at).all()
        if not resources:
            return series

        baseline = sum(1 for r in resources if r.created_at and r.created_at < cutoff)
        by_day: Dict[str, int] = {}
        for r in resources:
            if not r.created_at or r.created_at < cutoff:
                continue
            key = r.created_at.strftime('%Y-%m-%d')
            by_day[key] = by_day.get(key, 0) + 1

        running_total = baseline
        for key in sorted(by_day.keys()):
            running_total += by_day[key]
            series.add_point(datetime.strptime(key, '%Y-%m-%d'), running_total)

        if not series.data_points:
            series.add_point(datetime.utcnow(), len(resources))
        return series

    def _series_incidents(self, days: int) -> TimeSeries:
        series = TimeSeries('incidents', MetricType.INCIDENTS)
        series.unit = 'count'
        if self.user_id is None:
            return series

        from models import IncidentModel
        cutoff = datetime.utcnow() - timedelta(days=days)
        incidents = IncidentModel.query.filter(
            IncidentModel.user_id == self.user_id,
            IncidentModel.triggered_at >= cutoff,
        ).all()

        by_day: Dict[str, int] = {}
        for i in incidents:
            if not i.triggered_at:
                continue
            key = i.triggered_at.strftime('%Y-%m-%d')
            by_day[key] = by_day.get(key, 0) + 1

        for key in sorted(by_day.keys()):
            series.add_point(datetime.strptime(key, '%Y-%m-%d'), by_day[key])
        return series

    def _series_deployments(self, days: int) -> TimeSeries:
        series = TimeSeries('deployments', MetricType.DEPLOYMENTS)
        series.unit = 'count'
        if self.user_id is None:
            return series

        from models import UsageLog
        cutoff = datetime.utcnow() - timedelta(days=days)
        rows = UsageLog.query.filter(
            UsageLog.user_id == self.user_id,
            UsageLog.tool_name.in_(_DEPLOYMENT_TOOL_NAMES),
            UsageLog.created_at >= cutoff,
        ).all()

        by_day: Dict[str, int] = {}
        for r in rows:
            key = r.created_at.strftime('%Y-%m-%d')
            by_day[key] = by_day.get(key, 0) + 1

        for key in sorted(by_day.keys()):
            series.add_point(datetime.strptime(key, '%Y-%m-%d'), by_day[key])
        return series

    def _series_api_calls(self, days: int) -> TimeSeries:
        series = TimeSeries('api_calls', MetricType.API_CALLS)
        series.unit = 'calls'
        if self.user_id is None:
            return series

        from models import UsageLog
        cutoff = datetime.utcnow() - timedelta(days=days)
        rows = UsageLog.query.filter(
            UsageLog.user_id == self.user_id,
            UsageLog.tool_name.isnot(None),
            UsageLog.created_at >= cutoff,
        ).all()

        by_day: Dict[str, int] = {}
        for r in rows:
            key = r.created_at.strftime('%Y-%m-%d')
            by_day[key] = by_day.get(key, 0) + 1

        for key in sorted(by_day.keys()):
            series.add_point(datetime.strptime(key, '%Y-%m-%d'), by_day[key])
        return series

    def get_trend_analysis(self, metric: str) -> Dict:
        """Analyze trends for a metric."""
        series = self.get_time_series(metric, TimeRange.QUARTER)
        if not series or len(series.data_points) < 7:
            return {'error': 'Insufficient data'}

        values = [p.value for p in series.data_points]

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

    # ---- Dashboard summary --------------------------------------------

    def get_dashboard_metrics(self, days: int = 30) -> Dict:
        """Get key metrics for dashboard — all real, per-user."""
        cost_series = self.get_time_series('daily_cost', TimeRange.MONTH)
        resource_series = self.get_time_series('resource_count', TimeRange.MONTH)
        incident_series = self.get_time_series('incidents', TimeRange.MONTH)
        deploy_series = self.get_time_series('deployments', TimeRange.MONTH)

        cost_total = self._real_cost_breakdown(days=days).get('total', 0)

        return {
            'cost': {
                'current_month': cost_total,
                'trend': cost_series.get_trend() if cost_series else 'stable',
                'forecast': self.get_cost_forecast().get_monthly_projection()
            },
            'resources': {
                'total': self._resource_query().count(),
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

    # ---- Resources ------------------------------------------------------

    def get_resource_utilization(self) -> Dict:
        """Get resource utilization summary from real synced resources and,
        where possible, real CloudWatch metrics. ``utilization_avg`` is only
        populated when live metrics could actually be read; otherwise it is
        left at 0 rather than a plausible-looking invented figure."""
        resources = list(self._resource_query())
        total = len(resources)
        by_type: Dict[str, int] = {}
        for r in resources:
            by_type[r.resource_type] = by_type.get(r.resource_type, 0) + 1

        utilization_avg = self._sample_ec2_cpu_average(resources)

        return {
            'total_resources': total,
            'trend': self._series_resource_count(30).get_trend(),
            'by_type': by_type,
            'utilization_avg': utilization_avg,
        }

    def _sample_ec2_cpu_average(self, resources: List[Any], sample_size: int = 5) -> float:
        """Average real CloudWatch CPU utilization across a bounded sample of
        this user's running EC2 instances. Returns 0.0 (not a fabricated
        figure) when there is nothing to sample or the account can't be read."""
        if self.user_id is None:
            return 0.0

        ec2_instances = [
            r for r in resources
            if r.resource_type == 'ec2' and r.status == 'running'
        ][:sample_size]
        if not ec2_instances:
            return 0.0

        try:
            from services.cost_explorer import get_instance_utilization
        except Exception:
            return 0.0

        samples = []
        for r in ec2_instances:
            try:
                util = get_instance_utilization(self.user_id, r.resource_id, days=1)
                cpu_avg = util.get('cpu', {}).get('average')
                if cpu_avg is not None:
                    samples.append(cpu_avg)
            except Exception:
                continue

        if not samples:
            return 0.0
        return round(sum(samples) / len(samples), 1)

    # ---- Alerts / incidents ---------------------------------------------

    def get_alerts_summary(self, days: int = 7) -> Dict:
        """Get alerts summary for the given number of days — real IncidentModel rows."""
        if self.user_id is None:
            return {'total': 0, 'critical': 0, 'high': 0, 'medium': 0, 'low': 0,
                    'resolved': 0, 'open': 0, 'trend': 'stable'}

        from models import IncidentModel
        cutoff = datetime.utcnow() - timedelta(days=days)
        incidents = IncidentModel.query.filter(
            IncidentModel.user_id == self.user_id,
            IncidentModel.triggered_at >= cutoff,
        ).all()

        total = len(incidents)
        critical = sum(1 for i in incidents if i.severity == 'critical')
        high = sum(1 for i in incidents if i.severity == 'high')
        medium = sum(1 for i in incidents if i.severity == 'medium')
        low = sum(1 for i in incidents if i.severity == 'low')
        resolved = sum(1 for i in incidents if i.status in ('resolved', 'closed'))
        open_count = total - resolved

        prior_cutoff = cutoff - timedelta(days=days)
        prior_total = IncidentModel.query.filter(
            IncidentModel.user_id == self.user_id,
            IncidentModel.triggered_at >= prior_cutoff,
            IncidentModel.triggered_at < cutoff,
        ).count()
        if prior_total == 0:
            trend = 'up' if total > 0 else 'stable'
        else:
            change = (total - prior_total) / prior_total
            trend = 'up' if change > 0.05 else 'down' if change < -0.05 else 'stable'

        return {
            'total': total,
            'critical': critical,
            'high': high,
            'medium': medium,
            'low': low,
            'resolved': resolved,
            'open': open_count,
            'trend': trend,
        }

    def get_incident_stats(self, days: int = 30) -> Dict:
        """Get incident statistics for the given number of days."""
        return self.get_alerts_summary(days=days)

    # ---- Deployments ------------------------------------------------------

    def get_deployment_stats(self, days: int = 30) -> Dict:
        """Get deployment statistics derived from real CI/CD tool calls
        (UsageLog). There is no dedicated Deployment model in this app, so
        this counts actual tool invocations rather than inventing figures.
        ``avg_duration_minutes`` is omitted — call duration isn't tracked."""
        if self.user_id is None:
            return {'total': 0, 'successful': 0, 'failed': 0, 'success_rate': 0.0, 'trend': 'stable'}

        from models import UsageLog
        cutoff = datetime.utcnow() - timedelta(days=days)
        rows = UsageLog.query.filter(
            UsageLog.user_id == self.user_id,
            UsageLog.tool_name.in_(_DEPLOYMENT_TOOL_NAMES),
            UsageLog.created_at >= cutoff,
        ).all()

        total = len(rows)
        successful = sum(1 for r in rows if r.success)
        failed = total - successful
        success_rate = round(successful / total * 100, 1) if total else 0.0

        deploy_series = self._series_deployments(days)

        return {
            'total': total,
            'successful': successful,
            'failed': failed,
            'success_rate': success_rate,
            'trend': deploy_series.get_trend(),
        }

    # ---- Dashboard Management with Database Persistence -------------------

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
