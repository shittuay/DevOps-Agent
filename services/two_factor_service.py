"""
Two-Factor Authentication Service

Provides TOTP-based 2FA with:
- QR code generation for authenticator apps
- Backup codes for account recovery
- Rate limiting on verification attempts
"""

import os
import io
import base64
import secrets
import hashlib
import logging
from typing import Optional, Tuple, List
from datetime import datetime

import pyotp
import qrcode
from qrcode.image.pure import PyPNGImage
from src.utils.timeutils import utcnow

logger = logging.getLogger(__name__)

# Constants
BACKUP_CODE_COUNT = 10
BACKUP_CODE_LENGTH = 8
ISSUER_NAME = "DevOps Agent"
MAX_VERIFICATION_ATTEMPTS = 5
LOCKOUT_DURATION_MINUTES = 15


class TwoFactorService:
    """
    Two-Factor Authentication service using TOTP.

    Features:
    - TOTP generation and verification
    - QR code generation for authenticator apps
    - Backup codes for account recovery
    - Rate limiting on verification attempts
    """

    def __init__(self, app=None):
        self.issuer = ISSUER_NAME
        if app:
            self.init_app(app)

    def init_app(self, app):
        """Initialize with Flask app configuration."""
        self.issuer = app.config.get('TWO_FACTOR_ISSUER', ISSUER_NAME)
        app.extensions = getattr(app, 'extensions', {})
        app.extensions['two_factor'] = self

    def generate_otp(self, length: int = 6) -> str:
        """Generate a cryptographically random numeric OTP code."""
        return ''.join(secrets.choice('0123456789') for _ in range(length))

    def generate_secret(self) -> str:
        """
        Generate a new TOTP secret for a user.

        Returns:
            Base32-encoded secret key
        """
        return pyotp.random_base32()

    def get_totp_uri(self, secret: str, email: str) -> str:
        """
        Generate TOTP provisioning URI for QR code.

        Args:
            secret: User's TOTP secret
            email: User's email address

        Returns:
            otpauth:// URI for authenticator apps
        """
        totp = pyotp.TOTP(secret)
        return totp.provisioning_uri(name=email, issuer_name=self.issuer)

    def generate_qr_code(self, secret: str, email: str) -> str:
        """
        Generate QR code image as base64 data URI.

        Args:
            secret: User's TOTP secret
            email: User's email address

        Returns:
            Base64-encoded PNG image data URI
        """
        uri = self.get_totp_uri(secret, email)

        # Generate QR code
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(uri)
        qr.make(fit=True)

        # Create image
        img = qr.make_image(fill_color="black", back_color="white")

        # Convert to base64
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        buffer.seek(0)
        img_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')

        return f"data:image/png;base64,{img_base64}"

    def verify_totp(self, secret: str, code: str, valid_window: int = 1) -> bool:
        """
        Verify a TOTP code.

        Args:
            secret: User's TOTP secret
            code: 6-digit code from authenticator
            valid_window: Number of time steps to allow (default: 1)

        Returns:
            True if code is valid
        """
        if not secret or not code:
            return False

        # Clean up code (remove spaces)
        code = code.replace(' ', '').replace('-', '')

        if not code.isdigit() or len(code) != 6:
            return False

        totp = pyotp.TOTP(secret)
        return totp.verify(code, valid_window=valid_window)

    def generate_backup_codes(self, count: int = BACKUP_CODE_COUNT) -> List[str]:
        """
        Generate backup codes for account recovery.

        Args:
            count: Number of backup codes to generate

        Returns:
            List of backup codes
        """
        codes = []
        for _ in range(count):
            # Generate readable code (e.g., "ABCD-1234")
            code = ''.join(secrets.choice('ABCDEFGHJKLMNPQRSTUVWXYZ23456789')
                          for _ in range(BACKUP_CODE_LENGTH))
            # Format with dash for readability
            formatted = f"{code[:4]}-{code[4:]}"
            codes.append(formatted)
        return codes

    def hash_backup_code(self, code: str) -> str:
        """
        Hash a backup code for storage.

        Args:
            code: Plain text backup code

        Returns:
            SHA-256 hash of the code
        """
        # Normalize code (remove dashes, uppercase)
        normalized = code.replace('-', '').upper()
        return hashlib.sha256(normalized.encode()).hexdigest()

    def verify_backup_code(self, code: str, hashed_codes: List[str]) -> Tuple[bool, Optional[str]]:
        """
        Verify a backup code against stored hashes.

        Args:
            code: Plain text backup code
            hashed_codes: List of hashed backup codes

        Returns:
            Tuple of (is_valid, matched_hash)
        """
        code_hash = self.hash_backup_code(code)

        for stored_hash in hashed_codes:
            if secrets.compare_digest(code_hash, stored_hash):
                return True, stored_hash

        return False, None


# Global service instance
two_factor_service = TwoFactorService()


def init_two_factor(app):
    """Initialize 2FA service with Flask app."""
    two_factor_service.init_app(app)
    return two_factor_service


# ==========================================
# Database Model Mixin
# ==========================================

class TwoFactorMixin:
    """
    Mixin to add 2FA fields to User model.

    Add to your User model:
        class User(db.Model, TwoFactorMixin):
            ...
    """

    # These fields should be added to your User model:
    # two_factor_enabled = db.Column(db.Boolean, default=False)
    # two_factor_secret = db.Column(db.String(32), nullable=True)
    # backup_codes = db.Column(db.JSON, nullable=True)  # List of hashed codes
    # two_factor_verified_at = db.Column(db.DateTime, nullable=True)
    # two_factor_attempts = db.Column(db.Integer, default=0)
    # two_factor_locked_until = db.Column(db.DateTime, nullable=True)

    def setup_two_factor(self) -> Tuple[str, str, List[str]]:
        """
        Set up 2FA for user.

        Returns:
            Tuple of (secret, qr_code_data_uri, backup_codes)
        """
        secret = two_factor_service.generate_secret()
        qr_code = two_factor_service.generate_qr_code(secret, self.email)
        backup_codes = two_factor_service.generate_backup_codes()

        # Store secret (but don't enable yet - wait for verification)
        self.two_factor_secret = secret

        # Hash and store backup codes
        self.backup_codes = [
            two_factor_service.hash_backup_code(code)
            for code in backup_codes
        ]

        return secret, qr_code, backup_codes

    def verify_and_enable_two_factor(self, code: str) -> bool:
        """
        Verify TOTP code and enable 2FA.

        Args:
            code: 6-digit TOTP code

        Returns:
            True if verified and enabled
        """
        if self.is_two_factor_locked():
            return False

        if two_factor_service.verify_totp(self.two_factor_secret, code):
            self.two_factor_enabled = True
            self.two_factor_verified_at = utcnow()
            self.two_factor_attempts = 0
            return True

        self.increment_two_factor_attempts()
        return False

    def verify_two_factor(self, code: str) -> bool:
        """
        Verify a 2FA code (TOTP or backup code).

        Args:
            code: TOTP code or backup code

        Returns:
            True if valid
        """
        if self.is_two_factor_locked():
            return False

        # Try TOTP first
        if two_factor_service.verify_totp(self.two_factor_secret, code):
            self.two_factor_attempts = 0
            return True

        # Try backup code
        is_valid, matched_hash = two_factor_service.verify_backup_code(
            code, self.backup_codes or []
        )

        if is_valid:
            # Remove used backup code
            self.backup_codes = [
                h for h in self.backup_codes if h != matched_hash
            ]
            self.two_factor_attempts = 0
            return True

        self.increment_two_factor_attempts()
        return False

    def disable_two_factor(self):
        """Disable 2FA for user."""
        self.two_factor_enabled = False
        self.two_factor_secret = None
        self.backup_codes = None
        self.two_factor_verified_at = None
        self.two_factor_attempts = 0
        self.two_factor_locked_until = None

    def is_two_factor_locked(self) -> bool:
        """Check if 2FA verification is locked due to too many attempts."""
        if self.two_factor_locked_until:
            if utcnow() < self.two_factor_locked_until:
                return True
            # Lockout expired, reset
            self.two_factor_locked_until = None
            self.two_factor_attempts = 0
        return False

    def increment_two_factor_attempts(self):
        """Increment failed attempt counter and lock if threshold reached."""
        self.two_factor_attempts = (self.two_factor_attempts or 0) + 1

        if self.two_factor_attempts >= MAX_VERIFICATION_ATTEMPTS:
            from datetime import timedelta
            self.two_factor_locked_until = utcnow() + timedelta(
                minutes=LOCKOUT_DURATION_MINUTES
            )
            logger.warning(f"2FA locked for user {self.id} due to too many attempts")

    def regenerate_backup_codes(self) -> List[str]:
        """
        Generate new backup codes (invalidates old ones).

        Returns:
            List of new backup codes
        """
        backup_codes = two_factor_service.generate_backup_codes()
        self.backup_codes = [
            two_factor_service.hash_backup_code(code)
            for code in backup_codes
        ]
        return backup_codes

    def get_backup_codes_remaining(self) -> int:
        """Get count of remaining backup codes."""
        return len(self.backup_codes) if self.backup_codes else 0
