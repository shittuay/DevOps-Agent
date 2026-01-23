# GitHub Secrets Setup Guide

## Required Secrets for Deployment

Go to: https://github.com/shittuay/DevOps-Agent/settings/secrets/actions

Click "New repository secret" and add each of the following:

---

### 1. **EC2_HOST**
- **Name**: `EC2_HOST`
- **Value**: `3.91.154.244`

---

### 2. **EC2_USERNAME**
- **Name**: `EC2_USERNAME`
- **Value**: `ec2-user`

> **Note**: If your EC2 instance uses Ubuntu, use `ubuntu` instead of `ec2-user`

---

### 3. **EC2_SSH_KEY** ⚠️ IMPORTANT
- **Name**: `EC2_SSH_KEY`
- **Value**: The **ENTIRE** contents of `my-keypair.pem` file

**How to get the value:**
1. Open `my-keypair.pem` in a text editor (Notepad, VSCode, etc.)
2. Copy the ENTIRE content including:
   - `-----BEGIN RSA PRIVATE KEY-----`
   - All the lines in between
   - `-----END RSA PRIVATE KEY-----`
3. Paste it into GitHub secrets

**Important**: Make sure there are no extra spaces or characters

---

### 4. **ANTHROPIC_API_KEY** ⚠️ REQUIRED
- **Name**: `ANTHROPIC_API_KEY`
- **Value**: Your Anthropic API key from https://console.anthropic.com/

**Format**: Should look like `sk-ant-api03-xxxxxxxxxxxxx`

---

### 5. **SECRET_KEY** ⚠️ REQUIRED
- **Name**: `SECRET_KEY`
- **Value**: A randomly generated secret key

**How to generate:**

**Option 1 - Using Python:**
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

**Option 2 - Using OpenSSL:**
```bash
openssl rand -hex 32
```

**Option 3 - Online Generator:**
- Go to: https://randomkeygen.com/
- Copy a "Fort Knox Password" (504 bits)

---

## How to Add Secrets

1. Go to your repository: https://github.com/shittuay/DevOps-Agent
2. Click **Settings** → **Secrets and variables** → **Actions**
3. Click **"New repository secret"**
4. Enter the **Name** and **Value**
5. Click **"Add secret"**
6. Repeat for each secret

---

## Verify Secrets Are Set

After adding all secrets, you should see:
- ✅ EC2_HOST
- ✅ EC2_USERNAME
- ✅ EC2_SSH_KEY
- ✅ ANTHROPIC_API_KEY
- ✅ SECRET_KEY

---

## Trigger Deployment

Once all secrets are configured:

### Option 1: Push a commit
```bash
git commit --allow-empty -m "Trigger deployment"
git push origin main
```

### Option 2: Manual trigger
1. Go to: https://github.com/shittuay/DevOps-Agent/actions
2. Click "Deploy to EC2" workflow
3. Click "Run workflow" button
4. Select branch: `main`
5. Click green "Run workflow" button

---

## Check Deployment Status

1. Go to: https://github.com/shittuay/DevOps-Agent/actions
2. Click on the latest "Deploy to EC2" workflow run
3. Watch the logs in real-time
4. Look for "✅ Deployment completed successfully!"

---

## Access Your Application

After successful deployment:

- **Direct IP**: http://3.91.154.244:5000
- **Domain** (after DNS setup): http://devopsagent.io

---

## Troubleshooting

### "ssh: no key found" error
- Make sure you copied the **entire** SSH key including BEGIN and END lines
- Check for no extra spaces or characters

### "Authentication failed" error
- Verify EC2_USERNAME is correct (`ec2-user` or `ubuntu`)
- Verify the SSH key matches the one attached to your EC2 instance

### "ANTHROPIC_API_KEY not found" error
- Make sure you added the ANTHROPIC_API_KEY secret
- Verify the API key is valid at https://console.anthropic.com/

---

## Security Notes

⚠️ **NEVER** commit these values to your repository
⚠️ Keep your SSH keys and API keys secure
⚠️ Rotate secrets regularly (every 90 days)
