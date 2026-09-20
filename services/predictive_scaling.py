"""
Predictive Scaling Service for DevOps Agent.

Uses historical metrics and patterns to predict future resource needs
and generate proactive scaling recommendations.
"""

import logging
import math
from datetime import datetime, timedelta
from typing import Any, Optional
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict
from src.utils.timeutils import utcnow

logger = logging.getLogger(__name__)


class ScalingDirection(Enum):
    """Direction of scaling action."""
    SCALE_UP = "scale_up"
    SCALE_DOWN = "scale_down"
    NO_CHANGE = "no_change"


class ResourceCategory(Enum):
    """Categories of scalable resources."""
    COMPUTE = "compute"
    CONTAINER = "container"
    DATABASE = "database"
    SERVERLESS = "serverless"
    CACHE = "cache"


class ConfidenceLevel(Enum):
    """Confidence level of prediction."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class MetricDataPoint:
    """A single metric observation."""
    timestamp: datetime
    value: float
    resource_id: str


@dataclass
class ScalingPrediction:
    """A predictive scaling recommendation."""
    id: str
    resource_type: str
    resource_id: str
    resource_name: str
    category: ResourceCategory
    direction: ScalingDirection
    current_capacity: int
    recommended_capacity: int
    predicted_peak: float
    predicted_time: datetime
    confidence: ConfidenceLevel
    reasoning: str
    potential_savings: float  # Monthly $ if scaling down
    risk_if_ignored: str
    created_at: datetime = field(default_factory=utcnow)


@dataclass
class ScalingPattern:
    """Detected usage pattern."""
    pattern_type: str  # daily, weekly, monthly, event-based
    peak_hours: list[int]
    peak_days: list[int]  # 0=Monday
    average_utilization: float
    peak_utilization: float
    growth_rate: float  # % per month


class PredictiveScalingService:
    """
    Service for predictive auto-scaling recommendations.

    Features:
    - Analyze historical metrics to detect patterns
    - Predict future resource needs
    - Generate proactive scaling recommendations
    - Estimate cost savings from right-sizing
    """

    def __init__(self):
        # All keyed by user_id for data isolation
        self.metrics: dict[int, dict[str, list[MetricDataPoint]]] = defaultdict(lambda: defaultdict(list))
        self.predictions: dict[int, list[ScalingPrediction]] = defaultdict(list)
        self.patterns: dict[int, dict[str, ScalingPattern]] = defaultdict(dict)
        # Resources a real metrics source has registered for this user, keyed by
        # resource_id. Empty until something calls register_resource() with real
        # data (e.g. a future CloudWatch/Prometheus ingestion path) — intentionally
        # never pre-populated with sample entries.
        self.resource_registry: dict[int, dict[str, dict]] = defaultdict(dict)

    def register_resource(self, user_id: int, resource_id: str, name: str,
                           resource_type: str, category: ResourceCategory,
                           current_capacity: int, max_capacity: int):
        """Register a real resource so generate_all_predictions() can analyze it."""
        self.resource_registry[user_id][resource_id] = {
            'name': name,
            'type': resource_type,
            'category': category,
            'current': current_capacity,
            'max': max_capacity,
        }

    def add_metric(self, user_id: int, resource_id: str, value: float, timestamp: datetime = None):
        """Add a metric data point."""
        self.metrics[user_id][resource_id].append(MetricDataPoint(
            timestamp=timestamp or utcnow(),
            value=value,
            resource_id=resource_id
        ))

    def analyze_patterns(self, user_id: int, resource_id: str) -> Optional[ScalingPattern]:
        """Analyze metrics to detect usage patterns."""
        data = self.metrics[user_id].get(resource_id, [])

        if len(data) < 24:  # Need at least 24 hours of data
            return None

        # Analyze hourly patterns
        hourly_avg = defaultdict(list)
        daily_avg = defaultdict(list)

        for point in data:
            hourly_avg[point.timestamp.hour].append(point.value)
            daily_avg[point.timestamp.weekday()].append(point.value)

        # Find peak hours
        hour_means = {h: sum(v)/len(v) for h, v in hourly_avg.items()}
        avg_value = sum(hour_means.values()) / len(hour_means)
        peak_hours = [h for h, v in hour_means.items() if v > avg_value * 1.2]

        # Find peak days
        day_means = {d: sum(v)/len(v) for d, v in daily_avg.items()}
        peak_days = [d for d, v in day_means.items() if v > avg_value * 1.1]

        # Calculate growth rate
        if len(data) >= 168:  # 1 week
            first_week_avg = sum(p.value for p in data[:84]) / 84
            second_week_avg = sum(p.value for p in data[84:]) / min(84, len(data) - 84)
            growth_rate = ((second_week_avg - first_week_avg) / first_week_avg) * 100 * 4  # Monthly
        else:
            growth_rate = 0

        pattern = ScalingPattern(
            pattern_type='daily' if peak_hours else 'steady',
            peak_hours=sorted(peak_hours),
            peak_days=sorted(peak_days),
            average_utilization=avg_value,
            peak_utilization=max(p.value for p in data),
            growth_rate=growth_rate
        )

        self.patterns[user_id][resource_id] = pattern
        return pattern

    def predict_scaling_needs(self, user_id: int, resource_id: str, resource_name: str,
                              resource_type: str, category: ResourceCategory,
                              current_capacity: int, max_capacity: int,
                              utilization_threshold: float = 80) -> Optional[ScalingPrediction]:
        """Generate scaling prediction for a resource."""
        import uuid

        # Analyze patterns first
        pattern = self.analyze_patterns(user_id, resource_id)

        if not pattern:
            return None

        data = self.metrics[user_id].get(resource_id, [])

        # Simple forecasting: use exponential smoothing
        recent_values = [p.value for p in data[-24:]]  # Last 24 hours
        avg_recent = sum(recent_values) / len(recent_values)
        trend = (recent_values[-1] - recent_values[0]) / len(recent_values) if recent_values else 0

        # Predict next peak (within 24 hours)
        predicted_peak = pattern.peak_utilization + (trend * 24)

        # Factor in growth rate
        monthly_growth = pattern.growth_rate / 100
        days_ahead = 7
        growth_factor = 1 + (monthly_growth * days_ahead / 30)
        predicted_peak *= growth_factor

        # Determine if scaling is needed
        if predicted_peak > utilization_threshold:
            direction = ScalingDirection.SCALE_UP
            # Calculate recommended capacity
            scale_factor = predicted_peak / 60  # Target 60% utilization after scaling
            recommended = math.ceil(current_capacity * scale_factor)
            recommended = min(recommended, max_capacity)

            reasoning = f"Predicted peak of {predicted_peak:.1f}% exceeds threshold. "
            reasoning += f"Pattern shows peaks at hours {pattern.peak_hours}. "
            if pattern.growth_rate > 5:
                reasoning += f"Growth rate of {pattern.growth_rate:.1f}%/month detected."

            risk = "Service degradation or outage during peak hours"
            savings = 0

        elif pattern.average_utilization < 30 and pattern.peak_utilization < 50:
            direction = ScalingDirection.SCALE_DOWN
            scale_factor = pattern.peak_utilization / 60  # Target 60% utilization at peak
            recommended = max(1, math.ceil(current_capacity * scale_factor))

            # Estimate savings (rough estimate: $50/month per unit)
            savings = (current_capacity - recommended) * 50

            reasoning = f"Average utilization of {pattern.average_utilization:.1f}% suggests over-provisioning. "
            reasoning += f"Peak utilization is only {pattern.peak_utilization:.1f}%."

            risk = "None - resource is significantly over-provisioned"

        else:
            direction = ScalingDirection.NO_CHANGE
            recommended = current_capacity
            reasoning = f"Current capacity is appropriate. Avg: {pattern.average_utilization:.1f}%, Peak: {pattern.peak_utilization:.1f}%"
            risk = "None"
            savings = 0

        # Determine confidence
        if len(data) >= 168:  # 1+ weeks of data
            confidence = ConfidenceLevel.HIGH
        elif len(data) >= 72:  # 3+ days
            confidence = ConfidenceLevel.MEDIUM
        else:
            confidence = ConfidenceLevel.LOW

        # Find next predicted peak time
        now = utcnow()
        if pattern.peak_hours:
            next_peak_hour = min((h for h in pattern.peak_hours if h > now.hour), default=pattern.peak_hours[0])
            if next_peak_hour <= now.hour:
                predicted_time = now.replace(hour=next_peak_hour, minute=0) + timedelta(days=1)
            else:
                predicted_time = now.replace(hour=next_peak_hour, minute=0)
        else:
            predicted_time = now + timedelta(hours=4)

        prediction = ScalingPrediction(
            id=str(uuid.uuid4())[:8],
            resource_type=resource_type,
            resource_id=resource_id,
            resource_name=resource_name,
            category=category,
            direction=direction,
            current_capacity=current_capacity,
            recommended_capacity=recommended,
            predicted_peak=predicted_peak,
            predicted_time=predicted_time,
            confidence=confidence,
            reasoning=reasoning,
            potential_savings=savings,
            risk_if_ignored=risk
        )

        self.predictions[user_id].append(prediction)
        return prediction

    def generate_all_predictions(self, user_id: int) -> list[ScalingPrediction]:
        """Generate predictions for resources with real recorded metric history.

        Deliberately does NOT fabricate resources or metrics — a resource only
        gets a prediction once something has fed it real data via add_metric()
        (e.g. a future CloudWatch/Prometheus ingestion path). No cloud metrics
        source is wired in yet, so this returns an empty list until one is;
        that must never be papered over with sample data (see CLAUDE.md's
        "every feature runs against a real cloud account" rule — this file
        previously seeded three hardcoded fake resources for every user).
        """
        predictions = []
        for resource_id, resource_config in self.resource_registry.get(user_id, {}).items():
            prediction = self.predict_scaling_needs(
                user_id=user_id,
                resource_id=resource_id,
                resource_name=resource_config['name'],
                resource_type=resource_config['type'],
                category=resource_config['category'],
                current_capacity=resource_config['current'],
                max_capacity=resource_config['max']
            )
            if prediction:
                predictions.append(prediction)

        return predictions

    def get_predictions(self, user_id: int, category: Optional[ResourceCategory] = None,
                        direction: Optional[ScalingDirection] = None) -> list[ScalingPrediction]:
        """Get recent predictions with optional filtering."""
        predictions = self.predictions.get(user_id, [])

        if category:
            predictions = [p for p in predictions if p.category == category]

        if direction:
            predictions = [p for p in predictions if p.direction == direction]

        return sorted(predictions, key=lambda p: p.created_at, reverse=True)

    def get_summary(self, user_id: int) -> dict:
        """Get summary of scaling recommendations."""
        user_predictions = self.predictions.get(user_id, [])
        scale_up = [p for p in user_predictions if p.direction == ScalingDirection.SCALE_UP]
        scale_down = [p for p in user_predictions if p.direction == ScalingDirection.SCALE_DOWN]

        total_savings = sum(p.potential_savings for p in scale_down)

        return {
            'total_predictions': len(user_predictions),
            'scale_up_recommendations': len(scale_up),
            'scale_down_recommendations': len(scale_down),
            'no_change': len(user_predictions) - len(scale_up) - len(scale_down),
            'potential_monthly_savings': total_savings,
            'high_confidence_count': sum(1 for p in user_predictions if p.confidence == ConfidenceLevel.HIGH),
            'resources_analyzed': len(self.metrics.get(user_id, {}))
        }

    def get_pattern(self, user_id: int, resource_id: str) -> Optional[ScalingPattern]:
        """Get the detected pattern for a resource."""
        return self.patterns.get(user_id, {}).get(resource_id)


# Global instance
_scaling_service: Optional[PredictiveScalingService] = None


def get_scaling_service() -> PredictiveScalingService:
    """Get or create the global predictive scaling service."""
    global _scaling_service
    if _scaling_service is None:
        _scaling_service = PredictiveScalingService()
    return _scaling_service
