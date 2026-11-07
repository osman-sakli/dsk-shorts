"""Publish a finished long-form film to YouTube via upload-post.com.

Separate from entrypoint.py, which posts the daily 15s vertical shorts to
four platforms. A 4-minute 16:9 film belongs on YouTube (and optionally
Facebook); TikTok and Instagram are vertical-first and would letterbox it.

Unlike the shorts path this one also sends a custom thumbnail and the
subtitle file, and it is always run by hand — never on a cron.

Usage:
    FAL_... not needed. UPLOAD_API_KEY from Secrets Manager:
    UPLOAD_API_KEY=$(aws secretsmanager get-secret-value \
        --secret-id dsk-shorts/upload-api-key --query SecretString --output text) \
    python3 pipeline/publish_film.py content/film-01.json --dry-run
    ... --platforms youtube facebook
"""
import argparse
import json
import os
import pathlib
import re
import sys

import requests

API = "https://api.upload-post.com/api/upload"
UPLOAD_POST_PROFILE = os.environ.get("UPLOAD_POST_PROFILE", "DSK")


def upload_filename(film, suffix=".mp4"):
    """The name the file is uploaded UNDER. On disk it is
    "film-01-the-lost-sprout.mp4" — the "film-01-" is our production
    counter, and the story name alone is not something anyone searches.
    YouTube treats the filename as a weak relevance signal and pre-fills
    the title from it on a manual upload, so it reads as a real line."""
    name = f"{film['title']} | Online Safety Cartoon for Kids".replace(":", " -")
    name = re.sub(r'[\\/*?"<>]', "", name)
    name = re.sub(r"\s{2,}", " ", name).strip()
    return name[:110].strip(" -|") + suffix


def build(film, out):
    title = f"{film['title']} | Online Safety Cartoon for Kids (Stranger Danger)"
    lessons = "\n".join(f"• {l}" for l in film.get("lessons", []))
    description = f"""An online safety cartoon for kids about stranger danger — and the oldest trick online: someone who is a little too friendly, too generous, and too keen to keep it secret.

{film['logline']}

{film['title']} is the first full-length Digital Safety Knights film: a {film['runtimeSeconds'] // 60}-minute animated story for children aged {film.get('ages', '5-10').replace('Ages ', '')}, free to watch and free to share with a classroom.

What the film teaches:
{lessons}

Digital Safety Knights is a free nonprofit that teaches children and families how to stay safe online — scams, AI chatbots and deepfakes, online grooming and strangers, cyberbullying and privacy. Everything we make is free, in English, Spanish, French and Turkish: short videos, quizzes, printable internet safety guides for parents, and live workshops for schools and community organisations.

Watch this film, the short episodes and the quizzes:
https://digitalsafetyknights.org/films.html
Free guides for parents and teachers:
https://digitalsafetyknights.org/resources.html
Book a free school or community session:
https://digitalsafetyknights.org/school-programs.html

If something ever happens online that worries a child: tell a trusted adult first — nobody is in trouble for asking for help. In the US you can report at CyberTipline.org, or call or text 988 any time, free and confidential.

This film's animation and music are AI-generated; the story, the script and every safety message in it are written and reviewed by our team.

#onlinesafety #strangerdanger #cartoonforkids"""
    tags = ["online safety for kids", "cartoon for kids", "internet safety for kids",
            "animated story for kids", "stranger danger", "adventure cartoon",
            "online predators", "knight cartoon", "grooming awareness", "roblox animation",
            "how to talk to your kids about online safety", "roblox story",
            "teaching kids internet safety", "short film for kids",
            "internet safety video for classroom", "funny cartoon", "kids adventure",
            "kids cartoon", "learning videos for kids", "3d animation", "online safety",
            "kids videos", "digital safety knights"]
    return {
        "user": UPLOAD_POST_PROFILE,
        "platform[]": None,  # filled per run
        "title": title,
        "youtube_description": description,
        "tags[]": tags,
        "categoryId": "27",            # Education
        "privacyStatus": "public",
        # Stated per video rather than inherited from the channel (see the
        # long note in entrypoint.py). The films are animated stories told
        # to children, so this one is honestly "true" — which does cost
        # reach, and is why the parent-facing material is where the
        # channel's growth has to come from.
        "selfDeclaredMadeForKids": "true",
        "containsSyntheticMedia": "true",
        "defaultLanguage": "en",
        "defaultAudioLanguage": "en-US",
        "youtube_notify_subscribers": "true",
        "youtube_subtitle_language": "en",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("film")
    ap.add_argument("--platforms", nargs="+", default=["youtube"])
    ap.add_argument("--privacy", default="public", choices=["public", "unlisted", "private"])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    film = json.loads(pathlib.Path(args.film).read_text())
    out = pathlib.Path("out") / film["id"]
    mp4 = out / f"{film['id']}.mp4"
    thumb = out / "thumbnail.jpg"
    srt = out / f"{film['id']}.srt"
    for f in (mp4, thumb, srt):
        if not f.exists():
            sys.exit(f"missing {f}")
    if thumb.stat().st_size > 2_000_000:
        sys.exit("thumbnail over YouTube's 2 MB limit")

    data = build(film, out)
    data["platform[]"] = args.platforms
    data["privacyStatus"] = args.privacy

    print(f"film      : {mp4} ({mp4.stat().st_size/1e6:.0f} MB)")
    print(f"thumbnail : {thumb} ({thumb.stat().st_size//1024} KB)")
    print(f"subtitles : {srt}")
    print(f"platforms : {args.platforms}   privacy: {args.privacy}")
    print(f"title     : {data['title']}")
    print("\n--- description ---\n" + data["youtube_description"])
    if args.dry_run:
        print("\n[dry run] nothing uploaded")
        return

    key = os.environ.get("UPLOAD_API_KEY")
    if not key:
        sys.exit("UPLOAD_API_KEY not set")
    with open(mp4, "rb") as v, open(thumb, "rb") as t, open(srt, "rb") as s:
        resp = requests.post(
            API,
            headers={"Authorization": f"Apikey {key}"},
            files={"video": (upload_filename(film), v, "video/mp4"),
                   "thumbnail": (upload_filename(film, ".jpg"), t, "image/jpeg"),
                   "youtube_subtitle_file": (upload_filename(film, ".srt"), s, "text/plain")},
            data=data,
            timeout=1800,
        )
    print(f"\nHTTP {resp.status_code}\n{resp.text[:1500]}")
    (out / "publish-result.json").write_text(resp.text)
    if not resp.ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
