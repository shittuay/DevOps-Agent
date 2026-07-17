---
date: 2026-07-15
type: decision
tags: [deploy, security, aws]
---

# Deploy via AWS SSM, not inbound SSH

**Decision:** Both deploy paths (`ci.yml` auto-deploy on main, `deploy.yml` manual backup) run the deploy script on EC2 instance `i-09af962714b13f9bc` through AWS SSM `AWS-RunShellScript`. Port 22 is restricted to the operator's IP; SSM is the only automated path.

**Why:**
- No inbound SSH port open to CI means no `EC2_SSH_KEY` secret to leak and no public attack surface for the deploy path.
- The private-repo pull uses a read-only SSH deploy key stored on the box (`/home/ubuntu/.ssh/deploy_key`, wired via `core.sshCommand`) so no token ever passes through SSM command parameters — SSM params land in CloudTrail logs.

**Consequences:**
- Deploy debugging happens through SSM session output / CloudWatch, not by SSHing in from CI.
- The instance must keep IAM role `devops-agent-ssm-role` (`AmazonSSMManagedInstanceCore`) attached and the SSM agent online, or deploys silently queue/fail.
