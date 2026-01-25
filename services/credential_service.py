"""
Service for managing per-user cloud credentials.
Provides functions to get user-specific cloud clients (AWS, Azure, GCP).
"""
import os
import json
import tempfile
from typing import Optional, Dict, Any, Tuple
from datetime import datetime

import boto3
from botocore.exceptions import NoCredentialsError, ClientError


def get_user_aws_credentials(user_id: int) -> Optional[Dict[str, str]]:
    """
    Get AWS credentials for a specific user.

    Args:
        user_id: The user's ID

    Returns:
        Dict with access_key, secret_key, and region, or None if not configured
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
    if not credentials.get('access_key') or not credentials.get('secret_key'):
        return None

    return {
        'access_key': credentials.get('access_key'),
        'secret_key': credentials.get('secret_key'),
        'region': cred.default_region or credentials.get('region', 'us-east-1')
    }


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


def get_user_boto_client(user_id: int, service: str, region: Optional[str] = None):
    """
    Get a boto3 client configured with user-specific AWS credentials.

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
        return boto3.client(
            service,
            aws_access_key_id=creds['access_key'],
            aws_secret_access_key=creds['secret_key'],
            region_name=region or creds['region']
        )
    except Exception as e:
        raise Exception(f"Failed to create AWS client: {str(e)}")


def get_user_boto_resource(user_id: int, service: str, region: Optional[str] = None):
    """
    Get a boto3 resource configured with user-specific AWS credentials.

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
        return boto3.resource(
            service,
            aws_access_key_id=creds['access_key'],
            aws_secret_access_key=creds['secret_key'],
            region_name=region or creds['region']
        )
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
    access_key: str,
    secret_key: str,
    region: str = 'us-east-1'
) -> Tuple[bool, str]:
    """
    Save AWS credentials for a user.

    Args:
        user_id: The user's ID
        access_key: AWS access key ID
        secret_key: AWS secret access key
        region: Default region

    Returns:
        Tuple of (success, message)
    """
    from models import UserCloudCredential, db

    # Validate credentials
    if not access_key or not secret_key:
        return False, "Access key and secret key are required"

    if not access_key.startswith('AKIA'):
        return False, "Invalid AWS access key format (should start with AKIA)"

    try:
        # Test credentials
        test_client = boto3.client(
            'sts',
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region
        )
        test_client.get_caller_identity()
    except ClientError as e:
        return False, f"Invalid AWS credentials: {str(e)}"
    except Exception as e:
        return False, f"Failed to validate credentials: {str(e)}"

    try:
        # Find or create credential record
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

        # Store encrypted credentials
        cred.set_credentials({
            'access_key': access_key,
            'secret_key': secret_key,
            'region': region
        })
        cred.default_region = region
        cred.verification_status = 'valid'
        cred.last_verified = datetime.utcnow()
        cred.is_active = True

        db.session.commit()
        return True, "AWS credentials saved successfully"
    except Exception as e:
        db.session.rollback()
        return False, f"Failed to save credentials: {str(e)}"


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
        cred.last_verified = datetime.utcnow()
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
        cred.last_verified = datetime.utcnow()
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
