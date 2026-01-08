# Branch Protection Configuration Guide

This document outlines the recommended branch protection rules for this repository to ensure code quality and security.

## Required Setup

### 1. Configure Branch Protection for `main`

Navigate to: **Settings → Branches → Add branch protection rule**

**Branch name pattern:** `main`

#### Required Settings:

- ✅ **Require a pull request before merging**
  - Required number of approvals: 1
  - ✅ Dismiss stale pull request approvals when new commits are pushed
  - ✅ Require review from Code Owners (if CODEOWNERS file is added)

- ✅ **Require status checks to pass before merging**
  - ✅ Require branches to be up to date before merging
  - **Required status checks:**
    - `test / Run Tests`
    - `security / Security Scan`
    - `lint / Code Quality`
    - `build-check / Build Verification`
    - `status-check / All Checks Passed`

- ✅ **Require conversation resolution before merging**

- ✅ **Require signed commits** (recommended for security)

- ✅ **Require linear history** (maintains clean git history)

- ✅ **Do not allow bypassing the above settings**

- ✅ **Restrict who can push to matching branches**
  - Only allow administrators and specific users/teams

- ❌ **Allow force pushes** - Keep disabled

- ❌ **Allow deletions** - Keep disabled

### 2. Configure Branch Protection for `develop`

Navigate to: **Settings → Branches → Add branch protection rule**

**Branch name pattern:** `develop`

#### Required Settings:

- ✅ **Require a pull request before merging**
  - Required number of approvals: 1
  - ✅ Dismiss stale pull request approvals when new commits are pushed

- ✅ **Require status checks to pass before merging**
  - ✅ Require branches to be up to date before merging
  - **Required status checks:**
    - `test / Run Tests`
    - `security / Security Scan`
    - `lint / Code Quality`
    - `build-check / Build Verification`

- ✅ **Require conversation resolution before merging**

- ❌ **Allow force pushes** - Keep disabled

- ❌ **Allow deletions** - Keep disabled

### 3. Configure Dependabot

Navigate to: **Settings → Security → Code security and analysis**

- ✅ Enable **Dependabot alerts**
- ✅ Enable **Dependabot security updates**

Create `.github/dependabot.yml`:

```yaml
version: 2
updates:
  - package-ecosystem: "pip"
    directory: "/"
    schedule:
      interval: "weekly"
    open-pull-requests-limit: 10
    target-branch: "develop"
    reviewers:
      - "your-username"
    labels:
      - "dependencies"
      - "automated"
```

### 4. Set Up CODEOWNERS (Optional but Recommended)

Create `.github/CODEOWNERS`:

```
# Default owners for everything in the repo
*       @your-username @your-team

# Security-sensitive files
requirements.txt    @security-team @your-username
.github/workflows/  @devops-team @your-username
app.py             @backend-team @your-username
models.py          @backend-team @your-username

# Infrastructure
.github/           @devops-team
*.yml              @devops-team
```

## Verification Checklist

After configuration, verify:

- [ ] Cannot push directly to `main` without a PR
- [ ] Cannot push directly to `develop` without a PR
- [ ] PRs to `main` require all status checks to pass
- [ ] PRs to `develop` require all status checks to pass
- [ ] PRs require at least 1 approval
- [ ] Force pushes are blocked on both branches
- [ ] Branch deletion is blocked on both branches
- [ ] Dependabot is creating PRs to `develop` branch
- [ ] CI/CD workflow runs on all PRs

## GitHub Actions Status Checks

The following workflows must pass before merging:

### CI/CD Pipeline (`ci.yml`)
- **test**: Runs comprehensive test suite
- **security**: Scans for vulnerabilities in dependencies
- **lint**: Checks code quality with flake8
- **build-check**: Verifies Flask app can be built
- **status-check**: Ensures all checks passed

### Dependabot Auto-Merge (`dependabot.yml`)
- Automatically reviews and merges patch and minor dependency updates
- Only applies to PRs targeting `develop` branch

## Workflow

1. **Feature Development**: `develop` → `feature/branch-name`
2. **Create PR**: `feature/branch-name` → `develop`
3. **CI/CD Runs**: All status checks must pass
4. **Code Review**: Requires 1 approval
5. **Merge**: Squash and merge to `develop`
6. **Release**: Create PR from `develop` → `main`
7. **Production Deploy**: After merge to `main`

## Emergency Hotfixes

For critical production issues:

1. Create hotfix branch from `main`: `hotfix/description`
2. Create PR to `main` with "hotfix" label
3. Expedite review process
4. After merge to `main`, backport to `develop`

## Troubleshooting

### Status checks not showing up
- Wait 5-10 minutes after first workflow run
- Ensure workflows have run at least once
- Check Actions tab for any failures

### Cannot merge despite passing checks
- Verify all required checks are listed in branch protection
- Ensure branch is up to date with base branch
- Check if conversations need to be resolved

### Dependabot PRs not auto-merging
- Verify permissions in workflow file
- Check Dependabot settings are enabled
- Ensure target branch is `develop`

## Additional Resources

- [GitHub Branch Protection Documentation](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches)
- [GitHub Actions Documentation](https://docs.github.com/en/actions)
- [Dependabot Documentation](https://docs.github.com/en/code-security/dependabot)
