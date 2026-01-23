"""
Verify IAM permissions for AWS Secrets Manager
Tests that your IAM user/role has proper access to Secrets Manager
"""
import boto3
from botocore.exceptions import ClientError
import json
import sys
import io

# Fix Windows console encoding issues
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')


def check_aws_credentials():
    """Check if AWS credentials are configured"""
    print("\n" + "="*60)
    print("Step 1: Checking AWS Credentials")
    print("="*60)

    try:
        sts = boto3.client('sts')
        identity = sts.get_caller_identity()

        print("✅ AWS credentials are configured")
        print(f"   Account ID: {identity['Account']}")
        print(f"   User/Role ARN: {identity['Arn']}")
        print(f"   User ID: {identity['UserId']}")

        return True, identity
    except Exception as e:
        print(f"❌ AWS credentials not configured: {str(e)}")
        print("   Run: aws configure")
        return False, None


def check_ec2_access():
    """Check if user has EC2 access"""
    print("\n" + "="*60)
    print("Step 2: Checking EC2 Access")
    print("="*60)

    try:
        ec2 = boto3.client('ec2')
        response = ec2.describe_regions()

        print(f"✅ EC2 access verified")
        print(f"   Can access {len(response['Regions'])} regions")

        return True
    except ClientError as e:
        print(f"❌ EC2 access denied: {e.response['Error']['Message']}")
        return False
    except Exception as e:
        print(f"❌ Error checking EC2 access: {str(e)}")
        return False


def check_secrets_manager_permissions():
    """Check Secrets Manager permissions"""
    print("\n" + "="*60)
    print("Step 3: Checking Secrets Manager Permissions")
    print("="*60)

    sm = boto3.client('secretsmanager', region_name='us-east-1')
    permissions = {
        'list': False,
        'describe': False,
        'get': False,
        'create': False
    }

    # Test list secrets
    try:
        response = sm.list_secrets()
        permissions['list'] = True
        print(f"✅ Can list secrets ({len(response.get('SecretList', []))} secrets found)")
    except ClientError as e:
        print(f"❌ Cannot list secrets: {e.response['Error']['Code']}")

    # Test describe (if we have any secrets)
    try:
        response = sm.list_secrets()
        if response.get('SecretList'):
            secret_name = response['SecretList'][0]['Name']
            sm.describe_secret(SecretId=secret_name)
            permissions['describe'] = True
            print(f"✅ Can describe secrets")
        else:
            print("⚠️  No secrets exist to test describe permission")
    except ClientError as e:
        print(f"❌ Cannot describe secrets: {e.response['Error']['Code']}")

    # Test get secret value
    try:
        response = sm.list_secrets()
        if response.get('SecretList'):
            secret_name = response['SecretList'][0]['Name']
            sm.get_secret_value(SecretId=secret_name)
            permissions['get'] = True
            print(f"✅ Can get secret values")
        else:
            print("⚠️  No secrets exist to test get permission")
    except ClientError as e:
        print(f"❌ Cannot get secret values: {e.response['Error']['Code']}")

    # Test create (will create a test secret)
    test_secret_name = 'test-secret-verification-temp'
    try:
        sm.create_secret(
            Name=test_secret_name,
            SecretString='test-value'
        )
        permissions['create'] = True
        print(f"✅ Can create secrets")

        # Clean up test secret
        try:
            sm.delete_secret(
                SecretId=test_secret_name,
                ForceDeleteWithoutRecovery=True
            )
            print(f"✅ Can delete secrets (test secret cleaned up)")
        except:
            pass

    except ClientError as e:
        if e.response['Error']['Code'] == 'ResourceExistsException':
            # Secret already exists, try to delete it
            try:
                sm.delete_secret(
                    SecretId=test_secret_name,
                    ForceDeleteWithoutRecovery=True
                )
                permissions['create'] = True
                print(f"✅ Can create/delete secrets")
            except:
                print(f"⚠️  Test secret already exists, skipping create test")
        else:
            print(f"❌ Cannot create secrets: {e.response['Error']['Code']}")

    return permissions


def check_kms_permissions():
    """Check KMS permissions for decryption"""
    print("\n" + "="*60)
    print("Step 4: Checking KMS Decrypt Permissions")
    print("="*60)

    try:
        kms = boto3.client('kms', region_name='us-east-1')
        # List keys to verify basic access
        response = kms.list_keys(Limit=1)
        print("✅ Can access KMS service")
        print("   (Decrypt permissions will be tested when retrieving secrets)")
        return True
    except ClientError as e:
        print(f"⚠️  KMS access limited: {e.response['Error']['Code']}")
        print("   This is okay if secrets use default encryption")
        return True


def list_existing_secrets():
    """List existing secrets"""
    print("\n" + "="*60)
    print("Step 5: Listing Existing Secrets")
    print("="*60)

    try:
        sm = boto3.client('secretsmanager', region_name='us-east-1')
        response = sm.list_secrets()

        secrets = response.get('SecretList', [])

        if not secrets:
            print("⚠️  No secrets found in us-east-1")
            print("   You need to create secrets for your application")
            print("\n   Quick create command:")
            print("   aws secretsmanager create-secret \\")
            print("     --name ANTHROPIC_API_KEY \\")
            print("     --secret-string 'your-api-key' \\")
            print("     --region us-east-1")
            return []

        print(f"✅ Found {len(secrets)} secret(s):")

        devops_secrets = []
        for secret in secrets:
            name = secret['Name']
            is_devops = 'devops' in name.lower() or 'ANTHROPIC' in name
            marker = "👉 " if is_devops else "   "
            print(f"{marker}- {name}")

            if is_devops:
                devops_secrets.append(name)
                try:
                    desc = sm.describe_secret(SecretId=name)
                    print(f"      Created: {desc['CreatedDate']}")
                    print(f"      Last accessed: {desc.get('LastAccessedDate', 'Never')}")
                except:
                    pass

        if devops_secrets:
            print(f"\n✅ Found {len(devops_secrets)} DevOps Agent related secret(s)")
        else:
            print("\n⚠️  No DevOps Agent secrets found")
            print("   Create them with:")
            print("   aws secretsmanager create-secret \\")
            print("     --name devops-agent/prod/secrets \\")
            print("     --secret-string '{...}' \\")
            print("     --region us-east-1")

        return secrets

    except Exception as e:
        print(f"❌ Error listing secrets: {str(e)}")
        return []


def check_iam_policy():
    """Check attached IAM policies"""
    print("\n" + "="*60)
    print("Step 6: Checking IAM Policies")
    print("="*60)

    try:
        iam = boto3.client('iam')
        sts = boto3.client('sts')
        identity = sts.get_caller_identity()

        # Extract user name from ARN
        arn = identity['Arn']

        if ':user/' in arn:
            user_name = arn.split(':user/')[1]
            print(f"Checking policies for IAM user: {user_name}")

            # List attached policies
            try:
                response = iam.list_attached_user_policies(UserName=user_name)
                if response['AttachedPolicies']:
                    print(f"\n✅ Attached managed policies:")
                    for policy in response['AttachedPolicies']:
                        print(f"   - {policy['PolicyName']}")
                        if 'EC2Full' in policy['PolicyName']:
                            print(f"     ✓ Includes EC2 access")

                # List inline policies
                response = iam.list_user_policies(UserName=user_name)
                if response['PolicyNames']:
                    print(f"\n✅ Inline policies:")
                    for policy_name in response['PolicyNames']:
                        print(f"   - {policy_name}")
                        # Get policy document
                        try:
                            policy_doc = iam.get_user_policy(
                                UserName=user_name,
                                PolicyName=policy_name
                            )
                            doc = policy_doc['PolicyDocument']
                            print(f"     Content: {json.dumps(doc, indent=6)[:200]}...")
                        except:
                            pass

            except ClientError as e:
                print(f"⚠️  Cannot list policies: {e.response['Error']['Code']}")
                print("   (This is normal if you don't have IAM read permissions)")

        elif ':assumed-role/' in arn:
            role_name = arn.split(':assumed-role/')[1].split('/')[0]
            print(f"Running as IAM role: {role_name}")
            print("   (EC2 instance profile or assumed role)")

        return True

    except Exception as e:
        print(f"⚠️  Could not check IAM policies: {str(e)}")
        return True


def generate_recommendations(permissions, secrets):
    """Generate recommendations based on findings"""
    print("\n" + "="*60)
    print("Recommendations")
    print("="*60)

    recommendations = []

    # Check permissions
    if not permissions.get('get'):
        recommendations.append({
            'priority': 'HIGH',
            'issue': 'Cannot retrieve secret values',
            'action': 'Add secretsmanager:GetSecretValue permission to your IAM policy'
        })

    if not permissions.get('list'):
        recommendations.append({
            'priority': 'MEDIUM',
            'issue': 'Cannot list secrets',
            'action': 'Add secretsmanager:ListSecrets permission (optional but helpful)'
        })

    # Check if secrets exist
    devops_secrets = [s for s in secrets if 'devops' in s['Name'].lower() or 'ANTHROPIC' in s['Name']]
    if not devops_secrets:
        recommendations.append({
            'priority': 'HIGH',
            'issue': 'No DevOps Agent secrets found',
            'action': 'Create secrets with: aws secretsmanager create-secret --name devops-agent/prod/secrets'
        })

    if not secrets:
        recommendations.append({
            'priority': 'HIGH',
            'issue': 'No secrets exist at all',
            'action': 'Create your first secret to test the integration'
        })

    if recommendations:
        for i, rec in enumerate(recommendations, 1):
            print(f"\n{i}. [{rec['priority']}] {rec['issue']}")
            print(f"   Action: {rec['action']}")
    else:
        print("\n✅ All checks passed!")
        print("   Your IAM setup looks good.")
        print("\n   Next steps:")
        print("   1. Create secrets if not already done")
        print("   2. Run: python test_secrets_manager.py")
        print("   3. Integrate into app.py (see INTEGRATE_SECRETS_MANAGER.md)")


def main():
    """Run all verification checks"""
    print("\n" + "="*70)
    print(" AWS Secrets Manager IAM Verification")
    print("="*70)
    print("\nThis script verifies that your IAM user/role has the necessary")
    print("permissions to use AWS Secrets Manager with the DevOps Agent.")

    # Check AWS credentials
    success, identity = check_aws_credentials()
    if not success:
        return

    # Check EC2 access
    check_ec2_access()

    # Check Secrets Manager permissions
    permissions = check_secrets_manager_permissions()

    # Check KMS
    check_kms_permissions()

    # List existing secrets
    secrets = list_existing_secrets()

    # Check IAM policies
    check_iam_policy()

    # Generate recommendations
    generate_recommendations(permissions, secrets)

    # Summary
    print("\n" + "="*70)
    print("Verification Complete")
    print("="*70)

    required_permissions = ['list', 'get']
    has_required = all(permissions.get(p) for p in required_permissions)

    if has_required and secrets:
        print("\n🎉 SUCCESS! You're ready to use AWS Secrets Manager")
        print("\n   Next step: Run the test script")
        print("   → python test_secrets_manager.py")
    elif has_required:
        print("\n✅ IAM permissions look good!")
        print("\n   Next step: Create secrets for your application")
        print("   → See AWS_SECRETS_MANAGER_SETUP.md for instructions")
    else:
        print("\n⚠️  Some permissions are missing")
        print("   Review the recommendations above")


if __name__ == '__main__':
    main()
