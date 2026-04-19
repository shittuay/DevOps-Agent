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

The gap: **between recommendation and action**. A model can tell you "your t3.large is underutilized, downsize to t3.medium, save $X/month." But you still have to:

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

### Layer 1: The Orchestrator

The DevOpsAgent class is the conductor. It takes a user message, decides which tools to call from a registry of 730 tools across AWS, K8s, Azure, GCP, Terraform, Docker, Git, and more, streams the response back to the user, and logs every decision.

The critical part: **it doesn't make decisions in a vacuum**. Every tool call is validated before execution.

```python
class DevOpsAgent:
    def _call_tool(self, tool_name, tool_input):
        validation = self.safety_validator.validate_tool_call(
            tool_name, tool_input
        )
        if not validation.is_safe:
            return f"Cannot execute {tool_name}: {validation.reason}"
        if validation.requires_confirmation:
            return self._create_change_request(tool_name, tool_input)
        result = execute_tool(tool_name, tool_input)
        self._audit_execution(tool_name, tool_input, result)
        return result
```

Safety is checked **before**, not after. This is the whole game.

### Layer 2: The Safety Validator

This is where we say no.

Every tool is classified into three risk levels:

- **LOW**: Read operations, creates that don't touch production. No confirmation needed.
- **MEDIUM**: Updates, restarts, IAM changes, scale operations. Requires confirmation.
- **HIGH**: Deletes, terminates, destructive operations. Requires confirmation + escalates to CRITICAL on production workloads.

The validator does **pattern matching on tool parameters**. Same tool, different inputs, different risk:

```python
# manage_ec2_instance with action='start'     → LOW  (no confirmation)
# manage_ec2_instance with action='stop'      → MEDIUM (requires confirmation)
# manage_ec2_instance with action='terminate' → HIGH (critical)
```

This action-aware classification is the difference between a helpful tool and a footgun.

**Current classification across 730 tools:**

- 42 tools explicitly classified as HIGH risk (delete/terminate)
- 36 tools explicitly classified as MEDIUM risk (updates/IAM/scale)
- 650 tools default to LOW risk (reads/creates)
- Auto-detection fallback: prefixes `delete_`, `terminate_`, `destroy_`, `remove_`, `drop_`, `purge_` → auto HIGH

### Layer 3: The Guardrails

Three layers fire before any credit is deducted or tool runs:

1. **Input Sanitizer** — 10 regex rules blocking injection patterns
2. **Haiku Pre-Screen** — Claude Haiku in structured mode classifying: prompt injection, malware requests, data exfiltration. ~99% accuracy, fails open on error.
3. **Hardened System Prompt** — Fixed identity, no self-disclosure, refuse malware generation regardless of framing.

Violate any of these 3 times in an hour → account locked for 60 minutes.

---

## The Tool Lifecycle: From Chat to Execution

When you type "downsize my ec2 instances that are under 20% CPU," here's the full path:

**Step 1 — Message Validation (20ms)**
Three gatekeepers in parallel. Any failure stops the request before any API call.

**Step 2 — Tool Selection (100–500ms)**
The agent reads your message, your infrastructure context, the 730-tool registry, and active domain skills. It picks the tool chain: `get_ec2_instances` → `get_cloudwatch_metrics` → filter → `resize_ec2_instance`.

**Step 3 — Safety Classification (10ms per tool)**

```
tool_name='resize_ec2_instance'
tool_input={'instance_id': 'i-0123...', 'new_instance_type': 't3.medium'}

→ Classification: HIGH RISK
→ Action: Queue for approval, create InfrastructureChange record
```

**Step 4 — Change Request**
We don't execute. We create an immutable `InfrastructureChange` record with rollback data captured before anything runs. It shows in the UI: approve, reject, or request modifications.

**Step 5 — Execution**
When approved:

```python
ec2_client = get_user_boto_client(user_id, 'ec2', region)
ec2_client.stop_instances(InstanceIds=[instance_id])
ec2_client.get_waiter('instance_stopped').wait(...)
ec2_client.modify_instance_attribute(InstanceType={'Value': 't3.medium'})
ec2_client.start_instances(InstanceIds=[instance_id])
```

Every step is timestamped in an immutable journal. Every failure shows the exact AWS error code verbatim.

**Step 6 — Rollback**
Rollback data captured before execution. One click reverses everything. All logged.

---

## What We Got Wrong (And Fixed)

**v1: manage_ec2_instance was LOW risk for all actions.**
Bug: user could terminate a production instance with no confirmation.
Fix: action-aware validation — same tool, different risk based on the `action` parameter.

**v2: Sandbox mode fabricated resources that didn't match production.**
Bug: users practiced on fake data then got confused executing the same operation live.
Fix: sandbox simulates writes but still makes real read API calls. Mock results use actual infrastructure data from the last sync.

**v3: No rollback data captured before execution.**
Bug: if something went wrong post-execution, no way to revert.
Fix: every change request captures full pre-execution state. Rollback creates a new reverse change request, also logged.

**v4: Model hallucinating tool results.**
Bug: the free-tier model (Kimi K2.5) would write `[Executing tool...]` in plain text instead of using function calling — fabricating results that looked real.
Fix: two-tier hallucination detection. Strong patterns (fake execution markers) always blocked. Streaming buffer: accumulate the full response, check for fabrication before yielding anything to the user.

---

## The Numbers

- **730 tools** across 17 platforms (AWS, Azure, GCP, K8s, Terraform, Docker, Git, Jenkins, GitHub Actions, SonarQube, Nexus, Ansible, PagerDuty, and more)
- **248 tests** covering auth, billing, tools, safety, user isolation
- **3-layer guardrails** at every request
- **0 unintended deletions** in production use
- **0 credential leaks** (Fernet/AES-128 encryption, per-user keys)
- **100% change audit trail** — immutable, timestamped, reversible

---

## The Moment It Clicked

A user sent this from chat:

> "My database is at 85% CPU and costs $400/month. What can I do?"

The agent found three options, got approval for all three, and executed them sequentially — read replica creation, IOPS reduction, primary downsize. Full audit trail, rollback available.

Database cost: $400/month → $180/month. Done in 5 minutes from chat.

That user went from "we need a DBA for this" to "I just did it." That's the gap the architecture closes.

---

## Try It

DevOps Agent is live at **devopsagent.io**.

Free tier: 20 credits/month, full agent access. No credit card needed.

You get: chat with your infrastructure, change request approval workflow, full audit trail, sandbox mode for learning, and one-click rollback for any change.

*Questions or feedback? Email hello@devopsagent.io*
