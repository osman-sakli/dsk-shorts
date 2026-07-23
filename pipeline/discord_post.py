"""Lambda: post the next rotating Discord message roughly every 48h.

Reads content/discord-posts.json (bundled in the deployment zip), tracks the
next index in the shared publish-queue DynamoDB table (pk="DISCORD_STATE"),
and POSTs it to the Discord webhook. Webhook URL is fetched from Secrets
Manager at call time rather than passed as a plain env var.
"""
import json
import os
import pathlib
import urllib.request

import boto3

TABLE_NAME = os.environ["QUEUE_TABLE"]
WEBHOOK_SECRET_ARN = os.environ["DISCORD_WEBHOOK_SECRET_ARN"]
POSTS_PATH = pathlib.Path(__file__).resolve().parent / "discord-posts.json"

dynamodb = boto3.resource("dynamodb")
secretsmanager = boto3.client("secretsmanager")


def _webhook_url():
    return secretsmanager.get_secret_value(SecretId=WEBHOOK_SECRET_ARN)["SecretString"]


def _next_index(total):
    resp = dynamodb.Table(TABLE_NAME).get_item(Key={"pk": "DISCORD_STATE"})
    last = int(resp.get("Item", {}).get("lastIndex", -1))
    return (last + 1) % total


def _advance(index):
    dynamodb.Table(TABLE_NAME).put_item(Item={"pk": "DISCORD_STATE", "lastIndex": index})


def handler(event, context):
    posts = json.loads(POSTS_PATH.read_text())
    idx = _next_index(len(posts))
    post = posts[idx]

    body = json.dumps({"content": post["text"]}).encode()
    req = urllib.request.Request(
        _webhook_url(), data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        status = resp.status

    _advance(idx)
    return {"statusCode": status, "postedType": post["type"], "index": idx}
