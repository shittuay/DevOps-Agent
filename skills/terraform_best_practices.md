---
id: terraform-best-practices
name: Terraform Best Practices
triggers: [terraform, tfstate, module, workspace, plan, apply, destroy, drift, state, hcl, infrastructure as code, iac, remote state, backend, variable, output]
compatible_providers: [aws, azure, gcp]
---
# Terraform Best Practices Context

## State Management
- **Always use remote state**: S3 + DynamoDB locking (AWS), GCS (GCP), Azure Blob (Azure), or Terraform Cloud
- **State locking**: DynamoDB table with `LockID` as partition key prevents concurrent applies
- **State encryption**: S3 bucket with server-side encryption + versioning enabled
- **Never commit state files**: `.terraform/` and `*.tfstate` must be in `.gitignore`
- **Workspaces**: Use for ephemeral environments (dev/staging/prod per workspace) or use separate root modules

## Module Design
- **One module per logical unit**: VPC module, EKS module, RDS module — not one giant module
- **Version pin your modules**: `source = "terraform-aws-modules/vpc/aws" version = "~> 5.0"`
- **Input validation**: Use `validation` blocks to catch bad inputs early
- **Outputs**: Always export resource IDs and ARNs that consumers need

## Safe Apply Workflow
1. `terraform_plan` → review the diff, check for unexpected destroys
2. If plan looks good: `terraform_apply`
3. For production: require plan approval in CI (Atlantis, Terraform Cloud, GitHub Actions with environments)
4. **Never use `-auto-approve` in production**
5. `terraform_validate` and `terraform_fmt` in CI before plan

## Drift Detection & Import
- `terraform_show` to compare desired vs actual state
- `terraform_import` to bring existing resources under Terraform management
- `terraform_refresh` to update state with real cloud state (use carefully — can remove resources from state)
- `terraform_state_list` to see all managed resources

## Variables & Secrets
- Use `variable` with `sensitive = true` for secrets (prevents printing in plan output)
- Source secrets from Vault, AWS Secrets Manager, or environment variables — not tfvars files
- Use `locals` to compute derived values from variables

## Common Patterns
- **-target**: Use only for emergency surgical applies — it leaves state inconsistent
- **count vs for_each**: Prefer `for_each` with maps; `count` creates index-based addressing that breaks on deletion
- **depends_on**: Last resort — prefer implicit resource references
- **lifecycle { prevent_destroy = true }**: Add to production databases and stateful resources
