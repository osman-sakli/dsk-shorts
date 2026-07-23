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
import json
import os
import pathlib
import subprocess
import sys

import boto3
import requests

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

# upload-post.com has no "made for kids" / COPPA field (confirmed against their
# docs) — YouTube is deliberately excluded from auto-publish and flagged for
# manual upload instead of silently skipping the COPPA declaration.
# Facebook isn't connected on the upload-post.com "DSK" profile yet — add it
# back to this list once it's connected there.
AUTO_PLATFORMS = ["tiktok", "instagram"]
MANUAL_REVIEW_PLATFORMS = ["youtube", "facebook"]

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


def make_caption(script):
    title = script.get("title", script["id"])
    hook = script["lines"][0]["text"].rstrip("—- ")
    return (
        f"{hook} \U0001f6e1️ {title}\n"
        f"Play today's quest → {SITE_URL}\n"
        f"#onlinesafety #digitalsafety #parentingtips #kidsonline"
    )


def make_thumbnail(mp4_path, out_path):
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(mp4_path), "-ss", "00:00:01", "-vframes", "1", str(out_path)],
        check=True,
        capture_output=True,
    )


def upload_to_s3(local_path, key):
    s3.upload_file(str(local_path), OUTPUT_BUCKET, key)


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


def main():
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

    print(f"Day {day}: rendering {script_id}")
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
    thumb_path = ROOT / "out" / f"{script_id}.jpg"
    make_thumbnail(mp4_path, thumb_path)

    caption = make_caption(script)
    caption_path = ROOT / "out" / f"{script_id}.caption.json"
    caption_path.write_text(json.dumps({"scriptId": script_id, "day": day, "caption": caption}, indent=2))

    date_prefix = datetime.date.today().isoformat()
    upload_to_s3(mp4_path, f"{date_prefix}/{script_id}.mp4")
    upload_to_s3(thumb_path, f"{date_prefix}/{script_id}.jpg")
    upload_to_s3(caption_path, f"{date_prefix}/{script_id}.caption.json")

    result = publish_to_platforms(mp4_path, script.get("title", script_id), caption)
    result["manual_review"] = (
        f"{', '.join(MANUAL_REVIEW_PLATFORMS)} need manual upload (YouTube: no COPPA "
        f"'made for kids' field in the API; Facebook: not yet connected on upload-post.com). "
        f"File: {date_prefix}/{script_id}.mp4 in s3://{OUTPUT_BUCKET}"
    )
    record_queue_status(script_id, day, result["status"], json.dumps(result))
    print(f"Day {day} ({script_id}): {result['status']} — {result['manual_review']}")

    if result["status"] == "failed":
        # Don't advance the day index — the video is already safe in S3, and
        # this leaves it to be retried on tomorrow's run instead of silently
        # skipped (e.g. a bad profile name or a transient API error).
        alert_failure(f"DSK Shorts publish failed: {script_id}", json.dumps(result))
        sys.exit(1)

    advance_day_index(day)


if __name__ == "__main__":
    main()
