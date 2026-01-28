"""
API Tests

Tests for REST API endpoints.
"""

import pytest
import json


class TestHealthEndpoints:
    """Tests for health check endpoints."""

    def test_health_check(self, client):
        """Test basic health check endpoint."""
        response = client.get('/api/v1/health')
        assert response.status_code == 200

        data = json.loads(response.data)
        assert data['status'] == 'healthy'
        assert 'timestamp' in data

    def test_detailed_health_check(self, client):
        """Test detailed health check endpoint."""
        response = client.get('/api/v1/health/detailed')
        assert response.status_code in [200, 503]

        data = json.loads(response.data)
        assert 'status' in data
        assert 'components' in data


class TestAuthEndpoints:
    """Tests for authentication API endpoints."""

    def test_validate_token(self, client, api_headers):
        """Test API key validation endpoint."""
        response = client.get('/api/v1/auth/validate', headers=api_headers)
        assert response.status_code == 200

        data = json.loads(response.data)
        assert data['valid'] == True

    def test_validate_token_invalid_key(self, client):
        """Test validation with invalid API key."""
        headers = {
            'Authorization': 'Bearer invalid_key',
            'Content-Type': 'application/json'
        }
        response = client.get('/api/v1/auth/validate', headers=headers)
        assert response.status_code == 401

    def test_get_current_user(self, client, api_headers, test_user):
        """Test getting current user info."""
        response = client.get('/api/v1/auth/me', headers=api_headers)
        assert response.status_code == 200

        data = json.loads(response.data)
        assert data['user']['email'] == test_user.email


class TestUserEndpoints:
    """Tests for user API endpoints."""

    def test_get_user_profile(self, client, api_headers, test_user):
        """Test getting user profile."""
        response = client.get('/api/v1/users/me', headers=api_headers)
        assert response.status_code == 200

        data = json.loads(response.data)
        assert data['user']['username'] == test_user.username

    def test_update_user_profile(self, client, api_headers):
        """Test updating user profile."""
        response = client.patch(
            '/api/v1/users/me',
            headers=api_headers,
            data=json.dumps({'full_name': 'Updated Name'}),
            content_type='application/json'
        )
        assert response.status_code == 200

        data = json.loads(response.data)
        assert data['user']['full_name'] == 'Updated Name'


class TestConversationEndpoints:
    """Tests for conversation API endpoints."""

    def test_list_conversations(self, client, api_headers):
        """Test listing conversations."""
        response = client.get('/api/v1/conversations', headers=api_headers)
        assert response.status_code == 200

        data = json.loads(response.data)
        assert 'conversations' in data
        assert 'pagination' in data

    def test_create_conversation(self, client, api_headers):
        """Test creating a conversation."""
        response = client.post(
            '/api/v1/conversations',
            headers=api_headers,
            data=json.dumps({'title': 'Test Conversation'}),
            content_type='application/json'
        )
        assert response.status_code == 201

        data = json.loads(response.data)
        assert data['conversation']['title'] == 'Test Conversation'


class TestResourceEndpoints:
    """Tests for resource API endpoints."""

    def test_list_resources(self, client, api_headers):
        """Test listing cloud resources."""
        response = client.get('/api/v1/resources', headers=api_headers)
        assert response.status_code == 200

        data = json.loads(response.data)
        assert 'resources' in data
        assert 'pagination' in data

    def test_get_resource_stats(self, client, api_headers):
        """Test getting resource statistics."""
        response = client.get('/api/v1/resources/stats', headers=api_headers)
        assert response.status_code == 200

        data = json.loads(response.data)
        assert 'total_resources' in data


class TestAPIKeyEndpoints:
    """Tests for API key management endpoints."""

    def test_list_api_keys(self, client, api_headers):
        """Test listing API keys."""
        response = client.get('/api/v1/api-keys', headers=api_headers)
        assert response.status_code == 200

        data = json.loads(response.data)
        assert 'api_keys' in data

    def test_create_api_key(self, client, api_headers):
        """Test creating an API key."""
        response = client.post(
            '/api/v1/api-keys',
            headers=api_headers,
            data=json.dumps({
                'name': 'New Test Key',
                'scopes': ['read']
            }),
            content_type='application/json'
        )
        assert response.status_code == 201

        data = json.loads(response.data)
        assert 'key' in data
        assert data['api_key']['name'] == 'New Test Key'

    def test_create_api_key_without_name(self, client, api_headers):
        """Test creating API key without name fails."""
        response = client.post(
            '/api/v1/api-keys',
            headers=api_headers,
            data=json.dumps({'scopes': ['read']}),
            content_type='application/json'
        )
        assert response.status_code == 400


class TestRateLimiting:
    """Tests for API rate limiting."""

    def test_rate_limit_headers(self, client, api_headers):
        """Test rate limit headers are present."""
        response = client.get('/api/v1/auth/usage', headers=api_headers)
        assert response.status_code == 200

        data = json.loads(response.data)
        assert 'rate_limit' in data['api_key']
        assert 'rate_limit_remaining' in data['api_key']
