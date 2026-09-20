"""
Infrastructure Health Score

Calculates an A–F letter grade for a user's cloud infrastructure based on:
  - Open critical security findings   (-20 pts each, up to -60)
  - Open high security findings        (-8 pts each, up to -24)
  - Cost waste > $100/mo               (-10 pts per $100 waste, up to -30)
  - Unresolved incidents (past 7 days) (-5 pts each, up to -20)
  - Active critical alerts             (-5 pts each, up to -15)

Starting score is 100. Minimum is 0.

Grade thresholds:
  A  90–100
  B  75–89
  C  60–74
  D  45–59
  F  0–44
"""

from datetime import datetime, timedelta
from typing import Dict, Any
from src.utils.timeutils import utcnow


def calculate_health_score(user_id: int) -> Dict[str, Any]:
    """
    Calculate infrastructure health score for a user.

    Returns a dict:
        grade         str     'A' | 'B' | 'C' | 'D' | 'F'
        score         int     0–100
        color         str     CSS color class name
        breakdown     dict    per-category deductions and labels
        last_updated  str     ISO timestamp
    """
    from models import SecurityFinding, CostOptimization, IncidentModel, Alert

    score = 100
    breakdown = []

    # ── Security findings ────────────────────────────────────────────────────
    critical_sec = SecurityFinding.query.filter_by(
        user_id=user_id, status='open', severity='critical'
    ).count()
    high_sec = SecurityFinding.query.filter_by(
        user_id=user_id, status='open', severity='high'
    ).count()

    crit_deduction = min(critical_sec * 20, 60)
    high_deduction = min(high_sec * 8, 24)
    score -= crit_deduction + high_deduction

    if critical_sec > 0:
        breakdown.append({
            'category': 'Critical security findings',
            'value': critical_sec,
            'deduction': crit_deduction,
            'color': 'red',
        })
    if high_sec > 0:
        breakdown.append({
            'category': 'High severity findings',
            'value': high_sec,
            'deduction': high_deduction,
            'color': 'orange',
        })

    # ── Cost waste ───────────────────────────────────────────────────────────
    from models import db
    total_waste = db.session.query(
        db.func.sum(CostOptimization.potential_monthly_savings)
    ).filter_by(user_id=user_id, status='pending').scalar() or 0.0

    waste_deduction = min(int(total_waste / 100) * 10, 30)
    score -= waste_deduction

    if total_waste > 100:
        breakdown.append({
            'category': 'Cost waste',
            'value': f'${total_waste:.0f}/mo',
            'deduction': waste_deduction,
            'color': 'yellow',
        })

    # ── Recent incidents (past 7 days) ───────────────────────────────────────
    week_ago = utcnow() - timedelta(days=7)
    recent_incidents = IncidentModel.query.filter(
        IncidentModel.user_id == user_id,
        IncidentModel.triggered_at >= week_ago,
        IncidentModel.status != 'resolved'
    ).count()

    incident_deduction = min(recent_incidents * 5, 20)
    score -= incident_deduction

    if recent_incidents > 0:
        breakdown.append({
            'category': 'Unresolved incidents (7d)',
            'value': recent_incidents,
            'deduction': incident_deduction,
            'color': 'orange',
        })

    # ── Active critical alerts ───────────────────────────────────────────────
    critical_alerts = Alert.query.filter_by(
        user_id=user_id, status='active', severity='critical'
    ).count()

    alert_deduction = min(critical_alerts * 5, 15)
    score -= alert_deduction

    if critical_alerts > 0:
        breakdown.append({
            'category': 'Active critical alerts',
            'value': critical_alerts,
            'deduction': alert_deduction,
            'color': 'red',
        })

    # ── Grade ────────────────────────────────────────────────────────────────
    score = max(0, score)

    if score >= 90:
        grade, color = 'A', 'green'
    elif score >= 75:
        grade, color = 'B', 'blue'
    elif score >= 60:
        grade, color = 'C', 'yellow'
    elif score >= 45:
        grade, color = 'D', 'orange'
    else:
        grade, color = 'F', 'red'

    # Add a positive note if no deductions
    if not breakdown:
        breakdown.append({
            'category': 'No critical issues found',
            'value': '',
            'deduction': 0,
            'color': 'green',
        })

    return {
        'grade': grade,
        'score': score,
        'color': color,
        'breakdown': breakdown,
        'last_updated': utcnow().isoformat(),
    }


def get_grade_label(grade: str) -> str:
    return {
        'A': 'Excellent',
        'B': 'Good',
        'C': 'Fair',
        'D': 'Poor',
        'F': 'Critical',
    }.get(grade, 'Unknown')
