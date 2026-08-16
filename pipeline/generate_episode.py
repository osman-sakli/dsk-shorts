"""Generate a long-form DSK episode with Seedance 2.5 reference-to-video.

Separate from fal_video.py (the daily 13s shorts pipeline) because the model
and the intent differ: 2.5 renders up to 30 seconds as ONE continuous take,
which is the whole reason character appearance stays consistent across the
runtime. Stitching several short clips is what makes an ensemble cast drift.

Usage:
    FAL_API_KEY=... python3 pipeline/generate_episode.py content/episode-01.json
"""
import json
import os
import pathlib
import sys
import time

import requests

SEEDANCE_URL = "https://fal.run/bytedance/seedance-2.5/reference-to-video"
CHARACTER_BASE_URL = "https://digitalsafetyknights.org/assets/characters"
# fal's published rate for Seedance 2.5, used for the pre-flight cost estimate.
USD_PER_1K_TOKENS = 0.0214


def character_image_url(name):
    return f"{CHARACTER_BASE_URL}/{name}.jpg"


def estimate_cost(width, height, seconds):
    tokens = (width * height * seconds * 24) / 1024
    return tokens / 1000 * USD_PER_1K_TOKENS


def generate(script, out_path, api_key):
    image_urls = [character_image_url(n) for n in script["characters"]]
    duration = int(script.get("durationSeconds", 30))
    resolution = script.get("resolution", "720p")
    aspect = script.get("aspectRatio", "9:16")

    w, h = (720, 1280) if aspect == "9:16" else (1280, 720)
    print(f"Model      : seedance-2.5 reference-to-video (single {duration}s take)")
    print(f"References : {len(image_urls)} characters -> " + ", ".join(script["characters"]))
    print(f"Output     : {aspect} {resolution}, {duration}s")
    print(f"Est. cost  : ~${estimate_cost(w, h, duration):.2f}")
    print("Generating — this takes several minutes...")

    started = time.time()
    resp = requests.post(
        SEEDANCE_URL,
        headers={"Authorization": f"Key {api_key}", "Content-Type": "application/json"},
        json={
            "prompt": script["prompt"],
            "image_urls": image_urls,
            "resolution": resolution,
            "duration": str(duration),
            "aspect_ratio": aspect,
            "generate_audio": True,
        },
        timeout=1800,
    )
    if not resp.ok:
        print(f"FAILED {resp.status_code}: {resp.text[:600]}")
        resp.raise_for_status()

    result = resp.json()
    video_url = result["video"]["url"]
    print(f"Rendered in {int(time.time() - started)}s -> downloading")

    video = requests.get(video_url, timeout=300)
    video.raise_for_status()
    pathlib.Path(out_path).write_bytes(video.content)
    print(f"Saved {out_path} ({len(video.content) / 1_000_000:.1f} MB)")
    return {"video_url": video_url, "seed": result.get("seed")}


if __name__ == "__main__":
    key = os.environ.get("FAL_API_KEY")
    if not key:
        sys.exit("FAL_API_KEY not set")
    script_path = sys.argv[1] if len(sys.argv) > 1 else "content/episode-01.json"
    script = json.loads(pathlib.Path(script_path).read_text())
    pathlib.Path("out").mkdir(exist_ok=True)
    info = generate(script, f"out/{script['id']}.mp4", key)
    print(json.dumps(info, indent=2))
