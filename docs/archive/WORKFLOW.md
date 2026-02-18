# Git Workflow Guide

This project follows a **Git Flow** workflow with three main branch types:

## Branch Structure

### Main Branches

1. **`main`** - Production-ready code
   - Contains stable, released code
   - All commits should be tagged with version numbers
   - Protected branch - no direct commits
   - Only accepts merges from `develop` via pull requests

2. **`develop`** - Integration branch for features
   - Contains the latest development changes
   - Base branch for all feature branches
   - Protected branch - no direct commits
   - Merges into `main` for releases

### Supporting Branches

3. **`feature/*`** - Feature development branches
   - Branch from: `develop`
   - Merge into: `develop`
   - Naming convention: `feature/description-of-feature`
   - Example: `feature/add-user-authentication`

## Workflow Steps

### Starting a New Feature

```bash
# 1. Ensure you're on develop and have latest changes
git checkout develop
git pull origin develop

# 2. Create a new feature branch
git checkout -b feature/your-feature-name

# 3. Work on your feature (make commits)
git add .
git commit -m "feat: description of changes"

# 4. Push feature branch to remote
git push -u origin feature/your-feature-name
```

### Completing a Feature

```bash
# 1. Ensure feature branch is up to date with develop
git checkout develop
git pull origin develop
git checkout feature/your-feature-name
git merge develop

# 2. Resolve any conflicts if they exist
# 3. Push updated feature branch
git push origin feature/your-feature-name

# 4. Create a Pull Request on GitHub
#    - From: feature/your-feature-name
#    - To: develop
#    - Request code review
#    - Ensure CI/CD passes

# 5. After PR approval, merge and delete feature branch
git checkout develop
git pull origin develop
git branch -d feature/your-feature-name
git push origin --delete feature/your-feature-name
```

### Creating a Release

```bash
# 1. Ensure develop is ready for release
git checkout develop
git pull origin develop

# 2. Create a Pull Request on GitHub
#    - From: develop
#    - To: main
#    - Include release notes

# 3. After PR approval and merge
git checkout main
git pull origin main
git tag -a v1.0.0 -m "Release version 1.0.0"
git push origin v1.0.0

# 4. Merge back to develop if any hotfixes were made
git checkout develop
git merge main
git push origin develop
```

### Hotfixes (Emergency Production Fixes)

```bash
# 1. Create hotfix branch from main
git checkout main
git pull origin main
git checkout -b hotfix/critical-bug-fix

# 2. Make the fix and commit
git add .
git commit -m "fix: critical bug description"

# 3. Create PR to main
git push -u origin hotfix/critical-bug-fix
# Create PR: hotfix/critical-bug-fix → main

# 4. After merge, also merge to develop
git checkout develop
git merge hotfix/critical-bug-fix
git push origin develop

# 5. Delete hotfix branch
git branch -d hotfix/critical-bug-fix
git push origin --delete hotfix/critical-bug-fix
```

## Commit Message Convention

Follow conventional commits format:

- `feat:` - New feature
- `fix:` - Bug fix
- `docs:` - Documentation changes
- `style:` - Code style changes (formatting, etc.)
- `refactor:` - Code refactoring
- `test:` - Adding or updating tests
- `chore:` - Maintenance tasks

Example: `feat: add EC2 instance deployment feature`

## Branch Protection Rules

### Recommended GitHub Settings

**For `main` branch:**
- Require pull request reviews before merging
- Require status checks to pass
- Require branches to be up to date before merging
- Do not allow force pushes
- Do not allow deletions

**For `develop` branch:**
- Require pull request reviews before merging
- Require status checks to pass
- Do not allow force pushes
- Do not allow deletions

## Quick Reference

```bash
# View all branches
git branch -a

# View current branch
git branch --show-current

# Delete local branch
git branch -d branch-name

# Delete remote branch
git push origin --delete branch-name

# Update local branch list
git fetch --prune
```

## Best Practices

1. **Keep feature branches small** - Easier to review and merge
2. **Regularly sync with develop** - Avoid large merge conflicts
3. **Write descriptive commit messages** - Help team understand changes
4. **Use pull requests** - Enable code review and discussion
5. **Delete merged branches** - Keep repository clean
6. **Never commit directly to main or develop** - Always use feature branches
7. **Test before merging** - Ensure CI/CD passes before merge
8. **Tag releases** - Use semantic versioning (v1.0.0)

## Current Branch Status

- `main` - Production branch (protected)
- `develop` - Development branch (protected)

All new work should branch from `develop` and merge back via pull requests.
