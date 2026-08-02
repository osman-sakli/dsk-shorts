# Publishing notes

**Correction from an earlier version of this doc:** TikTok, Instagram,
YouTube, and (as of 2026-08-01, page "Dig Knights") Facebook posting are all
fully automated — `pipeline/entrypoint.py` renders the daily video and posts
it to all four via upload-post.com (`AUTO_PLATFORMS`), on the
`infra/eventbridge.tf` daily Fargate cron. `MANUAL_REVIEW_PLATFORMS` is empty
for now; nothing needs manual posting.

A one-time backfill (`infra/facebook_backfill.tf` +
`pipeline/facebook_backfill_lambda/`) is separately posting the 6 AI-path
videos that went out before Facebook was connected (ai-001..ai-006) to
Facebook too, one every 4 hours via its own EventBridge rule — done
automatically, no action needed. **Tear this down** (delete
`infra/facebook_backfill.tf` and the lambda folder, `terraform apply`) once
`FACEBOOK_BACKFILL_STATE.nextIndex` in DynamoDB reaches 6 (all posted).

## Why zero views is normal at first, and what actually fixes it

A brand-new account with 0 followers and 0 following gets no algorithmic
distribution — the platform has no signal yet for who to show your video to,
and an account that isn't following/commenting on anyone else in the niche
gets no reciprocal reach either. This is a cold-start problem, not a content
or automation problem. What moves it:

1. **Engage from the actual account, daily.** This is the one thing the
   pipeline can't do for you: 10-15 min/day following and leaving a real
   comment on 5-10 accounts in the parenting/online-safety niche. This is
   what gets a new account onto people's radar.
2. **Hashtags now rotate by content category** instead of being the same
   four tags on every post (fixed in `entrypoint.py`'s `build_hashtags()`):
   scam/predator-tactic scripts (Glitch present) get scam-alert tags,
   AI-themed scripts (Bot present) get AI-safety tags, everything else gets
   general parenting tags — each paired with a rotating broad tag
   (`#onlinesafety`/`#digitalsafety`) so posts don't look identical.
3. Give it real time before judging: expect near-zero for the first
   ~1-2 weeks of consistent daily posts + daily engagement, then watch for
   the first video that breaks out — that's the signal for what hook/topic
   to lean into next.

## Manual account-growth checklist (applies regardless of automation)

- [ ] Followed/commented on 5-10 niche accounts today, before checking
      today's video's stats
- [ ] Confirmed today's auto-post actually went out (check
      `DAY#NN#<date>` / `AI_STATE` items in the DynamoDB queue table, or the
      SNS failure alert inbox — silence means it worked)

## Automation status
✅ TikTok, Instagram, YouTube, Facebook — automated via upload-post.com (`entrypoint.py`)
✅ Discord, LinkedIn — automated (`discord_post.py`, `linkedin_lambda/`)
✅ Facebook backfill (ai-001..ai-006) — automated one-time job, tear down once done
