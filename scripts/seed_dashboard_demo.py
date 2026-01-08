"""Seed database with demo infrastructure data for testing dashboard"""
from app import app, db
from models import User, InfrastructureResource, CostOptimization
from datetime import datetime

def seed_demo_data():
    """Add demo infrastructure data for the first user"""
    with app.app_context():
        # Get first user
        user = User.query.first()
        if not user:
            print("No users found. Please create a user first.")
            return

        print(f"Adding demo data for user: {user.username}")

        # Clear existing demo data for this user
        InfrastructureResource.query.filter_by(user_id=user.id).delete()
        CostOptimization.query.filter_by(user_id=user.id).delete()

        # Add AWS EC2 instances
        resources = [
            InfrastructureResource(
                user_id=user.id,
                cloud_provider='aws',
                resource_type='ec2',
                resource_id='i-0123456789abcdef0',
                resource_name='web-server-prod',
                region='us-east-1',
                status='running',
                monthly_cost=60.00,
                resource_metadata={
                    'instance_type': 't3.large',
                    'launch_time': '2024-01-15T10:30:00',
                    'private_ip': '10.0.1.100',
                    'public_ip': '54.123.45.67'
                }
            ),
            InfrastructureResource(
                user_id=user.id,
                cloud_provider='aws',
                resource_type='ec2',
                resource_id='i-0abcdef1234567890',
                resource_name='web-server-dev',
                region='us-east-1',
                status='running',
                monthly_cost=60.00,
                resource_metadata={
                    'instance_type': 't3.large',
                    'launch_time': '2024-02-01T14:20:00',
                    'private_ip': '10.0.1.101',
                    'public_ip': '54.123.45.68'
                }
            ),
            InfrastructureResource(
                user_id=user.id,
                cloud_provider='aws',
                resource_type='ec2',
                resource_id='i-0fedcba0987654321',
                resource_name='analytics-instance',
                region='us-west-2',
                status='stopped',
                monthly_cost=5.00,
                resource_metadata={
                    'instance_type': 'm5.large',
                    'launch_time': '2023-12-10T09:15:00',
                    'private_ip': '10.0.2.50'
                }
            ),
            # Add AWS RDS
            InfrastructureResource(
                user_id=user.id,
                cloud_provider='aws',
                resource_type='rds',
                resource_id='mydb-prod',
                resource_name='mydb-prod',
                region='us-east-1',
                status='available',
                monthly_cost=96.00,
                resource_metadata={
                    'db_class': 'db.t3.large',
                    'engine': 'postgres',
                    'engine_version': '14.7',
                    'allocated_storage': 100,
                    'multi_az': True
                }
            ),
            # Add GCP resources
            InfrastructureResource(
                user_id=user.id,
                cloud_provider='gcp',
                resource_type='compute',
                resource_id='api-server-instance',
                resource_name='api-server',
                region='us-central1',
                status='running',
                monthly_cost=24.50,
                resource_metadata={
                    'machine_type': 'e2-medium',
                    'zone': 'us-central1-a'
                }
            ),
            # Add Azure resources
            InfrastructureResource(
                user_id=user.id,
                cloud_provider='azure',
                resource_type='vm',
                resource_id='backup-storage-vm',
                resource_name='backup-storage',
                region='East US',
                status='running',
                monthly_cost=110.00,
                resource_metadata={
                    'vm_size': 'Standard_D2s_v3',
                    'os_type': 'Linux'
                }
            ),
        ]

        for resource in resources:
            db.session.add(resource)

        db.session.commit()
        print(f"Added {len(resources)} infrastructure resources")

        # Add cost optimization recommendations
        # Get the dev EC2 instance
        dev_instance = InfrastructureResource.query.filter_by(
            user_id=user.id,
            resource_name='web-server-dev'
        ).first()

        # Get the stopped analytics instance
        stopped_instance = InfrastructureResource.query.filter_by(
            user_id=user.id,
            resource_name='analytics-instance'
        ).first()

        recommendations = []

        if dev_instance:
            recommendations.append(
                CostOptimization(
                    user_id=user.id,
                    resource_id=dev_instance.id,
                    recommendation_type='idle_resource',
                    title=f"Idle EC2 instance: {dev_instance.resource_name}",
                    description="This development instance is running 24/7 but only used during business hours. Consider stopping it overnight and on weekends, or use an auto-scaling schedule.",
                    potential_monthly_savings=45.00
                )
            )

        if stopped_instance:
            recommendations.append(
                CostOptimization(
                    user_id=user.id,
                    resource_id=stopped_instance.id,
                    recommendation_type='unused_resource',
                    title=f"Stopped instance for 30+ days: {stopped_instance.resource_name}",
                    description="This instance has been stopped for over a month. Consider creating an AMI snapshot and terminating the instance to eliminate EBS storage costs.",
                    potential_monthly_savings=5.00
                )
            )

        # Add a reserved instance recommendation
        recommendations.append(
            CostOptimization(
                user_id=user.id,
                resource_id=None,
                recommendation_type='reserved_instance',
                title="Reserved Instance Opportunity",
                description="You've been running t3.large instances continuously for 3+ months. Switch to 1-year Reserved Instances for 30-40% savings.",
                potential_monthly_savings=18.00
            )
        )

        for rec in recommendations:
            db.session.add(rec)

        db.session.commit()
        print(f"Added {len(recommendations)} cost optimization recommendations")

        # Print summary
        total_cost = sum(r.monthly_cost for r in resources)
        total_savings = sum(r.potential_monthly_savings for r in recommendations)

        print("\n" + "="*50)
        print("Demo Data Summary")
        print("="*50)
        print(f"Total Resources: {len(resources)}")
        print(f"  - AWS: {len([r for r in resources if r.cloud_provider == 'aws'])}")
        print(f"  - GCP: {len([r for r in resources if r.cloud_provider == 'gcp'])}")
        print(f"  - Azure: {len([r for r in resources if r.cloud_provider == 'azure'])}")
        print(f"Monthly Cost: ${total_cost:.2f}")
        print(f"Potential Savings: ${total_savings:.2f}")
        print(f"Recommendations: {len(recommendations)}")
        print("="*50)
        print("\nDemo data added successfully!")
        print("Visit http://localhost:5000/dashboard to see it in action")

if __name__ == '__main__':
    seed_demo_data()
