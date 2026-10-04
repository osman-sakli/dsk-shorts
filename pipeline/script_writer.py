"""Writes a brand-new ai-scripts.json entry on a topic not yet covered,
every NEW_SCRIPT_INTERVAL_DAYS (see entrypoint.py's bump_new_script_counter).

Uses the same Claude-via-fal.ai-OpenRouter-proxy call as the LinkedIn
research post (reuses FAL_API_KEY, no new secret), then commits the new
entry straight into content/ai-scripts.json on the default branch via
GitHub's Contents API — not a git CLI commit, since the running container
has no .git working tree, just the image baked from a prior checkout.
"""
import base64
import json
import os
import re

import requests

FAL_API_KEY = os.environ["FAL_API_KEY"]
VALID_CHARACTERS = {"shieldy", "pixel", "glitch", "bot", "dame-noble", "sprout"}

SYSTEM_PROMPT = """You write short-video scripts for Digital Safety Knights (DSK), a free child
digital-safety education nonprofit. Every short is a ~15-second 3D-animated scene starring 2-3 of
a permanent cast of 6 mascots: shieldy (gold knight, calm protector), pixel (eager kid gamer),
glitch (a trickster/scammer-coded character — the "danger" character for scam/stranger-danger
topics), bot (an AI/robot character — for AI-safety topics), dame-noble (rose-gold girl knight,
warm and steady), sprout (a small, shy child character).

Each script teaches exactly ONE concrete digital-safety lesson a child (roughly ages 7-13) can
actually use — a specific danger, trick, or rule, made vivid through one small scene, not a
lecture. Structure: one character encounters or almost falls for the danger; another character
(usually shieldy or dame-noble) steps in with a short, warm, specific line of advice; the danger
character or moment resolves safely. 2-4 lines of dialogue total, each short enough to read
clearly in 15 seconds.

Output ONLY a JSON object, no other text, with exactly these fields:
{
  "title": "Short, specific title (4-8 words) naming the lesson, not the danger alone",
  "characters": ["name1", "name2"],
  "prompt": "The full Seedance video-generation prompt..."
}

Rules for "characters": exactly 2 or 3 names, only from: shieldy, pixel, glitch, bot, dame-noble,
sprout.

Rules for "prompt": third person, present tense. Reference each character as @Image1, @Image2,
@Image3 IN THE SAME ORDER as the characters array, describing the scene, action, and exact
dialogue each character says in quotes. Must include verbatim the sentence: "CRITICAL: render NO
letters, NO words, NO numbers and NO writing anywhere in frame." Must include "Vertical 9:16."
End on a warm, resolved, kid-friendly note — never scary, never graphic. Match the tone and
structure of a children's educational cartoon.

Never frame the scene around a close-up of a screen, phone, chat window, keyboard, or any other
UI surface (buttons, checkboxes, menus) — even without readable text, the video model renders
these as garbled, broken-looking nonsense. Keep the camera on the characters themselves reacting
and talking to each other in a physical or clearly fantastical setting (a room, a courtyard, a
treehouse, an abstract glowing space) — a device can be mentioned in dialogue or gestured at
off-screen, but must never be the visual focus of the shot.

The topic must be genuinely new — not a rephrasing of any lesson already covered (a full list of
already-covered titles is provided in the user message; do not repeat their core lesson or
danger). Prefer a real, current kind of online risk a child could actually encounter, grounded in
something plausible today — not a dated or already-well-worn example."""


def _slug(title):
    s = re.sub(r"[^a-z0-9\s-]", "", title.lower())
    s = re.sub(r"\s+", "-", s.strip())
    return re.sub(r"-+", "-", s)[:40].strip("-")


def _next_id(existing_scripts):
    nums = [int(re.match(r"ai-(\d+)-", s["id"]).group(1)) for s in existing_scripts]
    return max(nums) + 1


def _call_claude(system, user):
    resp = requests.post(
        "https://fal.run/openrouter/router/openai/v1/chat/completions",
        headers={"Authorization": f"Key {FAL_API_KEY}", "Content-Type": "application/json"},
        json={
            "model": "anthropic/claude-sonnet-4.5",
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        },
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def _parse_and_validate(raw):
    text = re.sub(r"^```(json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
    data = json.loads(text)
    title = data["title"].strip()
    characters = [c.strip().lower() for c in data["characters"]]
    prompt = data["prompt"].strip()

    if not (2 <= len(characters) <= 3):
        raise ValueError(f"expected 2-3 characters, got {characters}")
    if not all(c in VALID_CHARACTERS for c in characters):
        raise ValueError(f"invalid character name(s) in {characters}")
    if "CRITICAL: render NO letters" not in prompt:
        prompt += (
            " CRITICAL: render NO letters, NO words, NO numbers and NO writing anywhere in frame."
        )
    if "9:16" not in prompt:
        prompt += " Vertical 9:16."
    for i in range(len(characters)):
        if f"@Image{i + 1}" not in prompt:
            raise ValueError(f"prompt missing @Image{i + 1} for character {characters[i]}")

    return {"title": title, "characters": characters, "prompt": prompt}


def generate_new_script(existing_scripts, max_attempts=3):
    """Returns {title, characters, prompt} — no "id" yet. The id is assigned
    in commit_new_script_to_github() from the live GitHub file, not from
    existing_scripts here, since existing_scripts is whatever list the
    *locally baked image* happened to load, which could in principle be a
    build or two behind the real file (e.g. a missed CI rebuild) — assigning
    against the live file is what actually prevents an id collision."""
    covered = "\n".join(f"- {s['title']}" for s in existing_scripts)
    user_prompt = (
        f"Already-covered lessons (do not repeat these):\n{covered}\n\n"
        f"Write one brand-new script now, on a genuinely different lesson."
    )
    last_error = None
    for attempt in range(1, max_attempts + 1):
        try:
            raw = _call_claude(SYSTEM_PROMPT, user_prompt)
            return _parse_and_validate(raw)
        except Exception as e:  # noqa: BLE001 — retry on any parse/validation failure
            last_error = e
            user_prompt += (
                f"\n\n(Previous attempt failed validation: {e}. Fix it and output valid JSON only, "
                f"no other text.)"
            )
    raise RuntimeError(f"generate_new_script failed after {max_attempts} attempts: {last_error}")


def commit_new_script_to_github(new_script, github_token, github_repo, path="content/ai-scripts.json"):
    """Assigns new_script["id"] from the live file's own contents (see the
    note in generate_new_script for why), appends it, and commits directly
    to the default branch via GitHub's Contents API — the running container
    has no git working tree (just the image baked from a prior checkout), so
    this is a real API commit, not `git commit` + `git push`. Pushing to
    content/** also triggers build-and-push.yml, rebuilding the image so the
    new script is baked in for future runs. Mutates and returns new_script
    with its id set, so the caller can use it to name/render/publish today's
    video."""
    api_base = f"https://api.github.com/repos/{github_repo}/contents/{path}"
    headers = {
        "Authorization": f"Bearer {github_token}",
        "Accept": "application/vnd.github+json",
    }
    resp = requests.get(api_base, headers=headers, timeout=15)
    resp.raise_for_status()
    current = resp.json()
    scripts = json.loads(base64.b64decode(current["content"]).decode("utf-8"))
    next_num = _next_id(scripts)
    new_script["id"] = f"ai-{next_num:03d}-{_slug(new_script['title'])}"
    scripts.append(new_script)
    new_content = json.dumps(scripts, indent=2, ensure_ascii=False) + "\n"

    put_resp = requests.put(
        api_base,
        headers=headers,
        json={
            "message": f"Add new short-video script: {new_script['id']} ({new_script['title']})",
            "content": base64.b64encode(new_content.encode("utf-8")).decode("ascii"),
            "sha": current["sha"],
        },
        timeout=15,
    )
    put_resp.raise_for_status()
    return new_script
