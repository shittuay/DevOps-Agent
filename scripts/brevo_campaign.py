"""
Brevo Marketing Campaign — DevOps Agent Launch

Usage:
  1. Put contacts in contacts.csv (columns: email, firstName, lastName)
  2. Run: python scripts/brevo_campaign.py

What it does:
  - Creates a Brevo contact list named "DevOps Agent Launch"
  - Imports all contacts from contacts.csv into that list
  - Creates a launch campaign with the HTML email template
  - Sends it immediately (or pass --schedule "2026-03-22 09:00:00" to schedule)

Env:
  BREVO_API_KEY — required
  BASE_URL      — optional, defaults to https://devopsagent.io
"""

import os
import sys
import csv
import json
import base64
import time
import requests
from datetime import datetime, timezone
from pathlib import Path

# Load .env files from the project root (one level up from scripts/)
def _load_env(path):
    if path.exists():
        with open(path, encoding='utf-8') as _f:
            for _line in _f:
                _line = _line.strip()
                if _line and not _line.startswith('#') and '=' in _line:
                    _k, _, _v = _line.partition('=')
                    os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))

_root = Path(__file__).resolve().parent.parent
_load_env(_root / 'config' / '.env')
_load_env(_root / '.env')

BREVO_API_KEY = os.getenv('BREVO_API_KEY', '')
BASE_URL = os.getenv('BASE_URL', 'https://devopsagent.io')
BREVO_BASE = 'https://api.brevo.com/v3'

SENDER_EMAIL = os.getenv('EMAIL_FROM', 'noreply@devopsagent.io')
SENDER_NAME = os.getenv('EMAIL_FROM_NAME', 'DevOps Agent')
REPLY_TO_EMAIL = os.getenv('REPLY_TO_EMAIL', 'hello@devopsagent.io')

LIST_NAME = 'DevOps Agent Launch'
CAMPAIGN_NAME = 'DevOps Agent — Free Trial Launch'
SUBJECT = 'Automate your cloud infrastructure with AI — free trial'


def headers():
    return {
        'api-key': BREVO_API_KEY,
        'Content-Type': 'application/json',
        'Accept': 'application/json',
    }


def build_html():
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{SUBJECT}</title>
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

              <p style="margin:0 0 8px;font-size:13px;font-weight:600;color:#ff6b35;text-transform:uppercase;letter-spacing:1px;">Introducing</p>
              <h1 style="margin:0 0 16px;font-size:32px;font-weight:700;line-height:1.2;color:#f8fafc;">
                Your AI DevOps engineer,<br>available 24/7
              </h1>
              <p style="margin:0 0 28px;font-size:16px;line-height:1.6;color:#94a3b8;">
                DevOps Agent lets you manage AWS, Azure, GCP, and Kubernetes through plain English — no CLIs, no console tabs, no context switching.
              </p>

              <!-- Terminal demo block -->
              <div style="background:#0f172a;border-radius:10px;padding:20px 24px;margin-bottom:28px;border:1px solid #334155;">
                <p style="margin:0 0 4px;font-size:11px;color:#64748b;font-family:monospace;">you</p>
                <p style="margin:0 0 16px;font-size:14px;color:#e2e8f0;font-family:monospace;">"List all EC2 instances running in us-east-1 and show me any with high CPU"</p>
                <p style="margin:0 0 4px;font-size:11px;color:#ff6b35;font-family:monospace;">agent</p>
                <p style="margin:0;font-size:14px;color:#86efac;font-family:monospace;">Found 12 instances. 2 have CPU &gt; 80% — i-0a3f... (web-prod) and i-09b2... (worker-3). Want me to investigate or scale up?</p>
              </div>

              <!-- Features -->
              <table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-bottom:32px;">
                <tr>
                  <td style="padding:12px 16px;background:#0f172a;border-radius:8px;border:1px solid #1e3a5f;vertical-align:top;width:48%;">
                    <p style="margin:0 0 4px;font-size:20px;">☁️</p>
                    <p style="margin:0 0 4px;font-size:14px;font-weight:600;color:#f1f5f9;">Multi-cloud</p>
                    <p style="margin:0;font-size:13px;color:#64748b;">AWS, Azure, GCP + Kubernetes — all from one chat</p>
                  </td>
                  <td width="16"></td>
                  <td style="padding:12px 16px;background:#0f172a;border-radius:8px;border:1px solid #1e3a5f;vertical-align:top;width:48%;">
                    <p style="margin:0 0 4px;font-size:20px;">🔒</p>
                    <p style="margin:0 0 4px;font-size:14px;font-weight:600;color:#f1f5f9;">Safe by default</p>
                    <p style="margin:0;font-size:13px;color:#64748b;">Destructive ops require confirmation. Always.</p>
                  </td>
                </tr>
                <tr><td height="12" colspan="3"></td></tr>
                <tr>
                  <td style="padding:12px 16px;background:#0f172a;border-radius:8px;border:1px solid #1e3a5f;vertical-align:top;width:48%;">
                    <p style="margin:0 0 4px;font-size:20px;">⚡</p>
                    <p style="margin:0 0 4px;font-size:14px;font-weight:600;color:#f1f5f9;">258 tools built in</p>
                    <p style="margin:0;font-size:13px;color:#64748b;">EC2, RDS, IAM, Lambda, EKS, GKE, AKS and more</p>
                  </td>
                  <td width="16"></td>
                  <td style="padding:12px 16px;background:#0f172a;border-radius:8px;border:1px solid #1e3a5f;vertical-align:top;width:48%;">
                    <p style="margin:0 0 4px;font-size:20px;">📊</p>
                    <p style="margin:0 0 4px;font-size:14px;font-weight:600;color:#f1f5f9;">Cost optimisation</p>
                    <p style="margin:0;font-size:13px;color:#64748b;">Spot idle resources, rightsizing suggestions, savings alerts</p>
                  </td>
                </tr>
              </table>

              <!-- Free trial callout -->
              <div style="background:linear-gradient(135deg,#1a1a2e,#16213e);border:1px solid #ff6b35;border-radius:12px;padding:24px;margin-bottom:32px;text-align:center;">
                <p style="margin:0 0 4px;font-size:13px;font-weight:600;color:#ff6b35;text-transform:uppercase;letter-spacing:1px;">Free trial</p>
                <p style="margin:0 0 8px;font-size:28px;font-weight:700;color:#f8fafc;">20 credits — no credit card</p>
                <p style="margin:0;font-size:14px;color:#94a3b8;">Full agent experience. Real tools. Real cloud access.</p>
              </div>

              <!-- CTA -->
              <table width="100%" cellpadding="0" cellspacing="0" border="0">
                <tr>
                  <td align="center">
                    <a href="{BASE_URL}/signup" style="display:inline-block;padding:16px 48px;background:linear-gradient(135deg,#ff6b35,#f7931e);color:#ffffff;text-decoration:none;border-radius:10px;font-size:16px;font-weight:700;letter-spacing:0.3px;">
                      Start Free Trial
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


def build_text():
    return f"""DevOps Agent — Your AI DevOps engineer, available 24/7

Manage AWS, Azure, GCP, and Kubernetes through plain English.
No CLIs, no console tabs, no context switching.

258 tools built in: EC2, RDS, IAM, Lambda, EKS, GKE, AKS and more.

Free trial: 20 credits, no credit card required.
Full agent experience. Real tools. Real cloud access.

Start your free trial: {BASE_URL}/signup

---
DevOps Agent | {BASE_URL}
"""


def get_or_create_list():
    """Return Brevo list ID for LIST_NAME, creating it if it doesn't exist."""
    resp = requests.get(f'{BREVO_BASE}/contacts/lists', headers=headers(), params={'limit': 50})
    resp.raise_for_status()
    for lst in resp.json().get('lists', []):
        if lst['name'] == LIST_NAME:
            print(f'  Using existing list "{LIST_NAME}" (id={lst["id"]})')
            return lst['id']

    resp = requests.post(
        f'{BREVO_BASE}/contacts/lists',
        headers=headers(),
        json={'name': LIST_NAME, 'folderId': 1},
    )
    resp.raise_for_status()
    list_id = resp.json()['id']
    print(f'  Created list "{LIST_NAME}" (id={list_id})')
    return list_id


def import_contacts(list_id, csv_path):
    """
    Import contacts from CSV into the Brevo list using file-based import.
    Single API call regardless of list size — handles 1000+ contacts safely.

    Brevo normalises column headers: email → EMAIL, firstName → FIRSTNAME, lastName → LASTNAME.
    Unrecognised columns are silently ignored.
    """
    # Read and validate the CSV
    rows = []
    with open(csv_path, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            email = row.get('email', '').strip()
            if not email or '@' not in email:
                continue
            rows.append(row)

    if not rows:
        print('  No valid contacts found in CSV.')
        return 0

    print(f'  {len(rows)} contacts read from {csv_path}')

    # Rebuild a clean CSV in memory with only the columns Brevo understands
    import io
    buf = io.StringIO()
    fieldnames = ['email', 'firstName', 'lastName']
    writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction='ignore', lineterminator='\n')
    writer.writeheader()
    for row in rows:
        writer.writerow({
            'email': row.get('email', '').strip(),
            'firstName': row.get('firstName', row.get('first_name', row.get('name', ''))).strip(),
            'lastName': row.get('lastName', row.get('last_name', '')).strip(),
        })

    csv_bytes = buf.getvalue().encode('utf-8')
    encoded = base64.b64encode(csv_bytes).decode('ascii')

    # Single Brevo file-import call
    resp = requests.post(
        f'{BREVO_BASE}/contacts/import',
        headers=headers(),
        json={
            'updateEnabled': True,
            'fileBody': encoded,
            'listIds': [list_id],
            'emailBlacklist': False,
            'smsBlacklist': False,
        },
    )

    if resp.status_code not in (200, 201, 202):
        print(f'  Import failed: {resp.status_code} — {resp.text}')
        resp.raise_for_status()

    process_id = resp.json().get('processId')
    print(f'  Import job submitted (processId={process_id}). Brevo processes this asynchronously.')
    print(f'  Polling for completion...')

    # Poll the process status (max 60s)
    if process_id:
        for attempt in range(12):
            time.sleep(5)
            poll = requests.get(f'{BREVO_BASE}/processes/{process_id}', headers=headers())
            if poll.status_code == 200:
                status = poll.json().get('status', '')
                print(f'  [{attempt + 1}/12] Status: {status}')
                if status == 'completed':
                    break
                if status == 'error':
                    print(f'  Import error: {poll.json()}')
                    break
            else:
                print(f'  Could not poll status: {poll.status_code}')
                break

    return len(rows)


def create_campaign(list_id):
    """Create the email campaign in Brevo and return campaign id."""
    payload = {
        'name': CAMPAIGN_NAME,
        'subject': SUBJECT,
        'sender': {'name': SENDER_NAME, 'email': SENDER_EMAIL},
        'replyTo': REPLY_TO_EMAIL,
        'htmlContent': build_html(),
        'textContent': build_text(),
        'recipients': {'listIds': [list_id]},
        'header': SENDER_NAME,
        'footer': f'© 2026 DevOps Agent · {BASE_URL}',
    }

    resp = requests.post(f'{BREVO_BASE}/emailCampaigns', headers=headers(), json=payload)
    if resp.status_code not in (200, 201):
        print(f'  Campaign creation failed: {resp.status_code} — {resp.text}')
        resp.raise_for_status()

    campaign_id = resp.json()['id']
    print(f'  Campaign created (id={campaign_id})')
    return campaign_id


def send_now(campaign_id):
    resp = requests.post(f'{BREVO_BASE}/emailCampaigns/{campaign_id}/sendNow', headers=headers())
    resp.raise_for_status()
    print(f'  Campaign {campaign_id} sent.')


def schedule_campaign(campaign_id, scheduled_at):
    """scheduled_at: ISO 8601 string e.g. '2026-03-22T09:00:00+01:00'"""
    resp = requests.put(
        f'{BREVO_BASE}/emailCampaigns/{campaign_id}',
        headers=headers(),
        json={'scheduledAt': scheduled_at},
    )
    resp.raise_for_status()
    resp2 = requests.post(f'{BREVO_BASE}/emailCampaigns/{campaign_id}/sendNow', headers=headers())
    resp2.raise_for_status()
    print(f'  Campaign {campaign_id} scheduled for {scheduled_at}.')


def main():
    if not BREVO_API_KEY:
        print('ERROR: BREVO_API_KEY not set.')
        sys.exit(1)

    # Determine contacts CSV path
    csv_path = 'contacts.csv'
    if len(sys.argv) > 1 and not sys.argv[1].startswith('--'):
        csv_path = sys.argv[1]

    # Determine schedule
    schedule_arg = None
    for i, arg in enumerate(sys.argv):
        if arg == '--schedule' and i + 1 < len(sys.argv):
            schedule_arg = sys.argv[i + 1]

    print('\n=== DevOps Agent — Brevo Launch Campaign ===\n')

    print('[1/3] Setting up contact list...')
    list_id = get_or_create_list()

    if os.path.exists(csv_path):
        print(f'[2/3] Importing contacts from {csv_path}...')
        count = import_contacts(list_id, csv_path)
        print(f'  Total imported: {count}')
    else:
        print(f'[2/3] No contacts.csv found at {csv_path} — skipping import.')
        print('      Create contacts.csv with columns: email, firstName, lastName')
        print('      Then re-run to import before sending.')

    print('[3/3] Creating campaign...')
    campaign_id = create_campaign(list_id)

    if schedule_arg:
        print(f'Scheduling campaign for {schedule_arg}...')
        schedule_campaign(campaign_id, schedule_arg)
    else:
        contact_count = count if os.path.exists(csv_path) else '?'
        print(f'\nCampaign ready — will send to {contact_count} contacts.')
        answer = input('Send campaign now? [y/N] ').strip().lower()
        if answer == 'y':
            send_now(campaign_id)
        else:
            print(f'\nCampaign saved as draft (id={campaign_id}).')
            print('Send it manually from the Brevo dashboard or re-run with --schedule.')

    print('\nDone.')


if __name__ == '__main__':
    main()
