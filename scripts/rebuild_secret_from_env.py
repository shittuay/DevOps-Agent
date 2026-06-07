"""Rebuild the consolidated AWS Secrets Manager secret from the server's .env.

One-off recovery utility (e.g. after an account migration where the
`devops-agent/production` secret was lost). Reads the managed keys from the
local .env and writes them into Secrets Manager using whatever AWS credentials
are in the boto3 default chain (on the EC2 box that's the instance role).

Deliberately EXCLUDES AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY: the app now
authenticates to AWS via the instance role, so the secret must not re-inject
static credentials into the environment.

Prints only the secret ARN, the key count, and the key *names* — never values.

Usage (on the server):
    cd /var/www/devops-agent && ./venv/bin/python scripts/rebuild_secret_from_env.py
"""
import json
import os
import sys

import boto3
from dotenv import dotenv_values

# Allow `from services...` when run as a standalone script
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from services.secrets_manager import MANAGED_SECRET_KEYS, PRIMARY_SECRET_NAME

REGION = "us-east-1"
ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
EXCLUDE = {"AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"}


def main() -> int:
    env = dotenv_values(ENV_PATH)
    payload = {
        k: env[k]
        for k in MANAGED_SECRET_KEYS
        if env.get(k) and k not in EXCLUDE
    }
    if not payload:
        print("ERROR: no managed keys found in .env — nothing to write")
        return 1

    client = boto3.client("secretsmanager", region_name=REGION)
    secret_string = json.dumps(payload)
    try:
        resp = client.create_secret(
            Name=PRIMARY_SECRET_NAME,
            Description="DevOps Agent consolidated production secrets (rebuilt from .env)",
            SecretString=secret_string,
        )
        print("CREATED_ARN:", resp["ARN"])
    except client.exceptions.ResourceExistsException:
        resp = client.put_secret_value(SecretId=PRIMARY_SECRET_NAME, SecretString=secret_string)
        print("UPDATED_ARN:", resp["ARN"])

    print("KEY_COUNT:", len(payload))
    print("KEYS:", ",".join(sorted(payload.keys())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
