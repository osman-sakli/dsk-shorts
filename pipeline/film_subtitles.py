"""Write an .srt for a finished film: Whisper supplies the timing, the script
supplies the words. Each transcribed segment is snapped to the closest
scripted line (fuzzy match), so the subtitle text is exactly what was
written rather than what the ASR heard ("How regly our glitch").

Usage:
    python3 pipeline/film_subtitles.py content/film-01.json out/film-01/film-01.mp4
"""
import difflib
import json
import pathlib
import sys


def ts(sec):
    ms = int(round(sec * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def main(script, video):
    import whisper
    film = json.loads(pathlib.Path(script).read_text())
    lines = [(d["who"], d["line"]) for s in film["shots"] for d in s["dialogue"]]
    model = whisper.load_model("base")
    res = model.transcribe(video, language="en", temperature=0, condition_on_previous_text=False)
    duration = float(res["segments"][-1]["end"]) if res["segments"] else 0
    out = []
    used = set()
    for seg in res["segments"]:
        text = seg["text"].strip()
        if not text or seg.get("no_speech_prob", 0) > 0.8 or seg["start"] >= film["runtimeSeconds"]:
            continue
        best, score = None, 0
        for i, (who, line) in enumerate(lines):
            r = difflib.SequenceMatcher(None, text.lower(), line.lower()).ratio()
            # a transcribed segment may contain two scripted lines back to back
            if r < 0.5 and line.lower()[:25] in text.lower():
                r = 0.6
            if r > score:
                best, score = i, r
        if best is not None and score >= 0.5:
            who, line = lines[best]
            shown = line if best not in used else line  # repeats keep the scripted text
            used.add(best)
            out.append((seg["start"], min(seg["end"], film["runtimeSeconds"]), f"{who}: {shown}"))
        else:
            out.append((seg["start"], min(seg["end"], film["runtimeSeconds"]), text))
    srt = pathlib.Path(video).with_suffix(".srt")
    srt.write_text("".join(f"{n}\n{ts(a)} --> {ts(b)}\n{t}\n\n" for n, (a, b, t) in enumerate(out, 1)))
    print(f"{len(out)} cues -> {srt}")
    for a, b, t in out:
        print(f"  {ts(a)} {t}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
