"""One-time backfill: post the AI-path videos that were already published to
TikTok/Instagram/YouTube (before Facebook was connected on upload-post.com,
2026-08-01) to Facebook too — one every ~4 hours via EventBridge, not all at
once, so it doesn't read as a spam dump on a page that had zero posts before.

Reads the next unposted item from BACKFILL_ITEMS below, downloads its mp4
from the existing S3 output bucket, and publishes it to Facebook only via
upload-post.com. State (which index is next) lives in the shared publish
queue DynamoDB table under pk="FACEBOOK_BACKFILL_STATE". Once every item is
posted, later invocations are a harmless no-op — this whole Lambda +
EventBridge rule (infra/facebook_backfill.tf) is meant to be torn down once
the backfill list is empty.
"""
import hashlib
import json
import os

import boto3
import requests

QUEUE_TABLE = os.environ["QUEUE_TABLE"]
OUTPUT_BUCKET = os.environ["OUTPUT_BUCKET"]
UPLOAD_API_KEY_SECRET_ARN = os.environ["UPLOAD_API_KEY_SECRET_ARN"]
UPLOAD_POST_PROFILE = os.environ.get("UPLOAD_POST_PROFILE", "DSK")
SITE_URL = "https://digitalsafetyknights.org"

# Fixed list — these are exactly the AI-path videos already live on
# TikTok/Instagram/YouTube as of 2026-08-01 (AI_STATE lastIndex=5, i.e.
# ai-001..ai-006) that predate Facebook being connected. Category mirrors
# pipeline/entrypoint.py's categorize_script() (bot > glitch > general),
# computed once here rather than re-derived at runtime to keep this
# one-shot backfill self-contained.
BACKFILL_ITEMS = [
    {"script_id": "ai-001-real-name", "s3_key": "2026-07-24/ai-001-real-name.mp4",
     "title": "Knight Rule: Real Names Stay Off Chat", "category": "general"},
    {"script_id": "ai-002-free-robux", "s3_key": "2026-07-27/ai-002-free-robux.mp4",
     "title": "Glitch Alert: Free Robux Trap", "category": "scam"},
    {"script_id": "ai-003-password-secret", "s3_key": "2026-07-29/ai-003-password-secret.mp4",
     "title": "Passwords Are Secrets", "category": "general"},
    {"script_id": "ai-004-ai-confidently-wrong", "s3_key": "2026-07-30/ai-004-ai-confidently-wrong.mp4",
     "title": "Bot Says: Confidently Wrong", "category": "ai"},
    {"script_id": "ai-005-voice-clone", "s3_key": "2026-07-31/ai-005-voice-clone.mp4",
     "title": "Voice Clone Scam: The Family Code Word", "category": "scam"},
    {"script_id": "ai-006-stranger-personal-questions", "s3_key": "2026-08-01/ai-006-stranger-personal-questions.mp4",
     "title": "Grooming Watch: Stranger Asks Personal Questions", "category": "scam"},
]

BROAD_TAGS = ["#onlinesafety", "#digitalsafety"]
NICHE_TAGS_BY_CATEGORY = {
    "scam": ["#scamalert", "#internetsafety", "#protectyourkids", "#parentsoftiktok"],
    "ai": ["#aisafety", "#medialiteracy", "#parentingintheAIage", "#factcheck"],
    "general": ["#parentingtips", "#screentimetips", "#digitalparenting", "#familysafety"],
}

dynamodb = boto3.resource("dynamodb")
s3 = boto3.client("s3")
secretsmanager = boto3.client("secretsmanager")


def _upload_api_key():
    return secretsmanager.get_secret_value(SecretId=UPLOAD_API_KEY_SECRET_ARN)["SecretString"]


def _next_index():
    resp = dynamodb.Table(QUEUE_TABLE).get_item(Key={"pk": "FACEBOOK_BACKFILL_STATE"})
    return int(resp.get("Item", {}).get("nextIndex", 0))


def _advance(index):
    dynamodb.Table(QUEUE_TABLE).put_item(Item={"pk": "FACEBOOK_BACKFILL_STATE", "nextIndex": index})


def build_caption(item):
    niche = NICHE_TAGS_BY_CATEGORY[item["category"]]
    digest = int(hashlib.sha256(item["script_id"].encode()).hexdigest(), 16)
    broad = BROAD_TAGS[digest % len(BROAD_TAGS)]
    tags = " ".join([broad] + niche)
    return f"{item['title']} \U0001f6e1️\nPlay today's quest → {SITE_URL}\n{tags}"


def handler(event, context):
    idx = _next_index()
    if idx >= len(BACKFILL_ITEMS):
        print("Backfill complete — nothing left to post. Safe to tear down this Lambda/rule.")
        return {"status": "done", "index": idx}

    item = BACKFILL_ITEMS[idx]
    print(f"Posting backfill item {idx + 1}/{len(BACKFILL_ITEMS)}: {item['script_id']}")

    obj = s3.get_object(Bucket=OUTPUT_BUCKET, Key=item["s3_key"])
    video_bytes = obj["Body"].read()
    caption = build_caption(item)

    resp = requests.post(
        "https://api.upload-post.com/api/upload",
        headers={"Authorization": f"Apikey {_upload_api_key()}"},
        files={"video": (f"{item['script_id']}.mp4", video_bytes, "video/mp4")},
        data={
            "title": item["title"],
            "caption": caption,
            "user": UPLOAD_POST_PROFILE,
            "platform[]": ["facebook"],
        },
        timeout=180,
    )
    result = {
        "status": "published" if resp.ok else "failed",
        "script_id": item["script_id"],
        "index": idx,
        "http_status": resp.status_code,
        "body": resp.text[:500],
    }
    print(json.dumps(result, indent=2))

    if resp.ok:
        _advance(idx + 1)
    # On failure, don't advance — the next 4h tick retries the same item
    # rather than silently skipping it.
    return result


if __name__ == "__main__":
    print(json.dumps(handler({}, None), indent=2))
