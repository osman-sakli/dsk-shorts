"""Cut vertical shorts out of a finished long film.

A 4-minute film is the thing people watch once; the shorts are what gets
it found. Each clip is pulled straight from the finished mix — same
characters, same voices, same score decisions — so nothing has to be
re-rendered or re-paid for.

The film is 16:9 and shorts are 9:16, so the frame is rebuilt rather than
cropped blind: the original sits in the middle of a blurred, darkened
enlargement of itself, which keeps both characters in frame (a centre crop
cuts whoever is on the left or right of a two-shot, which is most of this
film).

Clips are defined in the film JSON under "shorts":
    {"id": "secret", "start": 36, "end": 58, "hook": "...", "lesson": "..."}

Usage:
    python3 pipeline/film_shorts.py content/film-01.json            # cut all
    python3 pipeline/film_shorts.py content/film-01.json --only secret
"""
import argparse
import json
import pathlib
import subprocess
import sys

W, H = 1080, 1920
LOGO = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "assets" / "logo.png"
FONTS = [
    "/System/Library/Fonts/Supplemental/Arial Rounded Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Black.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
]


def font(size):
    from PIL import ImageFont
    for p in FONTS:
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.load_default()


def wrap(draw, text, f, max_w):
    words, lines, line = text.split(), [], ""
    for w_ in words:
        trial = (line + " " + w_).strip()
        if draw.textlength(trial, font=f) <= max_w or not line:
            line = trial
        else:
            lines.append(line)
            line = w_
    if line:
        lines.append(line)
    return lines


def overlay_png(clip, path):
    """The film is 16:9 inside a 9:16 canvas, so roughly a third of the
    screen is live image and the rest is blurred backdrop. This fills that
    space with the hook above and the takeaway below — which is also what
    makes a short readable with the sound off. Drawn with PIL because this
    ffmpeg build has no drawtext filter (no libfreetype)."""
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    fh, fl, fc = font(74), font(42), font(34)

    hook = clip.get("hook", "")
    for i, line in enumerate(wrap(d, hook, fh, W - 130)[:4]):
        y = 300 + i * 92
        d.text((W // 2 + 3, y + 3), line, font=fh, fill=(0, 0, 0, 170), anchor="ma")
        d.text((W // 2, y), line, font=fh, fill=(232, 197, 106, 255), anchor="ma")

    lesson = clip.get("lesson", "")
    lines = wrap(d, lesson, fl, W - 140)[:5]
    top = H - 430 - len(lines) * 56
    for i, line in enumerate(lines):
        d.text((W // 2, top + i * 56), line, font=fl, fill=(240, 244, 255, 255), anchor="ma")

    cta = "digitalsafetyknights.org   —   free, always"
    d.text((W // 2, H - 150), cta, font=fc, fill=(201, 168, 76, 255), anchor="ma")

    if LOGO.exists():
        logo = Image.open(LOGO).convert("RGBA")
        logo.thumbnail((150, 150))
        img.alpha_composite(logo, ((W - logo.width) // 2, 110))
    img.save(path)


def cut(film, clip, src, outdir):
    out = outdir / f"{film['id']}-{clip['id']}.mp4"
    dur = clip["end"] - clip["start"]
    ov = outdir / f".overlay-{clip['id']}.png"
    overlay_png(clip, ov)
    # Blurred 9:16 backdrop, the real frame centred on top, then the text
    # layer; a gentle fade in/out so a clip that starts mid-scene opens clean.
    vf = (
        f"[0:v]split=2[bg][fg];"
        f"[bg]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
        f"boxblur=30:2,eq=brightness=-0.22:saturation=0.70[bgb];"
        f"[fg]scale={W}:-2[fgs];"
        f"[bgb][fgs]overlay=(W-w)/2:(H-h)/2[stage];"
        f"[stage][1:v]overlay=0:0,"
        f"fade=t=in:st=0:d=0.4,fade=t=out:st={dur - 0.4:.2f}:d=0.4,format=yuv420p[v]"
    )
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-ss", str(clip["start"]), "-t", str(dur), "-i", str(src),
        "-i", str(ov),
        "-filter_complex", vf, "-map", "[v]", "-map", "0:a",
        "-af", f"afade=t=in:st=0:d=0.3,afade=t=out:st={dur - 0.3:.2f}:d=0.3",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-r", "24",
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out),
    ], check=True)
    ov.unlink(missing_ok=True)
    size = out.stat().st_size / 1e6
    print(f"  {clip['id']:<12} {clip['start']:>5.1f}-{clip['end']:<5.1f} ({dur:.0f}s)  {size:.1f} MB  -> {out.name}")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("film")
    ap.add_argument("--only", nargs="*")
    args = ap.parse_args()

    film = json.loads(pathlib.Path(args.film).read_text())
    clips = film.get("shorts") or []
    if not clips:
        sys.exit("no 'shorts' defined in the film file")
    d = pathlib.Path("out") / film["id"]
    src = d / f"{film['id']}.mp4"
    if not src.exists():
        sys.exit(f"missing {src} — stitch the film first")
    outdir = d / "shorts-cut"
    outdir.mkdir(exist_ok=True)

    print(f"Cutting {len(clips)} short(s) from {src.name} at {W}x{H}:")
    for clip in clips:
        if args.only and clip["id"] not in args.only:
            continue
        cut(film, clip, src, outdir)
    print(f"\nCaptions for posting are in the film file under shorts[].hook / .lesson")


if __name__ == "__main__":
    main()
