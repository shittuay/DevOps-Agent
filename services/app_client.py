"""Is this request coming from the DevOps Agent iPhone app?

The iOS app (Capacitor) appends IOS_APP_UA_MARKER to its WebView user agent
(``appendUserAgent`` in capacitor.config). Inside the app there is no buying: Apple requires
its own in-app purchase for anything sold in an app, and this app is a companion to the paid
web tool (App Store guideline 3.1.3(f)). So the app shows no prices, plan names, upgrade
prompts or links to Billing, and the billing pages and checkout APIs refuse to serve it.

The marker is not a security boundary (anyone can set a user agent); it only decides what the
app shows. Billing works normally in any browser.
"""
from flask import has_request_context, request

IOS_APP_UA_MARKER = 'DevOpsAgentiOS'

# Billing pages and the endpoints that start a purchase. Read-only balance endpoints
# (/api/subscription, /api/usage/*) stay available because the app shows the credit count.
BLOCKED_IN_APP_PREFIXES = (
    '/billing',
    '/api/subscription/upgrade',
    '/api/subscription/create-checkout',
    '/api/subscription/tiers',
    '/api/credits/purchase',
    '/api/credits/create-checkout',
    '/api/credits/packs',
    '/api/billing/',
)


def is_ios_app(req=None) -> bool:
    if req is None:
        if not has_request_context():
            return False
        req = request
    return IOS_APP_UA_MARKER in (req.headers.get('User-Agent') or '')


def blocked_in_app(path: str) -> bool:
    return any(path.startswith(p) for p in BLOCKED_IN_APP_PREFIXES)


IN_APP_PLAN_RULE = (
    "This user is in the DevOps Agent iPhone app. Never mention prices, plan names, upgrading, "
    "billing, buying credits, or where to pay, and don't link to the billing page. If they ask "
    "about plans or billing, say that isn't available in the app."
)


def plan_context(tier_name: str, credits_left: int, in_app: bool) -> str | None:
    """The PLAN CONTEXT line added to the agent's prompt (both chat routes)."""
    if tier_name != 'free':
        return IN_APP_PLAN_RULE if in_app else None
    text = (
        f"PLAN CONTEXT: This user is on the Free plan with {credits_left} of their 20 monthly "
        "credits left; they refill each month. "
        "They are experiencing the full DevOps agent with real tool execution. "
    )
    if in_app:
        return text + IN_APP_PLAN_RULE
    if credits_left <= 5:
        text += (
            "Their credits are running low. Naturally weave in a brief mention that they can "
            "upgrade to the Starter plan ($29/month) for 200 credits a month, or wait for next "
            "month's refill. Do NOT make this the focus -- still answer their question fully first."
        )
    return text
