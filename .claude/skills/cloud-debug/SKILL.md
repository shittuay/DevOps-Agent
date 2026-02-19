---
name: cloud-debug
description: Debug cloud resource issues for AWS, GCP, and Kubernetes. Use when troubleshooting cloud infrastructure, investigating resource problems, or diagnosing integration failures.
---

# Cloud Resource Debugging Guide

## Overview

This skill guides you through debugging AWS, GCP, and Kubernetes issues in the DevOps Agent application.

## AWS Debugging

### EC2 Issues

#### Instance Won't Start

```bash
# 1. Check instance status
aws ec2 describe-instances --instance-ids i-xxxxx \
  --query 'Reservations[*].Instances[*].[InstanceId,State.Name,StateReason]'

# 2. Check system status
aws ec2 describe-instance-status --instance-ids i-xxxxx

# 3. View console output
aws ec2 get-console-output --instance-id i-xxxxx

# 4. Check security groups
aws ec2 describe-security-groups --group-ids sg-xxxxx
```

#### Can't Connect to EC2

```bash
# 1. Verify security group allows SSH (port 22)
aws ec2 describe-security-groups --group-ids sg-xxxxx \
  --query 'SecurityGroups[*].IpPermissions'

# 2. Check network ACLs
aws ec2 describe-network-acls \
  --filters "Name=association.subnet-id,Values=subnet-xxxxx"

# 3. Verify key pair
ls -la ~/.ssh/
chmod 400 your-key.pem

# 4. Test connection
ssh -v -i your-key.pem ubuntu@ec2-ip
```

#### EC2 Performance Issues

```bash
# 1. Check CloudWatch metrics
aws cloudwatch get-metric-statistics \
  --namespace AWS/EC2 \
  --metric-name CPUUtilization \
  --dimensions Name=InstanceId,Value=i-xxxxx \
  --start-time 2026-01-22T00:00:00Z \
  --end-time 2026-01-22T23:59:59Z \
  --period 3600 \
  --statistics Average

# 2. SSH to instance and check
ssh -i key.pem ubuntu@ec2-ip
top  # Check CPU/memory
df -h  # Check disk space
netstat -an | grep ESTABLISHED  # Check connections
```

### S3 Issues

#### Access Denied

```bash
# 1. Check bucket policy
aws s3api get-bucket-policy --bucket your-bucket

# 2. Check IAM permissions
aws iam get-user-policy --user-name your-user --policy-name your-policy

# 3. Check bucket ACL
aws s3api get-bucket-acl --bucket your-bucket

# 4. Test with public access
aws s3 ls s3://your-bucket --no-sign-request
```

#### Upload/Download Failures

```bash
# 1. Check bucket region
aws s3api get-bucket-location --bucket your-bucket

# 2. Verify credentials
aws sts get-caller-identity

# 3. Test with small file
echo "test" > test.txt
aws s3 cp test.txt s3://your-bucket/

# 4. Check bucket versioning
aws s3api get-bucket-versioning --bucket your-bucket
```

### IAM Issues

#### Permission Denied

```bash
# 1. Check current user
aws sts get-caller-identity

# 2. List attached policies
aws iam list-attached-user-policies --user-name your-user

# 3. Get policy document
aws iam get-policy-version \
  --policy-arn arn:aws:iam::aws:policy/AmazonEC2FullAccess \
  --version-id v1

# 4. Simulate policy
aws iam simulate-principal-policy \
  --policy-source-arn arn:aws:iam::123456789012:user/your-user \
  --action-names ec2:DescribeInstances
```

### EKS Issues

#### Can't Connect to Cluster

```bash
# 1. Update kubeconfig
aws eks update-kubeconfig --region us-east-1 --name your-cluster

# 2. Verify cluster status
aws eks describe-cluster --name your-cluster \
  --query 'cluster.status'

# 3. Check IAM role
aws sts get-caller-identity

# 4. Test connection
kubectl cluster-info
```

#### Node Group Issues

```bash
# 1. Check node group status
aws eks describe-nodegroup \
  --cluster-name your-cluster \
  --nodegroup-name your-nodegroup

# 2. List nodes
kubectl get nodes

# 3. Describe problem node
kubectl describe node <node-name>
```

### CloudWatch Logs

#### Can't View Logs

```bash
# 1. List log groups
aws logs describe-log-groups

# 2. List log streams
aws logs describe-log-streams --log-group-name /aws/lambda/function-name

# 3. Get log events
aws logs get-log-events \
  --log-group-name /aws/lambda/function-name \
  --log-stream-name 2026/01/22/[$LATEST]abc123 \
  --limit 50

# 4. Tail logs
aws logs tail /aws/lambda/function-name --follow
```

## GCP Debugging

### Compute Engine Issues

#### Instance Problems

```bash
# 1. Check instance status
gcloud compute instances describe instance-name --zone=us-central1-a

# 2. View serial console output
gcloud compute instances get-serial-port-output instance-name

# 3. Check firewall rules
gcloud compute firewall-rules list

# 4. SSH to instance
gcloud compute ssh instance-name --zone=us-central1-a
```

### Cloud Storage Issues

#### Access Denied

```bash
# 1. Check bucket IAM
gsutil iam get gs://your-bucket

# 2. Check service account
gcloud auth list

# 3. Set correct project
gcloud config set project your-project-id

# 4. Test access
gsutil ls gs://your-bucket
```

### GKE Issues

#### Cluster Connection

```bash
# 1. Get credentials
gcloud container clusters get-credentials cluster-name --region=us-central1

# 2. Verify cluster
gcloud container clusters describe cluster-name --region=us-central1

# 3. Test kubectl
kubectl get nodes

# 4. Check service account permissions
gcloud projects get-iam-policy your-project-id
```

## Kubernetes Debugging

### Pod Issues

#### Pod Not Starting

```bash
# 1. Check pod status
kubectl get pods -n namespace

# 2. Describe pod
kubectl describe pod pod-name -n namespace

# 3. Check events
kubectl get events -n namespace --sort-by='.lastTimestamp'

# 4. Check logs
kubectl logs pod-name -n namespace
kubectl logs pod-name -n namespace --previous  # Previous container
```

#### CrashLoopBackOff

```bash
# 1. Get pod logs
kubectl logs pod-name -n namespace --tail=100

# 2. Check container status
kubectl get pod pod-name -n namespace -o jsonpath='{.status.containerStatuses[*]}'

# 3. Describe pod for reason
kubectl describe pod pod-name -n namespace | grep -A5 "State:"

# 4. Check resource limits
kubectl describe pod pod-name -n namespace | grep -A5 "Limits:"
```

#### ImagePullBackOff

```bash
# 1. Check image name
kubectl describe pod pod-name -n namespace | grep Image:

# 2. Check image pull secrets
kubectl get secrets -n namespace

# 3. Verify image exists
docker pull image-name:tag

# 4. Check registry credentials
kubectl describe secret registry-secret -n namespace
```

### Service Issues

#### Service Not Accessible

```bash
# 1. Check service
kubectl get svc service-name -n namespace

# 2. Check endpoints
kubectl get endpoints service-name -n namespace

# 3. Check pod labels match service selector
kubectl get pods -n namespace --show-labels
kubectl describe svc service-name -n namespace | grep Selector

# 4. Test from inside cluster
kubectl run test-pod --rm -it --image=busybox -- wget -O- service-name:port
```

### Deployment Issues

#### Deployment Stuck

```bash
# 1. Check deployment status
kubectl rollout status deployment/deployment-name -n namespace

# 2. Check replica sets
kubectl get rs -n namespace

# 3. Describe deployment
kubectl describe deployment deployment-name -n namespace

# 4. Check for issues
kubectl get events -n namespace --field-selector involvedObject.name=deployment-name
```

#### Rolling Update Failed

```bash
# 1. Check rollout history
kubectl rollout history deployment/deployment-name -n namespace

# 2. Rollback to previous version
kubectl rollout undo deployment/deployment-name -n namespace

# 3. Check current status
kubectl rollout status deployment/deployment-name -n namespace

# 4. Pause rollout if needed
kubectl rollout pause deployment/deployment-name -n namespace
```

### Node Issues

#### Node NotReady

```bash
# 1. Check node status
kubectl get nodes

# 2. Describe node
kubectl describe node node-name

# 3. Check node conditions
kubectl get node node-name -o jsonpath='{.status.conditions[*]}'

# 4. SSH to node (if possible) and check
ssh node
systemctl status kubelet
journalctl -u kubelet -n 100
```

### Resource Issues

#### Out of Resources

```bash
# 1. Check resource usage
kubectl top nodes
kubectl top pods -n namespace

# 2. Check resource requests/limits
kubectl describe nodes | grep -A5 "Allocated resources"

# 3. Find resource-heavy pods
kubectl top pods -A --sort-by=cpu
kubectl top pods -A --sort-by=memory

# 4. Check pod resource specs
kubectl get pods -n namespace -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.spec.containers[*].resources}{"\n"}{end}'
```

## DevOps Agent Integration Debugging

### Test AWS Connection

```bash
# Run test script
python test_aws_connection.py
```

This checks:
- AWS credentials configured
- Can list EC2 instances
- Can access S3 buckets
- IAM permissions

### Test Application Integrations

```bash
# Test all cloud integrations
python test_new_features.py
```

This tests:
- AWS tools
- GCP tools
- Kubernetes tools
- Git operations
- CI/CD integrations

### Debug Tool Failures

#### AWS Tools Failing

```python
# In app.py or interactive Python:
from src.tools import aws_tools

# Test individual tool
result = aws_tools.list_ec2_instances(region='us-east-1')
print(result)

# Check for errors
if 'error' in result:
    print(f"Error: {result['error']}")
    print(f"Details: {result.get('details', 'No details')}")
```

#### Kubernetes Tools Failing

```python
from src.tools import kubernetes_tools

# Test connection
result = kubernetes_tools.list_pods(namespace='default')
print(result)

# Check kubeconfig
import os
print(f"KUBECONFIG: {os.environ.get('KUBECONFIG', '~/.kube/config')}")
```

#### GCP Tools Failing

```python
from src.tools import gcp_tools

# Test connection
result = gcp_tools.list_instances(project='your-project', zone='us-central1-a')
print(result)

# Check service account
import os
print(f"GOOGLE_APPLICATION_CREDENTIALS: {os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')}")
```

## Logging and Monitoring

### Application Logs

```bash
# View application logs
tail -f logs/agent.log

# View security logs
tail -f logs/security.log

# Search for errors
grep -i error logs/agent.log
grep -i exception logs/agent.log
```

### CloudWatch Integration

```python
# In app.py, add CloudWatch logging
import boto3
from datetime import datetime

logs_client = boto3.client('logs')

def log_to_cloudwatch(message, log_group, log_stream):
    logs_client.put_log_events(
        logGroupName=log_group,
        logStreamName=log_stream,
        logEvents=[
            {
                'timestamp': int(datetime.now().timestamp() * 1000),
                'message': message
            }
        ]
    )
```

## Common Error Messages

### "NoCredentialsError: Unable to locate credentials"
- AWS credentials not configured
- Check `~/.aws/credentials` or environment variables
- Run `aws configure`

### "Error: You must be logged in to the server (Unauthorized)"
- Kubernetes credentials expired
- Run `aws eks update-kubeconfig` or `gcloud container clusters get-credentials`

### "AccessDenied: User is not authorized to perform"
- IAM permissions insufficient
- Add required permissions to IAM policy
- Check with `aws iam simulate-principal-policy`

### "Unable to connect to the server"
- Kubernetes API server unreachable
- Check network connectivity
- Verify kubeconfig is correct

## Quick Diagnostic Commands

```bash
# AWS
aws sts get-caller-identity  # Who am I?
aws ec2 describe-instances --output table  # List EC2
aws s3 ls  # List S3 buckets

# GCP
gcloud auth list  # Who am I?
gcloud compute instances list  # List VMs
gcloud storage buckets list  # List buckets

# Kubernetes
kubectl cluster-info  # Cluster status
kubectl get all -A  # All resources
kubectl get events -A --sort-by='.lastTimestamp'  # Recent events

# Application
python test_aws_connection.py  # Test AWS
python test_new_features.py  # Test all integrations
python test_integration.py  # Full integration test
```
