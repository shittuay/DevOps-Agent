"""
Global crisis support resources by country.

This service provides localized mental health crisis resources based on user location.
Used when crisis language is detected to direct users to professional help.

Organizations included:
- National suicide prevention lifelines
- Crisis text lines
- International hotlines and support services
"""

from typing import Dict, Optional
import logging

logger = logging.getLogger(__name__)

# Global crisis resources indexed by ISO 3166-1 alpha-2 country code
CRISIS_RESOURCES_BY_COUNTRY: Dict[str, Dict] = {
    # United States
    'US': {
        'name': '988 Suicide & Crisis Lifeline',
        'phone': '988',
        'sms': 'Text HOME to 741741',
        'sms_provider': 'Crisis Text Line',
        'url': 'https://988lifeline.org',
        'url_chat': 'https://988lifeline.org/chat',
        'available_24_7': True,
        'languages': ['en', 'es'],
    },

    # Canada
    'CA': {
        'name': 'Canada Suicide Prevention Service',
        'phone': '1-833-456-4566',
        'sms': 'Text HELLO to 741741',
        'url': 'https://www.crisisservicescanada.ca',
        'available_24_7': True,
        'languages': ['en', 'fr'],
    },

    # United Kingdom
    'GB': {
        'name': 'Samaritans',
        'phone': '+44-116-123-1123',
        'email': 'jo@samaritans.org',
        'url': 'https://www.samaritans.org',
        'available_24_7': True,
        'languages': ['en'],
    },

    # Ireland
    'IE': {
        'name': 'Samaritans Ireland',
        'phone': '+353-1-671-0071',
        'email': 'jo@samaritans.ie',
        'url': 'https://www.samaritans.ie',
        'available_24_7': True,
        'languages': ['en'],
    },

    # France
    'FR': {
        'name': 'SOS Amitié',
        'phone': '09-72-39-40-50',
        'url': 'https://www.sosemitie.org',
        'available_24_7': True,
        'languages': ['fr'],
    },

    # Germany
    'DE': {
        'name': 'Telefonseelsorge',
        'phone': '0800-111-0111 or 0800-111-0222',
        'url': 'https://www.telefonseelsorge.de',
        'available_24_7': True,
        'languages': ['de', 'en'],
    },

    # Spain
    'ES': {
        'name': 'Telégono de la Esperanza',
        'phone': '024 (new national number)',
        'phone_alt': '914-59-00-50',
        'url': 'https://www.telefonodellaesperanza.org',
        'available_24_7': True,
        'languages': ['es'],
    },

    # Italy
    'IT': {
        'name': 'Telefono Amico',
        'phone': '+39-02-2327-2327',
        'url': 'https://www.telefonoamico.it',
        'available_24_7': True,
        'languages': ['it'],
    },

    # Netherlands
    'NL': {
        'name': 'Stichting 113',
        'phone': '+31-900-0113',
        'email': 'info@113.nl',
        'url': 'https://www.113.nl',
        'available_24_7': True,
        'languages': ['nl', 'en'],
    },

    # Belgium
    'BE': {
        'name': 'Centre de Prévention du Suicide',
        'phone': '+32-2-649-95-55',
        'url': 'https://www.preventionsuicide.be',
        'available_24_7': True,
        'languages': ['fr', 'nl', 'de'],
    },

    # Switzerland
    'CH': {
        'name': 'Die Dargebotene Hand',
        'phone': '143',
        'url': 'https://www.143.ch',
        'available_24_7': True,
        'languages': ['de', 'fr', 'it', 'en'],
    },

    # Austria
    'AT': {
        'name': 'Telefonseelsorge Österreich',
        'phone': '142',
        'url': 'https://www.telefonseelsorge.at',
        'available_24_7': True,
        'languages': ['de'],
    },

    # Poland
    'PL': {
        'name': 'Centrum Zdrowia Psychicznego',
        'phone': '116-123',
        'url': 'https://www.116123.org.pl',
        'available_24_7': True,
        'languages': ['pl', 'en'],
    },

    # Sweden
    'SE': {
        'name': 'Nationellt centrum för suicidprevention',
        'phone': '+46-771-481-481',
        'url': 'https://www.lciv.se',
        'available_24_7': True,
        'languages': ['sv', 'en'],
    },

    # Norway
    'NO': {
        'name': 'Kirkens SOS',
        'phone': '+47-22-40-00-40',
        'url': 'https://www.kirkens-sos.no',
        'available_24_7': True,
        'languages': ['no', 'en'],
    },

    # Denmark
    'DK': {
        'name': 'Livslinien',
        'phone': '40-51-44-48',
        'url': 'https://livslinien.dk',
        'available_24_7': True,
        'languages': ['da', 'en'],
    },

    # Finland
    'FI': {
        'name': 'Suomen Mielenterveysseura',
        'phone': '+358-9-2525-0552',
        'url': 'https://www.mielenterveysseura.fi',
        'available_24_7': True,
        'languages': ['fi', 'en'],
    },

    # Australia
    'AU': {
        'name': 'Lifeline Australia',
        'phone': '13-11-14',
        'sms': 'Text 0477-131-114',
        'url': 'https://www.lifeline.org.au',
        'available_24_7': True,
        'languages': ['en'],
    },

    # New Zealand
    'NZ': {
        'name': '1737, Need to Talk?',
        'phone': '1737',
        'url': 'https://1737.org.nz',
        'available_24_7': True,
        'languages': ['en', 'mi'],
    },

    # India
    'IN': {
        'name': 'AASRA',
        'phone': '+91-22-2772-4030',
        'url': 'https://aasra.info',
        'available_24_7': True,
        'languages': ['en', 'hi'],
    },

    # Japan
    'JP': {
        'name': 'Inochi no Denwa',
        'phone': '+81-570-783-556',
        'url': 'https://www.inochinodenwa.org',
        'available_24_7': True,
        'languages': ['ja', 'en'],
    },

    # South Korea
    'KR': {
        'name': 'Korea Suicide Prevention Center',
        'phone': '1393',
        'url': 'https://www.0393.or.kr',
        'available_24_7': True,
        'languages': ['ko', 'en'],
    },

    # Brazil
    'BR': {
        'name': 'Centro de Valorização da Vida (CVV)',
        'phone': '188',
        'sms': 'Text "CVV" to 21988819060',
        'url': 'https://www.cvv.org.br',
        'available_24_7': True,
        'languages': ['pt'],
    },

    # Mexico
    'MX': {
        'name': 'Teléfono de la Esperanza',
        'phone': '5255-2592-0500',
        'url': 'https://www.telefonodellaesperanza.org',
        'available_24_7': True,
        'languages': ['es', 'en'],
    },

    # Nigeria
    'NG': {
        'name': 'Lifeline Nigeria',
        'phone': '+234-9119944357',
        'sms': 'SMS to 09119944357',
        'url': 'https://lifelineng.org',
        'available_24_7': True,
        'languages': ['en'],
    },

    # South Africa
    'ZA': {
        'name': 'Befrienders South Africa',
        'phone': '0861-BEFRIEND (0861-233-7436)',
        'url': 'https://www.befrienders.co.za',
        'available_24_7': True,
        'languages': ['en', 'zu', 'xh'],
    },

    # Kenya
    'KE': {
        'name': 'Befrienders Kenya',
        'phone': '+254-722-178-177',
        'url': 'https://befrienders.co.ke',
        'available_24_7': True,
        'languages': ['en', 'sw'],
    },

    # Malaysia
    'MY': {
        'name': 'Befrienders Malaysia',
        'phone': '03-7627-2929',
        'url': 'https://www.befrienders.org.my',
        'available_24_7': True,
        'languages': ['en', 'ms'],
    },

    # Singapore
    'SG': {
        'name': 'Samaritans Singapore',
        'phone': '1800-221-4444',
        'url': 'https://www.sos.org.sg',
        'available_24_7': True,
        'languages': ['en', 'zh', 'ms', 'ta'],
    },

    # Philippines
    'PH': {
        'name': 'In Touch Community Services',
        'phone': '+63-2-8893-7603',
        'url': 'https://www.itcservices.org.ph',
        'available_24_7': True,
        'languages': ['en', 'tl'],
    },

    # Thailand
    'TH': {
        'name': 'สถาบันสุขภาพจิตศรีสวัสดิ์ (Sresoonthorn Institute)',
        'phone': '+66-2-352-9090',
        'url': 'https://www.sresoonthorn.org',
        'available_24_7': True,
        'languages': ['th', 'en'],
    },

    # China
    'CN': {
        'name': 'Beijing Crisis Intervention Hotline',
        'phone': '+86-10-8295-1332',
        'url': 'https://www.crisis.org.cn',
        'available_24_7': True,
        'languages': ['zh', 'en'],
    },
}

# Global fallback (if country is unknown or not found)
DEFAULT_CRISIS_RESOURCE: Dict = {
    'name': 'International Association for Suicide Prevention',
    'url': 'https://www.iasp.info/resources/Crisis_Centres/',
    'phone': 'See https://findahelpline.com',
    'available_24_7': True,
    'languages': ['en'],
    'note': 'Global directory of crisis services',
}


def get_crisis_resources(country_code: Optional[str] = None) -> Dict:
    """
    Get localized crisis resources for a user's country.

    Args:
        country_code: ISO 3166-1 alpha-2 country code (e.g., 'US', 'NG', 'FR')
                     If None or unknown, returns global default.

    Returns:
        Dictionary with crisis resource information:
        {
            'name': str,
            'phone': str or None,
            'sms': str or None,
            'email': str or None,
            'url': str,
            'available_24_7': bool,
            'languages': [str],
            'note': str or None
        }
    """
    if country_code and country_code.upper() in CRISIS_RESOURCES_BY_COUNTRY:
        return CRISIS_RESOURCES_BY_COUNTRY[country_code.upper()]

    logger.debug(f"Crisis resource not found for country: {country_code}, using global default")
    return DEFAULT_CRISIS_RESOURCE


def format_crisis_banner_html(resources: Dict) -> str:
    """
    Format crisis resources as HTML for browser display.

    Args:
        resources: Dictionary from get_crisis_resources()

    Returns:
        HTML string for emergency banner
    """
    name = resources.get('name', 'Crisis Support')
    url_chat = resources.get('url_chat')
    url_main = resources.get('url', 'https://findahelpline.com')
    phone = resources.get('phone')
    sms = resources.get('sms')
    email = resources.get('email')

    buttons = []
    if phone:
        buttons.append(f'<a href="tel:{phone.replace("+", "").replace(" ", "").replace("-", "")}" '
                      f'class="btn" style="background: white; color: #d32f2f; padding: 12px; border-radius: 4px; '
                      f'text-align: center; font-weight: bold; text-decoration: none; display: block; margin: 8px 0;">'
                      f'📞 Call {phone}</a>')

    if url_chat:
        buttons.append(f'<a href="{url_chat}" target="_blank" '
                      f'class="btn" style="background: white; color: #d32f2f; padding: 12px; border-radius: 4px; '
                      f'text-align: center; font-weight: bold; text-decoration: none; display: block; margin: 8px 0;">'
                      f'💬 Chat Online</a>')

    if sms:
        buttons.append(f'<div style="background: white; color: #d32f2f; padding: 12px; border-radius: 4px; '
                      f'text-align: center; font-weight: bold; margin: 8px 0;">'
                      f'📱 {sms}</div>')

    buttons.append(f'<a href="{url_main}" target="_blank" '
                  f'class="btn" style="background: white; color: #d32f2f; padding: 12px; border-radius: 4px; '
                  f'text-align: center; font-weight: bold; text-decoration: none; display: block; margin: 8px 0;">'
                  f'🌐 Visit Website</a>')

    buttons_html = '\n'.join(buttons)

    html = f'''
    <div style="background: #d32f2f; padding: 20px; border-radius: 8px; color: white; margin: 20px 0;">
        <h3 style="color: white; margin: 0 0 10px 0; font-size: 18px;">
            🆘 We're Concerned for Your Safety
        </h3>
        <p style="color: #fff; margin: 0 0 15px 0; line-height: 1.5;">
            You deserve immediate support from trained professionals. {name} is available 24/7.
        </p>
        <div style="display: flex; flex-direction: column; gap: 10px;">
            {buttons_html}
        </div>
        <p style="color: #fff; margin: 15px 0 0 0; font-size: 12px; opacity: 0.9;">
            We care about your wellbeing. If you're in immediate danger, please call emergency services (911 in US, 999 in UK, etc.).
        </p>
    </div>
    '''
    return html.strip()


def get_user_country_from_request(request) -> Optional[str]:
    """
    Attempt to infer user's country from request headers.

    Args:
        request: Flask request object

    Returns:
        ISO 3166-1 alpha-2 country code or None
    """
    # Try CloudFlare header (common in production)
    country = request.headers.get('CF-IPCountry')
    if country:
        return country

    # Try other common geo-location headers
    for header in ['X-Appengine-Country', 'X-Country-Code', 'GeoIP-Country']:
        country = request.headers.get(header)
        if country:
            return country

    return None
