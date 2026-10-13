# Moving the platform to a new AWS account

Old account: `188046727805` (instance `i-09af962714b13f9bc`, us-east-1).
New account: `621203631557`. Placeholders below: `NEW_INSTANCE` (new EC2 id),
`NEW_IP` (new Elastic IP).

The code defaults already point at the new account in the cutover PR
(#236, branch `chore/aws-cutover-621203631557`, opened as a draft). **Merge that PR at
step 7, not before**: it switches
the onboarding trust snippet, the quick-create template URL and the deploy role to the new
account, all of which must exist first.

Do the steps in order. Nothing customer-facing changes until **Cutover** (step 7);
everything before it can be built and tested while the old account keeps serving.

---

## 0. Before you start

**Find out who will break.** Customers who connected AWS with an **IAM role** trust
account `188046727805` by id. When the app moves, AWS denies those calls unless the
customer updates their trust policy, or you run the migration bridge (step 6).
Customers who connected with **access keys** are unaffected.

On the current box:

```bash
cd /var/www/devops-agent && source venv/bin/activate
python scripts/count_role_arn_customers.py
```

- `0` role connections: skip step 6 and the customer email.
- Any role connections: do step 6, and keep the old account open until they move.

**Things that must not change:**

| Value | Why |
|---|---|
| `CREDENTIAL_ENCRYPTION_KEY` (and `SECRET_KEY`) | Every saved cloud credential is encrypted with it. A new value makes all of them unreadable. |
| Postgres data | Users, conversations, credentials, billing state. |
| Domain `devopsagent.io` | Stripe webhooks, OAuth callbacks and email links all point at it. |

## 1. New account baseline

1. Turn on MFA for the root user. Create an admin identity for daily use.
2. Set a billing budget and alert.
3. Stay in **us-east-1** unless you mean to move regions too. The workflows read
   `AWS_REGION` and default to us-east-1.

## 2. Server

1. Launch an Ubuntu instance like the old one: same size, an Elastic IP (`NEW_IP`)
   and a security group that allows 80/443 from Cloudflare plus 22 from your IP only.

   **If it's a Spot instance:** Postgres lives on this box, and AWS can reclaim Spot
   capacity with about two minutes' notice. By default a reclaimed instance is
   terminated and its root disk deleted, database included. Set up all of these:
   - request type **persistent** with interruption behavior **Stop** (Stop requires a
     persistent request), so a reclaim stops the box and the disk survives
   - **Delete on termination off** for the root volume
   - the Elastic IP attached, so the address is unchanged after a stop/start
   - the nightly `pg_dump` to S3 working before any users move over

   The site is down for as long as Spot capacity stays away. If that isn't acceptable for
   the one box every user hits, use On-Demand with a Savings Plan or Reserved Instance, or
   move the database to RDS so the box itself becomes disposable.
2. Create an instance role. List what the old role has and recreate it:

   ```bash
   # in the OLD account
   aws iam list-attached-role-policies --role-name devops-agent-ssm-role
   aws iam list-role-policies --role-name devops-agent-ssm-role
   aws iam get-role-policy --role-name devops-agent-ssm-role --policy-name <name>
   ```

   At minimum the new role needs:
   - `AmazonSSMManagedInstanceCore`, so GitHub deploys can run commands over SSM
   - `secretsmanager:GetSecretValue` on `devops-agent/production*`
   - `sts:AssumeRole` on `arn:aws:iam::*:role/*`, to assume customer roles and the bridge
   - the S3 backup permissions (inline policy `devops-agent-db-backup-s3`), pointed at the
     new backup bucket
3. Install the stack the same way as the old box: Postgres 14 or newer, Python venv,
   nginx, and the `devops-agent.service` unit with `--config gunicorn.conf.py`. Copy the
   nginx site config from `/etc/nginx` and any Cloudflare origin certificate.
4. Make a **new** read-only GitHub deploy key for the new box (repo → Settings →
   Deploy keys). Save it as `/home/ubuntu/.ssh/deploy_key` and clone into
   `/var/www/devops-agent`.

## 3. Secrets and config

1. Copy the app secret into the new account:

   ```bash
   # OLD account
   aws secretsmanager get-secret-value --secret-id devops-agent/production \
     --query SecretString --output text > prod-secret.json
   # NEW account
   aws secretsmanager create-secret --name devops-agent/production \
     --secret-string file://prod-secret.json
   shred -u prod-secret.json
   ```

2. Copy `/var/www/devops-agent/.env` to the new box over SSH; don't put it in git or
   chat. Then change:
   - `PLATFORM_AWS_ACCOUNT_ID=621203631557`
   - `CF_TEMPLATE_URL=` the new template URL (step 5)
   - `BACKUP_S3_BUCKET` / `BACKUP_S3_BUCKET_OWNER` for the new backup bucket
   - `PLATFORM_BRIDGE_ROLE_ARN` only if you use step 6
3. Check `CREDENTIAL_ENCRYPTION_KEY` matches the old box character for character.

## 4. GitHub deploys (OIDC)

1. In the new account: IAM → Identity providers → Add provider → OpenID Connect,
   URL `https://token.actions.githubusercontent.com`, audience `sts.amazonaws.com`.
2. Create role `github-actions-deploy` with this trust policy:

   ```json
   {
     "Version": "2012-10-17",
     "Statement": [{
       "Effect": "Allow",
       "Principal": {"Federated": "arn:aws:iam::621203631557:oidc-provider/token.actions.githubusercontent.com"},
       "Action": "sts:AssumeRoleWithWebIdentity",
       "Condition": {
         "StringEquals": {"token.actions.githubusercontent.com:aud": "sts.amazonaws.com"},
         "StringLike": {"token.actions.githubusercontent.com:sub": "repo:shittuay/DevOps-Agent:*"}
       }
     }]
   }
   ```

   Permissions: `ssm:SendCommand` on `NEW_INSTANCE` and on the `AWS-RunShellScript`
   document, plus `ssm:GetCommandInvocation`.
3. Leave the GitHub settings until cutover. Switching them early would send deploys to
   the new box while users are still on the old one.

## 5. CloudFormation quick-create template

Customers create their role from this template, and its trust policy names the platform
account. Bucket names are global and the old bucket still holds the name, so use a new
one:

```bash
# cloudformation/devops-agent-role.json in the cutover PR is already rebuilt for 621203631557;
# check out that branch to get it.
aws s3 mb s3://devopsagent-cf-templates-621203631557
# New buckets block public access by default. Turn that off for this bucket only and
# add a bucket policy allowing s3:GetObject on this one key (quick-create needs a
# public S3 URL). Then:
aws s3 cp cloudformation/devops-agent-role.json s3://devopsagent-cf-templates-621203631557/devops-agent-role.json
```

The cutover PR already defaults `CF_TEMPLATE_URL` to
`https://devopsagent-cf-templates-621203631557.s3.amazonaws.com/devops-agent-role.json`. If
you name the bucket differently, set `CF_TEMPLATE_URL` on the new box instead.

## 6. Migration bridge (only if step 0 found role customers)

This keeps existing customer roles working with no action from customers, while they
update their trust policies in their own time.

1. In the **old** account, create role `devops-agent-migration-bridge`:
   - Trust: the new instance role,
     `{"Principal": {"AWS": "arn:aws:iam::621203631557:role/<new-instance-role>"}, "Action": "sts:AssumeRole"}`
   - Permission: `sts:AssumeRole` on `arn:aws:iam::*:role/*`
2. On the new box, set
   `PLATFORM_BRIDGE_ROLE_ARN=arn:aws:iam::188046727805:role/devops-agent-migration-bridge`.

How it works (`services/credential_service._assume_role`): the app tries the customer
role directly first. Only if AWS denies it does the app assume the bridge in the old
account and try again from there. The customer's External ID is still sent and still
checked. Chained sessions last at most one hour, which is what the app already requests.
Every bridged call logs `assumed via migration bridge`, naming the customer role that
still needs updating.

The old account must stay open while the bridge is in use.

**Customer message** (send when you cut over):

> We've moved DevOps Agent to a new AWS account. Your connection keeps working for now.
> Before <date>, please update the trust policy on your DevOps Agent IAM role so the
> `Principal` includes `arn:aws:iam::621203631557:root` (keep or remove the old
> `arn:aws:iam::188046727805:root`). Your External ID stays the same.
>
> If you created the role with our CloudFormation button, one command does it:
>
> ```
> aws cloudformation update-stack --stack-name YOUR_STACK_NAME \
>   --template-url https://devopsagent-cf-templates-621203631557.s3.amazonaws.com/devops-agent-role.json \
>   --parameters ParameterKey=ExternalId,UsePreviousValue=true ParameterKey=PolicyLevel,UsePreviousValue=true ParameterKey=RoleName,UsePreviousValue=true \
>   --capabilities CAPABILITY_NAMED_IAM
> ```

That updates the role's trust policy in place, so its ARN and External ID stay the same and
nothing changes in DevOps Agent's settings. Deleting the stack and recreating it would give
the role a new ARN, which the customer would then have to paste back into Settings.
`RoleName,UsePreviousValue=true` matters: `RoleName` is a template parameter, and leaving
it out resets a custom name to the default, which replaces the role (new ARN).

## 7. Cutover (short maintenance window)

1. Lower the Cloudflare DNS TTL a day ahead if the record isn't proxied.
2. Stop writes on the old box, then dump:

   ```bash
   # OLD box
   sudo systemctl stop devops-agent
   sudo -u postgres pg_dump -Fc devops_agent > /tmp/devops_agent.dump
   ```

3. Copy it through your own machine (both boxes allow SSH from your IP):

   ```bash
   scp old-box:/tmp/devops_agent.dump . && scp devops_agent.dump new-box:/tmp/
   ```

4. Restore on the new box, into the database and user named in its `DATABASE_URL`:

   ```bash
   sudo -u postgres pg_restore --no-owner --role=<db_user> -d devops_agent /tmp/devops_agent.dump
   sudo systemctl start devops-agent
   ```

5. Point Cloudflare's `devopsagent.io` record at `NEW_IP`.
6. Switch GitHub to the new account:

   ```bash
   gh variable set AWS_DEPLOY_ROLE_ARN --body arn:aws:iam::621203631557:role/github-actions-deploy
   gh variable set AWS_REGION --body us-east-1
   gh secret set EC2_INSTANCE_ID --body NEW_INSTANCE
   ```

   Then merge the cutover PR (`chore/aws-cutover-621203631557`). Its first deploy goes to
   the new box.

7. Delete the dump file from both boxes and your machine. It contains every user's
   encrypted credentials.

**Rollback:** until users write data on the new box, point DNS back at the old IP,
`systemctl start devops-agent` on the old box, and unset the two GitHub variables.
After that point, rolling back loses whatever was written on the new box.

## 8. Verify

- `https://devopsagent.io` loads, you can log in, and a chat turn works.
- On the new box, `python scripts/count_role_arn_customers.py` shows **0 unreadable**.
  Anything else means the encryption key didn't carry over; stop and fix it.
- A role-based customer (or a test role of yours that trusts the old account) can list
  EC2 instances. With the bridge on, `journalctl -u devops-agent | grep "migration bridge"` shows it.
- Push a trivial PR to main and confirm the deploy job goes green.
- `/settings` shows the new account id in the trust snippet, and the CloudFormation
  button opens the new template.
- The next scheduled backup lands in the new bucket.

## 9. After cutover

- With the cutover PR merged, the code defaults match the new account, so the
  `AWS_DEPLOY_ROLE_ARN` / `AWS_REGION` variables can stay or be removed.
- Watch the bridge log line. When it has been quiet for a couple of weeks and the
  deadline has passed, unset `PLATFORM_BRIDGE_ROLE_ARN` and delete the bridge role.
- Decommission the old account last: snapshot or export anything you want to keep,
  terminate the old instance, release its Elastic IP, delete its buckets and secret,
  then close the account.
