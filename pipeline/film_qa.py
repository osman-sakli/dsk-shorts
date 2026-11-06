"""QA one rendered shot before the next one is paid for.

  * contact sheet at 1 fps (a 30s shot -> 30 thumbnails) so garbled text,
    duplicated characters or off-model drift can be spotted frame by frame —
    a 3-frame spot check missed exactly those problems in the shorts library
  * first/last frame compared against the keyframes the shot was asked to
    start and end on (mean pixel difference, 0 = identical)
  * Whisper transcript of the audio, checked against the scripted lines, so
    a mumbled or wrong-language delivery is caught before stitching

Usage:
    python3 pipeline/film_qa.py content/film-01.json 1
"""
import json
import pathlib
import subprocess
import sys

from PIL import Image, ImageChops, ImageDraw, ImageStat


def frame_diff(a, b):
    a = Image.open(a).convert("RGB").resize((320, 180))
    b = Image.open(b).convert("RGB").resize((320, 180))
    return sum(ImageStat.Stat(ImageChops.difference(a, b)).mean) / 3


def main(script, n):
    film = json.loads(pathlib.Path(script).read_text())
    shot = next(s for s in film["shots"] if s["n"] == n)
    d = pathlib.Path("out") / film["id"]
    mp4 = d / "shots" / f"shot{n:02d}.mp4"
    qa = d / "qa" / f"shot{n:02d}"
    qa.mkdir(parents=True, exist_ok=True)

    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                            "stream=width,height,r_frame_rate:format=duration", "-of", "json", str(mp4)],
                           capture_output=True, text=True, check=True).stdout
    info = json.loads(probe)
    dur = float(info["format"]["duration"])
    print(f"shot {n}: {info['streams'][0]['width']}x{info['streams'][0]['height']} {dur:.1f}s")

    # 1 fps thumbnails + first and last frame at full size
    for f in qa.glob("f*.jpg"):
        f.unlink()
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(mp4), "-vf", "fps=1,scale=320:-1",
                    str(qa / "f%03d.jpg")], check=True)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(mp4), "-frames:v", "1", str(qa / "first.png")], check=True)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-sseof", "-0.1", "-i", str(mp4), "-frames:v", "1",
                    "-update", "1", str(qa / "last.png")], check=True)

    thumbs = sorted(qa.glob("f*.jpg"))
    cols = 6
    w, h = Image.open(thumbs[0]).size
    rows = (len(thumbs) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * w, rows * (h + 16)), "black")
    dr = ImageDraw.Draw(sheet)
    for i, t in enumerate(thumbs):
        x, y = (i % cols) * w, (i // cols) * (h + 16)
        sheet.paste(Image.open(t), (x, y + 16))
        dr.text((x + 4, y + 2), f"{i}s", fill="white")
    sheet.save(qa / "contact-sheet.jpg", quality=85)
    print(f"contact sheet: {qa/'contact-sheet.jpg'} ({len(thumbs)} frames)")

    kf = d / "keyframes"
    d0 = frame_diff(qa / "first.png", kf / f"{shot['start']}.png")
    d1 = frame_diff(qa / "last.png", kf / f"{shot['end']}.png")
    print(f"first frame vs {shot['start']}: mean diff {d0:.1f}   last frame vs {shot['end']}: mean diff {d1:.1f}   (0 = identical, <12 good, >30 drifted)")

    try:
        import whisper
        model = whisper.load_model("base")
        res = model.transcribe(str(mp4), language="en")
        print("\nTRANSCRIPT:")
        for seg in res["segments"]:
            print(f"  [{seg['start']:5.1f}-{seg['end']:5.1f}] {seg['text'].strip()}")
        print("\nSCRIPTED:")
        for dl in shot["dialogue"]:
            print(f"  {dl['who']}: {dl['line']}")
        (qa / "transcript.txt").write_text("\n".join(s["text"].strip() for s in res["segments"]))
    except ImportError:
        print("whisper not installed — skipping transcript")


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]))
