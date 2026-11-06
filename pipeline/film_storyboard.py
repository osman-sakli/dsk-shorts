"""Build a single self-contained HTML storyboard for a film: every keyframe
inlined as a data URI next to the shot it opens and closes, with the
dialogue, lesson and budget — the review page to look at BEFORE any video
money is spent.

Usage:
    python3 pipeline/film_storyboard.py content/film-01.json [out.html]
"""
import base64
import html
import json
import pathlib
import sys

VIDEO_USD_PER_SEC = {"480p": 0.2205, "720p": 0.4730, "1080p": 1.164}


def img_tag(path, alt):
    if not path.exists():
        return f'<div class="missing">{html.escape(alt)}<br><small>not generated yet</small></div>'
    b64 = base64.b64encode(path.read_bytes()).decode()
    return f'<img src="data:image/png;base64,{b64}" alt="{html.escape(alt)}" loading="lazy">'


def main(script, out=None):
    film = json.loads(pathlib.Path(script).read_text())
    kfdir = pathlib.Path("out") / film["id"] / "keyframes"
    out = pathlib.Path(out) if out else pathlib.Path("out") / film["id"] / "storyboard.html"
    kfs = {k["id"]: k for k in film["keyframes"]}
    secs = film["shotSeconds"]
    n = len(film["shots"])
    cost = {r: VIDEO_USD_PER_SEC[r] * secs * n for r in VIDEO_USD_PER_SEC}

    rows = []
    for s in film["shots"]:
        lines = "".join(f'<li><b>{html.escape(d["who"])}</b> — {html.escape(d["line"])}</li>' for d in s["dialogue"])
        rows.append(f"""
<section class="shot">
  <header><span class="n">Shot {s['n']}</span> <h2>{html.escape(s['act'])}</h2>
    <span class="meta">{s['start']} → {s['end']}{' · continues shot ' + str(s['continuesFrom']) if s.get('continuesFrom') else ' · cut'}</span></header>
  <div class="frames">
    <figure>{img_tag(kfdir / (s['start'] + '.png'), s['start'])}<figcaption><b>{s['start']}</b> — first frame<br>{html.escape(kfs[s['start']]['frame'])}</figcaption></figure>
    <figure>{img_tag(kfdir / (s['end'] + '.png'), s['end'])}<figcaption><b>{s['end']}</b> — last frame<br>{html.escape(kfs[s['end']]['frame'])}</figcaption></figure>
  </div>
  <div class="text">
    {('<p class="lesson">🛡️ ' + html.escape(s['lesson']) + '</p>') if s.get('lesson') else ''}
    <p><b>Action.</b> {html.escape(s['action'])}</p>
    <ul>{lines}</ul>
    <p class="cam"><b>Camera.</b> {html.escape(s['camera'])}</p>
  </div>
</section>""")

    page = f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(film['title'])} — Storyboard</title>
<style>
  :root {{ --navy:#0d1b3e; --gold:#c9a84c; --light:#f4f6fb; --gray:#6c757d; }}
  body {{ margin:0; font-family: 'Nunito Sans', system-ui, sans-serif; background: var(--light); color:#2d3748; }}
  .hero {{ background: linear-gradient(135deg,#1a2f6e,#0d1b3e); color:#fff; padding: 2.2rem 1.5rem; }}
  .hero h1 {{ margin:0 0 .4rem; font-size: 1.9rem; }} .hero p {{ margin:.2rem 0; color:#cdd7f0; max-width: 820px; }}
  .wrap {{ max-width: 1100px; margin: 0 auto; padding: 1.5rem; }}
  .budget {{ background:#fff; border-radius: 14px; padding: 1rem 1.3rem; margin-bottom: 1.5rem; box-shadow:0 4px 18px rgba(13,27,62,.07); }}
  .budget table {{ border-collapse: collapse; font-size:.9rem; }} .budget td, .budget th {{ padding: 4px 14px 4px 0; text-align:left; }}
  .shot {{ background:#fff; border-radius: 16px; padding: 1.2rem 1.4rem; margin-bottom: 1.4rem; box-shadow:0 4px 18px rgba(13,27,62,.07); }}
  header {{ display:flex; align-items:baseline; gap: .8rem; flex-wrap: wrap; margin-bottom: .8rem; }}
  .n {{ background: var(--navy); color: var(--gold); font-weight: 900; padding: 3px 10px; border-radius: 10px; font-size:.78rem; }}
  h2 {{ margin:0; font-size: 1.15rem; color: var(--navy); }} .meta {{ color: var(--gray); font-size:.8rem; font-weight:700; }}
  .frames {{ display:grid; grid-template-columns: 1fr 1fr; gap: 1rem; }}
  figure {{ margin:0; }} figure img {{ width:100%; border-radius: 10px; display:block; aspect-ratio:16/9; object-fit:cover; background:#ddd; }}
  figcaption {{ font-size:.76rem; color: var(--gray); margin-top:.4rem; line-height:1.45; }}
  .missing {{ aspect-ratio:16/9; display:flex; align-items:center; justify-content:center; background:#e9edf6; border-radius:10px; color:var(--gray); text-align:center; }}
  .text {{ margin-top: .9rem; font-size:.9rem; line-height: 1.6; }} .lesson {{ background:#fdf3dc; border-left: 4px solid var(--gold); padding: 8px 12px; border-radius: 8px; }}
  ul {{ padding-left: 1.2rem; }} .cam {{ color: var(--gray); }}
  @media (max-width: 700px) {{ .frames {{ grid-template-columns: 1fr; }} }}
</style></head><body>
<div class="hero"><h1>🎬 {html.escape(film['title'])} — storyboard</h1>
<p>{html.escape(film.get('logline',''))}</p>
<p>{n} shots × {secs}s = {n*secs//60} min · {film['aspectRatio']} · keyframes by {html.escape(film['imageModel'])} · video by {html.escape(film['videoModel'])}</p></div>
<div class="wrap">
<div class="budget"><b>Budget</b> — keyframes ~${0.15*len(film['keyframes']):.2f} (done once). Video, 8 × 30s:
<table><tr><th>480p</th><td>${cost['480p']:.2f}</td><td>fits the $100 with margin</td></tr>
<tr><th>720p</th><td>${cost['720p']:.2f}</td><td>needs ~$20 more, or 7 shots (3.5 min) for ~$99</td></tr>
<tr><th>1080p</th><td>${cost['1080p']:.2f}</td><td>out of reach for now</td></tr></table></div>
{''.join(rows)}
</div></body></html>"""
    out.write_text(page)
    print(f"storyboard -> {out} ({out.stat().st_size//1024} KB)")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
