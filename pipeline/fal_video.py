"""AI-generated video path (odd calendar days): fal.ai Seedance 2.0
reference-to-video, using permanent character reference art hosted on the
site, so every character stays visually consistent across generations.
"""
import json
import os
import pathlib

import requests

FAL_API_KEY = os.environ["FAL_API_KEY"]
CHARACTER_BASE_URL = "https://digitalsafetyknights.org/assets/characters"
SEEDANCE_URL = "https://fal.run/bytedance/seedance-2.0/fast/reference-to-video"


def character_image_url(name):
    return f"{CHARACTER_BASE_URL}/{name}.jpg"


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

    resp = requests.post(
        SEEDANCE_URL,
        headers={
            "Authorization": f"Key {FAL_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "prompt": script["prompt"],
            "image_urls": image_urls,
            "resolution": resolution,
            "duration": str(duration),
            "aspect_ratio": "9:16",
            "generate_audio": True,
        },
        timeout=600,  # generation is synchronous and can take several minutes
    )
    resp.raise_for_status()
    result = resp.json()
    video_url = result["video"]["url"]

    video_resp = requests.get(video_url, timeout=120)
    video_resp.raise_for_status()
    pathlib.Path(out_path).write_bytes(video_resp.content)
    return {"seed": result.get("seed"), "video_url": video_url}


if __name__ == "__main__":
    import sys
    scripts = json.loads((pathlib.Path(__file__).resolve().parents[1] / "content/ai-scripts.json").read_text())
    script = scripts[0] if len(sys.argv) < 2 else next(s for s in scripts if s["id"] == sys.argv[1])
    info = generate_video(script, "out/ai-test.mp4")
    print(json.dumps(info, indent=2))
