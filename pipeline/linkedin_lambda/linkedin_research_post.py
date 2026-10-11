"""LinkedIn auto-research post — runs every 36 hours, fully automatic.

Scans English-language news (free Google News RSS, no API key) for recent
AI-safety / cybersecurity / child-safety stories, picks one not posted
before, fetches the article text, and has an LLM (Claude, via fal.ai's
OpenRouter proxy — reuses the existing FAL_API_KEY, no new secret) write a
short, natural-voice summary of the story with a real, verified source link.
Posts as the Digital Safety Knights company page via upload-post.com, with a
topical editorial illustration generated per article (fal.ai flux-pro/kontext,
using the real DSK logo as the reference image so it's pixel-accurate in every
post, not an AI reinterpretation of it) — not a video.

Google News RSS links are opaque redirect tokens, not real article URLs —
posting one of those directly reads as a broken/untrustworthy link on
LinkedIn. Before writing or publishing anything, we decode the token to the
real publisher URL (via Google's internal batchexecute endpoint) and do a
live HTTP check on it. If a candidate's link can't be decoded or doesn't
resolve, it's skipped in favor of the next candidate — nothing gets
published with a link that hasn't been confirmed to work.
"""
import datetime
import html
import json
import os
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

import boto3
import requests

QUEUE_TABLE = os.environ["QUEUE_TABLE"]
UPLOAD_API_KEY_SECRET_ARN = os.environ["UPLOAD_API_KEY_SECRET_ARN"]
FAL_API_KEY_SECRET_ARN = os.environ["FAL_API_KEY_SECRET_ARN"]
UPLOAD_POST_PROFILE = os.environ.get("UPLOAD_POST_PROFILE", "DSK")
LINKEDIN_PAGE_URN = os.environ["LINKEDIN_PAGE_URN"]
SNS_ALERT_TOPIC_ARN = os.environ.get("SNS_ALERT_TOPIC_ARN", "")

QUERIES = [
    "AI child safety",
    "AI security risk children",
    "child online safety report",
    "kids AI chatbot safety risk",
    "online predator technology arrest",
    "cybersecurity children privacy",
]
MAX_AGE_DAYS = 4  # keep it current — this runs every 36h
MAX_CANDIDATES_TRIED = 8  # give up after this many failed link resolutions

# Osman: prefer American-based outlets "as much as possible." Google News's
# RSS <source> tag already carries the publisher's display name with every
# item, so candidates can be sorted before spending a decode + live-check
# call on any of them — no extra requests needed.
#
# A curated allowlist of national brands turned out to be the wrong shape
# for this query space: checked against a real run (27 candidates for the
# AI/child-safety queries), it matched zero — the pool is dominated by U.S.
# local/regional outlets (FOX 2 Detroit, KQED, Lincoln Journal Star, KOKH)
# and trade/legal publications, which there's no hope of enumerating
# exhaustively. So this flags the clearly non-US ones instead (easy to name
# explicitly) and sorts everything else — the common case, already biased
# toward the US by the query's gl=US&ceid=US:en — ahead of them. A short
# allowlist of unmistakable national brands still gets top priority on the
# rare occasion one shows up. Not a hard filter either way: a flagged
# candidate can still run if nothing else resolves within
# MAX_CANDIDATES_TRIED, rather than skipping the day.
TOP_TIER_US_OUTLETS = {
    "the new york times", "the washington post", "cnn", "nbc news",
    "abc news", "cbs news", "fox news", "usa today", "associated press",
    "ap news", "npr", "cnbc", "axios", "politico", "the wall street journal",
    "bloomberg", "bloomberg.com", "forbes", "time", "the verge", "techcrunch",
    "wired", "ars technica", "the hill", "business insider", "pbs newshour",
    "newsweek", "the atlantic", "vox", "los angeles times", "nbcnews.com",
    "cnet", "engadget", "the daily beast", "msnbc", "reuters",
}
NON_US_OUTLET_MARKERS = (
    "malaysia", "africa", "india", "uk", "britain", "british", "canada",
    "canadian", "australia", "australian", "zealand", "ireland", "irish",
    "europe", "european", "asia", "asian", "china", "chinese", "japan",
    "korea", "singapore", "philippines", "nigeria", "kenya", "pakistan",
    "bangladesh", "indonesia", "thailand", "vietnam", "middle east", "gulf",
    "emirates", "saudi", "israel", "mexico", "mexican", "brazil", "france",
    "french", "german", "germany", "spain", "italy", "italian", "russia",
    "russian", "ukraine",
)


def _outlet_tier(source_name):
    """Lower sorts first. 0 = known national US brand, 1 = presumed US
    (everything not flagged otherwise), 2 = flagged likely non-US."""
    name = source_name.strip().lower()
    if name in TOP_TIER_US_OUTLETS:
        return 0
    if any(marker in name for marker in NON_US_OUTLET_MARKERS):
        return 2
    return 1

dynamodb = boto3.resource("dynamodb")
secretsmanager = boto3.client("secretsmanager")


def _upload_api_key():
    return secretsmanager.get_secret_value(SecretId=UPLOAD_API_KEY_SECRET_ARN)["SecretString"]


def _fal_api_key():
    return secretsmanager.get_secret_value(SecretId=FAL_API_KEY_SECRET_ARN)["SecretString"]


def _posted_urls():
    resp = dynamodb.Table(QUEUE_TABLE).get_item(Key={"pk": "LINKEDIN_POSTED_URLS"})
    return set(resp.get("Item", {}).get("urls", []))


def _mark_posted(url):
    table = dynamodb.Table(QUEUE_TABLE)
    table.update_item(
        Key={"pk": "LINKEDIN_POSTED_URLS"},
        UpdateExpression="ADD #u :url",
        ExpressionAttributeNames={"#u": "urls"},
        ExpressionAttributeValues={":url": {url}},
    )


def fetch_candidates():
    seen = _posted_urls()
    candidates = []
    for query in QUERIES:
        url = "https://news.google.com/rss/search?q=" + urllib.parse.quote(
            f"{query} when:{MAX_AGE_DAYS}d"
        ) + "&hl=en-US&gl=US&ceid=US:en"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (DSK research bot)"})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                root = ET.fromstring(resp.read())
        except Exception as e:  # noqa: BLE001 — one bad feed shouldn't kill the run
            print(f"[warn] query '{query}' failed: {e}")
            continue
        for item in root.findall(".//item")[:5]:
            link = (item.findtext("link") or "").strip()
            title = (item.findtext("title") or "").strip()
            source = (item.findtext("source") or "").strip()
            if link and title and link not in seen:
                candidates.append({"title": title, "link": link, "query": query, "source": source})
    # Stable sort: US-outlet candidates first (original relative order
    # preserved within each group), everything else after.
    candidates.sort(key=lambda c: _outlet_tier(c["source"]))
    return candidates


def resolve_google_news_url(rss_link):
    """Decodes a Google News RSS redirect link to the real publisher URL,
    using Google's internal batchexecute endpoint (the same call the News
    web app itself makes client-side). Returns None if anything about the
    decode fails — callers must treat that as "this candidate is unusable"
    rather than falling back to the raw redirect link."""
    try:
        path = urllib.parse.urlparse(rss_link).path.split("/")
        base64_str = path[-1]

        page = requests.get(rss_link, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        page.raise_for_status()
        sg_match = re.search(r'data-n-a-sg="([^"]+)"', page.text)
        ts_match = re.search(r'data-n-a-ts="([^"]+)"', page.text)
        if not sg_match or not ts_match:
            return None
        signature, timestamp = sg_match.group(1), ts_match.group(1)

        inner = (
            '["garturlreq",[["X","X",["X","X"],null,null,1,1,"US:en",null,1,'
            'null,null,null,null,null,0,1],"X","X",1,[1,1,1],1,1,null,0,0,null,0],'
            f'"{base64_str}",{timestamp},"{signature}"]'
        )
        resp = requests.post(
            "https://news.google.com/_/DotsSplashUi/data/batchexecute",
            headers={
                "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
            },
            data="f.req=" + urllib.parse.quote(json.dumps([[["Fbv4je", inner]]])),
            timeout=15,
        )
        resp.raise_for_status()
        parsed = json.loads(resp.text.split("\n\n")[1])[:-2]
        decoded_url = json.loads(parsed[0][2])[1]
        return decoded_url
    except Exception as e:  # noqa: BLE001 — decode failure just means "try the next candidate"
        print(f"[warn] link decode failed for {rss_link}: {e}")
        return None


def verify_link_is_live(url):
    """Confirms a URL actually resolves to a real page before we ever put it
    in a post. Rejects anything that's still a news.google.com URL (a failed
    or partial decode) or that doesn't come back with a real 2xx/3xx status."""
    try:
        host = urllib.parse.urlparse(url).hostname or ""
        if "google.com" in host:
            return False
        resp = requests.get(
            url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15, allow_redirects=True, stream=True
        )
        resp.close()
        return resp.status_code < 400
    except Exception as e:  # noqa: BLE001
        print(f"[warn] link verification failed for {url}: {e}")
        return False


def fetch_article(url, max_chars=6000):
    resp = requests.get(
        url, headers={"User-Agent": "Mozilla/5.0 (DSK research bot)"}, timeout=15, allow_redirects=True
    )
    resp.raise_for_status()
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", resp.text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_chars]


def find_publishable_article():
    """Walks candidates in order, resolving and live-verifying each one's
    real URL, and returns the first that checks out — with article text
    already fetched. Returns None if nothing in this run's candidate pool
    resolves to a working link."""
    candidates = fetch_candidates()
    tried = 0
    for candidate in candidates:
        if tried >= MAX_CANDIDATES_TRIED:
            break
        tried += 1
        real_url = resolve_google_news_url(candidate["link"])
        if not real_url or not verify_link_is_live(real_url):
            print(f"[skip] unresolvable/dead link for candidate: {candidate['title']}")
            continue
        try:
            text = fetch_article(real_url)
        except Exception as e:  # noqa: BLE001 — link is live but text extraction failed; still usable
            print(f"[warn] link is live but article text fetch failed: {e}")
            text = ""
        candidate["resolved_link"] = real_url
        candidate["text"] = text
        return candidate
    return None


def call_claude(system, user):
    resp = requests.post(
        "https://fal.run/openrouter/router/openai/v1/chat/completions",
        headers={"Authorization": f"Key {_fal_api_key()}", "Content-Type": "application/json"},
        json={
            "model": "anthropic/claude-sonnet-4.5",
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        },
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


POST_SYSTEM_PROMPT = """You write LinkedIn posts for Digital Safety Knights (DSK), a free child
digital-safety education nonprofit organization. Voice: a real person on the team who has been
thinking about this, writing to other parents and professionals — warm, precise, never
fear-mongering, no hype, no clickbait, no corporate-marketing cadence.

Write a short, natural summary of the article in your own words — 2-4 short paragraphs, the way
you'd actually explain it to a friend: what happened, why it actually matters for a family, and
(if the article supports it) one concrete thing a parent can do about it. Do not use a rigid
template, bullet points, bolded hooks, emoji bullets, or a signature sign-off line — vary the
opening and structure post to post, the way a person naturally would. End with the real source
link alone on its own line, with a short natural lead-in (e.g. "More here:" or "Full story:" or
just the link on its own — vary it).
Rules:
- 500-1000 characters total, not counting the link.
- Max 2 hashtags, only if they add real value — zero is usually right.
- Never fabricate a statistic or quote that isn't in the provided article text.
- If the article text is thin, stay general but accurate — do not invent detail.
- No markdown syntax (no #, no **, no [links]()) — LinkedIn renders plain text only."""


def write_post(article):
    user_prompt = (
        f"Headline: {article['title']}\n"
        f"Source URL: {article['resolved_link']}\n\n"
        f"Article text (may be partial or noisy, extracted from the page):\n{article['text']}\n\n"
        f"Write the LinkedIn post now."
    )
    post_text = call_claude(POST_SYSTEM_PROMPT, user_prompt)
    # The system prompt asks for the link, but an LLM instruction is not a
    # guarantee — a post about a real story with no way to verify or read it
    # defeats the entire point of sourcing real news. Enforce it in code
    # instead of trusting compliance.
    if article["resolved_link"] not in post_text:
        post_text = post_text.rstrip() + f"\n\n{article['resolved_link']}"
    return post_text


# The real, live logo — not something the model draws from a text description.
# flux-pro/kontext takes this as its reference image and is instructed to keep
# it pixel-accurate while building a fresh, topical illustration around it, so
# every post is unmistakably on-brand without relying on an AI model to get a
# wordmark/shield right from scratch each time.
DSK_LOGO_URL = "https://digitalsafetyknights.org/assets/logo.png"


def image_has_text(image_url):
    """flux-pro, despite being told not to, reliably hallucinates garbled
    fake-headline text or literally reprints the topic string as a caption
    when the prompt describes a news "concept" (confirmed across three
    different prompt rewordings while building this). A LinkedIn post goes
    out unattended every ~36h with nobody reviewing it first, so instead of
    trusting the prompt, each candidate image is shown to Claude (vision,
    same OpenRouter proxy already used for writing the post text) and
    rejected if it finds any readable text — the same "verify before
    trusting the output" approach already used for the video pipeline's
    Whisper language check (see memory feedback-dsk-shorts-speech-quality)."""
    resp = requests.post(
        "https://fal.run/openrouter/router/openai/v1/chat/completions",
        headers={"Authorization": f"Key {_fal_api_key()}", "Content-Type": "application/json"},
        json={
            "model": "anthropic/claude-sonnet-4.5",
            "messages": [{
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "Does this image contain ANY readable text, letters, words, "
                            "numbers, or writing anywhere in it — including garbled, "
                            "misspelled, or gibberish text that is clearly trying to be "
                            "words (not just abstract shapes)? Reply with exactly one "
                            "word: YES or NO."
                        ),
                    },
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            }],
        },
        timeout=60,
    )
    resp.raise_for_status()
    answer = resp.json()["choices"][0]["message"]["content"].strip().upper()
    return answer.startswith("YES")


def fallback_branded_image():
    """Zero-AI fallback for when every generate_image() attempt is rejected
    by image_has_text() — a plain navy-to-navy2 gradient with the real logo
    centered, built entirely in code. Nothing here is AI-generated, so there
    is nothing for a model to hallucinate garbled text into; this can always
    be produced. Added after the 2026-10-09 run: flux-pro rejected all 3
    attempts, Lambda's own automatic retry reran the whole invocation 2 more
    times (9 attempts total, all rejected), and generate_image raised —
    which meant LinkedIn posted nothing for over 36 hours with nobody
    noticing until Osman asked what was wrong. A plain-but-safe branded
    image beats silently skipping the day."""
    from io import BytesIO

    from PIL import Image, ImageDraw

    size = 1024
    top, bottom = (13, 27, 62), (26, 47, 110)  # navy -> navy2
    base = Image.new("RGB", (size, size))
    draw = ImageDraw.Draw(base)
    for y in range(size):
        t = y / size
        draw.line(
            [(0, y), (size, y)],
            fill=tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)),
        )
    base = base.convert("RGBA")

    logo_resp = requests.get(DSK_LOGO_URL, timeout=30)
    logo_resp.raise_for_status()
    logo = Image.open(BytesIO(logo_resp.content)).convert("RGBA")
    logo_w = int(size * 0.5)
    logo_h = int(logo.height * (logo_w / logo.width))
    logo = logo.resize((logo_w, logo_h), Image.LANCZOS)
    base.alpha_composite(logo, ((size - logo_w) // 2, (size - logo_h) // 2))

    out = BytesIO()
    base.convert("RGB").save(out, format="JPEG", quality=92)
    return out.getvalue()


def generate_image(article, max_attempts=4):
    """Pure text-to-image, no reference image. An earlier version passed the
    real logo in as a flux-pro/kontext reference and asked the model to draw
    a small corner badge of it plus a new scene — it reliably duplicated the
    shield and hallucinated garbled extra text instead (the same AI-text
    unreliability already documented in this project: see memory
    feedback-dsk-shorts-ui-text-risk). Keeping this call text-only avoids
    that specific failure mode; the real, pixel-accurate logo is composited
    on afterward in code by add_logo_badge() instead of asked of the model.
    image_has_text() catches the other failure mode (hallucinated text in
    the illustration itself) with a retry loop rather than trusting the
    prompt alone. If every attempt is still rejected, fallback_branded_image()
    guarantees a postable image rather than raising and losing the day."""
    prompt = (
        "A clean, modern editorial illustration about digital safety and online "
        f"security, themed around: {article['title']}. Abstract, professional, navy "
        "blue and gold color palette, minimalist corporate-editorial style, high "
        "detail, no readable text in the image. Leave the bottom-right corner "
        "visually simple and empty — a logo will be placed there afterward."
    )
    for attempt in range(1, max_attempts + 1):
        resp = requests.post(
            "https://fal.run/fal-ai/flux-pro/v1.1-ultra",
            headers={"Authorization": f"Key {_fal_api_key()}", "Content-Type": "application/json"},
            json={"prompt": prompt, "aspect_ratio": "1:1", "num_images": 1},
            timeout=60,
        )
        resp.raise_for_status()
        image_url = resp.json()["images"][0]["url"]

        if not image_has_text(image_url):
            img_resp = requests.get(image_url, timeout=30)
            img_resp.raise_for_status()
            return add_logo_badge(img_resp.content)

        print(f"  image attempt {attempt}/{max_attempts} had readable text, retrying")

    print(f"  all {max_attempts} attempts had readable text — using plain branded fallback")
    return fallback_branded_image()


def add_logo_badge(illustration_bytes, margin_frac=0.04, logo_frac=0.22):
    """Pastes the real DSK logo (true alpha transparency, fetched fresh each
    time rather than bundled, so a future logo update needs no redeploy) onto
    the bottom-right corner of the generated illustration. Deterministic and
    pixel-accurate — no AI model involved, so there's nothing for it to get
    wrong."""
    from io import BytesIO

    from PIL import Image

    base = Image.open(BytesIO(illustration_bytes)).convert("RGBA")
    logo_resp = requests.get(DSK_LOGO_URL, timeout=30)
    logo_resp.raise_for_status()
    logo = Image.open(BytesIO(logo_resp.content)).convert("RGBA")

    logo_w = int(base.width * logo_frac)
    logo_h = int(logo.height * (logo_w / logo.width))
    logo = logo.resize((logo_w, logo_h), Image.LANCZOS)

    margin = int(base.width * margin_frac)
    pos = (base.width - logo_w - margin, base.height - logo_h - margin)
    base.alpha_composite(logo, pos)

    out = BytesIO()
    base.convert("RGB").save(out, format="JPEG", quality=92)
    return out.getvalue()


def publish_to_linkedin(post_text, image_bytes):
    resp = requests.post(
        "https://api.upload-post.com/api/upload_photos",
        headers={"Authorization": f"Apikey {_upload_api_key()}"},
        files={"photos[]": ("post.jpg", image_bytes, "image/jpeg")},
        data={
            "title": post_text,
            "caption": post_text,
            "user": UPLOAD_POST_PROFILE,
            "platform[]": ["linkedin"],
            "target_linkedin_page_id": LINKEDIN_PAGE_URN,
        },
        timeout=120,
    )
    return {"status": "published" if resp.ok else "failed", "http_status": resp.status_code, "body": resp.text[:500]}


def _alert(subject, body):
    """Without this the Lambda failed silently: an exhausted fal.ai balance
    stopped every LinkedIn post from 2026-08-13 to 08-16 and the only trace
    was a stack trace in CloudWatch nobody was watching."""
    print(f"ALERT: {subject}\n{body}")
    if not SNS_ALERT_TOPIC_ARN:
        return
    try:
        boto3.client("sns").publish(
            TopicArn=SNS_ALERT_TOPIC_ARN, Subject=subject[:100], Message=body[:4000]
        )
    except Exception as e:  # an alert must never mask the original failure
        print(f"could not send alert: {e}")


def _balance_exhausted(exc):
    resp = getattr(exc, "response", None)
    if resp is None or getattr(resp, "status_code", None) != 403:
        return False
    body = (getattr(resp, "text", "") or "").lower()
    return "exhausted balance" in body or "user is locked" in body


def handler(event, context):
    try:
        return _run()
    except Exception as e:
        if _balance_exhausted(e):
            _alert(
                "DSK LinkedIn STOPPED — fal.ai balance exhausted",
                "LinkedIn posting is blocked because the fal.ai account is locked "
                "for lack of funds. The same balance also drives the daily shorts "
                "and the homepage news feed.\n\n"
                "Top up: https://fal.ai/dashboard/billing\n\n"
                f"Raw error: {e}",
            )
        else:
            _alert(f"DSK LinkedIn post failed: {type(e).__name__}", str(e))
        raise


def _run():
    article = find_publishable_article()
    if not article:
        print("No candidate this run had a link that decoded and verified — skipping.")
        return {"status": "no_verified_candidates"}

    post_text = write_post(article)
    image_bytes = generate_image(article)
    result = publish_to_linkedin(post_text, image_bytes)
    result["article"] = article["resolved_link"]
    result["post_text"] = post_text

    if result["status"] == "published":
        # Dedup key stays the original RSS link (stable across runs even
        # though the decoded destination is what actually gets posted).
        _mark_posted(article["link"])

    print(json.dumps(result, indent=2)[:2000])
    return result


if __name__ == "__main__":
    print(json.dumps(handler({}, None), indent=2))
