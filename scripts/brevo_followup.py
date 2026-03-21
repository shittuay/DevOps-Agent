"""
Brevo Follow-up Campaign — DevOps Agent (Non-openers)

Sends a follow-up email to everyone on the original list who hasn't opened
the first campaign. Run this 3+ days after the initial campaign.

Usage:
  python scripts/brevo_followup.py --campaign-id 7
  python scripts/brevo_followup.py --campaign-id 7 --send
  python scripts/brevo_followup.py --campaign-id 7 --schedule "2026-03-25T10:00:00+01:00"

  --campaign-id   ID of the original campaign (required)
  --send          Send immediately without confirmation prompt
  --schedule      Schedule at a specific ISO 8601 datetime
  --min-days      Minimum days since original send before following up (default: 3)
"""

import os
import sys
import time
import requests
from pathlib import Path
from datetime import datetime, timezone

# Load .env files from project root
def _load_env(path):
    if path.exists():
        with open(path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, _, v = line.partition('=')
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

_root = Path(__file__).resolve().parent.parent
_load_env(_root / 'config' / '.env')
_load_env(_root / '.env')

BREVO_API_KEY = os.getenv('BREVO_API_KEY', '')
_configured_url = os.getenv('BASE_URL', 'https://devopsagent.io')
BASE_URL = 'https://devopsagent.io' if 'localhost' in _configured_url else _configured_url
BREVO_BASE = 'https://api.brevo.com/v3'
SENDER_NAME = os.getenv('EMAIL_FROM_NAME', 'DevOps Agent')

FOLLOWUP_CAMPAIGN_NAME = 'DevOps Agent — Follow-up (Non-openers)'
FOLLOWUP_SUBJECT = 'Still managing cloud infra the hard way?'


def headers():
    return {
        'api-key': BREVO_API_KEY,
        'Content-Type': 'application/json',
        'Accept': 'application/json',
    }


def get_campaign_stats(campaign_id):
    """Fetch stats and metadata for the original campaign."""
    resp = requests.get(f'{BREVO_BASE}/emailCampaigns/{campaign_id}', headers=headers())
    resp.raise_for_status()
    return resp.json()


def get_verified_sender():
    resp = requests.get(f'{BREVO_BASE}/senders', headers=headers())
    resp.raise_for_status()
    active = [s for s in resp.json().get('senders', []) if s.get('active')]
    if not active:
        raise RuntimeError('No verified senders in Brevo. Add one first.')
    preferred = [s for s in active if s.get('email', '').endswith('@devopsagent.io')]
    sender = preferred[0] if preferred else active[0]
    print(f'  Sender: {SENDER_NAME} <{sender["email"]}>')
    return {'name': SENDER_NAME, 'email': sender['email']}


def build_followup_html():
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{FOLLOWUP_SUBJECT}</title>
</head>
<body style="margin:0;padding:0;background:#0f172a;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#0f172a;">
    <tr>
      <td align="center" style="padding:40px 16px;">
        <table width="560" cellpadding="0" cellspacing="0" border="0" style="max-width:560px;width:100%;">

          <!-- Header -->
          <tr>
            <td style="padding-bottom:32px;text-align:center;">
              <span style="font-size:22px;font-weight:700;color:#ff6b35;letter-spacing:-0.5px;">DevOps Agent</span>
            </td>
          </tr>

          <!-- Hero card -->
          <tr>
            <td style="background:#1e293b;border-radius:16px;padding:40px 36px;">

              <h1 style="margin:0 0 16px;font-size:28px;font-weight:700;line-height:1.3;color:#f8fafc;">
                Still managing cloud infra the hard way?
              </h1>
              <p style="margin:0 0 24px;font-size:16px;line-height:1.6;color:#94a3b8;">
                We reached out last week about DevOps Agent. In case it got buried — here's what it actually does in 30 seconds:
              </p>

              <!-- Quick demo -->
              <div style="background:#0f172a;border-radius:10px;padding:20px 24px;margin-bottom:28px;border:1px solid #334155;">
                <p style="margin:0 0 12px;font-size:13px;font-weight:600;color:#ff6b35;">Instead of this:</p>
                <p style="margin:0 0 16px;font-size:13px;color:#64748b;font-family:monospace;">
                  aws ec2 describe-instances --filters Name=instance-state-name,Values=running --query '...' | jq '.[][].Instances[].InstanceId'
                </p>
                <p style="margin:0 0 12px;font-size:13px;font-weight:600;color:#10b981;">You just type:</p>
                <p style="margin:0;font-size:14px;color:#86efac;font-family:monospace;">"List all running EC2 instances"</p>
              </div>

              <!-- 3 reasons -->
              <p style="margin:0 0 16px;font-size:15px;font-weight:600;color:#f1f5f9;">Why teams switch to DevOps Agent:</p>
              <table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-bottom:28px;">
                <tr>
                  <td style="padding:8px 0;vertical-align:top;width:28px;font-size:16px;">⚡</td>
                  <td style="padding:8px 0;">
                    <span style="font-size:14px;font-weight:600;color:#f1f5f9;">10x faster for routine ops</span>
                    <span style="font-size:13px;color:#64748b;display:block;">No CLI flags to memorise. No console tabs. Just ask.</span>
                  </td>
                </tr>
                <tr>
                  <td style="padding:8px 0;vertical-align:top;font-size:16px;">🔒</td>
                  <td style="padding:8px 0;">
                    <span style="font-size:14px;font-weight:600;color:#f1f5f9;">Safe by design</span>
                    <span style="font-size:13px;color:#64748b;display:block;">Deletes and restarts always ask for confirmation first.</span>
                  </td>
                </tr>
                <tr>
                  <td style="padding:8px 0;vertical-align:top;font-size:16px;">☁️</td>
                  <td style="padding:8px 0;">
                    <span style="font-size:14px;font-weight:600;color:#f1f5f9;">All clouds, one chat</span>
                    <span style="font-size:13px;color:#64748b;display:block;">AWS, Azure, GCP, Kubernetes — 258 tools, zero context switching.</span>
                  </td>
                </tr>
              </table>

              <!-- Social proof nudge -->
              <div style="background:#0f172a;border-left:3px solid #ff6b35;padding:16px 20px;margin-bottom:28px;border-radius:0 8px 8px 0;">
                <p style="margin:0;font-size:14px;color:#94a3b8;font-style:italic;">
                  "I cancelled my AWS Console bookmark. Everything I need is in the chat."
                </p>
              </div>

              <!-- Free trial reminder -->
              <p style="margin:0 0 24px;font-size:15px;color:#94a3b8;text-align:center;">
                Still <strong style="color:#f8fafc;">free to start</strong> — 20 credits, no credit card required.
              </p>

              <!-- CTA -->
              <table width="100%" cellpadding="0" cellspacing="0" border="0">
                <tr>
                  <td align="center">
                    <a href="{BASE_URL}/signup" style="display:inline-block;padding:16px 48px;background:linear-gradient(135deg,#ff6b35,#f7931e);color:#ffffff;text-decoration:none;border-radius:10px;font-size:16px;font-weight:700;">
                      Try It Free
                    </a>
                  </td>
                </tr>
              </table>

            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="padding-top:32px;text-align:center;">
              <p style="margin:0 0 8px;font-size:13px;color:#475569;">
                <a href="{BASE_URL}" style="color:#ff6b35;text-decoration:none;">devopsagent.io</a>
                &nbsp;·&nbsp;
                <a href="{BASE_URL}/docs" style="color:#475569;text-decoration:none;">Docs</a>
                &nbsp;·&nbsp;
                <a href="{BASE_URL}/status" style="color:#475569;text-decoration:none;">Status</a>
              </p>
              <p style="margin:0;font-size:12px;color:#334155;">
                You're receiving this because you know the team building DevOps Agent.<br>
                <a href="{{{{ unsubscribe }}}}" style="color:#475569;">Unsubscribe</a>
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def build_followup_text():
    return f"""Still managing cloud infra the hard way?

Instead of:
  aws ec2 describe-instances --filters ... | jq '...'

You just type: "List all running EC2 instances"

DevOps Agent supports AWS, Azure, GCP, and Kubernetes — 258 tools, one chat.
Deletes and restarts always confirm before executing.

Still free to start — 20 credits, no credit card.

{BASE_URL}/signup

---
DevOps Agent | {BASE_URL}
"""


def create_followup_campaign(list_ids, original_stats):
    """Create the follow-up campaign targeting the same list."""
    sender = get_verified_sender()

    sent = original_stats.get('campaignStats', [{}])[0].get('sent', 0)
    unique_views = original_stats.get('campaignStats', [{}])[0].get('uniqueViews', 0)
    open_rate = round(unique_views / sent * 100, 1) if sent else 0
    print(f'  Original campaign: {sent} sent, {unique_views} opens ({open_rate}% open rate)')

    payload = {
        'name': FOLLOWUP_CAMPAIGN_NAME,
        'subject': FOLLOWUP_SUBJECT,
        'sender': sender,
        'replyTo': sender['email'],
        'htmlContent': build_followup_html(),
        'textContent': build_followup_text(),
        'recipients': {'listIds': list_ids},
        'header': SENDER_NAME,
        'footer': f'© 2026 DevOps Agent · {BASE_URL}',
    }

    resp = requests.post(f'{BREVO_BASE}/emailCampaigns', headers=headers(), json=payload)
    if resp.status_code not in (200, 201):
        print(f'  Campaign creation failed: {resp.status_code} — {resp.text}')
        resp.raise_for_status()

    campaign_id = resp.json()['id']
    print(f'  Follow-up campaign created (id={campaign_id})')
    return campaign_id


def send_now(campaign_id):
    resp = requests.post(f'{BREVO_BASE}/emailCampaigns/{campaign_id}/sendNow', headers=headers())
    resp.raise_for_status()
    print(f'  Campaign {campaign_id} sent.')


def schedule_campaign(campaign_id, scheduled_at):
    resp = requests.put(
        f'{BREVO_BASE}/emailCampaigns/{campaign_id}',
        headers=headers(),
        json={'scheduledAt': scheduled_at},
    )
    resp.raise_for_status()
    resp2 = requests.post(f'{BREVO_BASE}/emailCampaigns/{campaign_id}/sendNow', headers=headers())
    resp2.raise_for_status()
    print(f'  Campaign {campaign_id} scheduled for {scheduled_at}.')


def parse_args():
    args = {'campaign_id': None, 'send': False, 'schedule': None, 'min_days': 3}
    i = 1
    while i < len(sys.argv):
        arg = sys.argv[i]
        if arg == '--campaign-id' and i + 1 < len(sys.argv):
            args['campaign_id'] = int(sys.argv[i + 1]); i += 2
        elif arg == '--send':
            args['send'] = True; i += 1
        elif arg == '--schedule' and i + 1 < len(sys.argv):
            args['schedule'] = sys.argv[i + 1]; i += 2
        elif arg == '--min-days' and i + 1 < len(sys.argv):
            args['min_days'] = int(sys.argv[i + 1]); i += 2
        else:
            i += 1
    return args


def main():
    if not BREVO_API_KEY:
        print('ERROR: BREVO_API_KEY not set.')
        sys.exit(1)

    args = parse_args()
    if not args['campaign_id']:
        print('Usage: python scripts/brevo_followup.py --campaign-id <id> [--send] [--schedule ISO8601]')
        print('       python scripts/brevo_followup.py --campaign-id 7')
        sys.exit(1)

    print(f'\n=== DevOps Agent — Follow-up Campaign (non-openers of #{args["campaign_id"]}) ===\n')

    print('[1/2] Fetching original campaign stats...')
    original = get_campaign_stats(args['campaign_id'])
    status = original.get('status', 'unknown')
    sent_date = original.get('sentDate', 'not sent yet')
    print(f'  Original campaign status: {status} | sent: {sent_date}')

    # Check minimum days have passed
    if sent_date and sent_date != 'not sent yet':
        try:
            sent_dt = datetime.fromisoformat(sent_date.replace('Z', '+00:00'))
            days_since = (datetime.now(timezone.utc) - sent_dt).days
            if days_since < args['min_days']:
                print(f'  Only {days_since} day(s) since original send.')
                print(f'  Recommended to wait at least {args["min_days"]} days. Use --min-days 0 to override.')
                if '--min-days' not in sys.argv:
                    sys.exit(0)
        except Exception:
            pass

    # Get list IDs from original campaign
    stats = original.get('statistics', {})
    campaign_stats = stats.get('campaignStats', [])
    list_ids = [s['listId'] for s in campaign_stats if s.get('listId')]
    if not list_ids:
        # Fallback: use the known list id
        list_ids = [3]
    print(f'  Targeting list(s): {list_ids}')

    print('[2/2] Creating follow-up campaign...')
    campaign_id = create_followup_campaign(list_ids, stats)

    print(f'\nFollow-up campaign ready (id={campaign_id}).')
    print(f'Links point to: {BASE_URL}')

    if args['schedule']:
        schedule_campaign(campaign_id, args['schedule'])
    elif args['send']:
        send_now(campaign_id)
    else:
        try:
            answer = input('\nSend follow-up now? [y/N] ').strip().lower()
        except EOFError:
            answer = 'n'
        if answer == 'y':
            send_now(campaign_id)
        else:
            print(f'\nSaved as draft (id={campaign_id}).')
            print(f'Send:     python scripts/brevo_followup.py --campaign-id {args["campaign_id"]} --send')
            print(f'Schedule: python scripts/brevo_followup.py --campaign-id {args["campaign_id"]} --schedule "2026-03-25T10:00:00+01:00"')

    print('\nDone.')


if __name__ == '__main__':
    main()
