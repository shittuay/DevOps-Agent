---
date: 2026-10-01
type: decision
tags: [marketing, growth, compliance]
---

# Marketing agent drafts; a person publishes

The marketing agent (`services/marketing_agent.py`, `/marketing/`) finds public
posts, writes replies/emails/posts, and stops at a review queue. It does not
post to Hacker News, Reddit, LinkedIn or X on its own.

**Why not fully autonomous posting:**
- HN and most subreddits ban or shadowban accounts that post automated or
  undisclosed self-promotion. One ban costs more reach than months of posting gains.
- An LLM writing ads will invent testimonials and statistics. In this codebase
  that is the same failure as fabricated cloud data (see CLAUDE.md "every feature
  runs against a real cloud account"). It is also an FTC deceptive-advertising risk.
  So the copy may only use `PRODUCT_FACTS`, and `check_compliance()` flags
  anything else. Approving a flagged draft requires an explicit acknowledgement.
- Cold email needs an unsubscribe link and a postal address (CAN-SPAM), plus a
  lawful basis under GDPR. So the agent never collects addresses. A person enters
  each recipient, sending refuses without `MARKETING_POSTAL_ADDRESS`, and
  unsubscribes go into `MarketingSuppression`.

Only `email` drafts are sent by the app. Everything else is copied out and
marked "posted" by hand.
