"""Render a multi-shot DSK film from keyframes: stills first, video second.

Workflow (the order is the whole point — nothing is generated twice):

  1. --keyframes   Generate every boundary still with an image model that
                   takes the character reference art as input, so the cast is
                   on-model BEFORE any video is rendered. Each still is also
                   handed back in as a location reference for the next still
                   in the same place, so sets and lighting stay identical.
  2. (review)      Look at out/<film>/keyframes/*.png. Fix a still by deleting
                   it and re-running --keyframes KFnn. Cheap (~$0.15 each).
  3. --shot N      Render one 30s shot with Seedance 2.5 image-to-video using
     --all         the approved stills as first AND last frame. Because shot N's
                   last frame IS shot N+1's first frame (same file), the cut
                   lands on an identical image — continuity by construction,
                   not by prompt luck.
  4. --stitch      Concatenate, then optionally lay a DSK song under the
                   dialogue with --music.

Usage:
    FAL_API_KEY=... python3 pipeline/generate_film.py content/film-01.json --check
    FAL_API_KEY=... python3 pipeline/generate_film.py content/film-01.json --keyframes
    FAL_API_KEY=... python3 pipeline/generate_film.py content/film-01.json --keyframes KF03 KF04
    FAL_API_KEY=... python3 pipeline/generate_film.py content/film-01.json --shot 1
    FAL_API_KEY=... python3 pipeline/generate_film.py content/film-01.json --all
    python3 pipeline/generate_film.py content/film-01.json --stitch --music "path/to/song.mp3"
"""
import argparse
import base64
import json
import os
import pathlib
import subprocess
import sys
import time

import requests

IMAGE_EDIT_URL = "https://fal.run/fal-ai/nano-banana-pro/edit"
IMAGE_T2I_URL = "https://fal.run/fal-ai/nano-banana-pro"
VIDEO_URL = "https://fal.run/bytedance/seedance-2.5/us/image-to-video"

# fal list prices, 2026-11 (per the model pages): nano-banana-pro $0.15/image,
# seedance 2.5 $0.2205/s @480p, $0.4730/s @720p, $1.164/s @1080p.
IMAGE_USD = 0.15
VIDEO_USD_PER_SEC = {"480p": 0.2205, "720p": 0.4730, "1080p": 1.164}


def log(msg):
    print(msg, flush=True)


def load(path):
    film = json.loads(pathlib.Path(path).read_text())
    film["_path"] = pathlib.Path(path)
    return film


def outdir(film):
    d = pathlib.Path("out") / film["id"]
    (d / "keyframes").mkdir(parents=True, exist_ok=True)
    (d / "shots").mkdir(parents=True, exist_ok=True)
    return d


def manifest_path(film):
    return outdir(film) / "manifest.json"


def read_manifest(film):
    p = manifest_path(film)
    return json.loads(p.read_text()) if p.exists() else {"keyframes": {}, "shots": {}, "spent_usd": 0.0}


def write_manifest(film, m):
    manifest_path(film).write_text(json.dumps(m, indent=2))


def kf_by_id(film):
    return {k["id"]: k for k in film["keyframes"]}


def ref_url(film, name):
    return film["characters"][name]


# ---------------------------------------------------------------- prompts

def cast_block(film, names):
    """Only the characters actually in frame are described (and sent as
    references) — sending everyone is what tempts the model to crowd the
    frame. The wording for each character is copied verbatim from the film
    file every time; paraphrase is what causes drift."""
    lines = []
    for i, n in enumerate(names, 1):
        lines.append(f"Reference image {i} = {n}: {film['CAST'][n]}")
    return "\n".join(lines)


def keyframe_prompt(film, kf, location_ref_index):
    on = kf.get("onScreen", [])
    parts = [
        "Create ONE cinematic 16:9 film still — a single frame from a Pixar-style 3D animated feature film. "
        "Soft cinematic lighting, high detail, shallow depth of field, rich colour.",
    ]
    if on:
        parts.append(
            "CHARACTERS — use the attached reference images and keep every character's exact design, proportions, "
            "colours and outfit, each appearing exactly once:\n" + cast_block(film, on)
        )
        absent = [c for c in film["castOrder"] if c not in on]
        if absent:
            parts.append("NOT in this frame (do not draw them): " + ", ".join(absent) + ".")
    else:
        parts.append("No characters in this frame.")
    parts.append(film["CANONICAL_WORLD"])
    if location_ref_index:
        note = kf.get("locationNote") or (
            "the EXACT same location and lighting as this frame — keep the architecture, colours and "
            "light direction identical to it"
        )
        parts.append(f"Reference image {location_ref_index} shows {note}.")
    parts.append("FRAME: " + kf["frame"])
    parts.append(film["NO_TEXT_CLAUSE"])
    return "\n\n".join(parts)


def shot_prompt(film, shot):
    on = shot["onScreen"]
    absent = [c for c in film["castOrder"] if c not in on]
    lines = "\n".join(f'{d["who"]} says: "{d["line"]}"' for d in shot["dialogue"])
    presence = "ON SCREEN — only these characters appear: " + ", ".join(on) + "."
    if absent:
        presence += " NOT present, must not appear: " + ", ".join(absent) + "."
    presence += " Each character appears exactly once."
    cast = "\n".join(f"{n}: {film['CAST'][n]}" for n in on)
    return "\n\n".join([
        "Pixar-style 3D animated film, continuous single shot.",
        "CAST (exact appearance, unchanged):\n" + cast,
        film["CANONICAL_WORLD"],
        film["CANONICAL_VOICES"],
        presence,
        "The video begins exactly on the provided first frame and must arrive naturally at and end exactly on the "
        "provided last frame — same positions, poses and lighting as that final image.",
        "ACTION: " + shot["action"],
        "SPOKEN DIALOGUE, in this order, clear natural child-friendly English, lips in sync, each line fully audible:\n" + lines,
        "CAMERA: " + shot["camera"],
        film["NO_TEXT_CLAUSE"],
    ])


# ---------------------------------------------------------------- check

def check(film):
    kfs = kf_by_id(film)
    problems = []
    for s in film["shots"]:
        for key in ("start", "end"):
            if s[key] not in kfs:
                problems.append(f"shot {s['n']}: {key} keyframe {s[key]} not defined")
        for d in s["dialogue"]:
            if d["who"] not in s["onScreen"]:
                problems.append(f"shot {s['n']}: {d['who']} speaks but is not onScreen")
            if len(d["line"]) > 90:
                problems.append(f"shot {s['n']}: line too long — {d['line'][:40]}...")
        for n in s["onScreen"]:
            if n not in film["castOrder"]:
                problems.append(f"shot {s['n']}: unknown character {n}")
        src = s.get("continuesFrom")
        if src:
            prev = next(x for x in film["shots"] if x["n"] == src)
            if prev["end"] != s["start"]:
                problems.append(f"shot {s['n']} continues from {src} but starts on {s['start']}, not {prev['end']}")
    for k in film["keyframes"]:
        for n in k.get("onScreen", []):
            if n not in film["castOrder"]:
                problems.append(f"{k['id']}: unknown character {n}")
        lr = k.get("locationRef")
        if lr and lr not in kfs:
            problems.append(f"{k['id']}: locationRef {lr} not defined")

    secs = film["shotSeconds"]
    vid = VIDEO_USD_PER_SEC[film["resolution"]] * secs * len(film["shots"])
    img = IMAGE_USD * len(film["keyframes"])
    log(f"Title      : {film['title']}")
    log(f"Shots      : {len(film['shots'])} x {secs}s = {len(film['shots'])*secs}s ({len(film['shots'])*secs/60:.1f} min) @ {film['resolution']}")
    log(f"Keyframes  : {len(film['keyframes'])}  (~${img:.2f})")
    log(f"Video est. : ~${vid:.2f}   (${VIDEO_USD_PER_SEC[film['resolution']]}/s)")
    log(f"TOTAL est. : ~${vid+img:.2f}")
    log("")
    log("Chain:")
    for s in film["shots"]:
        cf = f" (continues {s['continuesFrom']})" if s.get("continuesFrom") else ""
        log(f"  {s['n']}. {s['start']} -> {s['end']}  {s['act']}{cf}")
    if problems:
        log("\nPROBLEMS:")
        for p in problems:
            log("  - " + p)
        return False
    log("\nOK: every shot starts and ends on a defined keyframe; threads resume on the frame they left.")
    return True


# ---------------------------------------------------------------- fal calls

def fal_post(url, payload, key, timeout):
    r = requests.post(url, headers={"Authorization": f"Key {key}", "Content-Type": "application/json"},
                      json=payload, timeout=timeout)
    if not r.ok:
        raise RuntimeError(f"{r.status_code}: {r.text[:500]}")
    return r.json()


def download(url, path):
    data = requests.get(url, timeout=600).content
    path.write_bytes(data)
    return len(data)


def data_uri(path):
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()


def gen_keyframe(film, kf, key, m):
    d = outdir(film) / "keyframes"
    out = d / f"{kf['id']}.png"
    if out.exists():
        log(f"[{kf['id']}] exists, skipping (delete the file to regenerate)")
        return
    on = kf.get("onScreen", [])
    image_urls = [ref_url(film, n) for n in on]
    loc_index = None
    if kf.get("locationRef"):
        loc_file = d / f"{kf['locationRef']}.png"
        if not loc_file.exists():
            raise RuntimeError(f"{kf['id']} needs {kf['locationRef']} first")
        image_urls.append(data_uri(loc_file))
        loc_index = len(image_urls)
    prompt = keyframe_prompt(film, kf, loc_index)
    payload = {"prompt": prompt, "aspect_ratio": "16:9", "resolution": "1K", "num_images": 1, "output_format": "png"}
    url = IMAGE_T2I_URL
    if image_urls:
        payload["image_urls"] = image_urls
        url = IMAGE_EDIT_URL
    log(f"[{kf['id']}] {kf['frame'][:70]}...  (refs: {len(image_urls)})")
    t0 = time.time()
    res = fal_post(url, payload, key, timeout=600)
    img = res["images"][0]
    size = download(img["url"], out)
    m["keyframes"][kf["id"]] = {"fal_url": img["url"], "file": str(out), "w": img.get("width"), "h": img.get("height")}
    m["spent_usd"] = round(m.get("spent_usd", 0) + IMAGE_USD, 2)
    write_manifest(film, m)
    log(f"   done {int(time.time()-t0)}s -> {out.name} {img.get('width')}x{img.get('height')} ({size//1024} KB)")


def frame_source(film, m, kf_id):
    """Prefer the fal-hosted URL (small request); fall back to inlining the
    local file if it is missing from the manifest."""
    entry = m["keyframes"].get(kf_id)
    if entry and entry.get("fal_url"):
        return entry["fal_url"]
    f = outdir(film) / "keyframes" / f"{kf_id}.png"
    if not f.exists():
        raise RuntimeError(f"keyframe {kf_id} not generated")
    return data_uri(f)


def render_shot(film, shot, key, m):
    out = outdir(film) / "shots" / f"shot{shot['n']:02d}.mp4"
    if out.exists():
        log(f"[shot {shot['n']}] exists, skipping (delete the file to re-render)")
        return
    cost = VIDEO_USD_PER_SEC[film["resolution"]] * film["shotSeconds"]
    log(f"[shot {shot['n']}] {shot['act']}  {shot['start']} -> {shot['end']}  ~${cost:.2f}")
    payload = {
        "prompt": shot_prompt(film, shot),
        "image_url": frame_source(film, m, shot["start"]),
        "end_image_url": frame_source(film, m, shot["end"]),
        "resolution": film["resolution"],
        "duration": str(film["shotSeconds"]),
        "generate_audio": True,
        "bitrate_mode": "high",
    }
    t0 = time.time()
    res = fal_post(VIDEO_URL, payload, key, timeout=2400)
    size = download(res["video"]["url"], out)
    m["shots"][str(shot["n"])] = {"fal_url": res["video"]["url"], "file": str(out), "seed": res.get("seed")}
    m["spent_usd"] = round(m.get("spent_usd", 0) + cost, 2)
    write_manifest(film, m)
    log(f"   done {int(time.time()-t0)}s -> {out.name} ({size/1_000_000:.1f} MB)   spent so far ~${m['spent_usd']:.2f}")


# ---------------------------------------------------------------- stitch

def stitch(film, music=None, music_db=-16.0):
    d = outdir(film)
    parts = [d / "shots" / f"shot{s['n']:02d}.mp4" for s in film["shots"]]
    missing = [p.name for p in parts if not p.exists()]
    if missing:
        sys.exit("missing shots: " + ", ".join(missing))
    listfile = d / "concat.txt"
    listfile.write_text("".join(f"file 'shots/{p.name}'\n" for p in parts))
    joined = d / f"{film['id']}-nomusic.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(listfile),
                    "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(joined)],
                   check=True, cwd=d)
    log(f"Joined {len(parts)} shots -> {joined}")
    if not music:
        return joined
    final = d / f"{film['id']}.mp4"
    # Song bed sits well under the dialogue, fades in/out, and loops if short.
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(joined), "-stream_loop", "-1", "-i", str(music),
                    "-filter_complex",
                    f"[1:a]volume={music_db}dB,afade=t=in:d=2,afade=t=out:st={len(parts)*film['shotSeconds']-4}:d=4[m];"
                    f"[0:a][m]amix=inputs=2:duration=first:dropout_transition=2[a]",
                    "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                    "-shortest", "-movflags", "+faststart", str(final)],
                   check=True, cwd=d)
    log(f"With music -> {final}")
    return final


# ---------------------------------------------------------------- main

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("film")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--keyframes", nargs="*", metavar="KF", help="generate all (or the named) keyframes")
    ap.add_argument("--shot", type=int)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--stitch", action="store_true")
    ap.add_argument("--music")
    ap.add_argument("--print-prompt", metavar="KF_or_shotN")
    args = ap.parse_args()

    film = load(args.film)
    m = read_manifest(film)

    if args.print_prompt:
        if args.print_prompt.upper().startswith("KF"):
            k = kf_by_id(film)[args.print_prompt.upper()]
            print(keyframe_prompt(film, k, 99 if k.get("locationRef") else None))
        else:
            s = next(x for x in film["shots"] if x["n"] == int(args.print_prompt))
            print(shot_prompt(film, s))
        sys.exit(0)
    if args.stitch:
        stitch(film, args.music)
        sys.exit(0)
    if args.check or (args.keyframes is None and not args.shot and not args.all):
        sys.exit(0 if check(film) else 1)
    if not check(film):
        sys.exit("fix the problems above before spending anything")

    key = os.environ.get("FAL_API_KEY")
    if not key:
        sys.exit("FAL_API_KEY not set")

    if args.keyframes is not None:
        wanted = {k.upper() for k in args.keyframes} or None
        for kf in film["keyframes"]:
            if wanted is None or kf["id"] in wanted:
                gen_keyframe(film, kf, key, m)
        log(f"\nKeyframes done. Spent so far ~${m['spent_usd']:.2f}. Review out/{film['id']}/keyframes/ before rendering video.")
    if args.shot or args.all:
        for s in film["shots"]:
            if args.all or s["n"] == args.shot:
                render_shot(film, s, key, m)
        log(f"\nSpent so far ~${m['spent_usd']:.2f}")
