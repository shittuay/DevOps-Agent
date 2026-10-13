"""List users whose AWS connection is an IAM role that trusts the platform account.

Those roles name the platform AWS account id in their trust policy, so they stop
working when the platform moves to a new account unless each customer updates the
trust policy (or PLATFORM_BRIDGE_ROLE_ARN bridges them during the transition). See
docs/aws-account-migration.md.

Run on the production box, where the database and the credential key are:

    python scripts/count_role_arn_customers.py

Prints counts, plus one line per role-based user (id, email, role ARN). External IDs
and access keys are never printed.
"""
import os
import sys
from typing import Dict, Iterable, List, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def summarize(rows: Iterable[Tuple[int, str, Dict]]) -> Dict:
    """rows: (user_id, email, decrypted credential dict) for active AWS credentials."""
    role_users: List[Tuple[int, str, str]] = []
    access_key = 0
    unreadable = 0
    for user_id, email, creds in rows:
        if creds is None:
            unreadable += 1
        elif creds.get('role_arn'):
            role_users.append((user_id, email, creds['role_arn']))
        elif creds.get('access_key'):
            access_key += 1
        else:
            unreadable += 1
    return {'role_arn': role_users, 'access_key': access_key, 'unreadable': unreadable}


def _rows():
    from models import User, UserCloudCredential

    query = (UserCloudCredential.query
             .filter_by(cloud_provider='aws', is_active=True)
             .join(User, User.id == UserCloudCredential.user_id)
             .with_entities(UserCloudCredential, User.email))
    for cred, email in query:
        try:
            creds = cred.get_credentials()
        except Exception:
            creds = None
        yield cred.user_id, email, creds


def main() -> None:
    from app import app

    with app.app_context():
        result = summarize(_rows())

    print(f"Active AWS connections using an IAM role: {len(result['role_arn'])}")
    print(f"Active AWS connections using access keys: {result['access_key']} (unaffected by the move)")
    if result['unreadable']:
        print(f"Unreadable/empty AWS connections: {result['unreadable']} (check CREDENTIAL_ENCRYPTION_KEY)")
    for user_id, email, role_arn in result['role_arn']:
        print(f"  user {user_id}  {email}  {role_arn}")


if __name__ == '__main__':
    main()
