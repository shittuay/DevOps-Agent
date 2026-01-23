"""
Demo Mode - Allow users to explore the app without API costs.
Shows sample/mock data and pre-written responses.
"""
from datetime import datetime, timedelta
import random


# Sample infrastructure data for demo mode
DEMO_INFRASTRUCTURE = {
    'aws': [
        {
            'id': 'demo-ec2-1',
            'name': 'web-app-prod-1',
            'type': 'ec2',
            'provider': 'aws',
            'region': 'us-east-1',
            'status': 'running',
            'cost': 62.00,
            'instance_type': 't3.large',
            'launch_time': (datetime.utcnow() - timedelta(days=45)).isoformat()
        },
        {
            'id': 'demo-ec2-2',
            'name': 'api-server-prod',
            'type': 'ec2',
            'provider': 'aws',
            'region': 'us-west-2',
            'status': 'running',
            'cost': 140.00,
            'instance_type': 'm5.xlarge',
            'launch_time': (datetime.utcnow() - timedelta(days=120)).isoformat()
        },
        {
            'id': 'demo-s3-1',
            'name': 'app-assets-bucket',
            'type': 's3',
            'provider': 'aws',
            'region': 'us-east-1',
            'status': 'active',
            'cost': 23.50,
            'storage_gb': 1024
        },
        {
            'id': 'demo-rds-1',
            'name': 'main-database-prod',
            'type': 'rds',
            'provider': 'aws',
            'region': 'us-east-1',
            'status': 'available',
            'cost': 240.00,
            'instance_class': 'db.t3.large',
            'engine': 'postgresql'
        }
    ],
    'gcp': [
        {
            'id': 'demo-gce-1',
            'name': 'analytics-vm',
            'type': 'compute_engine',
            'provider': 'gcp',
            'region': 'us-central1',
            'status': 'RUNNING',
            'cost': 97.00,
            'machine_type': 'n2-standard-4'
        },
        {
            'id': 'demo-gcs-1',
            'name': 'backup-storage',
            'type': 'cloud_storage',
            'provider': 'gcp',
            'region': 'us-central1',
            'status': 'active',
            'cost': 15.20,
            'storage_gb': 760,
            'storage_class': 'STANDARD'
        }
    ],
    'azure': [
        {
            'id': 'demo-vm-1',
            'name': 'devops-agent-demo',
            'type': 'virtual_machine',
            'provider': 'azure',
            'region': 'eastus',
            'status': 'running',
            'cost': 140.00,
            'vm_size': 'Standard_D4s_v3'
        }
    ]
}


# Sample cost optimization recommendations
DEMO_RECOMMENDATIONS = [
    {
        'id': 1,
        'type': 'idle_resource',
        'severity': 'high',
        'title': 'Idle EC2 Instance: api-server-prod',
        'description': 'This m5.xlarge instance has been running at <5% CPU utilization for the past 30 days. Consider stopping it during non-business hours or downsizing to a smaller instance type.',
        'potential_savings': 84.00,
        'resource_id': 'demo-ec2-2',
        'action': 'downsize'
    },
    {
        'id': 2,
        'type': 'reserved_instance',
        'severity': 'medium',
        'title': 'Convert to Reserved Instance: main-database-prod',
        'description': 'This RDS instance has been running consistently for 4+ months. Purchasing a 1-year reserved instance would save 40% ($96/month).',
        'potential_savings': 96.00,
        'resource_id': 'demo-rds-1',
        'action': 'purchase_reserved'
    },
    {
        'id': 3,
        'type': 'storage_optimization',
        'severity': 'low',
        'title': 'Move Old Backups to Glacier',
        'description': 'Backups older than 90 days in backup-storage can be moved to Archive storage class, saving 70% on storage costs.',
        'potential_savings': 10.64,
        'resource_id': 'demo-gcs-1',
        'action': 'change_storage_class'
    }
]


# Sample security findings
DEMO_SECURITY_FINDINGS = [
    {
        'id': 1,
        'severity': 'critical',
        'title': 'Public S3 Bucket Detected',
        'description': 'S3 bucket "app-assets-bucket" has public read access enabled. This could expose sensitive data.',
        'resource_id': 'demo-s3-1',
        'recommendation': 'Disable public access and use CloudFront with signed URLs instead.',
        'compliance': ['PCI-DSS', 'SOC 2']
    },
    {
        'id': 2,
        'severity': 'high',
        'title': 'Database Without Encryption',
        'description': 'RDS instance "main-database-prod" does not have encryption at rest enabled.',
        'resource_id': 'demo-rds-1',
        'recommendation': 'Create encrypted snapshot and restore to new encrypted instance.',
        'compliance': ['HIPAA', 'GDPR']
    },
    {
        'id': 3,
        'severity': 'medium',
        'title': 'Unrestricted SSH Access',
        'description': 'Security group allows SSH (port 22) from 0.0.0.0/0 for instance "web-app-prod-1".',
        'resource_id': 'demo-ec2-1',
        'recommendation': 'Restrict SSH access to specific IP ranges or use AWS Systems Manager Session Manager.',
        'compliance': ['CIS Benchmark']
    }
]


# Pre-written chat responses for demo mode
DEMO_CHAT_RESPONSES = {
    'hello': "Hello! I'm the DevOps Agent demo assistant. I can answer questions about our features, show you sample data, and help you understand how the agent works. Try asking: 'What can you do?' or 'Show me my infrastructure'",

    'what can you do': """I'm an AI-powered DevOps automation agent that can help you with:

🔹 **Infrastructure Management**
   - Monitor AWS, GCP, and Azure resources
   - Track costs in real-time
   - Automated resource provisioning

🔹 **Cost Optimization**
   - Identify idle resources
   - Recommend reserved instances
   - Storage tier optimization

🔹 **Security Scanning**
   - Detect vulnerabilities
   - Compliance checking (PCI, HIPAA, SOC 2)
   - Security best practices

🔹 **Team Collaboration**
   - Role-based access control
   - Audit logs
   - Team management

Try asking: "Show me cost optimization tips" or "What security issues do I have?" """,

    'show infrastructure': """Here's your demo infrastructure overview:

**AWS (4 resources - $465.50/month)**
- 2 EC2 instances ($202/month)
- 1 S3 bucket ($23.50/month)
- 1 RDS database ($240/month)

**GCP (2 resources - $112.20/month)**
- 1 Compute Engine VM ($97/month)
- 1 Cloud Storage bucket ($15.20/month)

**Azure (1 resource - $140/month)**
- 1 Virtual Machine ($140/month)

**Total: 7 resources costing $717.70/month**

You can save up to $190.64/month with our optimization recommendations!""",

    'cost optimization': """Here are your top 3 cost optimization opportunities:

💰 **High Priority - Save $84/month**
Idle EC2 Instance: api-server-prod
This m5.xlarge instance is underutilized. Downsize to t3.large.

💰 **Medium Priority - Save $96/month**
Reserved Instance Opportunity: main-database-prod
Running 24/7 for 4+ months. Purchase 1-year reservation.

💰 **Low Priority - Save $10.64/month**
Storage Optimization: backup-storage
Move old backups to Archive storage class.

**Total Potential Savings: $190.64/month ($2,288/year)**

Upgrade to a paid plan to implement these optimizations automatically!""",

    'security': """Security Scan Results:

🔴 **Critical (1 finding)**
Public S3 Bucket: app-assets-bucket
Risk: Data exposure
Action: Disable public access immediately

🟡 **High (1 finding)**
Unencrypted Database: main-database-prod
Risk: Compliance violation
Action: Enable encryption at rest

🟢 **Medium (1 finding)**
Unrestricted SSH: web-app-prod-1
Risk: Unauthorized access
Action: Restrict to specific IPs

Upgrade to fix these issues with one click!""",

    'upgrade': """Ready to unlock the full power of DevOps Agent?

✨ **Start Your 7-Day Trial**
- 10 AI agent actions to test everything
- Full access to all features
- No credit card required to start

📦 **Starter Plan - $29/month**
- 100 AI actions/month
- All cloud providers
- Infrastructure monitoring
- Cost optimization
- Security scanning
- Team collaboration (3 users)

🚀 **Professional Plan - $99/month**
- 500 AI actions/month
- Priority support
- Advanced analytics
- Team collaboration (10 users)
- API access

Want to start your trial? Click 'Start Trial' in the menu!""",

    'default': "I'm in demo mode, so I can only answer basic questions about DevOps Agent features. Try asking: 'What can you do?', 'Show me my infrastructure', 'Cost optimization tips', or 'Security issues'. To unlock full AI capabilities, start your free trial!"
}


def get_demo_infrastructure():
    """Get sample infrastructure data for demo mode."""
    return DEMO_INFRASTRUCTURE


def get_demo_summary():
    """Get dashboard summary for demo mode."""
    total_resources = sum(len(resources) for resources in DEMO_INFRASTRUCTURE.values())
    total_cost = sum(
        resource.get('cost', 0)
        for resources in DEMO_INFRASTRUCTURE.values()
        for resource in resources
    )

    return {
        'total_resources': total_resources,
        'total_cost': total_cost,
        'aws_resources': len(DEMO_INFRASTRUCTURE['aws']),
        'gcp_resources': len(DEMO_INFRASTRUCTURE['gcp']),
        'azure_resources': len(DEMO_INFRASTRUCTURE['azure']),
        'aws_cost': sum(r.get('cost', 0) for r in DEMO_INFRASTRUCTURE['aws']),
        'gcp_cost': sum(r.get('cost', 0) for r in DEMO_INFRASTRUCTURE['gcp']),
        'azure_cost': sum(r.get('cost', 0) for r in DEMO_INFRASTRUCTURE['azure'])
    }


def get_demo_recommendations():
    """Get sample cost optimization recommendations."""
    return DEMO_RECOMMENDATIONS


def get_demo_security_findings():
    """Get sample security findings."""
    return DEMO_SECURITY_FINDINGS


def get_demo_chat_response(user_message):
    """Get pre-written response for demo mode chat."""
    message_lower = user_message.lower().strip()

    # Check for keyword matches
    if 'hello' in message_lower or 'hi' in message_lower or 'hey' in message_lower:
        return DEMO_CHAT_RESPONSES['hello']
    elif 'what can you do' in message_lower or 'help' in message_lower or 'features' in message_lower:
        return DEMO_CHAT_RESPONSES['what can you do']
    elif 'infrastructure' in message_lower or 'resources' in message_lower or 'show me' in message_lower:
        return DEMO_CHAT_RESPONSES['show infrastructure']
    elif 'cost' in message_lower or 'optimization' in message_lower or 'save money' in message_lower or 'expensive' in message_lower:
        return DEMO_CHAT_RESPONSES['cost optimization']
    elif 'security' in message_lower or 'vulnerab' in message_lower or 'threat' in message_lower:
        return DEMO_CHAT_RESPONSES['security']
    elif 'upgrade' in message_lower or 'pricing' in message_lower or 'trial' in message_lower or 'plan' in message_lower:
        return DEMO_CHAT_RESPONSES['upgrade']
    else:
        return DEMO_CHAT_RESPONSES['default']


def is_user_in_demo_mode(user):
    """Check if user is in demo mode."""
    # User is in demo mode if:
    # 1. No active subscription
    # 2. Trial expired
    # 3. Out of credits
    # 4. Explicitly set demo_mode flag

    if hasattr(user, 'demo_mode') and user.demo_mode:
        return True

    if not hasattr(user, 'subscription') or not user.subscription:
        return True

    subscription = user.subscription

    # Check if trial expired
    if subscription.payment_status == 'trial':
        if subscription.current_period_end < datetime.utcnow():
            return True

    # Check if out of credits
    if subscription.credits_remaining <= 0:
        return True

    return False


def get_demo_mode_banner():
    """Get banner message for demo mode."""
    return {
        'mode': 'demo',
        'message': '📌 You are in Demo Mode - Exploring with sample data',
        'description': 'Start your 7-day free trial to connect your real cloud accounts and use full AI features!',
        'cta_text': 'Start Free Trial',
        'cta_link': '/subscription'
    }
