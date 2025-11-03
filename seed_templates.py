"""
Seed default command templates for the DevOps Agent
Run this script to populate the database with useful starter templates
"""
from app import app, db
from models import CommandTemplate, User

# Default templates organized by category
DEFAULT_TEMPLATES = [
    # AWS Templates
    {
        'name': 'List EC2 Instances',
        'description': 'Show all EC2 instances with their status',
        'command': 'List all EC2 instances in us-east-1',
        'category': 'aws',
        'is_public': True
    },
    {
        'name': 'List S3 Buckets',
        'description': 'Display all S3 buckets in the account',
        'command': 'List all S3 buckets',
        'category': 'aws',
        'is_public': True
    },
    {
        'name': 'Check EC2 Instance Status',
        'description': 'Get detailed status of a specific EC2 instance',
        'command': 'Get the status of EC2 instance i-xxxxx',
        'category': 'aws',
        'is_public': True
    },
    {
        'name': 'Create S3 Bucket',
        'description': 'Create a new S3 bucket with encryption',
        'command': 'Create an S3 bucket named my-app-data with encryption enabled',
        'category': 'aws',
        'is_public': True
    },
    {
        'name': 'List RDS Databases',
        'description': 'Show all RDS database instances',
        'command': 'List all RDS database instances',
        'category': 'aws',
        'is_public': True
    },
    {
        'name': 'CloudWatch Logs',
        'description': 'Retrieve CloudWatch logs for troubleshooting',
        'command': 'Get CloudWatch logs for /aws/lambda/my-function from the last hour',
        'category': 'aws',
        'is_public': True
    },

    # Azure Templates
    {
        'name': 'List Azure VMs',
        'description': 'Display all virtual machines in Azure',
        'command': 'List all Azure virtual machines',
        'category': 'azure',
        'is_public': True
    },
    {
        'name': 'Create Azure VM',
        'description': 'Create a new virtual machine in Azure',
        'command': 'Create an Azure VM named web-server with Standard_B2s in East US',
        'category': 'azure',
        'is_public': True
    },
    {
        'name': 'List Storage Accounts',
        'description': 'Show all Azure storage accounts',
        'command': 'List all Azure storage accounts',
        'category': 'azure',
        'is_public': True
    },
    {
        'name': 'Check VM Status',
        'description': 'Get the status of a specific Azure VM',
        'command': 'Get the status of Azure VM web-server in resource group prod-rg',
        'category': 'azure',
        'is_public': True
    },
    {
        'name': 'List Resource Groups',
        'description': 'Display all Azure resource groups',
        'command': 'List all Azure resource groups',
        'category': 'azure',
        'is_public': True
    },

    # GCP Templates
    {
        'name': 'List GCE Instances',
        'description': 'Show all Compute Engine instances',
        'command': 'List all GCE instances',
        'category': 'gcp',
        'is_public': True
    },
    {
        'name': 'List GCS Buckets',
        'description': 'Display all Cloud Storage buckets',
        'command': 'List all GCS buckets',
        'category': 'gcp',
        'is_public': True
    },
    {
        'name': 'Create GCE Instance',
        'description': 'Create a new Compute Engine instance',
        'command': 'Create a GCE instance named web-server in us-central1-a',
        'category': 'gcp',
        'is_public': True
    },
    {
        'name': 'List Cloud SQL Instances',
        'description': 'Show all Cloud SQL database instances',
        'command': 'List all Cloud SQL instances',
        'category': 'gcp',
        'is_public': True
    },

    # Kubernetes Templates
    {
        'name': 'List Pods',
        'description': 'Show all pods in a namespace',
        'command': 'List all pods in namespace production',
        'category': 'kubernetes',
        'is_public': True
    },
    {
        'name': 'Get Pod Logs',
        'description': 'Retrieve logs from a specific pod',
        'command': 'Get logs from pod nginx-deployment-xxxxx',
        'category': 'kubernetes',
        'is_public': True
    },
    {
        'name': 'Scale Deployment',
        'description': 'Scale a deployment to specified replicas',
        'command': 'Scale the api-service deployment to 5 replicas',
        'category': 'kubernetes',
        'is_public': True
    },
    {
        'name': 'List Services',
        'description': 'Show all Kubernetes services',
        'command': 'List all services in namespace production',
        'category': 'kubernetes',
        'is_public': True
    },
    {
        'name': 'Describe Pod',
        'description': 'Get detailed information about a pod',
        'command': 'Describe pod nginx-xxxxx in namespace production',
        'category': 'kubernetes',
        'is_public': True
    },
    {
        'name': 'Restart Deployment',
        'description': 'Restart all pods in a deployment',
        'command': 'Restart the api-service deployment',
        'category': 'kubernetes',
        'is_public': True
    },
    {
        'name': 'Check Cluster Health',
        'description': 'Verify Kubernetes cluster health status',
        'command': 'Check the health status of the Kubernetes cluster',
        'category': 'kubernetes',
        'is_public': True
    },

    # Docker Templates
    {
        'name': 'List Containers',
        'description': 'Show all running Docker containers',
        'command': 'List all running Docker containers',
        'category': 'docker',
        'is_public': True
    },
    {
        'name': 'Container Logs',
        'description': 'View logs from a specific container',
        'command': 'Show logs from Docker container nginx-001',
        'category': 'docker',
        'is_public': True
    },
    {
        'name': 'Container Stats',
        'description': 'Display resource usage for containers',
        'command': 'Show resource usage for all Docker containers',
        'category': 'docker',
        'is_public': True
    },
    {
        'name': 'Stop Container',
        'description': 'Stop a running Docker container',
        'command': 'Stop Docker container nginx-001',
        'category': 'docker',
        'is_public': True
    },
    {
        'name': 'List Images',
        'description': 'Show all Docker images',
        'command': 'List all Docker images',
        'category': 'docker',
        'is_public': True
    },
    {
        'name': 'Remove Unused Images',
        'description': 'Clean up unused Docker images',
        'command': 'Remove all unused Docker images',
        'category': 'docker',
        'is_public': True
    },

    # Terraform Templates
    {
        'name': 'Terraform Plan',
        'description': 'Preview infrastructure changes',
        'command': 'Run terraform plan for ./infrastructure',
        'category': 'terraform',
        'is_public': True
    },
    {
        'name': 'Terraform Apply',
        'description': 'Apply infrastructure changes',
        'command': 'Apply terraform configuration in ./infrastructure',
        'category': 'terraform',
        'is_public': True
    },
    {
        'name': 'Terraform State',
        'description': 'Show current Terraform state',
        'command': 'Show terraform state',
        'category': 'terraform',
        'is_public': True
    },
    {
        'name': 'List Workspaces',
        'description': 'Display all Terraform workspaces',
        'command': 'List all terraform workspaces',
        'category': 'terraform',
        'is_public': True
    },

    # Git Templates
    {
        'name': 'Git Status',
        'description': 'Check repository status',
        'command': 'Show git repository status',
        'category': 'git',
        'is_public': True
    },
    {
        'name': 'Git Branches',
        'description': 'List all branches',
        'command': 'List all git branches',
        'category': 'git',
        'is_public': True
    },
    {
        'name': 'Git Log',
        'description': 'View commit history',
        'command': 'Show the last 10 git commits',
        'category': 'git',
        'is_public': True
    },

    # Monitoring Templates
    {
        'name': 'Prometheus Query',
        'description': 'Execute a Prometheus query',
        'command': 'Query Prometheus for CPU usage over the last hour',
        'category': 'monitoring',
        'is_public': True
    },
    {
        'name': 'List Datadog Monitors',
        'description': 'Show all Datadog monitoring alerts',
        'command': 'List all Datadog monitors with status alert',
        'category': 'monitoring',
        'is_public': True
    },
    {
        'name': 'Grafana Dashboards',
        'description': 'Display all Grafana dashboards',
        'command': 'List all Grafana dashboards',
        'category': 'monitoring',
        'is_public': True
    },

    # CI/CD Templates
    {
        'name': 'Trigger Jenkins Build',
        'description': 'Start a Jenkins job build',
        'command': 'Trigger Jenkins job deploy-production',
        'category': 'cicd',
        'is_public': True
    },
    {
        'name': 'GitHub Workflow Status',
        'description': 'Check GitHub Actions workflow status',
        'command': 'Show status of GitHub Actions workflow runs',
        'category': 'cicd',
        'is_public': True
    },
]


def seed_templates():
    """Create default templates in the database"""
    with app.app_context():
        # Get the first user (or create a system user)
        user = User.query.first()

        if not user:
            print("No users found in database. Please create a user account first.")
            print("Run the app and register at http://localhost:5000/register")
            return

        print(f"Creating default templates for user: {user.username}")

        # Check if templates already exist
        existing_count = CommandTemplate.query.filter_by(user_id=user.id).count()

        if existing_count > 0:
            response = input(f"\nFound {existing_count} existing templates. Do you want to add more? (y/n): ")
            if response.lower() != 'y':
                print("Cancelled. No templates added.")
                return

        # Create templates
        created_count = 0
        for template_data in DEFAULT_TEMPLATES:
            # Check if template already exists
            existing = CommandTemplate.query.filter_by(
                user_id=user.id,
                name=template_data['name']
            ).first()

            if existing:
                print(f"  [SKIP] {template_data['name']} (already exists)")
                continue

            template = CommandTemplate(
                user_id=user.id,
                name=template_data['name'],
                description=template_data['description'],
                command=template_data['command'],
                category=template_data['category'],
                is_public=template_data['is_public']
            )

            db.session.add(template)
            created_count += 1
            print(f"  [OK] Created: {template_data['name']} ({template_data['category']})")

        db.session.commit()

        print(f"\n{'='*60}")
        print(f"Success! Created {created_count} new templates")
        print(f"Total templates: {CommandTemplate.query.filter_by(user_id=user.id).count()}")
        print(f"{'='*60}")
        print(f"\nVisit http://localhost:5000/templates to view your templates!")


if __name__ == '__main__':
    seed_templates()
