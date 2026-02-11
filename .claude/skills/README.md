# DevOps Agent Custom Skills

This directory contains custom Claude Code skills specifically designed for the DevOps Agent Flask application.

## Available Skills

### 1. flask-test
**Purpose:** Comprehensive testing workflow for the Flask application

**Use when:**
- Running test suites
- Testing endpoints
- Validating functionality
- Checking code coverage

**Key features:**
- Unit test execution
- Integration testing
- Endpoint validation
- Security testing
- Performance testing
- Test reporting

**Example usage:**
```
You: Use flask-test to run the full test suite
You: Test the authentication endpoints
You: Run tests with coverage report
```

### 2. db-migrate
**Purpose:** Database migration and schema management

**Use when:**
- Creating database migrations
- Updating database schema
- Adding new tables or columns
- Managing database changes

**Key features:**
- Migration script templates
- Pre-migration checks
- Rollback procedures
- Data migration patterns
- Production migration workflow

**Example usage:**
```
You: Use db-migrate to add a new column to the users table
You: Create a migration for the new feature table
You: Help me rollback the last migration
```

### 3. deploy-verify
**Purpose:** Deploy and verify the application across platforms

**Use when:**
- Deploying to AWS, Railway, Render, or Netlify
- Verifying deployment health
- Troubleshooting deployment issues
- Checking post-deployment functionality

**Key features:**
- Multi-platform deployment guides
- Pre-deployment checklist
- Health checks
- Performance testing
- Security verification
- Rollback procedures

**Example usage:**
```
You: Use deploy-verify to deploy to AWS Elastic Beanstalk
You: Verify the production deployment is healthy
You: Help me troubleshoot the EC2 deployment
```

### 4. cloud-debug
**Purpose:** Debug cloud resource issues for AWS, GCP, and Kubernetes

**Use when:**
- Troubleshooting cloud infrastructure
- Investigating resource problems
- Diagnosing integration failures
- Debugging AWS/GCP/K8s issues

**Key features:**
- AWS debugging (EC2, S3, IAM, EKS, CloudWatch)
- GCP debugging (Compute Engine, Cloud Storage, GKE)
- Kubernetes debugging (Pods, Services, Deployments)
- Integration testing
- Common error solutions

**Example usage:**
```
You: Use cloud-debug to troubleshoot the EC2 connection issue
You: Help me debug why pods are crashing
You: Investigate the AWS permission denied error
```

### 5. devops-agent-dev
**Purpose:** Development guide for the DevOps Agent codebase

**Use when:**
- Adding new features
- Modifying existing tools
- Updating the UI
- Working on the codebase

**Key features:**
- Project architecture overview
- Adding new tools guide
- Database model creation
- Adding new pages
- Testing workflows
- Debugging tips
- Best practices

**Example usage:**
```
You: Use devops-agent-dev to add a new AWS tool
You: Help me add a new database model
You: Guide me through creating a new page
```

### 6. secrets-mgmt
**Purpose:** Manage application secrets using AWS Secrets Manager

**Use when:**
- Setting up AWS Secrets Manager
- Migrating from .env files to Secrets Manager
- Managing secrets in production
- Troubleshooting secret access issues
- Rotating secrets

**Key features:**
- AWS Secrets Manager setup
- IAM permission configuration
- Secret creation and management
- Integration into app.py
- Environment separation
- Cost optimization
- Security best practices

**Example usage:**
```
You: Use secrets-mgmt to set up AWS Secrets Manager
You: Help me migrate from .env to Secrets Manager
You: Troubleshoot secret access denied error
You: Rotate the production API keys
```

## How to Use Skills

### Method 1: Mention the Skill
Simply mention the skill in your request:

```
You: Use flask-test to run all tests with coverage
```

### Method 2: Reference by Purpose
Claude will automatically select the appropriate skill based on your task:

```
You: I need to add a new column to the database
(Claude will use db-migrate skill)

You: Deploy the app to AWS
(Claude will use deploy-verify skill)
```

### Method 3: Ask for the Skill
```
You: What skills are available?
You: Show me the flask-test skill
```

## Skill Structure

Each skill follows the Agent Skills standard with:

```markdown
---
name: skill-name
description: When to use this skill
---

# Skill Content

Instructions, commands, best practices, etc.
```

## Customizing Skills

To modify a skill:

1. Edit the corresponding `.md` file in `.claude/skills/`
2. Update the description in the YAML frontmatter
3. Modify the content as needed
4. Save the file

Changes take effect immediately.

## Creating New Skills

To create a new skill:

1. Create a new `.md` file in `.claude/skills/`
2. Add YAML frontmatter with name and description
3. Write the skill content
4. Test by asking Claude to use it

Example template:

```markdown
---
name: my-skill
description: What this skill does and when to use it
---

# My Skill

## Overview
Describe the skill purpose

## Workflow
Step-by-step instructions

## Commands
Useful commands

## Best Practices
Tips and recommendations
```

## Skills Repository

These skills were inspired by the Anthropic skills repository:
https://github.com/anthropics/skills

### 7. update-context
**Purpose:** Keep CLAUDE.md up to date with codebase changes

**Use when:**
- After adding new tools, routes, or features
- After fixing bugs or discovering gotchas
- After architecture or configuration changes
- After adding new environment variables

**Example usage:**
```
You: /update-context
You: Update CLAUDE.md with the changes I just made
```

### 8. resume-work
**Purpose:** Recover context after rate limit or token reset disruptions

**Use when:**
- Starting a new session after a rate limit disruption
- Context was compressed and you lost track
- Need to pick up where you left off

**Example usage:**
```
You: /resume-work
You: What was I working on before the reset?
```

### 9. memory
**Purpose:** Maintain a persistent work log (WORKLOG.md) across sessions

**Use when:**
- End of a work session to save progress
- Start of a new session to reload context
- After token resets or rate limit disruptions
- When the user says "remember this"

**Example usage:**
```
You: /memory
You: Save what we did today
You: What were we working on?
```

## Need Help?

If you need assistance with skills:
- Ask Claude: "Help me understand the flask-test skill"
- Read the skill file directly: `.claude/skills/flask-test.md`
- Check the Anthropic documentation: https://support.claude.com/en/articles/12512198-creating-custom-skills

## Best Practices

1. **Use the right skill** - Choose the skill that matches your task
2. **Be specific** - Provide context when asking Claude to use a skill
3. **Update skills** - Keep skills current with project changes
4. **Create new skills** - Add skills for frequently repeated tasks
5. **Share skills** - Share useful skills with your team

---

**Last Updated:** 2026-01-22
**Created by:** Claude Code based on Anthropic skills standard
