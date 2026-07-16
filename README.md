# DSK Shorts 🛡️

Automated 10–15s educational shorts pipeline for **Digital Safety Knights**
(digitalsafetyknights.org) — YouTube Shorts, TikTok, Instagram Reels, Facebook.

Kids' online-safety lessons delivered by 4 recurring characters:

| Character | Role | Voice profile |
|---|---|---|
| **Sir Shieldy** | Hero, teaches the rule | warm, confident |
| **Pixel** | Kid who makes the mistake | energetic, curious |
| **Glitch** | Comic villain (scams/predators, abstracted) | sneaky-funny |
| **Bot** | Confidently-wrong AI | flat robotic |

## Stack

- **Remotion** — programmatic video (same approach as pencil-shorts)
- **edge-tts** (Python) — character voices
- **Script-as-JSON** — `content/scripts/*.json` drive everything
- Target: 1080×1920 (9:16), 30fps, ~12–14s

## Quick start

```bash
npm install
pip install -r pipeline/requirements.txt

# 1. Generate TTS audio for a script
python pipeline/tts.py content/scripts/001-knight-rule-1.json

# 2. Preview in Remotion Studio
npx remotion studio

# 3. Render one short
bash pipeline/render.sh 001-knight-rule-1

# 4. Render everything
for f in content/scripts/*.json; do bash pipeline/render.sh $(basename $f .json); done
```

## Content pipeline

1. Pick the day's topic from `content/calendar-30day.json`
2. Write/generate a script JSON (see `content/scripts/` for the format)
3. `tts.py` → per-line MP3s + `timing.json` into `assets/audio/<id>/`
4. `render.sh` → `out/<id>.mp4`
5. Upload (manual for now; `pipeline/publish.md` tracks the automation plan)

## Script JSON format

```json
{
  "id": "001-knight-rule-1",
  "title": "Knight Rule #1 — Real Names",
  "scene": "game-chat",
  "lines": [
    { "who": "PIXEL",   "text": "Hi! My name is—" },
    { "who": "SHIELDY", "text": "Woah woah woah! Knight Rule number one!" }
  ]
}
```

`who` maps to a character component + voice in `content/characters.json`.
Every video auto-appends the **"Shield up!"** outro (logo + site).

## Publishing to GitHub

```bash
gh repo create dsk-shorts --private --source . --push
# or manually:
git remote add origin git@github.com:<you>/dsk-shorts.git
git push -u origin main
```

## Roadmap

- [ ] Replace placeholder SVG characters with final art (see Character Bible)
- [ ] Lip-sync (reuse pencil-shorts approach)
- [ ] Batch weekly render on Fargate
- [ ] Auto-captions + per-platform caption/hashtag templates
- [ ] Upload automation (YouTube Data API first)

— Built by the DSK father–daughter team. Shield up! 🛡️
