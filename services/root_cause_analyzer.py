"""
AI-Powered Root Cause Analysis Service for DevOps Agent.

Uses Claude to analyze incidents, logs, metrics, and system state
to identify root causes and suggest remediation steps.

Persisted to DB with per-user isolation.
"""

import logging
import json
from datetime import datetime
from typing import Any, Optional
from dataclasses import dataclass, field
from enum import Enum
import os
from src.utils.timeutils import utcnow

logger = logging.getLogger(__name__)


class AnalysisStatus(Enum):
    PENDING = "pending"
    ANALYZING = "analyzing"
    COMPLETED = "completed"
    FAILED = "failed"


class ConfidenceLevel(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    VERY_HIGH = "very_high"


@dataclass
class RootCause:
    id: str
    title: str
    description: str
    confidence: ConfidenceLevel
    evidence: list[str]
    affected_components: list[str]
    remediation_steps: list[str]
    prevention_measures: list[str]
    related_incidents: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "confidence": self.confidence.value,
            "evidence": self.evidence,
            "affected_components": self.affected_components,
            "remediation_steps": self.remediation_steps,
            "prevention_measures": self.prevention_measures,
            "related_incidents": self.related_incidents,
        }


@dataclass
class AnalysisResult:
    id: str
    incident_id: str
    status: AnalysisStatus
    root_causes: list[RootCause]
    summary: str
    timeline_analysis: str
    impact_assessment: str
    recommendations: list[str]
    analyzed_at: datetime
    analysis_duration_seconds: float
    data_sources_used: list[str]
    db_id: int = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "incident_id": self.incident_id,
            "status": self.status.value,
            "root_causes": [rc.to_dict() for rc in self.root_causes],
            "summary": self.summary,
            "timeline_analysis": self.timeline_analysis,
            "impact_assessment": self.impact_assessment,
            "recommendations": self.recommendations,
            "analyzed_at": self.analyzed_at.isoformat(),
            "analysis_duration_seconds": self.analysis_duration_seconds,
            "data_sources_used": self.data_sources_used,
        }


class RootCauseAnalyzer:
    """
    AI-powered root cause analysis engine.

    Per-user isolation with DB persistence and in-memory cache.
    """

    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.environ.get('ANTHROPIC_API_KEY')
        self._user_analyses: dict[int, dict[str, AnalysisResult]] = {}
        self._users_loaded: set[int] = set()
        self._app = None
        self._client = None

    def set_app(self, app):
        self._app = app

    def _get_client(self):
        if self._client is None:
            try:
                import anthropic
                self._client = anthropic.Anthropic(api_key=self.api_key)
            except ImportError:
                logger.error("anthropic package not installed")
                return None
        return self._client

    # ---- User loading ----

    def _ensure_user_loaded(self, user_id: int):
        if user_id in self._users_loaded:
            return
        if not self._app:
            self._user_analyses.setdefault(user_id, {})
            self._users_loaded.add(user_id)
            return

        with self._app.app_context():
            from models import AnalysisModel

            db_rows = AnalysisModel.query.filter_by(user_id=user_id).order_by(
                AnalysisModel.analyzed_at.desc()
            ).limit(200).all()

            analyses = {}
            for row in db_rows:
                root_causes = self._deserialize_root_causes(row.root_causes or [])
                result = AnalysisResult(
                    id=row.analysis_key,
                    incident_id=row.incident_id or 'unknown',
                    status=AnalysisStatus(row.status or 'completed'),
                    root_causes=root_causes,
                    summary=row.summary or '',
                    timeline_analysis=row.timeline_analysis or '',
                    impact_assessment=row.impact_assessment or '',
                    recommendations=row.recommendations or [],
                    analyzed_at=row.analyzed_at or utcnow(),
                    analysis_duration_seconds=row.analysis_duration_seconds or 0.0,
                    data_sources_used=row.data_sources_used or [],
                    db_id=row.id,
                )
                analyses[row.analysis_key] = result

            self._user_analyses[user_id] = analyses
            self._users_loaded.add(user_id)

    def _deserialize_root_causes(self, rc_list: list) -> list[RootCause]:
        confidence_map = {
            'low': ConfidenceLevel.LOW,
            'medium': ConfidenceLevel.MEDIUM,
            'high': ConfidenceLevel.HIGH,
            'very_high': ConfidenceLevel.VERY_HIGH,
        }
        results = []
        for rc in rc_list:
            results.append(RootCause(
                id=rc.get('id', 'rc1'),
                title=rc.get('title', 'Unknown'),
                description=rc.get('description', ''),
                confidence=confidence_map.get(rc.get('confidence', 'medium'), ConfidenceLevel.MEDIUM),
                evidence=rc.get('evidence', []),
                affected_components=rc.get('affected_components', []),
                remediation_steps=rc.get('remediation_steps', []),
                prevention_measures=rc.get('prevention_measures', []),
                related_incidents=rc.get('related_incidents', []),
            ))
        return results

    # ---- DB persistence ----

    def _save_to_db(self, user_id: int, result: AnalysisResult):
        if not self._app:
            return
        try:
            with self._app.app_context():
                from models import AnalysisModel, db

                row = AnalysisModel(
                    user_id=user_id,
                    analysis_key=result.id,
                    incident_id=result.incident_id,
                    status=result.status.value,
                    summary=result.summary,
                    timeline_analysis=result.timeline_analysis,
                    impact_assessment=result.impact_assessment,
                    root_causes=[rc.to_dict() for rc in result.root_causes],
                    recommendations=result.recommendations,
                    data_sources_used=result.data_sources_used,
                    analysis_duration_seconds=result.analysis_duration_seconds,
                    analyzed_at=result.analyzed_at,
                )
                db.session.add(row)
                db.session.commit()
                result.db_id = row.id
        except Exception as e:
            logger.error(f"Failed to persist analysis: {e}")

    # ---- Public API (all user-scoped) ----

    def analyze_incident(self, user_id: int, incident_data: dict,
                         logs: list[str] = None,
                         metrics: dict = None,
                         related_events: list[dict] = None) -> AnalysisResult:
        """Perform root cause analysis on an incident for a specific user."""
        import uuid
        import time

        self._ensure_user_loaded(user_id)

        analysis_id = str(uuid.uuid4())[:8]
        start_time = time.time()

        context = self._build_analysis_context(
            incident_data, logs, metrics, related_events
        )

        try:
            analysis = self._perform_ai_analysis(context)

            result = AnalysisResult(
                id=analysis_id,
                incident_id=incident_data.get('id', 'unknown'),
                status=AnalysisStatus.COMPLETED,
                root_causes=analysis['root_causes'],
                summary=analysis['summary'],
                timeline_analysis=analysis['timeline_analysis'],
                impact_assessment=analysis['impact_assessment'],
                recommendations=analysis['recommendations'],
                analyzed_at=utcnow(),
                analysis_duration_seconds=time.time() - start_time,
                data_sources_used=self._get_data_sources(logs, metrics, related_events)
            )

        except Exception as e:
            logger.error(f"Root cause analysis failed: {e}")
            result = AnalysisResult(
                id=analysis_id,
                incident_id=incident_data.get('id', 'unknown'),
                status=AnalysisStatus.FAILED,
                root_causes=[],
                summary=f"Analysis failed: {str(e)}",
                timeline_analysis="",
                impact_assessment="",
                recommendations=[],
                analyzed_at=utcnow(),
                analysis_duration_seconds=time.time() - start_time,
                data_sources_used=[]
            )

        self._user_analyses[user_id][analysis_id] = result
        self._save_to_db(user_id, result)
        return result

    def get_analysis(self, user_id: int, analysis_id: str) -> Optional[AnalysisResult]:
        self._ensure_user_loaded(user_id)
        return self._user_analyses.get(user_id, {}).get(analysis_id)

    def get_analyses_for_incident(self, user_id: int, incident_id: str) -> list[AnalysisResult]:
        self._ensure_user_loaded(user_id)
        return [a for a in self._user_analyses.get(user_id, {}).values()
                if a.incident_id == incident_id]

    def get_all_analyses(self, user_id: int) -> list[dict]:
        self._ensure_user_loaded(user_id)
        analyses = list(self._user_analyses.get(user_id, {}).values())
        analyses.sort(key=lambda a: a.analyzed_at, reverse=True)
        return [a.to_dict() for a in analyses]

    # ---- AI analysis (unchanged) ----

    def _build_analysis_context(self, incident_data: dict,
                                 logs: list[str] = None,
                                 metrics: dict = None,
                                 related_events: list[dict] = None) -> str:
        context_parts = []

        context_parts.append("## Incident Information")
        context_parts.append(f"Title: {incident_data.get('title', 'Unknown')}")
        context_parts.append(f"Description: {incident_data.get('description', 'No description')}")
        context_parts.append(f"Severity: {incident_data.get('severity', 'Unknown')}")
        context_parts.append(f"Status: {incident_data.get('status', 'Unknown')}")
        context_parts.append(f"Source: {incident_data.get('source', 'Unknown')}")

        if incident_data.get('triggered_at'):
            context_parts.append(f"Triggered At: {incident_data['triggered_at']}")

        if incident_data.get('timeline'):
            context_parts.append("\n## Timeline")
            for event in incident_data['timeline']:
                context_parts.append(f"- {event.get('timestamp', 'Unknown')}: {event.get('event', '')} - {event.get('details', '')}")

        if incident_data.get('actions_taken'):
            context_parts.append("\n## Actions Taken")
            for action in incident_data['actions_taken']:
                result = "Success" if action.get('result', {}).get('success') else "Failed"
                context_parts.append(f"- {action.get('action', 'Unknown')}: {result}")

        if logs:
            context_parts.append("\n## Relevant Logs")
            for log in logs[:50]:
                context_parts.append(f"  {log}")

        if metrics:
            context_parts.append("\n## System Metrics")
            for metric_name, metric_value in metrics.items():
                context_parts.append(f"- {metric_name}: {metric_value}")

        if related_events:
            context_parts.append("\n## Related Events")
            for event in related_events[:20]:
                context_parts.append(f"- {event.get('timestamp', 'Unknown')}: {event.get('type', '')} - {event.get('description', '')}")

        return "\n".join(context_parts)

    def _perform_ai_analysis(self, context: str) -> dict:
        client = self._get_client()

        if client is None:
            return self._perform_fallback_analysis(context)

        prompt = f"""You are an expert Site Reliability Engineer performing root cause analysis on an incident.

Analyze the following incident data and provide a detailed root cause analysis.

{context}

Provide your analysis in the following JSON format:
{{
    "summary": "A brief summary of the incident and its root cause",
    "timeline_analysis": "Analysis of the sequence of events leading to the incident",
    "impact_assessment": "Assessment of the impact on users and systems",
    "root_causes": [
        {{
            "id": "rc1",
            "title": "Primary Root Cause Title",
            "description": "Detailed description of the root cause",
            "confidence": "high|medium|low",
            "evidence": ["Evidence point 1", "Evidence point 2"],
            "affected_components": ["component1", "component2"],
            "remediation_steps": ["Step 1", "Step 2"],
            "prevention_measures": ["Measure 1", "Measure 2"]
        }}
    ],
    "recommendations": ["Recommendation 1", "Recommendation 2", "Recommendation 3"]
}}

Focus on:
1. Identifying the primary root cause with supporting evidence
2. Understanding the chain of events
3. Providing actionable remediation steps
4. Suggesting preventive measures for the future

Return ONLY valid JSON, no additional text."""

        try:
            response = client.messages.create(
                model="claude-sonnet-4-5-20250929",
                max_tokens=2000,
                messages=[{"role": "user", "content": prompt}]
            )

            response_text = response.content[0].text

            import re
            json_match = re.search(r'\{[\s\S]*\}', response_text)
            if json_match:
                analysis = json.loads(json_match.group())
            else:
                analysis = json.loads(response_text)

            root_causes = self._deserialize_root_causes(analysis.get('root_causes', []))

            return {
                'summary': analysis.get('summary', 'Analysis completed'),
                'timeline_analysis': analysis.get('timeline_analysis', ''),
                'impact_assessment': analysis.get('impact_assessment', ''),
                'root_causes': root_causes,
                'recommendations': analysis.get('recommendations', []),
            }

        except Exception as e:
            logger.error(f"AI analysis failed: {e}")
            return self._perform_fallback_analysis(context)

    def _perform_fallback_analysis(self, context: str) -> dict:
        root_causes = []
        recommendations = []

        context_lower = context.lower()

        if 'cpu' in context_lower and ('high' in context_lower or '80' in context_lower or '90' in context_lower):
            root_causes.append(RootCause(
                id="rc-cpu", title="High CPU Utilization",
                description="The system experienced high CPU utilization which may have caused performance degradation.",
                confidence=ConfidenceLevel.MEDIUM,
                evidence=["CPU metrics indicate elevated usage"],
                affected_components=["compute", "application"],
                remediation_steps=["Identify CPU-intensive processes", "Consider scaling horizontally", "Optimize application code"],
                prevention_measures=["Set up CPU-based auto-scaling", "Implement resource limits"]
            ))
            recommendations.append("Review and optimize CPU-intensive operations")

        if 'memory' in context_lower and ('high' in context_lower or 'oom' in context_lower):
            root_causes.append(RootCause(
                id="rc-memory", title="Memory Pressure",
                description="The system experienced memory pressure which may have caused instability.",
                confidence=ConfidenceLevel.MEDIUM,
                evidence=["Memory metrics indicate high usage"],
                affected_components=["compute", "application"],
                remediation_steps=["Identify memory leaks", "Increase memory allocation", "Restart affected services"],
                prevention_measures=["Implement memory monitoring", "Set memory limits and alerts"]
            ))
            recommendations.append("Investigate potential memory leaks")

        if 'timeout' in context_lower or 'latency' in context_lower:
            root_causes.append(RootCause(
                id="rc-latency", title="Service Latency Issues",
                description="Services experienced increased latency or timeouts.",
                confidence=ConfidenceLevel.MEDIUM,
                evidence=["Timeout or latency mentioned in incident"],
                affected_components=["network", "database", "application"],
                remediation_steps=["Check database query performance", "Review network connectivity", "Increase timeout thresholds if appropriate"],
                prevention_measures=["Implement circuit breakers", "Add caching layers"]
            ))
            recommendations.append("Review service dependencies and timeouts")

        if 'error' in context_lower and ('5' in context_lower or 'exception' in context_lower):
            root_causes.append(RootCause(
                id="rc-errors", title="Application Errors",
                description="Application errors were detected during the incident.",
                confidence=ConfidenceLevel.MEDIUM,
                evidence=["Error patterns detected in logs"],
                affected_components=["application"],
                remediation_steps=["Review error logs for root cause", "Deploy fix or rollback", "Clear any corrupted state"],
                prevention_measures=["Improve error handling", "Add better logging"]
            ))
            recommendations.append("Review application error handling")

        if not root_causes:
            root_causes.append(RootCause(
                id="rc-unknown", title="Further Investigation Required",
                description="Unable to automatically determine root cause. Manual investigation recommended.",
                confidence=ConfidenceLevel.LOW,
                evidence=["Insufficient data for automatic analysis"],
                affected_components=["unknown"],
                remediation_steps=["Gather additional logs and metrics", "Conduct manual investigation"],
                prevention_measures=["Improve monitoring coverage"]
            ))
            recommendations.append("Gather additional data for analysis")

        return {
            'summary': f"Analysis identified {len(root_causes)} potential root cause(s)",
            'timeline_analysis': "Timeline analysis requires additional context",
            'impact_assessment': "Impact assessment requires additional metrics",
            'root_causes': root_causes,
            'recommendations': recommendations or ["Continue monitoring the system"],
        }

    def _get_data_sources(self, logs, metrics, related_events) -> list[str]:
        sources = ["incident_data"]
        if logs is not None:
            sources.append(f"logs ({len(logs)} entries)")
        if metrics is not None:
            sources.append(f"metrics ({len(metrics)} metrics)")
        if related_events is not None:
            sources.append(f"related_events ({len(related_events)} events)")
        return sources


# Global instance
_analyzer: Optional[RootCauseAnalyzer] = None


def get_root_cause_analyzer() -> RootCauseAnalyzer:
    global _analyzer
    if _analyzer is None:
        _analyzer = RootCauseAnalyzer()
    return _analyzer
