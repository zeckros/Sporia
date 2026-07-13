#!/usr/bin/env python
# Aperçu : inline les .svg dans une page HTML. Dédoublonne les @font-face (1 seul jeu partagé).
import os, glob, sys, re
SRC = r"d:\champi_pipeline_package\brand\templates\social"
OUT = sys.argv[1]
PAT = sys.argv[2] if len(sys.argv) > 2 else "*.svg"
TITLE = sys.argv[3] if len(sys.argv) > 3 else "Aperçu SVG"
files = sorted(glob.glob(os.path.join(SRC, PAT)))
STYLE_RE = re.compile(r"<style>.*?</style>", re.S)
fonts, cards = "", []
for f in files:
    name = os.path.basename(f)[:-4]
    svg = open(f, "r", encoding="utf-8").read()
    m = STYLE_RE.search(svg)
    if m and not fonts:
        fonts = m.group(0)          # garde un seul jeu de polices
    svg = STYLE_RE.sub("", svg)     # retire les @font-face dupliqués
    cards.append(f'<figure><div class="frame">{svg}</div><figcaption>{name}.svg</figcaption></figure>')
html = f"""{fonts}<style>
 body{{margin:0;background:#0f0c08;color:#efe6d3;font-family:system-ui,sans-serif}}
 .page{{max-width:1200px;margin:0 auto;padding:40px 24px 90px}}
 h1{{font-family:'Clash Display',system-ui;font-weight:800;text-transform:uppercase;font-size:26px;margin:0 0 6px}}
 p.note{{color:#b9ad93;font-size:14px;line-height:1.5;max-width:72ch;margin:0 0 32px}}
 .grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:28px;align-items:start}}
 figure{{margin:0;display:flex;flex-direction:column;gap:10px}}
 .frame{{border-radius:8px;overflow:hidden;box-shadow:0 18px 44px rgba(0,0,0,.5)}}
 .frame svg{{display:block;width:100%;height:auto}}
 figcaption{{font-family:ui-monospace,monospace;font-size:11px;color:#8f856f}}
</style>
<div class="page">
 <h1>{TITLE} ({len(files)})</h1>
 <p class="note">Rendu réel des fichiers <code>brand/templates/social/*.svg</code> (texte vectoriel éditable,
 polices embarquées). Dis-moi si un alignement/débordement est à corriger — je règle le moteur et tout se régénère.</p>
 <div class="grid">{''.join(cards)}</div>
</div>"""
open(OUT, "w", encoding="utf-8").write(html)
print(f"OK -> {OUT} ({os.path.getsize(OUT)//1024} Ko, {len(files)} svg)")
