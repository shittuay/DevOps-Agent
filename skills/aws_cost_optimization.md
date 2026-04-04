---
id: aws-cost-optimization
name: AWS Cost Optimization
triggers: [cost, billing, spend, rightsizing, reserved, savings plan, expensive, overprovisioned, waste, idle, underutilized, ec2 cost, rds cost, s3 cost]
compatible_providers: [aws]
---
# AWS Cost Optimization Context

## Quick Wins
- **Rightsizing**: Instances with <5% avg CPU over 14 days are prime candidates. Use `get_optimization_recommendations` to find them.
- **Unattached EBS**: Every unattached volume costs ~$0.10/GB/month. List and delete unused volumes.
- **Idle Load Balancers**: ALBs with 0 healthy targets or <1 req/min still cost ~$18/month.
- **Unused Elastic IPs**: Unassociated EIPs cost $0.005/hr.
- **NAT Gateway data**: Review VPC flow logs — NAT Gateway at $0.045/GB can surprise teams.

## Reserved Instances & Savings Plans
- **Compute Savings Plans**: 1-year no-upfront ~17% discount, 3-year ~40%. Flexible across EC2, Fargate, Lambda.
- **EC2 Instance Savings Plans**: Locked to family/region but up to 72% off. Best for stable, predictable workloads.
- **RDS Reserved**: 1-year no-upfront ~30%, 3-year up to 60%. Multi-AZ RIs available.
- Coverage target: 70–80% of steady-state spend should be covered by RIs/SPs.

## Storage Optimization
- **S3 Intelligent-Tiering**: Auto-moves objects between frequent/infrequent access. Break-even at ~128KB objects accessed less than once per month.
- **S3 Lifecycle**: Transition to Glacier Instant Retrieval at 90 days, Deep Archive at 180 days for logs.
- **EBS gp2→gp3**: gp3 is 20% cheaper than gp2 with same performance baseline. No downtime required.
- **Snapshot cleanup**: Old AMI snapshots, EBS snapshots older than 90 days with no active AMI.

## Tooling
- Run `get_cost_summary` to see current spend breakdown by service.
- Run `get_optimization_recommendations` to get AI-powered rightsizing suggestions.
- Use `get_infrastructure_summary` to enumerate all resources for audit.
