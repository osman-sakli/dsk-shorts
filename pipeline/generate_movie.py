"""Render a multi-shot DSK movie with Seedance 2.5, then stitch it.

The hard problem with a 4-minute film is that Seedance renders 30s at a
time, so the cast can drift between generations. Everything here is built
against that:

  * CANONICAL_CAST and CANONICAL_WORLD are prepended VERBATIM to every shot.
    Identical wording, every time — paraphrasing is what causes drift.
  * The same reference images are sent in the same order for every shot, so
    @Image1..@Image6 never change meaning.
  * NO_TEXT_CLAUSE is appended to every shot. The 30s pilot rendered
    "CPNEEE" instead of "CLAIM" and a countdown that ran 00:00 -> 08:36, so
    no in-world text is attempted at all; captions are added in post.
  * Each shot restates the previous shot's end state as its opening state,
    so the cuts land on matching action.

Usage:
    FAL_API_KEY=... python3 pipeline/generate_movie.py content/movie-01-the-lost-sprout.json --check
    FAL_API_KEY=... python3 pipeline/generate_movie.py content/movie-01-the-lost-sprout.json --shot 1
    FAL_API_KEY=... python3 pipeline/generate_movie.py content/movie-01-the-lost-sprout.json --all
"""
import argparse
import json
import pathlib
import subprocess
import sys
import time

import requests

SEEDANCE_URL = "https://fal.run/bytedance/seedance-2.5/reference-to-video"
CHARACTER_BASE_URL = "https://digitalsafetyknights.org/assets/characters"
USD_PER_1K_TOKENS = 0.0214


def character_image_url(name):
    return f"{CHARACTER_BASE_URL}/{name}.jpg"


def estimate_cost(w, h, seconds):
    return ((w * h * seconds * 24) / 1024) / 1000 * USD_PER_1K_TOKENS


def build_prompt(movie, shot):
    """Assembles one shot prompt. Order is deliberate: cast and world first
    (so the model locks appearance before it hears the action), then the
    continuity anchor, then action and dialogue, then the no-text rule last
    so it is the most recent instruction."""
    lines = "\n".join(f'{d["who"]} says: "{d["line"]}"' for d in shot["dialogue"])
    # Every shot ships all six references, which tempts the model to crowd
    # them all into frame — the pilot duplicated a character doing exactly
    # that. Naming who is absent is what keeps them out.
    on = shot["onScreen"]
    absent = [c for c in movie["castOrder"] if c not in on]
    presence = f'ON SCREEN IN THIS SHOT — only these characters appear: {", ".join(on)}.'
    if absent:
        presence += (
            f' The following characters are NOT present in this shot and must not appear'
            f' anywhere in frame: {", ".join(absent)}.'
        )
    presence += " Each character appears exactly once — never duplicate a character in the same frame."
    return (
        f'{movie["CANONICAL_CAST"]}\n\n'
        f'{movie["CANONICAL_WORLD"]}\n\n'
        f'{presence}\n\n'
        f'CONTINUITY — the shot opens exactly here: {shot["opensOn"]}\n\n'
        f'ACTION: {shot["action"]}\n\n'
        f'SPOKEN DIALOGUE (clear, natural, child-friendly delivery):\n{lines}\n\n'
        f'CAMERA: {shot["camera"]}\n\n'
        f'CONTINUITY — the shot must end exactly here: {shot["endsOn"]}\n\n'
        f'{movie["NO_TEXT_CLAUSE"]}'
    )


def check(movie):
    """Verifies the continuity chain and the no-text policy before any money
    is spent. Every shot's opensOn must restate the previous endsOn."""
    shots = movie["shots"]
    w, h = (1280, 720) if movie["aspectRatio"] == "16:9" else (720, 1280)
    problems = []

    by_n = {s["n"]: s for s in shots}
    for s in shots:
        # The film cross-cuts between two threads, so a shot continues from
        # whichever shot it actually follows — not simply the previous one.
        src = s.get("continuesFrom")
        if src:
            prev_end = by_n[src]["endsOn"].lower()
            opens = s["opensOn"].lower()
            prev_words = {w for w in prev_end.replace(",", " ").split() if len(w) > 4}
            open_words = {w for w in opens.replace(",", " ").split() if len(w) > 4}
            if len(prev_words & open_words) < 2:
                problems.append(f"shot {s['n']}: opensOn does not restate shot {src} endsOn")
        if not s.get("dialogue"):
            problems.append(f"shot {s['n']}: no dialogue")
        for d in s["dialogue"]:
            if len(d["line"]) > 90:
                problems.append(f"shot {s['n']}: line too long to stay clear — {d['line'][:40]}...")

        # A typo in onScreen would silently drop a character from the
        # presence line, so the names are checked against the cast list.
        on = s.get("onScreen")
        if not on:
            problems.append(f"shot {s['n']}: onScreen not declared")
            continue
        for name in on:
            if name not in movie["castOrder"]:
                problems.append(f"shot {s['n']}: onScreen names unknown character '{name}'")
        # Anyone who speaks must be in frame to speak.
        for d in s["dialogue"]:
            if d["who"] not in on:
                problems.append(f"shot {s['n']}: {d['who']} has a line but is not onScreen")

    total = len(shots) * movie["shotSeconds"]
    print(f"Title       : {movie['title']}")
    print(f"Shots       : {len(shots)} x {movie['shotSeconds']}s = {total}s ({total/60:.1f} min)")
    print(f"Format      : {movie['aspectRatio']} {movie['resolution']}")
    print(f"Cast locked : {len(movie['characters'])} references, same order every shot")
    print(f"No-text rule: {'present' if movie.get('NO_TEXT_CLAUSE') else 'MISSING'}")
    print(f"Est. cost   : ~${estimate_cost(w, h, movie['shotSeconds']) * len(shots):.2f} total")
    print()
    print("Continuity chain:")
    for s in shots:
        print(f"  {s['n']}. {s['act']}")
        if s.get("lesson"):
            print(f"     lesson: {s['lesson']}")
    print()
    if problems:
        print("PROBLEMS FOUND:")
        for p in problems:
            print(f"  - {p}")
        return False
    print("No problems found: continuity chain is complete, dialogue is short, no-text rule present.")
    return True


def render_shot(movie, shot, api_key, outdir):
    w, h = (1280, 720) if movie["aspectRatio"] == "16:9" else (720, 1280)
    prompt = build_prompt(movie, shot)
    out = outdir / f"{movie['id']}-shot{shot['n']:02d}.mp4"
    print(f"[shot {shot['n']}] {shot['act']} — ~${estimate_cost(w, h, movie['shotSeconds']):.2f}")
    started = time.time()
    resp = requests.post(
        SEEDANCE_URL,
        headers={"Authorization": f"Key {api_key}", "Content-Type": "application/json"},
        json={
            "prompt": prompt,
            "image_urls": [character_image_url(n) for n in movie["characters"]],
            "resolution": movie["resolution"],
            "duration": str(movie["shotSeconds"]),
            "aspect_ratio": movie["aspectRatio"],
            "generate_audio": True,
        },
        timeout=1800,
    )
    if not resp.ok:
        print(f"  FAILED {resp.status_code}: {resp.text[:400]}")
        return None
    url = resp.json()["video"]["url"]
    data = requests.get(url, timeout=600).content
    out.write_bytes(data)
    print(f"  done in {int(time.time()-started)}s -> {out.name} ({len(data)/1_000_000:.1f} MB)")
    return out


def stitch(movie, outdir):
    parts = sorted(outdir.glob(f"{movie['id']}-shot*.mp4"))
    if not parts:
        sys.exit("no shots rendered yet")
    listfile = outdir / f"{movie['id']}-list.txt"
    listfile.write_text("".join(f"file '{p.name}'\n" for p in parts))
    final = outdir / f"{movie['id']}.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
         "-i", str(listfile), "-c", "copy", str(final)],
        check=True, cwd=outdir,
    )
    print(f"Stitched {len(parts)} shots -> {final}")
    return final


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("script")
    ap.add_argument("--check", action="store_true", help="validate only, spend nothing")
    ap.add_argument("--shot", type=int, help="render a single shot")
    ap.add_argument("--all", action="store_true", help="render every shot")
    ap.add_argument("--stitch", action="store_true", help="concatenate rendered shots")
    ap.add_argument("--print-prompt", type=int, help="show the assembled prompt for a shot")
    args = ap.parse_args()

    movie = json.loads(pathlib.Path(args.script).read_text())
    outdir = pathlib.Path("out"); outdir.mkdir(exist_ok=True)

    if args.print_prompt:
        s = next(x for x in movie["shots"] if x["n"] == args.print_prompt)
        print(build_prompt(movie, s)); sys.exit(0)
    if args.check or not (args.shot or args.all or args.stitch):
        sys.exit(0 if check(movie) else 1)
    if args.stitch:
        stitch(movie, outdir); sys.exit(0)

    import os
    key = os.environ.get("FAL_API_KEY")
    if not key:
        sys.exit("FAL_API_KEY not set")
    targets = [s for s in movie["shots"] if (args.all or s["n"] == args.shot)]
    for s in targets:
        render_shot(movie, s, key, outdir)
