---
date: 2026-11-15
type: postmortem
tags: [organizations, invitations, security, scheduled-review]
---
# Organization invitations never worked

The invite flow stored a pending invite as an `OrganizationMember` row with `user_id=None`,
but that column is `NOT NULL`. Every invite raised, so no organization ever gained a member,
and the flagged security issues (join on GET, no email binding, owner via invite) sat on code
that could not run. The bug was invisible because the page never rendered flash messages and
nobody had a second account to invite.

Why a separate table instead of making `user_id` nullable: auto-migration only adds columns,
it never changes nullability, so the existing Postgres column would have stayed NOT NULL. A new
table is created by `db.create_all()` with no manual migration.

Lesson: a "still open" security item on a feature should first be checked for whether the
feature works at all; a broken happy path hides both the bug and the risk.

Related: [[INDEX]]
