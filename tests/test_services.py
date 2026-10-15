"""
Service Tests

Tests for service layer components.
"""

import pytest


class TestCacheService:
    """Tests for cache service."""

    def test_cache_set_get(self, app):
        """Test setting and getting cache values."""
        from services.cache_service import cache

        with app.app_context():
            cache.init_app(app)

            cache.set('test_key', 'test_value', ttl=60)
            value = cache.get('test_key')

            assert value == 'test_value'

    def test_cache_delete(self, app):
        """Test deleting cache values."""
        from services.cache_service import cache

        with app.app_context():
            cache.init_app(app)

            cache.set('delete_key', 'value')
            cache.delete('delete_key')
            value = cache.get('delete_key')

            assert value is None

    def test_cache_get_or_set(self, app):
        """Test get_or_set functionality."""
        from services.cache_service import cache

        with app.app_context():
            cache.init_app(app)

            call_count = 0

            def factory():
                nonlocal call_count
                call_count += 1
                return 'computed_value'

            # First call should compute
            value1 = cache.get_or_set('computed_key', factory, ttl=60)
            assert value1 == 'computed_value'
            assert call_count == 1

            # Second call should use cache
            value2 = cache.get_or_set('computed_key', factory, ttl=60)
            assert value2 == 'computed_value'
            assert call_count == 1  # Factory not called again


class TestAPIKeyService:
    """Tests for API key service."""

    def test_generate_key(self, app):
        """Test API key generation."""
        from services.api_key_service import api_key_service

        with app.app_context():
            key = api_key_service.generate_key()

            assert key.startswith('doa_live_')
            assert len(key) == 41

    def test_hash_key(self, app):
        """Test API key hashing."""
        from services.api_key_service import api_key_service

        with app.app_context():
            key = 'doa_live_test123456789012345678901234567890'
            hash1 = api_key_service.hash_key(key)
            hash2 = api_key_service.hash_key(key)

            assert hash1 == hash2
            assert len(hash1) == 64

    def test_create_and_validate_key(self, app, test_user):
        """Test creating and validating an API key."""
        from services.api_key_service import api_key_service
        from models import db

        with app.app_context():
            api_key, plain_key = api_key_service.create_key(
                user_id=test_user.id,
                name='Service Test Key',
                scopes=['read', 'write']
            )

            assert api_key.name == 'Service Test Key'
            assert 'read' in api_key.scopes

            # Validate the key
            is_valid, validated_key, error = api_key_service.validate_key(
                plain_key,
                required_scope='read'
            )

            assert is_valid
            assert validated_key.id == api_key.id
            assert error == ''

            # Cleanup
            db.session.delete(api_key)
            db.session.commit()


class TestTwoFactorService:
    """Tests for two-factor authentication service."""

    def test_generate_secret(self, app):
        """Test TOTP secret generation."""
        from services.two_factor_service import two_factor_service

        with app.app_context():
            secret = two_factor_service.generate_secret()

            assert len(secret) == 32
            assert secret.isalnum()

    def test_generate_backup_codes(self, app):
        """Test backup code generation."""
        from services.two_factor_service import two_factor_service

        with app.app_context():
            codes = two_factor_service.generate_backup_codes(count=10)

            assert len(codes) == 10
            assert all('-' in code for code in codes)  # Should be formatted

    def test_backup_code_verification(self, app):
        """Test backup code verification."""
        from services.two_factor_service import two_factor_service

        with app.app_context():
            codes = two_factor_service.generate_backup_codes(count=5)
            hashed_codes = [two_factor_service.hash_backup_code(c) for c in codes]

            # Valid code should verify
            is_valid, matched = two_factor_service.verify_backup_code(
                codes[0], hashed_codes
            )
            assert is_valid
            assert matched == hashed_codes[0]

            # Invalid code should fail
            is_valid, matched = two_factor_service.verify_backup_code(
                'XXXX-XXXX', hashed_codes
            )
            assert not is_valid
            assert matched is None
