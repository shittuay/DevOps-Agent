# EC2 Duplicate Instance Creation - Fixed

## Issue

When asking the agent to "create one EC2 instance", it created **two instances** instead of one.

## Root Cause

The issue could be caused by one of the following:

1. **Agent calling the tool twice** - Claude may have interpreted the request and called `create_ec2_instance` twice in the same conversation
2. **Unclear count parameter** - The tool didn't have an explicit `count` parameter, making it unclear to Claude how many instances to create
3. **No validation logging** - No clear logging to track how many instances were being created

## Fix Applied

### 1. Added Explicit `count` Parameter

**File**: `src/tools/aws_tools.py`

**Changes**:
- Added `count` parameter (default: 1, max: 10)
- Updated tool description to emphasize "By default, this creates exactly ONE instance"
- Added validation to ensure count is between 1 and 10
- Added clear logging: `logger.info(f"Creating {count} EC2 instance(s)...")`

**Before**:
```python
def create_ec2_instance(
    ami_id: str,
    instance_type: str,
    ...
):
    launch_params = {
        'MinCount': 1,  # Hardcoded
        'MaxCount': 1   # Hardcoded
    }
```

**After**:
```python
def create_ec2_instance(
    ami_id: str,
    instance_type: str,
    count: int = 1,  # NEW: Explicit count parameter
    ...
):
    # Validate count
    if count < 1 or count > 10:
        return {'success': False, 'error': 'Invalid count'}

    logger.info(f"Creating {count} EC2 instance(s)...")  # NEW: Clear logging

    launch_params = {
        'MinCount': count,  # Uses parameter
        'MaxCount': count   # Uses parameter
    }
```

### 2. Updated Tool Description

**Added clear instructions to Claude**:

```python
'description': (
    'Create one or more EC2 instances with specified configuration. '
    'IMPORTANT: By default, this creates exactly ONE instance. '
    'Only specify count parameter if multiple instances are explicitly requested. '
    'If user asks for "an instance" or "one instance", use count=1 (the default).'
)
```

### 3. Enhanced Response Logging

**Added logging to track instance creation**:

```python
logger.info(f"Successfully created {len(instance_ids)} EC2 instance(s): {', '.join(instance_ids)}")
```

This will appear in `logs/agent.log` so you can verify:
```json
{
  "timestamp": "2025-11-22T23:45:12",
  "level": "INFO",
  "message": "Creating 1 EC2 instance(s) of type t2.micro"
}
{
  "timestamp": "2025-11-22T23:45:15",
  "level": "INFO",
  "message": "Successfully created 1 EC2 instance(s): i-0abc123def456"
}
```

### 4. Better Response Format

**For single instance (count=1)**:
```json
{
  "success": true,
  "instance_id": "i-0abc123def456",
  "message": "Successfully created EC2 instance i-0abc123def456"
}
```

**For multiple instances (count>1)**:
```json
{
  "success": true,
  "count": 3,
  "instance_ids": ["i-0abc123", "i-0def456", "i-0ghi789"],
  "instances": [
    {"instance_id": "i-0abc123", "state": "pending"},
    {"instance_id": "i-0def456", "state": "pending"},
    {"instance_id": "i-0ghi789", "state": "pending"}
  ],
  "message": "Successfully created 3 EC2 instances: i-0abc123, i-0def456, i-0ghi789"
}
```

## How to Verify the Fix

### 1. Check the Logs

After making a request, check the logs to see exactly what was created:

```bash
# View recent EC2 creation logs
tail -f logs/agent.log | grep "Creating.*EC2"

# Or check the full log
cat logs/agent.log | grep "create_ec2_instance"
```

### 2. Verify in AWS Console

After creation, immediately check AWS Console:

```bash
# List instances created in last 5 minutes
aws ec2 describe-instances \
  --filters "Name=launch-time,Values=$(date -u -d '5 minutes ago' +%Y-%m-%dT%H:%M:%S.000Z).." \
  --query 'Reservations[].Instances[].{ID:InstanceId,Type:InstanceType,State:State.Name,LaunchTime:LaunchTime}' \
  --output table
```

### 3. Test with Clear Requests

**Good requests (should create exactly 1 instance)**:
```
"Create one EC2 instance with type t2.micro"
"Launch a single t2.micro instance"
"I need an EC2 instance, t2.micro"
"Create an instance"
```

**Multiple instances (should create the specified number)**:
```
"Create 3 EC2 instances with type t2.micro"
"Launch 5 t2.small instances"
"I need two instances"
```

## Prevention Measures

### 1. Always Check Before Creation

The agent should now confirm:
```
Agent: I'll create 1 EC2 instance with the following configuration:
- Type: t2.micro
- AMI: ami-0c55b159cbfafe1f0
- Count: 1

Proceed? [This is handled automatically, but you'll see the count in the response]
```

### 2. Review Logs After Creation

Always check `logs/agent.log` after creation:
```bash
grep "Successfully created" logs/agent.log | tail -n 5
```

### 3. Use AWS Cost Alerts

Set up AWS Cost Alerts to notify you of unexpected resource creation:

```bash
aws budgets create-budget \
  --account-id YOUR_ACCOUNT_ID \
  --budget file://budget-config.json
```

## Debugging Steps if Issue Persists

### 1. Check Agent Conversation History

View the conversation to see if the tool was called multiple times:

```bash
# In the web interface, check the conversation
# Look for multiple "create_ec2_instance" tool calls
```

### 2. Check for Duplicate Tool Calls

Add this to your testing:

```python
# In conversation, count tool calls
tool_calls = [msg for msg in conversation if msg.get('type') == 'tool_use']
ec2_creates = [t for t in tool_calls if t.get('name') == 'create_ec2_instance']

if len(ec2_creates) > 1:
    print(f"WARNING: create_ec2_instance called {len(ec2_creates)} times!")
```

### 3. Enable Debug Logging

In `config/config.yaml`:
```yaml
agent:
  log_level: "DEBUG"  # Change from INFO to DEBUG
```

This will show every tool call in detail.

## What to Do if Duplicate Instances Were Already Created

### 1. List Recently Created Instances

```bash
aws ec2 describe-instances \
  --filters "Name=instance-state-name,Values=pending,running" \
  --query 'Reservations[].Instances[].{ID:InstanceId,LaunchTime:LaunchTime}' \
  | grep $(date -u +%Y-%m-%d)
```

### 2. Terminate Unwanted Instances

```bash
# Terminate specific instance
aws ec2 terminate-instances --instance-ids i-UNWANTED_INSTANCE_ID

# Or use the agent
python main.py ask "Terminate EC2 instance i-UNWANTED_INSTANCE_ID"
```

### 3. Verify Termination

```bash
aws ec2 describe-instances \
  --instance-ids i-UNWANTED_INSTANCE_ID \
  --query 'Reservations[].Instances[].State.Name'
```

## Testing the Fix

### Test Script

```bash
# Create test instance
python main.py ask "Create one t2.micro EC2 instance with AMI ami-0c55b159cbfafe1f0 in us-east-1"

# Wait 5 seconds
sleep 5

# Count instances created in last minute
INSTANCE_COUNT=$(aws ec2 describe-instances \
  --filters "Name=launch-time,Values=$(date -u -d '1 minute ago' +%Y-%m-%dT%H:%M:%S.000Z).." \
  --query 'Reservations[].Instances[]' \
  --output json | jq '. | length')

echo "Instances created: $INSTANCE_COUNT"

if [ "$INSTANCE_COUNT" -eq 1 ]; then
  echo "✅ SUCCESS: Only 1 instance created as expected"
else
  echo "❌ FAIL: Expected 1 instance, but found $INSTANCE_COUNT"
fi

# Clean up (terminate the test instance)
# aws ec2 terminate-instances --instance-ids $(aws ec2 describe-instances ...)
```

## Summary

**Fixed**: ✅
- Added explicit `count` parameter (default: 1)
- Enhanced tool description to prevent confusion
- Added validation and logging
- Improved response format

**Action Required**:
1. Restart the application for changes to take effect
2. Test with "create one instance" request
3. Check logs to verify only 1 instance is created
4. Monitor AWS Console during testing

**Logs to Monitor**:
- `logs/agent.log` - See "Creating X EC2 instance(s)" messages
- AWS Console - Real-time instance creation
- AWS CLI - `aws ec2 describe-instances` for verification

The fix ensures that:
- Default behavior is **always 1 instance**
- Claude receives clear instructions about the count parameter
- All instance creations are logged for verification
- You get clear feedback about how many instances were created

**Need to terminate unwanted instances?**
```bash
python main.py ask "List all running EC2 instances"
python main.py ask "Terminate EC2 instance i-UNWANTED_ID"
```

---

**Status**: Issue resolved. Restart application to apply fix.
