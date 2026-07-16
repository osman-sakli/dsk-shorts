#!/usr/bin/env python3
"""Generate per-line TTS audio for a script JSON using edge-tts.
Usage: python pipeline/tts.py content/scripts/001-knight-rule-1.json
Outputs: assets/audio/<id>/line-XX.mp3 + timing.json (durInFrames per line @30fps)
"""
import asyncio, json, sys, pathlib

try:
    import edge_tts
except ImportError:
    sys.exit("pip install edge-tts")

FPS = 30
ROOT = pathlib.Path(__file__).resolve().parents[1]
VOICES = json.loads((ROOT / "content/characters.json").read_text())

async def synth(line, voice_cfg, out_path):
    tts = edge_tts.Communicate(
        line["text"], voice_cfg["voice"],
        rate=voice_cfg.get("rate", "+0%"), pitch=voice_cfg.get("pitch", "+0Hz"),
    )
    await tts.save(str(out_path))

def mp3_duration_seconds(path):
    # lightweight duration probe via mutagen if available, else ffprobe
    try:
        from mutagen.mp3 import MP3
        return MP3(path).info.length
    except Exception:
        import subprocess
        out = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(path)], capture_output=True, text=True)
        return float(out.stdout.strip() or 2.0)

async def main(script_path):
    script = json.loads(pathlib.Path(script_path).read_text())
    out_dir = ROOT / "assets/audio" / script["id"]
    out_dir.mkdir(parents=True, exist_ok=True)
    timing = []
    for i, line in enumerate(script["lines"]):
        voice = VOICES.get(line["who"], VOICES["SHIELDY"])
        mp3 = out_dir / f"line-{i:02d}.mp3"
        await synth(line, voice, mp3)
        dur = mp3_duration_seconds(mp3)
        frames = max(30, int((dur + 0.35) * FPS))  # +0.35s breathing room
        timing.append({"index": i, "who": line["who"], "seconds": round(dur, 2), "durInFrames": frames})
        print(f"  line {i:02d} [{line['who']}] {dur:.2f}s -> {frames}f")
    (out_dir / "timing.json").write_text(json.dumps(timing, indent=2))
    # write timing back into the script json (durInFrames per line)
    for i, t in enumerate(timing):
        script["lines"][i]["durInFrames"] = t["durInFrames"]
    pathlib.Path(script_path).write_text(json.dumps(script, indent=2))
    print(f"OK: {script['id']} — timing written back to script")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    asyncio.run(main(sys.argv[1]))
