#!/usr/bin/env python3
"""Daily video factory task: render today's short, upload to S3, publish, record status.

Runs once per day inside the Fargate task (EventBridge cron). Day index is
persisted in DynamoDB so the task is stateless between runs.

Env vars (set by the ECS task definition, values sourced from Secrets Manager):
  OUTPUT_BUCKET     - S3 bucket for rendered mp4/thumbnail/caption
  QUEUE_TABLE       - DynamoDB table name for publish-queue + day-index state
  UPLOAD_API_KEY    - upload-post.com API key (optional; skips publish if absent)
  UPLOAD_POST_PROFILE - upload-post.com managed-user profile name to post as
  GITHUB_TOKEN      - repo-scoped token: opens "need new scripts" issues, and
                      (see script_writer.py) commits each new auto-written script
  GITHUB_REPO       - "owner/repo" for the above (default osman-sakli/dsk-shorts)
  SNS_ALERT_TOPIC_ARN - optional; publish a message here on failure
  SITE_BUCKET       - optional; public website S3 bucket (digitalsafetyknights.org)
                      to also receive a copy of each render under shorts/,
                      for frontend/topics.html. Skipped if unset.
"""
import datetime
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys

import boto3
import requests

import fal_video
import script_writer

ROOT = pathlib.Path(__file__).resolve().parents[1]
SITE_URL = "https://digitalsafetyknights.org"
CALENDAR_LEN = 30
# Every this-many runs, write and render a brand-new script (new topic, never
# posted before) instead of pulling the next item off the fixed rotation —
# see script_writer.py and bump_new_script_counter() below. Osman asked for
# new content "every 3 days" on top of the daily repost rotation, so the
# library keeps growing instead of only ever cycling the same fixed set.
NEW_SCRIPT_INTERVAL_DAYS = 3

# Osman, 2026-10-15: pulled the "Hush Now" lullaby content for having nothing
# to do with the actual mission, and asked for a hard refocus — "gelecek
# haftadan itibaren yeni 15 original hiç değinilmemiş ama şu anda ai
# kullanımı ve oyunlarda yaşanan cyberbullying ve diğer digital safety
# konularına odaklan, arada bir eskilerden yayınla" (starting next week,
# focus on 15 new scripts on current AI-safety angles and in-game
# cyberbullying, nothing covered before, with the old rotation mixed in
# occasionally). These 15 (ai-045 through ai-059) take priority over both
# the normal rotation and the new-script-every-3-days feature once the
# window opens; PRIORITY_REPOST_EVERY keeps the "arada bir eskilerden" mix
# alive instead of pausing the old rotation outright.
PRIORITY_START_DATE = datetime.date(2026, 10, 20)
PRIORITY_REPOST_EVERY = 4  # 1 old-rotation day out of every 4 while draining this list
PRIORITY_SCRIPT_IDS = [
    "ai-045-a-video-isnt-a-promise",
    "ai-046-an-app-doesnt-need-your-whole-life",
    "ai-047-tricking-a-filter-doesnt-make-it-okay",
    "ai-048-a-crowd-of-strangers-overnight",
    "ai-049-a-picture-of-words-can-lie-too",
    "ai-050-a-prize-that-asks-first",
    "ai-051-muting-is-not-losing",
    "ai-052-a-pile-on-is-still-bullying",
    "ai-053-knocking-down-what-someone-built",
    "ai-054-you-dont-owe-anyone-a-reaction",
    "ai-055-a-game-name-can-lead-home",
    "ai-056-never-hand-over-the-controller",
    "ai-057-a-code-can-hide-a-door",
    "ai-058-a-hidden-account-is-a-heavy-secret",
    "ai-059-one-call-shouldnt-move-your-key",
]

OUTPUT_BUCKET = os.environ["OUTPUT_BUCKET"]
QUEUE_TABLE = os.environ["QUEUE_TABLE"]
UPLOAD_API_KEY = os.environ.get("UPLOAD_API_KEY")
UPLOAD_POST_PROFILE = os.environ.get("UPLOAD_POST_PROFILE", "dsk")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "osman-sakli/dsk-shorts")
SNS_ALERT_TOPIC_ARN = os.environ.get("SNS_ALERT_TOPIC_ARN")
SITE_BUCKET = os.environ.get("SITE_BUCKET")

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


def bump_new_script_counter():
    """True once every NEW_SCRIPT_INTERVAL_DAYS calls (and resets the count on
    that call) — independent of the fixed-rotation AI_STATE index, so calling
    this never disturbs where the normal rotation is."""
    table = dynamodb.Table(QUEUE_TABLE)
    resp = table.get_item(Key={"pk": "NEW_SCRIPT_STATE"})
    count = int(resp.get("Item", {}).get("count", 0)) + 1
    is_new_script_day = count >= NEW_SCRIPT_INTERVAL_DAYS
    table.put_item(Item={"pk": "NEW_SCRIPT_STATE", "count": 0 if is_new_script_day else count})
    return is_new_script_day


def next_priority_script(scripts):
    """None if the priority window hasn't opened yet (see PRIORITY_START_DATE),
    the list is fully drained, or today lands on one of the periodic
    old-rotation repost days. Otherwise the next script dict in
    PRIORITY_SCRIPT_IDS order, advancing that index in DynamoDB."""
    if datetime.date.today() < PRIORITY_START_DATE:
        return None
    table = dynamodb.Table(QUEUE_TABLE)
    resp = table.get_item(Key={"pk": "PRIORITY_STATE"})
    item = resp.get("Item", {})
    next_idx = int(item.get("nextIndex", 0))
    run_count = int(item.get("runCount", 0)) + 1
    if next_idx >= len(PRIORITY_SCRIPT_IDS):
        return None  # fully drained — normal rotation handles every day from here on

    if run_count % PRIORITY_REPOST_EVERY == 0:
        # An "arada bir eskilerden" day: let the normal rotation take this
        # turn without advancing nextIndex, so the next priority script is
        # still waiting tomorrow.
        table.put_item(Item={"pk": "PRIORITY_STATE", "nextIndex": next_idx, "runCount": run_count})
        return None

    script_id = PRIORITY_SCRIPT_IDS[next_idx]
    script = next((s for s in scripts if s["id"] == script_id), None)
    table.put_item(Item={"pk": "PRIORITY_STATE", "nextIndex": next_idx + 1, "runCount": run_count})
    if script is None:
        print(f"[warn] priority script_id {script_id} not found in ai-scripts.json, skipping it")
    return script


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

# YouTube's backend "tags" field is a different surface than hashtags (plain
# keywords, not shown on-screen, used for search/related-video matching) —
# same category split as NICHE_TAGS_BY_CATEGORY, just without the "#".
YT_TAGS_BY_CATEGORY = {
    "scam": ["online scam alert", "internet safety", "protect your kids online", "stranger danger"],
    "ai": ["ai safety for kids", "media literacy", "parenting in the ai age", "deepfake awareness"],
    "general": ["parenting tips", "screen time tips", "digital parenting", "family internet safety"],
}
YT_BASE_TAGS = ["digital safety knights", "kids online safety", "cyberbullying prevention"]


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


def make_youtube_description(script, caption):
    """YouTube's own "description" field (distinct from the short on-screen
    caption used by TikTok/IG/FB): same hook + link, but with the episode's
    full line-by-line content folded in for keyword coverage, since YouTube's
    search/suggested-video matching reads description text, not just title."""
    if script.get("lines"):
        # Remotion-path scripts: structured dialogue lines.
        lines = " ".join(l["text"] for l in script["lines"] if l.get("text")).strip()
    else:
        # AI-path scripts (ai-scripts.json) have no "lines", only a single
        # "prompt" block for Seedance — pull the quoted dialogue out of it
        # as a lightweight approximation of what's actually said on-screen.
        lines = " ".join(re.findall(r'"([^"]{4,})"', script.get("prompt", ""))).strip()
    parts = [caption]
    if lines:
        parts.append(f"\nWhat happens in this episode: {lines}")
    parts.append(
        "\nDigital Safety Knights is a free daily series teaching kids to "
        "recognize online scams, AI-generated deception, and cyberbullying "
        "— one short lesson at a time. New episode every day."
    )
    return "\n".join(parts)


def make_youtube_tags(script):
    category = categorize_script(script)
    return YT_BASE_TAGS + YT_TAGS_BY_CATEGORY[category]


def make_thumbnail(mp4_path, out_path):
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(mp4_path), "-ss", "00:00:01", "-vframes", "1", str(out_path)],
        check=True,
        capture_output=True,
    )


def normalize_for_platforms(mp4_path):
    """Re-mux in place: video stream copied as-is (already valid — confirmed
    by decoding frames across the full timeline), audio resampled to 48kHz.

    fal.ai's Seedance output is 32kHz audio, an unusual rate outside what
    mobile social apps' own ingest pipelines are tuned for. upload-post.com
    was already silently resampling it for Facebook/Instagram (visible in
    its own response as an audio "changes" note) but not for TikTok — and
    confirmed directly (Osman: "donmuş resim", a post stuck on its poster
    frame, never actually playing) that TikTok, Instagram and Facebook posts
    were all affected. Doing this ourselves, once, for every platform
    up front is more reliable than depending on each platform's own
    transcoder to handle the odd rate correctly."""
    fixed_path = mp4_path.with_suffix(".fixed.mp4")
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(mp4_path), "-c:v", "copy", "-c:a", "aac",
         "-ar", "48000", "-b:a", "192k", "-movflags", "+faststart", str(fixed_path)],
        check=True,
        capture_output=True,
    )
    fixed_path.replace(mp4_path)


def upload_to_s3(local_path, key):
    s3.upload_file(str(local_path), OUTPUT_BUCKET, key)


def publish_to_site_library(script_id, mp4_path, thumb_path):
    """Copies a normalized render + its thumbnail onto the public website
    bucket under shorts/{script_id}.{ext}, so frontend/topics.html can play
    it. OUTPUT_BUCKET itself stays private by design (see infra/s3.tf) —
    this is a deliberate, narrow exception for the two files meant to be
    publicly browsable, not a general publish path. Best-effort: a failure
    here shouldn't take down the day's social publish, which is the part
    that actually has to succeed."""
    if not SITE_BUCKET:
        return
    try:
        s3.upload_file(str(mp4_path), SITE_BUCKET, f"shorts/{script_id}.mp4",
                        ExtraArgs={"ContentType": "video/mp4"})
        s3.upload_file(str(thumb_path), SITE_BUCKET, f"shorts/{script_id}.jpg",
                        ExtraArgs={"ContentType": "image/jpeg"})
    except Exception as e:  # noqa: BLE001 — same reasoning as find_existing_render
        print(f"[warn] publish_to_site_library({script_id}) failed, topics.html won't have it yet: {e}")


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


def publish_to_platforms(mp4_path, title, caption, script=None):
    if not UPLOAD_API_KEY:
        print("[warn] no UPLOAD_API_KEY set, skipping publish (video stays in S3 only)")
        return {"status": "skipped_no_key", "platforms": []}
    data = {
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
        # YouTube has its own separate synthetic-media disclosure (not
        # covered by TikTok's is_aigc above) — same honesty requirement.
        "containsSyntheticMedia": "true",
        # Deliberately NOT setting selfDeclaredMadeForKids here: the DSK
        # YouTube channel has "Made for Kids" set at the channel level
        # (confirmed with the owner), so every upload inherits it. An
        # explicit per-video value would override that — don't.
        "categoryId": "27",  # Education — closer fit than upload-post's default "22"
        "defaultLanguage": "en",
        "defaultAudioLanguage": "en-US",
    }
    if script is not None:
        data["youtube_description"] = make_youtube_description(script, caption)
        data["tags[]"] = make_youtube_tags(script)  # requests expands a list value into repeated form fields
    with open(mp4_path, "rb") as f:
        resp = requests.post(
            "https://api.upload-post.com/api/upload",
            headers={"Authorization": f"Apikey {UPLOAD_API_KEY}"},
            files={"video": f},
            data=data,
            timeout=300,
        )
    status = "published" if resp.ok else "failed"
    return {
        "status": status,
        "platforms": AUTO_PLATFORMS,
        "http_status": resp.status_code,
        "body": resp.text[:500],
    }


def finish_and_publish(script_id, day, mp4_path, title, caption, script=None):
    """Shared tail end for both paths: thumbnail, S3 upload, publish, status.
    Caller advances its own state counter only after this returns (i.e. only
    on success — this exits the process on failure).

    Runs on every call — including reposts pulled from S3 — so the catalog
    self-heals: each script_id gets fixed the next time its turn comes up,
    and the newly re-uploaded (now-normalized) S3 copy is what
    find_existing_render() will serve from then on."""
    normalize_for_platforms(mp4_path)

    thumb_path = ROOT / "out" / f"{script_id}.jpg"
    make_thumbnail(mp4_path, thumb_path)

    caption_path = ROOT / "out" / f"{script_id}.caption.json"
    caption_path.write_text(json.dumps({"scriptId": script_id, "day": day, "caption": caption}, indent=2))

    date_prefix = datetime.date.today().isoformat()
    upload_to_s3(mp4_path, f"{date_prefix}/{script_id}.mp4")
    upload_to_s3(thumb_path, f"{date_prefix}/{script_id}.jpg")
    upload_to_s3(caption_path, f"{date_prefix}/{script_id}.caption.json")
    publish_to_site_library(script_id, mp4_path, thumb_path)

    result = publish_to_platforms(mp4_path, title, caption, script=script)
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
    finish_and_publish(script_id, day, mp4_path, script.get("title", script_id), caption, script=script)
    advance_day_index(day)


def run_ai_path():
    """fal.ai Seedance 2.0 reference-to-video with the permanent character
    cast (Shieldy, Pixel, Glitch, Bot, Dame Noble, Sprout). Every
    NEW_SCRIPT_INTERVAL_DAYS runs, writes and renders a brand-new script
    (script_writer.py) instead of pulling the next item off the fixed
    rotation — all other runs continue the normal repost-or-generate logic
    unchanged, and the rotation's own index is untouched on a new-script
    day so it resumes exactly where it left off next time.

    next_priority_script() takes first refusal once PRIORITY_START_DATE
    hits: while it's returning a script, neither the new-script-every-3-days
    feature nor the normal rotation gets a turn — see its own docstring for
    the "arada bir eskilerden" exception."""
    scripts = json.loads((ROOT / "content/ai-scripts.json").read_text())
    day = datetime.date.today().day

    new_script = next_priority_script(scripts)
    if new_script is None and bump_new_script_counter():
        try:
            new_script = script_writer.generate_new_script(scripts)
            script_writer.commit_new_script_to_github(new_script, GITHUB_TOKEN, GITHUB_REPO)
            print(f"Day {day}: wrote new script {new_script['id']} "
                  f"({new_script['title']}) and committed it to GitHub")
        except Exception as e:  # noqa: BLE001 — fall back to the normal rotation, don't lose the day
            alert_failure(
                "DSK Shorts: new-script generation failed, falling back to rotation", str(e)
            )
            new_script = None

    if new_script:
        script = new_script
        script_id = script["id"]
        index = None  # not part of the indexed rotation — AI_STATE stays untouched
    else:
        resp = dynamodb.Table(QUEUE_TABLE).get_item(Key={"pk": "AI_STATE"})
        last = int(resp.get("Item", {}).get("lastIndex", -1))
        index = (last + 1) % len(scripts)
        script = scripts[index]
        script_id = script["id"]

    mp4_path = ROOT / "out" / f"{script_id}.mp4"
    mp4_path.parent.mkdir(parents=True, exist_ok=True)

    # A freshly-written script can't possibly have a prior render, so skip
    # the S3 existence check entirely and go straight to generation.
    existing_key = None if new_script else find_existing_render(script_id)
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
    finish_and_publish(script_id, day, mp4_path, script["title"], caption, script=script)
    if index is not None:
        dynamodb.Table(QUEUE_TABLE).put_item(Item={"pk": "AI_STATE", "lastIndex": index})


def main():
    # Was alternating AI (odd days) / Polly+Remotion (even days). The Remotion
    # path also had no scriptId mapped for 20 of its 30 calendar days, so most
    # "even day" runs silently skipped rendering entirely. The AI path posts
    # every day now; run_remotion_path() is left in place but unused.
    run_ai_path()


if __name__ == "__main__":
    main()
