"""Write an .srt for a finished film: Whisper supplies the timing, the script
supplies the words.

Whisper on a 4-minute film hallucinates — it repeats a line a dozen times
over a shout, or hears a line from a later shot — so matching is
constrained: a segment may only match lines of the shot that contains its
timestamp, lines are consumed in script order and each is used once, and
anything that matches nothing (improvised mumbles) gets no cue at all.

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


def similarity(heard, line):
    heard, line = heard.lower().strip(), line.lower().strip()
    r = difflib.SequenceMatcher(None, heard, line).ratio()
    core = line.rstrip("!.?")[:22]
    if core and core in heard:
        r = max(r, 0.6)
    return r


def main(script, video):
    import whisper
    film = json.loads(pathlib.Path(script).read_text())
    secs = film["shotSeconds"]
    res = whisper.load_model("base").transcribe(video, language="en", temperature=0, condition_on_previous_text=False)

    cues = []
    for shot in film["shots"]:
        base = (shot["n"] - 1) * secs
        lines = list(shot["dialogue"])
        next_i = 0
        for seg in res["segments"]:
            if not (base <= seg["start"] < base + secs) or seg.get("no_speech_prob", 0) > 0.8:
                continue
            heard = seg["text"].strip()
            if not heard or next_i >= len(lines):
                continue
            # The segment may carry one line or two consecutive lines.
            one = similarity(heard, lines[next_i]["line"])
            two = similarity(heard, lines[next_i]["line"] + " " + lines[next_i + 1]["line"]) if next_i + 1 < len(lines) else 0
            if max(one, two) < 0.45:
                continue
            start, end = seg["start"], min(seg["end"], base + secs)
            if two > one and next_i + 1 < len(lines):
                mid = start + (end - start) * len(lines[next_i]["line"]) / (len(lines[next_i]["line"]) + len(lines[next_i + 1]["line"]))
                cues.append((start, mid, lines[next_i]))
                cues.append((mid, end, lines[next_i + 1]))
                next_i += 2
            else:
                cues.append((start, end, lines[next_i]))
                next_i += 1
        missing = lines[next_i:]
        if missing:
            print(f"shot {shot['n']}: {len(missing)} line(s) not heard clearly -> no cue: " + " | ".join(d["line"][:30] for d in missing))

    srt = pathlib.Path(video).with_suffix(".srt")
    srt.write_text("".join(f"{n}\n{ts(a)} --> {ts(b)}\n{d['who']}: {d['line']}\n\n" for n, (a, b, d) in enumerate(cues, 1)))
    print(f"{len(cues)} cues -> {srt}")
    for a, b, d in cues:
        print(f"  {ts(a)}  {d['who']}: {d['line']}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
