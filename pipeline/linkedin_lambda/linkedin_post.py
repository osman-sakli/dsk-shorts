"""Lambda: post the next rotating LinkedIn update roughly every 48h, as the
Digital Safety Knights company page (never the owner's personal profile).

Reads content/linkedin-posts.json + content/linkedin-images/NN.png (bundled
in the deployment zip), tracks the next index in the shared publish-queue
DynamoDB table (pk="LINKEDIN_STATE"), and posts via upload-post.com's
photo-upload endpoint with target_linkedin_page_id set to the DSK
organization URN — the personal/company distinction happens at post time,
not at connection time (upload-post.com only has ONE LinkedIn OAuth
connection; it exposes company pages that account administers via
target_linkedin_page_id).
"""
import json
import os
import pathlib

import boto3
import requests

TABLE_NAME = os.environ["QUEUE_TABLE"]
UPLOAD_API_KEY_SECRET_ARN = os.environ["UPLOAD_API_KEY_SECRET_ARN"]
UPLOAD_POST_PROFILE = os.environ.get("UPLOAD_POST_PROFILE", "DSK")
LINKEDIN_PAGE_URN = os.environ["LINKEDIN_PAGE_URN"]

ROOT = pathlib.Path(__file__).resolve().parent
POSTS_PATH = ROOT / "linkedin-posts.json"
IMAGES_DIR = ROOT / "linkedin-images"

dynamodb = boto3.resource("dynamodb")
secretsmanager = boto3.client("secretsmanager")


def _api_key():
    return secretsmanager.get_secret_value(SecretId=UPLOAD_API_KEY_SECRET_ARN)["SecretString"]


def _next_index(total):
    resp = dynamodb.Table(TABLE_NAME).get_item(Key={"pk": "LINKEDIN_STATE"})
    last = int(resp.get("Item", {}).get("lastIndex", -1))
    return (last + 1) % total


def _advance(index):
    dynamodb.Table(TABLE_NAME).put_item(Item={"pk": "LINKEDIN_STATE", "lastIndex": index})


def handler(event, context):
    posts = json.loads(POSTS_PATH.read_text())
    idx = _next_index(len(posts))
    post = posts[idx]
    image_path = IMAGES_DIR / f"{post['id']:02d}.png"

    with open(image_path, "rb") as f:
        resp = requests.post(
            "https://api.upload-post.com/api/upload_photos",
            headers={"Authorization": f"Apikey {_api_key()}"},
            files={"photos[]": f},
            data={
                "title": post["text"],
                "user": UPLOAD_POST_PROFILE,
                "platform[]": ["linkedin"],
                "target_linkedin_page_id": LINKEDIN_PAGE_URN,
            },
            timeout=120,
        )

    result = {
        "status": "published" if resp.ok else "failed",
        "http_status": resp.status_code,
        "body": resp.text[:500],
        "postId": post["id"],
    }
    if resp.ok:
        _advance(idx)
    print(json.dumps(result))
    return result
