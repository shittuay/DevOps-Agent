"""
Advanced Analytics Service for DevOps Agent.

Provides charts, trends, cost breakdowns, and usage analytics — backed by
real per-user data only (synced cloud resources, real incidents, real
infrastructure-change audit rows, real tool-usage logs). Uses database
persistence for dashboards and widgets.

Every method that reports a metric fails closed with a clear
`data_available: False` / `message` when the user has no connected cloud
account and nothing has ever been synced, rather than inventing numbers.
See CLAUDE.md's "every feature runs against a real cloud account" rule and
CLAUDE_RUNBOOK.md's analytics-fabrication entry — this file used to seed a
90-day fake cost/incident/deployment/API-call history plus hardcoded
per-service and per-team dollar figures via `_ensure_sample_data()`, and
`get_resource_utilization()` returned a fresh `random.uniform(40, 75)`
"utilization_avg" on every call.
"""

import logging
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from enum import Enum

logger = logging.getLogger(__name__)


class AnalyticsDataError(Exception):
    """Raised internally when a metric cannot be computed because the user
    has no connected cloud account and nothing has ever been synced.

    Mirrors `drift_detection.DriftScanError`: "there is nothing real to show
    yet" and "here is your real data" are different conclusions, and
    reporting the first as the second (by falling back to sample data) is
    exactly the bug this service was fixed for. Every public method that
    would otherwise compute real-but-derived data catches this itself and
    returns an explicit no-data shape — callers/routes never need to know
    about this exception.
    """


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
    """Cost forecasting model — pure linear regression over real historical
    data points. Deliberately has no randomness of its own; the caller
    (`AnalyticsService.forecast_costs`) never invokes `generate_forecast()`
    today because this app does not collect the day-by-day cost history a
    real forecast needs (only the latest synced snapshot). Kept as the
    reusable algorithm for whenever a real cost-history source exists.
    """

    def __init__(self, historical_data: List[DataPoint]):
        self.historical = historical_data
        self.forecast: List[DataPoint] = []
        self.confidence = 0.0

    def generate_forecast(self, days_ahead: int = 30):
        """Generate cost forecast using simple linear regression over
        `self.historical` — the caller is responsible for ensuring that
        data is real."""
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
    """Service for advanced analytics with database persistence.

    Every metric is either a real SQL aggregation over this user's own rows
    (`InfrastructureResource`, `IncidentModel`, `InfrastructureChange`,
    `UsageLog`) or is explicitly reported as unavailable. Nothing here
    fabricates a value.
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

    # ------------------------------------------------------------------
    # Real-data gating
    # ------------------------------------------------------------------

    def _has_data_source(self) -> bool:
        """True once this user has a live, verified cloud credential, or has
        any real row that could only exist because of one — synced
        infrastructure, a real incident, or a real audited change — real
        signals only. Never assumed true."""
        if not self.user_id:
            return False
        try:
            from services.credential_service import get_user_configured_providers
            if any(get_user_configured_providers(self.user_id).values()):
                return True
        except Exception:
            logger.exception("analytics: failed to check configured providers for user %s", self.user_id)

        from models import InfrastructureResource, IncidentModel, InfrastructureChange
        if InfrastructureResource.query.filter_by(user_id=self.user_id).first() is not None:
            return True
        if IncidentModel.query.filter_by(user_id=self.user_id).first() is not None:
            return True
        if InfrastructureChange.query.filter_by(user_id=self.user_id).first() is not None:
            return True
        return False

    def _require_data_source(self) -> None:
        if not self._has_data_source():
            raise AnalyticsDataError(
                'No cloud account connected. Connect an AWS, Azure, or GCP '
                'account in Settings to see real analytics data.'
            )

    @staticmethod
    def _real_trend(timestamps: List[Optional[datetime]], days: int) -> str:
        """Trend direction from real event timestamps only (incidents,
        infrastructure changes) — splits the window in half and compares
        counts. 'stable' is the honest default when there isn't enough
        signal to say more, matching `TimeSeries.get_trend()`'s own
        fallback above."""
        timestamps = [t for t in timestamps if t]
        if not timestamps or days < 2:
            return 'stable'
        now = datetime.utcnow()
        mid = now - timedelta(days=days / 2)
        start = now - timedelta(days=days)
        recent = sum(1 for t in timestamps if t >= mid)
        older = sum(1 for t in timestamps if start <= t < mid)
        if older == 0:
            return 'up' if recent > 0 else 'stable'
        change = (recent - older) / older
        if change > 0.1:
            return 'up'
        if change < -0.1:
            return 'down'
        return 'stable'

    @staticmethod
    def _range_cutoff(time_range: TimeRange, now: datetime) -> datetime:
        if time_range == TimeRange.HOUR:
            return now - timedelta(hours=1)
        elif time_range == TimeRange.DAY:
            return now - timedelta(days=1)
        elif time_range == TimeRange.WEEK:
            return now - timedelta(weeks=1)
        elif time_range == TimeRange.MONTH:
            return now - timedelta(days=30)
        elif time_range == TimeRange.QUARTER:
            return now - timedelta(days=90)
        return now - timedelta(days=365)

    @staticmethod
    def _bucket_daily(name: str, metric_type: MetricType, unit: str,
                       timestamps: List[Optional[datetime]]) -> TimeSeries:
        """Build a real daily-count TimeSeries from real event timestamps."""
        series = TimeSeries(name, metric_type)
        series.unit = unit
        counts: Dict[Any, int] = {}
        for t in timestamps:
            if not t:
                continue
            key = t.date()
            counts[key] = counts.get(key, 0) + 1
        for day in sorted(counts):
            series.add_point(datetime.combine(day, datetime.min.time()), counts[day])
        return series

    # ------------------------------------------------------------------
    # Time series (real sources only; 'daily_cost' has none — see
    # forecast_costs()'s docstring)
    # ------------------------------------------------------------------

    def get_time_series(self, name: str, time_range: TimeRange = TimeRange.MONTH) -> Optional[TimeSeries]:
        """Real time series only, built from this user's own timestamped
        rows. Returns None when there's no real source for `name`, or when
        the user has no connected/previously-synced cloud account — never a
        sample series."""
        if not self._has_data_source():
            return None

        now = datetime.utcnow()
        cutoff = self._range_cutoff(time_range, now)

        if name == 'daily_cost':
            # No historical cost data is ever collected — InfrastructureResource
            # stores only the latest synced snapshot per resource (overwritten
            # in place by services/infrastructure_sync.py on every sync), not a
            # day-by-day history. Reporting a fabricated trend here was the
            # original bug; report "no series" instead until real cost history
            # is tracked.
            return None

        if name == 'resource_count':
            from models import InfrastructureResource
            earlier_count = (
                InfrastructureResource.query
                .filter(
                    InfrastructureResource.user_id == self.user_id,
                    InfrastructureResource.created_at < cutoff,
                )
                .count()
            )
            rows = (
                InfrastructureResource.query
                .filter(
                    InfrastructureResource.user_id == self.user_id,
                    InfrastructureResource.created_at >= cutoff,
                )
                .order_by(InfrastructureResource.created_at)
                .all()
            )
            series = TimeSeries(name, MetricType.RESOURCES)
            series.unit = 'count'
            by_day: Dict[Any, int] = {}
            for r in rows:
                if not r.created_at:
                    continue
                key = r.created_at.date()
                by_day[key] = by_day.get(key, 0) + 1
            running_total = earlier_count
            for day in sorted(by_day):
                running_total += by_day[day]
                series.add_point(datetime.combine(day, datetime.min.time()), running_total)
            return series

        if name == 'incidents':
            from models import IncidentModel
            rows = IncidentModel.query.filter(
                IncidentModel.user_id == self.user_id,
                IncidentModel.triggered_at >= cutoff,
            ).all()
            return self._bucket_daily(name, MetricType.INCIDENTS, 'count',
                                       [r.triggered_at for r in rows])

        if name == 'deployments':
            from models import InfrastructureChange
            rows = InfrastructureChange.query.filter(
                InfrastructureChange.user_id == self.user_id,
                InfrastructureChange.created_at >= cutoff,
            ).all()
            return self._bucket_daily(name, MetricType.DEPLOYMENTS, 'count',
                                       [r.created_at for r in rows])

        if name == 'api_calls':
            from models import UsageLog
            rows = UsageLog.query.filter(
                UsageLog.user_id == self.user_id,
                UsageLog.created_at >= cutoff,
            ).all()
            return self._bucket_daily(name, MetricType.API_CALLS, 'calls',
                                       [r.created_at for r in rows])

        return None

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

    def get_trend_analysis(self, metric: str) -> Dict:
        """Analyze trends for a metric, from its real time series."""
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

    # ------------------------------------------------------------------
    # Cost — real per-resource costs synced from live cloud APIs
    # (services/infrastructure_sync.py). No per-team breakdown or daily
    # history exists anywhere in this codebase (see docstrings below).
    # ------------------------------------------------------------------

    def get_cost_breakdown(self) -> Dict:
        """Cost breakdown by service, aggregated from real synced
        `InfrastructureResource` rows (`monthly_cost` is estimated per
        resource from a live cloud API read — see
        services/infrastructure_sync.py's `calculate_*_cost` helpers).

        `by_team` is intentionally always empty/unavailable: no resource in
        this codebase is ever associated with a `Team` row (the `Team`
        model exists for org membership only), so a per-team cost split has
        no real data to compute from. Previously this returned a hardcoded
        `{'Development': 380.00, 'Production': 420.00, ...}` dict, byte
        identical for every user.
        """
        try:
            self._require_data_source()
            from models import InfrastructureResource
            from sqlalchemy import func
            db = self._get_db()
            rows = (
                db.session.query(
                    InfrastructureResource.resource_type,
                    func.sum(InfrastructureResource.monthly_cost).label('total'),
                )
                .filter(InfrastructureResource.user_id == self.user_id)
                .group_by(InfrastructureResource.resource_type)
                .all()
            )
            by_service = {
                (r.resource_type or 'other').upper(): round(r.total or 0.0, 2)
                for r in rows
            }
            return {
                'by_service': by_service,
                'by_team': {},
                'by_team_available': False,
                'total': round(sum(by_service.values()), 2),
                'data_available': True,
            }
        except AnalyticsDataError as e:
            return {
                'by_service': {},
                'by_team': {},
                'by_team_available': False,
                'total': 0,
                'data_available': False,
                'message': str(e),
            }

    def get_cost_analytics(self, start_date: datetime, end_date: datetime) -> Dict:
        """Get cost analytics for a date range. The date range is accepted
        for API compatibility; it cannot select a historical slice because
        no cost history is stored (see `forecast_costs()`), so this
        currently reports the same real current-snapshot breakdown
        regardless of range."""
        breakdown = self.get_cost_breakdown()
        days = max(1, (end_date - start_date).days)
        return {
            'by_service': breakdown['by_service'],
            'by_team': breakdown['by_team'],
            'by_team_available': breakdown['by_team_available'],
            'by_resource': breakdown['by_service'],  # alias for resource view
            'total': breakdown['total'],
            'trend': [],
            'trend_available': False,
            'period_days': days,
            'data_available': breakdown['data_available'],
            'message': breakdown.get('message'),
        }

    def get_cost_forecast(self, days_ahead: int = 30) -> CostForecast:
        """Kept for API compatibility. Always returns an empty
        `CostForecast` — see `forecast_costs()`'s docstring for why a real
        forecast isn't computed here."""
        return CostForecast([])

    def forecast_costs(self, days: int = 30) -> Dict:
        """Cost forecast. NEVER fabricated with random noise.

        Real forecasting needs day-by-day historical cost data, and nothing
        in this codebase collects that yet — `InfrastructureResource`
        stores only the latest synced snapshot per resource, overwritten in
        place on every sync, not a time series. Previously this generated a
        90-day fake history (`base_cost = 150` + `random.uniform(-20, 30)`
        noise) and then added `random.uniform(-0.05, 0.05)` noise on top of
        the linear-regression forecast itself. Until a real cost-history
        source exists, this reports `status: 'insufficient_data'` rather
        than inventing numbers a user could act on for a real budget
        decision.
        """
        try:
            self._require_data_source()
        except AnalyticsDataError as e:
            return {
                'status': 'no_account',
                'message': str(e),
                'historical': [],
                'forecast': [],
                'confidence': 0,
                'monthly_projection': None,
                'data_available': False,
            }
        return {
            'status': 'insufficient_data',
            'message': (
                'Cost forecasting needs day-by-day historical cost data. '
                'This app currently only stores the latest synced snapshot '
                'per resource, not a history, so there is not yet enough '
                'data to forecast from.'
            ),
            'historical': [],
            'forecast': [],
            'confidence': 0,
            'monthly_projection': None,
            'data_available': True,
        }

    # ------------------------------------------------------------------
    # Resources — real counts from synced InfrastructureResource rows.
    # CPU/memory utilization has no real source wired in (would need a
    # live CloudWatch/Prometheus metrics pull) so it is reported as
    # unavailable rather than randomly generated.
    # ------------------------------------------------------------------

    def get_resource_utilization(self) -> Dict:
        """Resource counts by type are real. `utilization_avg` (CPU/memory)
        is NOT available — this service has no live metrics source
        (CloudWatch/Prometheus) wired in; previously this was
        `random.uniform(40, 75)` regenerated on every single call.
        """
        try:
            self._require_data_source()
            from models import InfrastructureResource
            resources = InfrastructureResource.query.filter_by(user_id=self.user_id).all()
            by_type: Dict[str, int] = {}
            for r in resources:
                key = r.resource_type or 'other'
                by_type[key] = by_type.get(key, 0) + 1
            trend = self._real_trend([r.created_at for r in resources], 30)
            return {
                'total_resources': len(resources),
                'by_type': by_type,
                'utilization_avg': None,
                'utilization_available': False,
                'trend': trend,
                'data_available': True,
            }
        except AnalyticsDataError as e:
            return {
                'total_resources': 0,
                'by_type': {},
                'utilization_avg': None,
                'utilization_available': False,
                'trend': 'stable',
                'data_available': False,
                'message': str(e),
            }

    # ------------------------------------------------------------------
    # Incidents / alerts — real, from IncidentModel (created by
    # services/incident_response.py from real monitoring events).
    # ------------------------------------------------------------------

    def get_alerts_summary(self, days: int = 7) -> Dict:
        """Incident/alert counts and severity breakdown, real — aggregated
        from this user's `IncidentModel` rows."""
        try:
            self._require_data_source()
            from models import IncidentModel
            cutoff = datetime.utcnow() - timedelta(days=days)
            rows = IncidentModel.query.filter(
                IncidentModel.user_id == self.user_id,
                IncidentModel.triggered_at >= cutoff,
            ).all()
            total = len(rows)
            by_sev = {'critical': 0, 'high': 0, 'medium': 0, 'low': 0}
            resolved = 0
            for r in rows:
                if r.severity in by_sev:
                    by_sev[r.severity] += 1
                if r.status == 'resolved':
                    resolved += 1
            trend = self._real_trend([r.triggered_at for r in rows], days)
            return {
                'total': total,
                'critical': by_sev['critical'],
                'high': by_sev['high'],
                'medium': by_sev['medium'],
                'low': by_sev['low'],
                'resolved': resolved,
                'open': total - resolved,
                'trend': trend,
                'data_available': True,
            }
        except AnalyticsDataError as e:
            return {
                'total': 0, 'critical': 0, 'high': 0, 'medium': 0, 'low': 0,
                'resolved': 0, 'open': 0, 'trend': 'stable',
                'data_available': False, 'message': str(e),
            }

    def get_incident_stats(self, days: int = 30) -> Dict:
        """Get incident statistics for the given number of days."""
        return self.get_alerts_summary(days=days)

    # ------------------------------------------------------------------
    # Deployments — real, from InfrastructureChange (written by
    # src/agent/core.py's _audit_infrastructure_change() when a
    # create/resize/security-group-modify tool succeeds from chat).
    # ------------------------------------------------------------------

    def get_deployment_stats(self, days: int = 30) -> Dict:
        """Real count of audited infrastructure changes in the period.

        `_audit_infrastructure_change()` only ever writes a row when the
        underlying tool call *succeeds* (`if not result.get('success'):
        return`), so there is no real failure signal to report here — every
        row is by definition a successful, executed change, and average
        duration isn't tracked at all. Previously this was a hardcoded
        92%/8% success/fail split with `random.uniform(5, 20)` minutes as
        "avg duration"; both are now reported as not tracked rather than
        invented.
        """
        try:
            self._require_data_source()
            from models import InfrastructureChange
            cutoff = datetime.utcnow() - timedelta(days=days)
            rows = InfrastructureChange.query.filter(
                InfrastructureChange.user_id == self.user_id,
                InfrastructureChange.created_at >= cutoff,
            ).all()
            trend = self._real_trend([r.created_at for r in rows], days)
            return {
                'total': len(rows),
                'successful': None,
                'failed': None,
                'success_rate': None,
                'success_rate_available': False,
                'avg_duration_minutes': None,
                'duration_available': False,
                'trend': trend,
                'data_available': True,
            }
        except AnalyticsDataError as e:
            return {
                'total': 0, 'successful': None, 'failed': None,
                'success_rate': None, 'success_rate_available': False,
                'avg_duration_minutes': None, 'duration_available': False,
                'trend': 'stable', 'data_available': False, 'message': str(e),
            }

    # ------------------------------------------------------------------
    # Dashboard summary — composes the real methods above.
    # ------------------------------------------------------------------

    def get_dashboard_metrics(self, days: int = 30) -> Dict:
        """Get key metrics for dashboard, real end to end."""
        try:
            self._require_data_source()
        except AnalyticsDataError as e:
            return {
                'data_available': False,
                'message': str(e),
                'cost': {'current_month': 0, 'trend': 'stable', 'forecast': None, 'forecast_status': 'no_account'},
                'resources': {'total': 0, 'trend': 'stable'},
                'incidents': {'this_month': 0, 'trend': 'stable'},
                'deployments': {'this_month': 0, 'trend': 'stable'},
            }

        cost_breakdown = self.get_cost_breakdown()
        resource_util = self.get_resource_utilization()
        alerts = self.get_alerts_summary(days=days)
        deployments = self.get_deployment_stats(days=days)
        forecast = self.forecast_costs(days=30)

        return {
            'data_available': True,
            'cost': {
                'current_month': cost_breakdown['total'],
                # No historical cost series exists to compare against — see
                # forecast_costs()'s docstring. 'stable' is the honest
                # neutral default, same semantics as TimeSeries.get_trend().
                'trend': 'stable',
                'trend_available': False,
                'forecast': forecast.get('monthly_projection'),
                'forecast_status': forecast.get('status'),
            },
            'resources': {
                'total': resource_util['total_resources'],
                'trend': resource_util['trend'],
            },
            'incidents': {
                'this_month': alerts['total'],
                'trend': alerts['trend'],
            },
            'deployments': {
                'this_month': deployments['total'],
                'trend': deployments['trend'],
            },
        }

    # ------------------------------------------------------------------
    # Dashboard Management with Database Persistence
    # ------------------------------------------------------------------

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
