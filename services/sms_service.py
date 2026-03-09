"""
SMS Service — Brevo (formerly Sendinblue)

Sends transactional SMS via Brevo's REST API.
Uses the same Brevo account as the email service.

Configure via environment variables:
  BREVO_API_KEY   — Brevo API key (v3, starts with "xkeysib-...")
  SMS_SENDER_NAME — Sender name shown on SMS (max 11 chars, alpha-only, default "DevOpsAgent")

Brevo SMS docs: https://developers.brevo.com/reference/sendtransacsms
"""
import os
import logging

import requests

logger = logging.getLogger(__name__)

BREVO_SMS_URL = "https://api.brevo.com/v3/transactionalSMS/sms"


class SMSService:
    def __init__(self):
        self.api_key = os.getenv('BREVO_API_KEY', '')
        self.sender = os.getenv('SMS_SENDER_NAME', 'DevOpsAgent')[:11]

    def send_sms(self, phone_number: str, message: str) -> bool:
        """Send an SMS to *phone_number* (E.164 format, e.g. +2348012345678).

        Returns True on success, False on failure.
        """
        if not self.api_key:
            logger.warning("BREVO_API_KEY not configured, skipping SMS send")
            return False

        try:
            resp = requests.post(
                BREVO_SMS_URL,
                json={
                    "type": "transactional",
                    "sender": self.sender,
                    "recipient": phone_number,
                    "content": message,
                },
                headers={
                    "api-key": self.api_key,
                    "Content-Type": "application/json",
                },
                timeout=10,
            )

            if resp.status_code in (200, 201):
                logger.info(f"SMS sent to {phone_number}")
                return True
            else:
                logger.error(f"Brevo SMS error {resp.status_code}: {resp.text}")
                return False

        except Exception as e:
            logger.error(f"SMS send error: {e}")
            return False

    def send_otp(self, phone_number: str, code: str) -> bool:
        """Send a formatted OTP message."""
        message = f"Your DevOps Agent code is: {code}. Expires in 10 min. Do not share it."
        return self.send_sms(phone_number, message)


sms_service = SMSService()
