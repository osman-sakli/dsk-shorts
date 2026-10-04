#!/usr/bin/env python3
"""Daily video factory task: render today's short, upload to S3, publish, record status.

Runs once per day inside the Fargate task (EventBridge cron). Day index is
persisted in DynamoDB so the task is stateless between runs.

Env vars (set by the ECS task definition, values sourced from Secrets Manager):
  OUTPUT_BUCKET     - S3 bucket for rendered mp4/thumbnail/caption
  QUEUE_TABLE       - DynamoDB table name for publish-queue + day-index state
  UPLOAD_API_KEY    - upload-post.com API key (optional; skips publish if absent)
  UPLOAD_POST_PROFILE - upload-post.com managed-user profile name to post as
  GITHUB_TOKEN      - repo-scoped token, used only to open "need new scripts" issues
  GITHUB_REPO       - "owner/repo" for the issue above (default osman-sakli/dsk-shorts)
  SNS_ALERT_TOPIC_ARN - optional; publish a message here on failure
"""
import datetime
import hashlib
import json
import os
import pathlib
import subprocess
import sys

import boto3
import requests

import fal_video

ROOT = pathlib.Path(__file__).resolve().parents[1]
SITE_URL = "https://digitalsafetyknights.org"
CALENDAR_LEN = 30

OUTPUT_BUCKET = os.environ["OUTPUT_BUCKET"]
QUEUE_TABLE = os.environ["QUEUE_TABLE"]
UPLOAD_API_KEY = os.environ.get("UPLOAD_API_KEY")
UPLOAD_POST_PROFILE = os.environ.get("UPLOAD_POST_PROFILE", "dsk")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "osman-sakli/dsk-shorts")
SNS_ALERT_TOPIC_ARN = os.environ.get("SNS_ALERT_TOPIC_ARN")

# upload-post.com has no per-video "made for kids" / COPPA field, but the
# Digital Safety Knights YouTube channel has "Made for Kids" set at the
# channel level (confirmed with the owner) — every upload inherits that
# designation, so YouTube is safe to include here.
# Facebook connected on the upload-post.com "DSK" profile 2026-08-01 (page:
# "Dig Knights") — moved from manual to auto.
AUTO_PLATFORMS = ["tiktok", "instagram", "youtube", "facebook"]
MANUAL_REVIEW_PLATFORMS = []

dynamodb = boto3.resource("dynamodb")
s3 = boto3.client("s3")
sns = boto3.client("sns") if SNS_ALERT_TOPIC_ARN else None


def get_next_day_index():
    table = dynamodb.Table(QUEUE_TABLE)
    resp = table.get_item(Key={"pk": "STATE"})
    last = resp.get("Item", {}).get("lastDayIndex", 0)
    return (int(last) % CALENDAR_LEN) + 1


def advance_day_index(day):
    dynamodb.Table(QUEUE_TABLE).put_item(Item={"pk": "STATE", "lastDayIndex": day})


def record_queue_status(script_id, day, status, detail=""):
    dynamodb.Table(QUEUE_TABLE).put_item(
        Item={
            "pk": f"DAY#{day:02d}#{datetime.date.today().isoformat()}",
            "date": datetime.date.today().isoformat(),
            "scriptId": script_id or "MISSING",
            "status": status,
            "detail": detail,
        }
    )


def open_github_issue(title, body):
    if not GITHUB_TOKEN:
        print(f"[warn] no GITHUB_TOKEN set, would have opened issue: {title}")
        return
    try:
        r = requests.post(
            f"https://api.github.com/repos/{GITHUB_REPO}/issues",
            headers={
                "Authorization": f"Bearer {GITHUB_TOKEN}",
                "Accept": "application/vnd.github+json",
            },
            json={"title": title, "body": body},
            timeout=15,
        )
        r.raise_for_status()
    except requests.RequestException as e:
        # A broken/placeholder token shouldn't crash the task — the day still
        # gets recorded as "no_script" below, just without the GitHub issue.
        print(f"[warn] failed to open GitHub issue ({e}); title was: {title}")


def alert_failure(subject, message):
    print(f"[alert] {subject}: {message}", file=sys.stderr)
    if sns:
        sns.publish(TopicArn=SNS_ALERT_TOPIC_ARN, Subject=subject[:100], Message=message)


# Broad tags (#onlinesafety, #digitalsafety) are heavily saturated by large
# existing accounts and don't help a new/small account get discovered on
# their own. Pairing one with a set of smaller niche tags — rotated by
# content category so every post isn't the same four hashtags — gives the
# algorithm a more specific, less-crowded audience to test the video against.
BROAD_TAGS = ["#onlinesafety", "#digitalsafety"]
NICHE_TAGS_BY_CATEGORY = {
    # GLITCH present (without BOT) — scam/predator-tactic content
    "scam": ["#scamalert", "#internetsafety", "#protectyourkids", "#parentsoftiktok"],
    # BOT present — AI-safety / media-literacy content
    "ai": ["#aisafety", "#medialiteracy", "#parentingintheAIage", "#factcheck"],
    # everything else — general parenting-tip / knight-rule content
    "general": ["#parentingtips", "#screentimetips", "#digitalparenting", "#familysafety"],
}


def _script_characters(script):
    """Works for both content shapes: ai-scripts.json's explicit "characters"
    list, and the older scripts/*.json's per-line "who" speaker field."""
    if "characters" in script:
        return {c.lower() for c in script["characters"]}
    return {line.get("who", "").lower() for line in script.get("lines", [])}


def categorize_script(script):
    chars = _script_characters(script)
    if "bot" in chars:
        return "ai"
    if "glitch" in chars:
        return "scam"
    return "general"


def build_hashtags(script):
    category = categorize_script(script)
    niche = NICHE_TAGS_BY_CATEGORY[category]
    # Deterministic (not random) so re-running the same script_id is stable,
    # but different scripts land on a different broad tag for variety.
    digest = int(hashlib.sha256(script["id"].encode()).hexdigest(), 16)
    broad = BROAD_TAGS[digest % len(BROAD_TAGS)]
    return " ".join([broad] + niche)


def make_caption(script):
    title = script.get("title", script["id"])
    hook = script["lines"][0]["text"].rstrip("—- ")
    return (
        f"{hook} \U0001f6e1️ {title}\n"
        f"Play today's quest → {SITE_URL}\n"
        f"{build_hashtags(script)}"
    )


def make_thumbnail(mp4_path, out_path):
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(mp4_path), "-ss", "00:00:01", "-vframes", "1", str(out_path)],
        check=True,
        capture_output=True,
    )


def upload_to_s3(local_path, key):
    s3.upload_file(str(local_path), OUTPUT_BUCKET, key)


def find_existing_render(script_id):
    """Newest already-rendered s3 key for this script_id (date-prefixed keys
    sort chronologically as strings), or None if it has never been rendered.

    Reposting an existing render costs nothing. Regenerating a script that's
    already in S3 pays fal.ai again (~$14/short) for a video that already
    exists — with only 36 scripts in the rotation and one render per day,
    the round-robin index was wrapping back to script #1 every 36 days and
    silently re-buying videos that were sitting in this same bucket. This
    check is what makes a repost the default from the second time a given
    script_id comes up; only a script's first-ever turn pays for generation.
    """
    try:
        paginator = s3.get_paginator("list_objects_v2")
        newest = None
        suffix = f"/{script_id}.mp4"
        for page in paginator.paginate(Bucket=OUTPUT_BUCKET):
            for obj in page.get("Contents", []):
                if obj["Key"].endswith(suffix) and (newest is None or obj["Key"] > newest):
                    newest = obj["Key"]
        return newest
    except Exception as e:  # noqa: BLE001 — a listing hiccup shouldn't block posting
        # Falling through to "generate" here means this exact failure (e.g.
        # a missing s3:ListBucket permission) pays fal.ai again every single
        # day instead of once — that happened silently for 4 days (2026-10-01
        # through 10-04) before anyone noticed. alert_failure() makes sure a
        # repeat of this is loud, not just a buried [warn] print.
        alert_failure(
            f"DSK Shorts: existence check failed for {script_id}, generating anyway",
            f"find_existing_render({script_id}) raised: {e}\n\n"
            f"This means today's run will pay fal.ai even if {script_id} is "
            f"already in s3://{OUTPUT_BUCKET} — check the task role's S3 permissions.",
        )
        return None


def publish_to_platforms(mp4_path, title, caption):
    if not UPLOAD_API_KEY:
        print("[warn] no UPLOAD_API_KEY set, skipping publish (video stays in S3 only)")
        return {"status": "skipped_no_key", "platforms": []}
    with open(mp4_path, "rb") as f:
        resp = requests.post(
            "https://api.upload-post.com/api/upload",
            headers={"Authorization": f"Apikey {UPLOAD_API_KEY}"},
            files={"video": f},
            data={
                "title": title,
                "caption": caption,
                "user": UPLOAD_POST_PROFILE,
                "platform[]": AUTO_PLATFORMS,
                # TikTok kept landing in the account inbox with no public URL,
                # so the intent is now stated explicitly rather than relying on
                # the API default. If TikTok still holds it as a draft, that is
                # its unaudited-client rule (such clients may only post
                # SELF_ONLY) and no amount of retrying changes it — the API
                # client has to pass TikTok's audit.
                "post_mode": "DIRECT_POST",
                "privacy_level": "PUBLIC_TO_EVERYONE",
                # These shorts are generated with Seedance. TikTok requires
                # AI-generated content to be disclosed, and labelling it here
                # is both the honest and the safer option for the account.
                "is_aigc": "true",
            },
            timeout=300,
        )
    status = "published" if resp.ok else "failed"
    return {
        "status": status,
        "platforms": AUTO_PLATFORMS,
        "http_status": resp.status_code,
        "body": resp.text[:500],
    }


def finish_and_publish(script_id, day, mp4_path, title, caption):
    """Shared tail end for both paths: thumbnail, S3 upload, publish, status.
    Caller advances its own state counter only after this returns (i.e. only
    on success — this exits the process on failure)."""
    thumb_path = ROOT / "out" / f"{script_id}.jpg"
    make_thumbnail(mp4_path, thumb_path)

    caption_path = ROOT / "out" / f"{script_id}.caption.json"
    caption_path.write_text(json.dumps({"scriptId": script_id, "day": day, "caption": caption}, indent=2))

    date_prefix = datetime.date.today().isoformat()
    upload_to_s3(mp4_path, f"{date_prefix}/{script_id}.mp4")
    upload_to_s3(thumb_path, f"{date_prefix}/{script_id}.jpg")
    upload_to_s3(caption_path, f"{date_prefix}/{script_id}.caption.json")

    result = publish_to_platforms(mp4_path, title, caption)
    if MANUAL_REVIEW_PLATFORMS:
        result["manual_review"] = (
            f"{', '.join(MANUAL_REVIEW_PLATFORMS)} need manual upload "
            f"(not yet connected on upload-post.com). "
            f"File: {date_prefix}/{script_id}.mp4 in s3://{OUTPUT_BUCKET}"
        )
    else:
        result["manual_review"] = "none — all platforms auto-published"
    record_queue_status(script_id, day, result["status"], json.dumps(result))
    print(f"Day {day} ({script_id}): {result['status']} — {result['manual_review']}")

    if result["status"] == "failed":
        # Don't advance state — the video is already safe in S3, and this
        # leaves it to be retried next time instead of silently skipped
        # (e.g. a bad profile name or a transient API error).
        alert_failure(f"DSK Shorts publish failed: {script_id}", json.dumps(result))
        sys.exit(1)


def run_remotion_path():
    """Even calendar days: the original Polly + Remotion cartoon pipeline."""
    calendar = json.loads((ROOT / "content/calendar-30day.json").read_text())
    day = get_next_day_index()
    entry = next((e for e in calendar if e["day"] == day), None)
    script_id = entry.get("scriptId") if entry else None

    if not script_id:
        topic = f"{entry['format']}: {entry['topic']}" if entry else "unknown"
        open_github_issue(
            title=f"DSK Shorts: need script for calendar day {day}",
            body=(
                f"Calendar day {day} ('{topic}') has no `scriptId` yet.\n\n"
                f"Add `content/scripts/0XX-*.json` for it and set `scriptId` "
                f"in `content/calendar-30day.json`."
            ),
        )
        record_queue_status(None, day, "no_script", topic)
        advance_day_index(day)
        print(f"Day {day}: no script mapped yet, issue opened, skipping render.")
        return

    print(f"Day {day}: rendering {script_id} (Remotion path)")
    script_path = ROOT / "content/scripts" / f"{script_id}.json"
    script = json.loads(script_path.read_text())

    try:
        subprocess.run([sys.executable, "pipeline/tts.py", str(script_path)], check=True, cwd=ROOT)
        subprocess.run(["bash", "pipeline/render.sh", script_id], check=True, cwd=ROOT)
    except subprocess.CalledProcessError as e:
        alert_failure(f"DSK Shorts render failed: {script_id}", str(e))
        record_queue_status(script_id, day, "render_failed", str(e))
        sys.exit(1)

    mp4_path = ROOT / "out" / f"{script_id}.mp4"
    caption = make_caption(script)
    finish_and_publish(script_id, day, mp4_path, script.get("title", script_id), caption)
    advance_day_index(day)


def run_ai_path():
    """Odd calendar days: fal.ai Seedance 2.0 reference-to-video with the
    permanent character cast (Shieldy, Pixel, Glitch, Bot, Dame Noble, Sprout)."""
    scripts = json.loads((ROOT / "content/ai-scripts.json").read_text())
    resp = dynamodb.Table(QUEUE_TABLE).get_item(Key={"pk": "AI_STATE"})
    last = int(resp.get("Item", {}).get("lastIndex", -1))
    index = (last + 1) % len(scripts)
    script = scripts[index]
    script_id = script["id"]
    day = datetime.date.today().day

    mp4_path = ROOT / "out" / f"{script_id}.mp4"
    mp4_path.parent.mkdir(parents=True, exist_ok=True)

    existing_key = find_existing_render(script_id)
    if existing_key:
        print(f"Day {day}: reposting existing render of {script_id} "
              f"from s3://{OUTPUT_BUCKET}/{existing_key} (no AI generation, no cost)")
        s3.download_file(OUTPUT_BUCKET, existing_key, str(mp4_path))
    else:
        print(f"Day {day}: generating {script_id} (fal.ai Seedance path — first-ever render)")
        try:
            fal_video.generate_video(script, mp4_path)
        except fal_video.BalanceExhausted as e:
            # Distinct subject line: this one needs Osman to top up, not a retry.
            alert_failure("DSK Shorts STOPPED — fal.ai balance exhausted", str(e))
            record_queue_status(script_id, day, "balance_exhausted", str(e))
            sys.exit(1)
        except requests.RequestException as e:
            alert_failure(f"DSK Shorts AI generation failed: {script_id}", str(e))
            record_queue_status(script_id, day, "generation_failed", str(e))
            sys.exit(1)

    caption = (
        f"{script['title']} \U0001f6e1️\n"
        f"Play today's quest → {SITE_URL}\n"
        f"{build_hashtags(script)}"
    )
    finish_and_publish(script_id, day, mp4_path, script["title"], caption)
    dynamodb.Table(QUEUE_TABLE).put_item(Item={"pk": "AI_STATE", "lastIndex": index})


def main():
    # Was alternating AI (odd days) / Polly+Remotion (even days). The Remotion
    # path also had no scriptId mapped for 20 of its 30 calendar days, so most
    # "even day" runs silently skipped rendering entirely. The AI path posts
    # every day now; run_remotion_path() is left in place but unused.
    run_ai_path()


if __name__ == "__main__":
    main()
