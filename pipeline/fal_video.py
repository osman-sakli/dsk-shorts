"""AI-generated video path (odd calendar days): fal.ai Seedance 2.0
reference-to-video, using permanent character reference art hosted on the
site, so every character stays visually consistent across generations.
"""
import json
import os
import pathlib
import time

import requests

FAL_API_KEY = os.environ["FAL_API_KEY"]
CHARACTER_BASE_URL = "https://digitalsafetyknights.org/assets/characters"
SEEDANCE_URL = "https://fal.run/bytedance/seedance-2.0/fast/reference-to-video"

# On 2026-08-15 a single 403 from fal lost that whole day's short: the caller
# exits on the first exception, so one transient blip means nothing is posted
# that day. These statuses are the ones worth trying again — 429/5xx are
# plainly transient, and fal returns 403 for temporary balance and rate
# problems too. 422 is excluded on purpose: a rejected payload stays rejected,
# so retrying it only burns time.
RETRY_STATUSES = {403, 408, 429, 500, 502, 503, 504}
MAX_ATTEMPTS = 4
BACKOFF_SECONDS = 30


def character_image_url(name):
    return f"{CHARACTER_BASE_URL}/{name}.jpg"


def _should_retry(exc):
    if isinstance(exc, (requests.ConnectionError, requests.Timeout)):
        return True
    resp = getattr(exc, "response", None)
    return resp is not None and resp.status_code in RETRY_STATUSES


def generate_video(script, out_path, duration=13, resolution="720p"):
    """script: one entry from content/ai-scripts.json.
    Downloads the finished mp4 to out_path. Raises on any failure — caller
    handles retries/alerts the same way as a Remotion render failure.

    duration: seconds, 4-15 per Seedance 2.0's documented range (passed as a
    string per the API's own examples). 13 leaves headroom under the 15s
    cap while giving each script noticeably more room to land its beat than
    the original 9s default.
    """
    image_urls = [character_image_url(name) for name in script["characters"]]
    payload = {
        "prompt": script["prompt"],
        "image_urls": image_urls,
        "resolution": resolution,
        "duration": str(duration),
        "aspect_ratio": "9:16",
        "generate_audio": True,
    }
    headers = {
        "Authorization": f"Key {FAL_API_KEY}",
        "Content-Type": "application/json",
    }

    # Only the POST is retried, and only when it failed outright. If a
    # generation succeeded and merely the download broke, retrying the POST
    # would pay for a second video — so the download is retried on its own
    # below, where it costs nothing.
    result = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            resp = requests.post(
                SEEDANCE_URL,
                headers=headers,
                json=payload,
                timeout=600,  # generation is synchronous and can take several minutes
            )
            resp.raise_for_status()
            result = resp.json()
            break
        except requests.RequestException as e:
            if attempt == MAX_ATTEMPTS or not _should_retry(e):
                raise
            wait = BACKOFF_SECONDS * attempt
            print(f"  fal attempt {attempt}/{MAX_ATTEMPTS} failed ({e}); retrying in {wait}s")
            time.sleep(wait)

    video_url = result["video"]["url"]
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            video_resp = requests.get(video_url, timeout=120)
            video_resp.raise_for_status()
            break
        except requests.RequestException as e:
            if attempt == MAX_ATTEMPTS:
                raise
            print(f"  download attempt {attempt}/{MAX_ATTEMPTS} failed ({e}); retrying")
            time.sleep(BACKOFF_SECONDS)

    pathlib.Path(out_path).write_bytes(video_resp.content)
    return {"seed": result.get("seed"), "video_url": video_url}


if __name__ == "__main__":
    import sys
    scripts = json.loads((pathlib.Path(__file__).resolve().parents[1] / "content/ai-scripts.json").read_text())
    script = scripts[0] if len(sys.argv) < 2 else next(s for s in scripts if s["id"] == sys.argv[1])
    info = generate_video(script, "out/ai-test.mp4")
    print(json.dumps(info, indent=2))
