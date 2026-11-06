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
import sys

import requests

API = "https://api.upload-post.com/api/upload"
UPLOAD_POST_PROFILE = os.environ.get("UPLOAD_POST_PROFILE", "DSK")


def build(film, out):
    title = f"{film['title']} — A Digital Safety Knights Film (Episode 1)"
    lessons = "\n".join(f"• {l}" for l in film.get("lessons", []))
    description = f"""{film['logline']}

{film['title']} is the first full-length Digital Safety Knights film — a {film['runtimeSeconds'] // 60}-minute animated story for children about one of the hardest things to teach: what it feels like when someone online is too friendly, too generous, and too keen to keep it secret.

What the film teaches:
{lessons}

Digital Safety Knights is a free nonprofit that teaches children and families how to stay safe online — scams, AI chatbots and deepfakes, strangers, cyberbullying and privacy. Everything we make is free, in English, Spanish and Turkish: short videos, quizzes, printable guides for parents, and live workshops for schools and community organisations.

Watch this film, the short episodes and the quizzes:
https://digitalsafetyknights.org/films.html
Free guides for parents and teachers:
https://digitalsafetyknights.org/resources.html
Book a free school or community session:
https://digitalsafetyknights.org/school-programs.html

If something ever happens online that worries a child: tell a trusted adult first — nobody is in trouble for asking for help. In the US you can report at CyberTipline.org, or call or text 988 any time, free and confidential.

This film's animation and music are AI-generated; the story, the script and every safety message in it are written and reviewed by our team.

#onlinesafety #digitalsafety #parenting #kidsafety #animation"""
    tags = ["online safety", "digital safety", "kids safety", "internet safety for kids",
            "stranger danger", "online predators", "parenting", "child safety",
            "animated short film", "digital safety knights", "cyber safety", "online grooming",
            "safety for children", "educational animation"]
    return {
        "user": UPLOAD_POST_PROFILE,
        "platform[]": None,  # filled per run
        "title": title,
        "youtube_description": description,
        "tags[]": tags,
        "categoryId": "27",            # Education
        "privacyStatus": "public",
        # The channel is Made-for-Kids at channel level (see entrypoint.py);
        # an explicit per-video value would override it, so it is not sent.
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
            files={"video": (mp4.name, v, "video/mp4"),
                   "thumbnail": (thumb.name, t, "image/jpeg"),
                   "youtube_subtitle_file": (srt.name, s, "text/plain")},
            data=data,
            timeout=1800,
        )
    print(f"\nHTTP {resp.status_code}\n{resp.text[:1500]}")
    (out / "publish-result.json").write_text(resp.text)
    if not resp.ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
