"""DNS TXT-record domain ownership verification for SSO email-domain routing.

An organization proves it controls an email domain by publishing a TXT record
before that domain is trusted to route SSO logins. Until verified, a domain is
ignored by ``sso_service.resolve_org_for_email``.

Record the admin must publish:
    host:  _devops-agent-challenge.<domain>
    type:  TXT
    value: devops-agent-verification=<token>
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime
from typing import List, Tuple

logger = logging.getLogger(__name__)

TXT_HOST_PREFIX = '_devops-agent-challenge'
TXT_VALUE_PREFIX = 'devops-agent-verification='
_DNS_TIMEOUT = 5


def generate_token() -> str:
    return secrets.token_hex(16)


def challenge_host(domain: str) -> str:
    return f"{TXT_HOST_PREFIX}.{domain.strip().lower().lstrip('@')}"


def expected_txt_value(token: str) -> str:
    return TXT_VALUE_PREFIX + token


def ensure_token(domain_row) -> str:
    """Make sure the domain has a verification token, generating one if needed."""
    from models import db
    if not domain_row.verification_token:
        domain_row.verification_token = generate_token()
        db.session.commit()
    return domain_row.verification_token


def dns_instructions(domain_row) -> dict:
    """Everything the admin needs to display the required DNS record."""
    token = ensure_token(domain_row)
    return {
        'host': challenge_host(domain_row.domain),
        'type': 'TXT',
        'value': expected_txt_value(token),
        'token': token,
    }


def _resolve_txt(host: str) -> List[str]:
    """Return the TXT record string values for ``host`` (separated for mocking)."""
    import dns.resolver
    answers = dns.resolver.resolve(host, 'TXT', lifetime=_DNS_TIMEOUT)
    values = []
    for rdata in answers:
        # Each TXT record can be split into multiple character-strings.
        parts = getattr(rdata, 'strings', None)
        if parts:
            values.append(b''.join(parts).decode('utf-8', 'ignore'))
        else:
            values.append(str(rdata).strip('"'))
    return values


def verify_domain(domain_row) -> Tuple[bool, str]:
    """Look up the challenge TXT record and mark the domain verified on match."""
    from models import db
    import dns.exception
    import dns.resolver

    token = ensure_token(domain_row)
    expected = expected_txt_value(token)
    host = challenge_host(domain_row.domain)

    try:
        values = _resolve_txt(host)
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
        return False, f"No TXT record found at {host}. DNS changes can take time to propagate."
    except (dns.resolver.NoNameservers, dns.exception.Timeout):
        return False, "DNS lookup timed out. Please try again shortly."
    except dns.exception.DNSException as e:
        logger.warning("DNS verification error for %s: %s", host, e)
        return False, "DNS lookup failed. Check the record and try again."

    for value in values:
        v = value.strip().strip('"')
        if v == expected or v == token:
            domain_row.verified = True
            domain_row.verified_at = datetime.utcnow()
            db.session.commit()
            logger.info("Verified SSO domain %s for org %s",
                        domain_row.domain, domain_row.organization_id)
            return True, "Domain verified successfully."

    return False, (f"TXT record at {host} did not match. "
                   f"Expected value '{expected}'.")
