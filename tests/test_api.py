"""
API Tests

Tests for REST API endpoints matching actual app routes.
"""

import pytest
import json


class TestHealthEndpoints:
    """Tests for health check endpoint."""

    def test_health_check(self, client):
        """Test basic health check endpoint."""
        response = client.get('/health')
        assert response.status_code == 200

        data = json.loads(response.data)
        assert data['status'] == 'healthy'
        assert 'timestamp' in data


class TestConversationEndpoints:
    """Tests for conversation API endpoints."""

    def test_list_conversations_requires_auth(self, client):
        """Test listing conversations requires login."""
        response = client.get('/api/conversations')
        assert response.status_code in [302, 401]

    def test_list_conversations(self, authenticated_client):
        """Test listing conversations when authenticated."""
        response = authenticated_client.get('/api/conversations')
        assert response.status_code == 200

        data = json.loads(response.data)
        assert 'conversations' in data

    def test_new_conversation(self, authenticated_client):
        """Test creating a new conversation."""
        response = authenticated_client.post('/api/conversations/new')
        # May return 200/503 depending on agent init
        assert response.status_code in [200, 503]


class TestSubscriptionEndpoints:
    """Tests for subscription API endpoints."""

    def test_get_subscription_tiers(self, client):
        """Test getting subscription tiers (public endpoint)."""
        response = client.get('/api/subscription/tiers')
        assert response.status_code == 200

        data = json.loads(response.data)
        assert 'tiers' in data

    def test_get_subscription_requires_auth(self, client):
        """Test getting subscription details requires login."""
        response = client.get('/api/subscription')
        assert response.status_code in [302, 401]

    def test_upgrade_disabled(self, authenticated_client):
        """Test direct upgrade endpoint is disabled (returns 403)."""
        response = authenticated_client.post('/api/subscription/upgrade',
            data=json.dumps({'tier': 'starter'}),
            content_type='application/json'
        )
        assert response.status_code == 403


class TestStatsEndpoints:
    """Tests for statistics endpoints."""

    def test_stats_requires_auth(self, client):
        """Test stats endpoint requires login."""
        response = client.get('/api/stats')
        assert response.status_code in [302, 401]

    def test_stats(self, authenticated_client):
        """Test getting conversation stats when authenticated."""
        response = authenticated_client.get('/api/stats')
        assert response.status_code == 200

        data = json.loads(response.data)
        assert 'total_messages' in data


class TestHistoryEndpoints:
    """Tests for chat history endpoints."""

    def test_history_requires_auth(self, client):
        """Test history endpoint requires login."""
        response = client.get('/api/history')
        assert response.status_code in [302, 401]

    def test_history(self, authenticated_client):
        """Test getting chat history when authenticated."""
        response = authenticated_client.get('/api/history')
        assert response.status_code == 200


class TestToolsEndpoint:
    """Tests for tools listing endpoint."""

    def test_tools_requires_auth(self, client):
        """Test tools endpoint requires login."""
        response = client.get('/api/tools')
        assert response.status_code in [302, 401]

    def test_tools(self, authenticated_client):
        """Test listing available tools (503 if agent not initialized without real API key)."""
        response = authenticated_client.get('/api/tools')
        assert response.status_code in [200, 503]

        data = json.loads(response.data)
        if response.status_code == 200:
            assert 'categories' in data
        else:
            assert 'error' in data


class TestCreditsPurchaseDisabled:
    """Tests for disabled legacy payment endpoints."""

    def test_credits_purchase_disabled(self, authenticated_client):
        """Test direct credit purchase endpoint is disabled (returns 403)."""
        response = authenticated_client.post('/api/credits/purchase',
            data=json.dumps({'pack': '100'}),
            content_type='application/json'
        )
        assert response.status_code == 403
