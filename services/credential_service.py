"""
Service for managing per-user cloud credentials.
Provides functions to get user-specific cloud clients (AWS, Azure, GCP).
"""
import os
import json
import logging
import tempfile
from typing import Optional, Dict, Any, Tuple
from datetime import datetime

import boto3
from botocore.exceptions import NoCredentialsError, ClientError
from src.utils.timeutils import utcnow

logger = logging.getLogger(__name__)

def get_user_aws_credentials(user_id: int) -> Optional[Dict[str, str]]:
    """
    Get AWS credentials for a specific user.

    Supports two auth modes:
      - 'access_key': Direct access key + secret key (simple, for self-hosting teams)
      - 'role_arn': IAM Role ARN via AssumeRole (cross-account delegation)

    Args:
        user_id: The user's ID

    Returns:
        Dict with auth_mode and credentials, or None if not configured
    """
    from models import UserCloudCredential, db

    cred = UserCloudCredential.query.filter_by(
        user_id=user_id,
        cloud_provider='aws',
        is_active=True
    ).first()

    if not cred:
        return None

    credentials = cred.get_credentials()
    region = cred.default_region or credentials.get('region', 'us-east-1')

    if credentials.get('role_arn'):
        return {
            'auth_mode': 'role_arn',
            'role_arn': credentials['role_arn'],
            'external_id': credentials.get('external_id', ''),
            'region': region,
            'self_grant': bool(credentials.get('self_grant')),
        }

    if credentials.get('access_key') and credentials.get('secret_key'):
        return {
            'auth_mode': 'access_key',
            'access_key': credentials['access_key'],
            'secret_key': credentials['secret_key'],
            'region': region
        }

    return None


def get_user_azure_credentials(user_id: int) -> Optional[Dict[str, str]]:
    """
    Get Azure credentials for a specific user.

    Args:
        user_id: The user's ID

    Returns:
        Dict with subscription_id, tenant_id, client_id, client_secret, or None
    """
    from models import UserCloudCredential, db

    cred = UserCloudCredential.query.filter_by(
        user_id=user_id,
        cloud_provider='azure',
        is_active=True
    ).first()

    if not cred:
        return None

    credentials = cred.get_credentials()
    required_fields = ['subscription_id', 'tenant_id', 'client_id', 'client_secret']
    if not all(credentials.get(f) for f in required_fields):
        return None

    return {
        'subscription_id': credentials.get('subscription_id'),
        'tenant_id': credentials.get('tenant_id'),
        'client_id': credentials.get('client_id'),
        'client_secret': credentials.get('client_secret'),
        'location': cred.default_region or credentials.get('location', 'eastus')
    }


def get_user_gcp_credentials(user_id: int) -> Optional[Dict[str, Any]]:
    """
    Get GCP credentials for a specific user.

    Args:
        user_id: The user's ID

    Returns:
        Dict with project_id and service_account_json, or None
    """
    from models import UserCloudCredential, db

    cred = UserCloudCredential.query.filter_by(
        user_id=user_id,
        cloud_provider='gcp',
        is_active=True
    ).first()

    if not cred:
        return None

    credentials = cred.get_credentials()
    if not credentials.get('project_id') or not credentials.get('service_account_json'):
        return None

    return {
        'project_id': credentials.get('project_id'),
        'service_account_json': credentials.get('service_account_json'),
        'region': cred.default_region or credentials.get('region', 'us-central1'),
        'zone': cred.default_zone or credentials.get('zone', 'us-central1-a')
    }


def _assume_role(role_arn: str, external_id: str = '', session_name: str = 'devops-agent') -> Dict[str, str]:
    """
    Assume an IAM role and return temporary credentials.

    Uses the platform's own identity (instance profile / env vars) to call STS AssumeRole.

    Args:
        role_arn: The IAM Role ARN to assume
        external_id: Optional external ID for confused-deputy protection
        session_name: Session name for CloudTrail auditing

    Returns:
        Dict with AccessKeyId, SecretAccessKey, SessionToken

    Raises:
        Exception if AssumeRole fails
    """
    params = {
        'RoleArn': role_arn,
        'RoleSessionName': session_name,
        # 3600s is also the hard ceiling for a chained session (bridge path below).
        'DurationSeconds': 3600,
    }
    if external_id:
        params['ExternalId'] = external_id

    try:
        response = boto3.client('sts').assume_role(**params)
        return response['Credentials']
    except NoCredentialsError:
        raise Exception(
            "Platform AWS credentials not configured. The server needs an IAM role or "
            "environment credentials to assume customer roles. Contact your administrator."
        )
    except ClientError as e:
        code = e.response['Error']['Code']
        if code != 'AccessDenied':
            raise Exception(f"Failed to assume role: {e.response['Error']['Message']}")
        bridged = _assume_role_via_bridge(params)
        if bridged is not None:
            return bridged
        raise Exception(
            f"Access denied when assuming role {role_arn}. Verify the role's trust policy "
            "allows this platform to assume it, and the External ID matches if required."
        )


def _assume_role_via_bridge(params: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """Retry a denied AssumeRole through the previous platform account (migration only).

    Customer roles trust the platform account by id. After the platform moves to a new
    AWS account, roles that still trust the old one deny the direct call. When
    PLATFORM_BRIDGE_ROLE_ARN names a role in the old account that trusts the new
    platform role, assume it first and call the customer role from there (role
    chaining). The customer's External ID is still sent and still enforced by their
    trust policy. Unset (the default), this is a no-op. Remove the setting once every
    customer role trusts the new account.
    """
    bridge_arn = os.environ.get('PLATFORM_BRIDGE_ROLE_ARN', '').strip()
    if not bridge_arn:
        return None
    try:
        bridge = boto3.client('sts').assume_role(
            RoleArn=bridge_arn, RoleSessionName='devops-agent-bridge', DurationSeconds=3600,
        )['Credentials']
        chained = boto3.client(
            'sts',
            aws_access_key_id=bridge['AccessKeyId'],
            aws_secret_access_key=bridge['SecretAccessKey'],
            aws_session_token=bridge['SessionToken'],
        ).assume_role(**params)
    except (ClientError, NoCredentialsError) as e:
        logger.warning('Bridge AssumeRole failed for %s: %s', params['RoleArn'], e)
        return None
    # Each hit is a customer role that still trusts only the old account.
    logger.warning('Customer role %s assumed via migration bridge; its trust policy '
                   'still names the old platform account', params['RoleArn'])
    return chained['Credentials']


def _get_boto_kwargs(creds: Dict[str, str], region: Optional[str] = None) -> Dict[str, str]:
    """
    Build boto3 credential kwargs from either access-key or role-ARN credentials.

    Returns dict suitable for passing to boto3.client() / boto3.resource().
    """
    effective_region = region or creds['region']

    if creds['auth_mode'] == 'role_arn':
        temp_creds = _assume_role(creds['role_arn'], creds.get('external_id', ''))
        return {
            'aws_access_key_id': temp_creds['AccessKeyId'],
            'aws_secret_access_key': temp_creds['SecretAccessKey'],
            'aws_session_token': temp_creds['SessionToken'],
            'region_name': effective_region
        }

    return {
        'aws_access_key_id': creds['access_key'],
        'aws_secret_access_key': creds['secret_key'],
        'region_name': effective_region
    }


def get_user_boto_client(user_id: int, service: str, region: Optional[str] = None, **client_kwargs):
    """
    Get a boto3 client configured with user-specific AWS credentials.

    Supports both direct access keys and IAM Role ARN (AssumeRole).

    Args:
        user_id: The user's ID
        service: AWS service name (ec2, s3, rds, etc.)
        region: Optional region override

    Returns:
        boto3 client configured for the user

    Raises:
        Exception if credentials not found or invalid
    """
    creds = get_user_aws_credentials(user_id)

    if not creds:
        raise Exception(
            "AWS credentials not configured. Please configure your AWS credentials in Settings."
        )

    try:
        return boto3.client(service, **_get_boto_kwargs(creds, region), **client_kwargs)
    except Exception as e:
        raise Exception(f"Failed to create AWS client: {str(e)}")


def get_user_boto_resource(user_id: int, service: str, region: Optional[str] = None):
    """
    Get a boto3 resource configured with user-specific AWS credentials.

    Supports both direct access keys and IAM Role ARN (AssumeRole).

    Args:
        user_id: The user's ID
        service: AWS service name (ec2, s3, etc.)
        region: Optional region override

    Returns:
        boto3 resource configured for the user
    """
    creds = get_user_aws_credentials(user_id)

    if not creds:
        raise Exception(
            "AWS credentials not configured. Please configure your AWS credentials in Settings."
        )

    try:
        return boto3.resource(service, **_get_boto_kwargs(creds, region))
    except Exception as e:
        raise Exception(f"Failed to create AWS resource: {str(e)}")


def get_user_azure_credential(user_id: int):
    """
    Get Azure credential object for a specific user.

    Args:
        user_id: The user's ID

    Returns:
        Tuple of (ClientSecretCredential, subscription_id, location)

    Raises:
        Exception if credentials not found
    """
    from azure.identity import ClientSecretCredential

    creds = get_user_azure_credentials(user_id)

    if not creds:
        raise Exception(
            "Azure credentials not configured. Please configure your Azure credentials in Settings."
        )

    try:
        credential = ClientSecretCredential(
            tenant_id=creds['tenant_id'],
            client_id=creds['client_id'],
            client_secret=creds['client_secret']
        )
        return credential, creds['subscription_id'], creds['location']
    except Exception as e:
        raise Exception(f"Failed to create Azure credential: {str(e)}")


def get_user_gcp_credentials_file(user_id: int) -> Tuple[str, str, str, str]:
    """
    Get GCP credentials as a temporary file path for a specific user.

    Args:
        user_id: The user's ID

    Returns:
        Tuple of (credentials_file_path, project_id, region, zone)

    Raises:
        Exception if credentials not found
    """
    creds = get_user_gcp_credentials(user_id)

    if not creds:
        raise Exception(
            "GCP credentials not configured. Please configure your GCP credentials in Settings."
        )

    # Write service account JSON to a temporary file
    # This file should be cleaned up after use
    try:
        service_account = creds['service_account_json']
        if isinstance(service_account, str):
            service_account = json.loads(service_account)

        # Create a temporary file with the service account JSON
        fd, temp_path = tempfile.mkstemp(suffix='.json', prefix='gcp_creds_')
        with os.fdopen(fd, 'w') as f:
            json.dump(service_account, f)

        return temp_path, creds['project_id'], creds['region'], creds['zone']
    except Exception as e:
        raise Exception(f"Failed to prepare GCP credentials: {str(e)}")


def save_user_aws_credentials(
    user_id: int,
    access_key: str = '',
    secret_key: str = '',
    role_arn: str = '',
    external_id: str = '',
    region: str = 'us-east-1'
) -> Tuple[bool, str]:
    """
    Save AWS credentials for a user. Supports two modes:

      1. Access Keys — pass access_key + secret_key (simple, for self-hosting teams)
      2. Role ARN — pass role_arn + optional external_id (cross-account delegation)

    Exactly one mode must be provided. The credentials are verified before saving.

    Returns:
        Tuple of (success, message)
    """
    import re
    from models import UserCloudCredential, db

    has_keys = bool(access_key and secret_key)
    has_role = bool(role_arn)

    if not has_keys and not has_role:
        return False, "Provide either Access Key + Secret Key, or a Role ARN"

    # --- Validate & test ---
    if has_role:
        if not re.match(r'^arn:aws:iam::\d{12}:role/.+$', role_arn):
            return False, "Invalid Role ARN format. Expected: arn:aws:iam::123456789012:role/RoleName"
        try:
            temp_creds = _assume_role(role_arn, external_id, session_name='devops-agent-verify')
            verify_client = boto3.client(
                'sts',
                aws_access_key_id=temp_creds['AccessKeyId'],
                aws_secret_access_key=temp_creds['SecretAccessKey'],
                aws_session_token=temp_creds['SessionToken'],
                region_name=region
            )
            identity = verify_client.get_caller_identity()
        except Exception as e:
            return False, str(e)
        stored = {'role_arn': role_arn, 'external_id': external_id, 'region': region}
        success_msg = f"AWS role configured. Assumed identity: {identity.get('Arn', '')}"
    else:
        if not access_key.startswith('AKIA'):
            return False, "Invalid AWS access key format (should start with AKIA)"
        try:
            test_client = boto3.client(
                'sts',
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region
            )
            identity = test_client.get_caller_identity()
        except ClientError as e:
            return False, f"Invalid AWS credentials: {str(e)}"
        except Exception as e:
            return False, f"Failed to validate credentials: {str(e)}"
        stored = {'access_key': access_key, 'secret_key': secret_key, 'region': region}
        success_msg = f"AWS credentials saved. Identity: {identity.get('Arn', '')}"

    # --- Persist ---
    try:
        cred = UserCloudCredential.query.filter_by(
            user_id=user_id,
            cloud_provider='aws'
        ).first()

        if not cred:
            cred = UserCloudCredential(
                user_id=user_id,
                cloud_provider='aws'
            )
            db.session.add(cred)

        cred.set_credentials(stored)
        cred.default_region = region
        cred.verification_status = 'valid'
        cred.last_verified = utcnow()
        cred.is_active = True

        db.session.commit()
        return True, success_msg
    except Exception as e:
        db.session.rollback()
        return False, f"Failed to save credentials: {str(e)}"


def set_aws_self_grant(user_id: int, enabled: bool) -> Tuple[bool, str]:
    """Let the agent add missing permissions to its own role after the owner says yes.

    Only for role-ARN connections, and only when the role has a permissions boundary
    (the CloudFormation template sets one when launched with AllowSelfGrant=Yes): the
    boundary is what stops the role granting itself more than the owner allowed.
    Saving new AWS credentials turns it off again.
    """
    from models import UserCloudCredential, db

    cred = UserCloudCredential.query.filter_by(user_id=user_id, cloud_provider='aws',
                                               is_active=True).first()
    if not cred:
        return False, "Connect an AWS account first"
    stored = cred.get_credentials()
    if not stored.get('role_arn'):
        return False, "Only available when DevOps Agent connects with an IAM role (Role ARN), not access keys"

    if enabled:
        role_name = stored['role_arn'].rsplit('/', 1)[-1]
        try:
            role = get_user_boto_client(user_id, 'iam').get_role(RoleName=role_name)['Role']
        except Exception as e:
            return False, f"Couldn't read the role to check its permissions boundary: {e}"
        if not role.get('PermissionsBoundary'):
            return False, ("The role has no permissions boundary. Update the CloudFormation stack with "
                           "AllowSelfGrant=Yes (it adds the boundary and the self-grant permission), then try again.")

    try:
        stored['self_grant'] = bool(enabled)
        cred.set_credentials(stored)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return False, f"Failed to save setting: {e}"
    return True, ("DevOps Agent will add approved permissions to its role itself" if enabled
                  else "You'll add approved permissions in AWS yourself")


def save_user_azure_credentials(
    user_id: int,
    subscription_id: str,
    tenant_id: str,
    client_id: str,
    client_secret: str,
    location: str = 'eastus'
) -> Tuple[bool, str]:
    """
    Save Azure credentials for a user.

    Args:
        user_id: The user's ID
        subscription_id: Azure subscription ID
        tenant_id: Azure tenant ID
        client_id: Azure client/application ID
        client_secret: Azure client secret
        location: Default location/region

    Returns:
        Tuple of (success, message)
    """
    from models import UserCloudCredential, db

    # Validate required fields
    if not all([subscription_id, tenant_id, client_id, client_secret]):
        return False, "All Azure credential fields are required"

    try:
        # Test credentials
        from azure.identity import ClientSecretCredential
        from azure.mgmt.resource import SubscriptionClient

        credential = ClientSecretCredential(
            tenant_id=tenant_id,
            client_id=client_id,
            client_secret=client_secret
        )
        sub_client = SubscriptionClient(credential)
        # Try to get subscription to verify credentials
        list(sub_client.subscriptions.list())
    except Exception as e:
        return False, f"Invalid Azure credentials: {str(e)}"

    try:
        # Find or create credential record
        cred = UserCloudCredential.query.filter_by(
            user_id=user_id,
            cloud_provider='azure'
        ).first()

        if not cred:
            cred = UserCloudCredential(
                user_id=user_id,
                cloud_provider='azure'
            )
            db.session.add(cred)

        # Store encrypted credentials
        cred.set_credentials({
            'subscription_id': subscription_id,
            'tenant_id': tenant_id,
            'client_id': client_id,
            'client_secret': client_secret,
            'location': location
        })
        cred.default_region = location
        cred.verification_status = 'valid'
        cred.last_verified = utcnow()
        cred.is_active = True

        db.session.commit()
        return True, "Azure credentials saved successfully"
    except Exception as e:
        db.session.rollback()
        return False, f"Failed to save credentials: {str(e)}"


def save_user_gcp_credentials(
    user_id: int,
    project_id: str,
    service_account_json: str,
    region: str = 'us-central1',
    zone: str = 'us-central1-a'
) -> Tuple[bool, str]:
    """
    Save GCP credentials for a user.

    Args:
        user_id: The user's ID
        project_id: GCP project ID
        service_account_json: Service account JSON (as string)
        region: Default region
        zone: Default zone

    Returns:
        Tuple of (success, message)
    """
    from models import UserCloudCredential, db

    # Validate required fields
    if not project_id or not service_account_json:
        return False, "Project ID and service account JSON are required"

    # Validate JSON format
    try:
        sa_json = json.loads(service_account_json) if isinstance(service_account_json, str) else service_account_json
        if 'type' not in sa_json or sa_json.get('type') != 'service_account':
            return False, "Invalid service account JSON format"
    except json.JSONDecodeError:
        return False, "Invalid JSON format for service account"

    try:
        # Test credentials by creating a temporary file and validating
        fd, temp_path = tempfile.mkstemp(suffix='.json')
        try:
            with os.fdopen(fd, 'w') as f:
                json.dump(sa_json, f)

            # Set credentials and test
            from google.cloud import storage
            from google.oauth2 import service_account

            credentials = service_account.Credentials.from_service_account_file(temp_path)
            client = storage.Client(project=project_id, credentials=credentials)
            # Try to list buckets to verify credentials
            list(client.list_buckets(max_results=1))
        finally:
            os.unlink(temp_path)
    except Exception as e:
        return False, f"Invalid GCP credentials: {str(e)}"

    try:
        # Find or create credential record
        cred = UserCloudCredential.query.filter_by(
            user_id=user_id,
            cloud_provider='gcp'
        ).first()

        if not cred:
            cred = UserCloudCredential(
                user_id=user_id,
                cloud_provider='gcp'
            )
            db.session.add(cred)

        # Store encrypted credentials
        cred.set_credentials({
            'project_id': project_id,
            'service_account_json': sa_json,
            'region': region,
            'zone': zone
        })
        cred.default_region = region
        cred.default_zone = zone
        cred.verification_status = 'valid'
        cred.last_verified = utcnow()
        cred.is_active = True

        db.session.commit()
        return True, "GCP credentials saved successfully"
    except Exception as e:
        db.session.rollback()
        return False, f"Failed to save credentials: {str(e)}"


def delete_user_cloud_credentials(user_id: int, cloud_provider: str) -> Tuple[bool, str]:
    """
    Delete cloud credentials for a user.

    Args:
        user_id: The user's ID
        cloud_provider: Cloud provider (aws, azure, gcp)

    Returns:
        Tuple of (success, message)
    """
    from models import UserCloudCredential, db

    try:
        cred = UserCloudCredential.query.filter_by(
            user_id=user_id,
            cloud_provider=cloud_provider
        ).first()

        if not cred:
            return False, f"No {cloud_provider.upper()} credentials found"

        db.session.delete(cred)
        db.session.commit()
        return True, f"{cloud_provider.upper()} credentials deleted successfully"
    except Exception as e:
        db.session.rollback()
        return False, f"Failed to delete credentials: {str(e)}"


def get_user_configured_providers(user_id: int) -> Dict[str, bool]:
    """
    Get which cloud providers are configured for a user.

    Args:
        user_id: The user's ID

    Returns:
        Dict with provider names as keys and boolean configured status
    """
    from models import UserCloudCredential

    creds = UserCloudCredential.query.filter_by(
        user_id=user_id,
        is_active=True
    ).all()

    configured = {
        'aws': False,
        'azure': False,
        'gcp': False
    }

    for cred in creds:
        if cred.verification_status == 'valid':
            configured[cred.cloud_provider] = True

    return configured


# Policy grants that appeared in published policy versions before 2026-07-24
# but are not real IAM action prefixes (AWS uses elasticfilesystem: and es:),
# so a role still carrying them predates the fixed template.
STALE_ACTION_PREFIXES = ('efs:', 'opensearch:')


def _stale_policy_actions(policy_document: Dict[str, Any]) -> list:
    statements = policy_document.get('Statement', [])
    if isinstance(statements, dict):
        statements = [statements]
    stale = []
    for stmt in statements:
        actions = stmt.get('Action', [])
        if isinstance(actions, str):
            actions = [actions]
        for action in actions:
            if action.lower().startswith(STALE_ACTION_PREFIXES):
                stale.append(action)
    return stale


def check_aws_policy_freshness(user_id: int) -> Dict[str, Any]:
    """Check whether the user's connected IAM role still carries dead policy
    grants that the published policies fixed on 2026-07-24 (efs:*/opensearch:*
    granted nothing, breaking the EFS and OpenSearch tools).

    Inspects the role's inline policies and customer-managed attached policies
    using the role's own iam:Get*/List* permissions. Returns:
      - {'applicable': False} for access-key mode or unconfigured AWS
      - {'applicable': True, 'outdated': True/False, 'stale_actions': [...]}
      - {'applicable': True, 'outdated': None, 'error': ...} when the role
        cannot read its own policies (custom setups without IAM read)
    """
    creds = get_user_aws_credentials(user_id)
    if not creds or creds.get('auth_mode') != 'role_arn':
        return {'applicable': False}

    role_name = creds['role_arn'].rsplit('/', 1)[-1]
    try:
        iam = get_user_boto_client(user_id, 'iam')
        stale = []
        checked = []
        for policy_name in iam.list_role_policies(RoleName=role_name)['PolicyNames']:
            doc = iam.get_role_policy(RoleName=role_name, PolicyName=policy_name)['PolicyDocument']
            checked.append(policy_name)
            stale.extend(_stale_policy_actions(doc))
        for attached in iam.list_attached_role_policies(RoleName=role_name)['AttachedPolicies']:
            if attached['PolicyArn'].startswith('arn:aws:iam::aws:'):
                continue  # AWS-managed policies can't carry the stale grants
            policy = iam.get_policy(PolicyArn=attached['PolicyArn'])['Policy']
            version = iam.get_policy_version(
                PolicyArn=attached['PolicyArn'],
                VersionId=policy['DefaultVersionId']
            )
            checked.append(attached['PolicyName'])
            stale.extend(_stale_policy_actions(version['PolicyVersion']['Document']))
        return {
            'applicable': True,
            'outdated': bool(stale),
            'stale_actions': sorted(set(stale)),
            'checked_policies': checked,
        }
    except ClientError as e:
        return {'applicable': True, 'outdated': None,
                'error': e.response['Error']['Code']}
    except Exception as e:
        return {'applicable': True, 'outdated': None, 'error': str(e)}
