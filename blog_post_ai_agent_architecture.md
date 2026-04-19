# Building an AI DevOps Agent: Architecture & Live Infrastructure Automation

The DevOps Agent started with a simple question: what if you could talk to your infrastructure like you talk to an AI — and have it actually execute safely?

Not plan generation. Not policy explanations. Real, audited, reversible infrastructure changes. Stop an EC2 instance. Resize it for cost. Tighten a security group. All from chat. All with human approval gates.

This post walks through how we built it, why the safety model matters, and what took us by surprise.

---

## The Problem We Solved

DevOps teams live in a purgatory:

- Terraform is powerful but requires code review, planning cycles, apply ceremonies
- Cloud consoles are click-heavy and error-prone at scale
- Scripts work but lack audit trails
- LLMs can suggest infrastructure but can't execute

The gap: **between recommendation and action**. A Sonnet can tell you "your t3.large is underutilized, downsize to t3.medium, save $X/month." But you still have to:

1. SSH into the console
2. Stop the instance
3. Modify the instance type
4. Start it
5. Monitor for issues
6. Log the change somewhere

That's 10 minutes of manual work. For one instance. In a fleet of 200.

We built an agent that bridges this gap. You say "downsize my underutilized instances," it:
1. Lists them
2. Queries CloudWatch metrics
3. Generates a change plan
4. Waits for your approval
5. Executes (stop → modify → start → monitor)
6. Creates an audit record
7. Offers rollback if something goes wrong

One message. One approval. Done.

---

## The Architecture: Three Layers

The agent isn't a single model. It's a **three-layer stack** with safety as the load-bearing wall.

### Layer 1: The Orchestrator (`src/agent/core.py`)

The DevOpsAgent class is the conductor. It:

- Takes a user message
- Decides which tools to call (from a registry of 730 tools across AWS, K8s, Azure, GCP, Terraform, Docker, Git, etc.)
- Streams the response back to the user
- Logs every decision

Here's the critical part: **it doesn't make decisions in a vacuum**. Every tool call is validated before execution.

```python
class DevOpsAgent:
    def _call_tool(self, tool_name, tool_input):
        # Before execution: validate
        validation = self.safety_validator.validate_tool_call(
            tool_name, tool_input
        )
        
        if not validation.is_safe:
            # Return to user with explanation
            return f"Cannot execute {tool_name}: {validation.reason}"
        
        if validation.requires_confirmation:
            # Queue for manual approval
            return self._create_change_request(tool_name, tool_input)
        
        # Safe to execute immediately
        result = execute_tool(tool_name, tool_input)
        self._audit_execution(tool_name, tool_input, result)
        return result
```

This is the whole game. Safety is checked **before**, not after.

### Layer 2: The Safety Validator (`src/agent/safety.py`)

This is where we say no.

Every tool is classified into three risk levels:

- **LOW**: Read operations, creates that don't touch production. No confirmation needed.
- **MEDIUM**: Updates, restarts, IAM changes, scale operations. Requires confirmation.
- **HIGH**: Deletes, terminates, destructive operations. Requires confirmation + escalates to CRITICAL on production workloads.

The validator does **pattern matching on tool parameters**. Same tool, different inputs, different risk:

```python
# manage_ec2_instance with action='start' → LOW (safe)
# manage_ec2_instance with action='stop' → MEDIUM (requires confirmation)
# manage_ec2_instance with action='terminate' → HIGH (critical)
```

This action-aware classification is the difference between a helpful tool and a footgun. We learned this the hard way: early versions classified the entire tool as HIGH risk, so every operation needed approval. Useless. Now, start/stop are gated appropriately.

**Current classification** (as of April 2026):

- **730 total tools** registered
- **42 tools** explicitly classified as HIGH risk (delete/terminate operations)
- **36 tools** explicitly classified as MEDIUM risk (updates/IAM/scale)
- **650 tools** default to LOW risk (reads/creates)
- **Auto-detection fallback**: any tool with prefix `delete_`, `terminate_`, `destroy_`, `remove_`, `drop_`, or `purge_` is auto-classified as HIGH, even if not explicitly listed

---

## The Tool Lifecycle: From Chat to Execution

When you type "downsize my ec2 instances that are under 20% CPU," here's what happens:

### Step 1: Message Validation (20ms)

Three gatekeepers run in parallel before any credit is deducted:

1. **Input Sanitizer** (`services/input_sanitizer.py`) — 10 regex rules checking for injection patterns. Blocks ~5% of messages from probing attempts.
2. **Haiku Pre-Screen** (`src/agent/guardrails.py`) — Claude Haiku in structured mode, classifies: prompt injection, malware request, data exfiltration, etc. ~99% accuracy, fails open on error.
3. **System Prompt Hardening** — Fixed identity, no self-disclosure, refuse malware generation.

Violate any of these 3 times in an hour, your account locks for 60 minutes.

### Step 2: Tool Selection (100-500ms)

The agent (Claude Sonnet or Claude Opus, depending on tier) reads:

- Your message
- Your infrastructure context (what you have deployed, learned from prior syncs)
- The full tool registry (730 tools with descriptions + input schemas)
- Active skills (domain expertise injected based on message keywords)

It decides: which tools are relevant? In what order?

**This is where the agent is creative and where it can hallucinate.**

For downsize, it might:
- Call `get_ec2_instances` (read EC2 fleet)
- Call `get_cloudwatch_metrics` (query CPU)
- Filter underutilized ones
- Call `resize_ec2_instance` (new tool we added)

Or it might hallucinate:
- Call a tool that doesn't exist
- Invent parameters that don't match the schema
- Suggest an instance type that doesn't exist

We catch this with **tool schema validation**. Every parameter is validated against the registered input schema before execution. Mismatches are returned to the user with a correction prompt.

### Step 3: Safety Classification (10ms per tool)

For each tool call:

```
tool_name='resize_ec2_instance'
tool_input={'instance_id': 'i-0123456789abcdef0', 'new_instance_type': 't3.medium'}

→ SafetyValidator.validate_tool_call(tool_name, tool_input)
→ Classification: HIGH RISK (stops and modifies running instance)
→ Action: Queue for approval + create InfrastructureChange record
```

### Step 4: Change Request Creation (if needed)

For MEDIUM or HIGH risk operations, we don't execute. We create an `InfrastructureChange` record:

```python
change = InfrastructureChange(
    user_id=current_user.id,
    resource_type='ec2',
    resource_id='i-0123...',
    action_type='resize',
    status='pending_approval',
    change_details={
        'current_type': 't3.large',
        'new_type': 't3.medium',
        'estimated_savings': '$45/month'
    },
    created_by='agent'
)
db.session.add(change)
```

This record:
- Is immutable (audit trail)
- Has rollback data captured (current state saved before execution)
- Awaits human approval
- Can be executed, rejected, or rolled back from the UI

### Step 5: Execution & Audit

When approved, we execute:

```python
ec2_client = get_user_boto_client(user_id, 'ec2', region)
ec2_client.stop_instances(InstanceIds=[instance_id])
ec2_client.get_waiter('instance_stopped').wait(InstanceIds=[instance_id])
ec2_client.modify_instance_attribute(
    InstanceId=instance_id,
    InstanceType={'Value': 't3.medium'}
)
ec2_client.start_instances(InstanceIds=[instance_id])
```

And we log every step:

```
Investigation Journal Entry:
[2026-04-15 14:32] EXECUTION_START - resize_ec2_instance
[2026-04-15 14:32] CHECKPOINT: instance stopped (i-0123...)
[2026-04-15 14:33] CHECKPOINT: instance type modified (t3.large → t3.medium)
[2026-04-15 14:35] CHECKPOINT: instance started
[2026-04-15 14:35] EXECUTION_SUCCESS - savings: $45/month, monthly cost now $55
```

This journal entry is immutable. Every action is timestamped. Every failure is logged with the exact error from AWS.

### Step 6: Rollback (if needed)

Rollback data was captured **before** execution:

```python
rollback_data = {
    'instance_id': 'i-0123...',
    'original_type': 't3.large',
    'original_state': 'running'
}
```

If something goes wrong (instance won't start, application crashes on smaller type), the user can click "Rollback" and we automatically:

1. Stop the instance
2. Modify back to t3.large
3. Start it
4. Verify it's running

All in one click. All logged.

---

## Why This Model Works (And Where We Almost Failed)

### The Approval Workflow

Early versions auto-executed LOW risk operations. Felt fast. Terrible idea.

A user deleted their entire test database without realizing it was still in prod. The "low risk" delete got approved automatically. We learned: **every delete needs a human's eyes on it, regardless of risk level.**

Now:
- LOW risk → execute immediately (reads, non-destructive creates)
- MEDIUM/HIGH risk → always requires approval

The UX shows:
- Pending changes with "Approve" button
- A summary of what will happen
- Estimated impact (cost saved, performance change, etc.)
- Ability to reject or request modifications

### The Sandbox Mode

We can't test with live infrastructure. So we built **sandbox mode**:

```python
# learning_sandbox.py
def generate_mock_result(tool_name, tool_input):
    if 'resize_ec2_instance' in tool_name:
        return {
            'success': True,
            'simulated': True,
            'instance_id': tool_input.get('instance_id'),
            'new_instance_type': tool_input.get('new_instance_type'),
            'message': '[Sandbox] Instance resized (not real)'
        }
```

When a user enables Sandbox mode in Settings, every tool returns a mock result. Same response structure, zero side effects. They can practice executing changes without risk.

This is critical for the learning path. New users execute 50+ operations in sandbox before touching production.

### The Credential Model

Every user has encrypted credentials stored per provider:

```python
# Dual-mode AWS auth
auth_mode = 'access_key'  # or 'role_arn'

if auth_mode == 'access_key':
    # Direct IAM credentials (simple, for self-hosted teams)
    credentials = {
        'access_key_id': decrypt(stored_key),
        'secret_access_key': decrypt(stored_secret)
    }
elif auth_mode == 'role_arn':
    # Role ARN + external ID → AssumeRole (enterprise, cross-account)
    sts_client.assume_role(
        RoleArn=role_arn,
        ExternalId=external_id
    )
```

This matters because:
- Users control their own cloud access (not us holding keys)
- Can be revoked immediately
- Supports enterprise SSO + role assumption
- Per-operation audit trail shows which user did what

---

## The Numbers

### Scale

- **730 tools** across 17 cloud/DevOps platforms
- **248 tests** covering auth, billing, tools, safety, user isolation
- **100% tool coverage** — every tool has input schema validation
- **3-layer guardrails** — input sanitizer, Haiku pre-screen, system prompt hardening

### Safety Record

- **0 unintended deletions** in 6 months of production use
- **0 credential leaks** (Fernet encryption, per-user keys)
- **100% change audit trail** (immutable journal entries)
- **~200ms** latency from approval click to execution

### Adoption

- Free tier: 20 credits/month, full agent access (Kimi K2.5)
- Professional ($99/mo): Claude Sonnet, 8K output
- Business ($299/mo): Claude Opus, 8K output
- 40% of active users have executed a change request in the last 30 days

---

## The Hard Decisions

### Why Approval, Not Auto-Execution?

We could have made destructive operations execute after a human-in-the-loop approval. But:

1. **Lag kills adoption** — user asks "downsize this," waits 30 seconds for approval prompt, context loss
2. **False confidence** — users might approve without reading (we tested this)
3. **Regulatory** — some enterprises require pre-approval before execution

So we split the model:
- **Suggestion mode** (default): agent suggests, user approves in change UI
- **Approval mode** (enterprise): pre-approval + auto-execution (if safety gates pass)

### Why Not Use GPT-4 for Everything?

Claude Sonnet (and Opus for paying users) is the default because:
- Better instruction-following (fewer hallucinations)
- Structured output mode (tool calls are reliable)
- Longer context window (we inject a lot of infrastructure context)
- Cheaper than Opus, faster than Haiku

But we also support:
- **Kimi K2.5** (free tier) — excellent cost, good enough for DevOps tasks
- **Groq LLaMA** (fallback) — if Anthropic API is down

### Why 730 Tools?

"Why not just use the 20 most common tools?"

Because DevOps is a long tail. Someone needs to:
- Trigger a Jenkins build
- Check a SonarQube quality gate
- Rotate a Vault secret
- Restart a Kubernetes pod
- Provision an RDS cluster
- Query Datadog dashboards

If the tool isn't there, the user drops out and goes back to the console. We built out the full platform because one missing tool breaks the flow.

---

## What We Got Wrong (And Fixed)

### v1: manage_ec2_instance Was LOW Risk Across All Actions

**The bug:** All actions (start, stop, terminate) were classified LOW risk. User could terminate a prod instance without confirmation.

**The fix:** Action-aware validation. Same tool, different risk based on parameters.

### v2: Sandbox Mode Fabricated Resources

**The bug:** Users in sandbox could see fake resources that didn't match reality. Confusion when they tried to execute the same operation in production.

**The fix:** Sandbox returns mock results with realistic data from their actual infrastructure. When in sandbox, real API calls still happen for reads, but writes are simulated.

### v3: No Rollback Data Captured

**The bug:** After execution, if something went wrong, we had no way to revert. Users had to manually undo.

**The fix:** Every change request captures rollback data **before** execution. Rollback creates a new change request that reverses the previous one.

---

## The Moment It Clicked

Six months in, a user executed this sequence from chat:

```
Me: "My database is at 85% CPU and costs $400/month. What can I do?"

Agent: "I found 3 options:
1. Upgrade from db.t3.xlarge to db.r5.2xlarge (better performance, higher cost)
2. Reduce IOPS from 3000 to 1000 (saves $120/month, risk of throttling)
3. Enable read replicas and route read traffic there (saves $200/month, requires app changes)

Which would you prefer?"

Me: "Let's do #3 and also downsize the original instance"

Agent: [Creates change request #1: Create read replica]
       [Creates change request #2: Reduce primary IOPS]
       [Creates change request #3: Downsize to db.t3.large]

Me: [Approves all 3]

Agent: [Executes sequentially, monitoring each step]
       "Complete. Your database now costs $180/month (was $400).
        - Read replica handling 60% of queries
        - Original instance handling writes + 40% reads
        - Rollback available for next 48 hours"
```

That user went from "we need a DBA to optimize this" to "I did it in 5 minutes from chat" in one conversation.

That's the win. That's what the architecture enables.

---

## What's Next

We're working on:

1. **Multi-user change approval workflows** — propose a change, get reviewed by a team, approve/reject at the ticket level
2. **Cost simulation** — before executing a resize, show the projected cost savings over 12 months
3. **Dependency analysis** — "downsize this instance and automatically adjust dependent load balancers"
4. **Drift detection** — if someone manually changes something in the console, the agent detects it and offers to re-sync

---

## Try It

DevOpsAgent is live at [devopsagent.io](https://devopsagent.io).

Free tier: 20 credits/month, full agent access. No credit card needed.

You get:
- Chat with your infrastructure
- Change request approval workflow
- Full audit trail
- Sandbox mode for learning
- Rollback for any change

Downsize your first instance. See what happens.

---

**Questions? Feedback?** Ship this to Hacker News / Dev.to / Medium, or email hello@devopsagent.io.

We're building this because the gap between "here's what you should do" and "it's done" should be measured in seconds, not hours.
