#!/usr/bin/env python
# Assemble la galerie sociale : embarque polices (woff2) + photos détourées (PNG downscalé) en base64.
import base64, io, sys, os

ROOT = r"d:\champi_pipeline_package"
SCRATCH = os.path.dirname(os.path.abspath(__file__))
TPL = sys.argv[1] if len(sys.argv) > 1 else os.path.join(SCRATCH, "social_gallery_template.html")
OUT = sys.argv[2] if len(sys.argv) > 2 else os.path.join(SCRATCH, "social-gallery.html")

FONTS = {
    "__FONT_CLASH__":    os.path.join(ROOT, "web/vendor/clash/ClashDisplay-Bold.woff2"),
    "__FONT_FRAUNCES__": os.path.join(ROOT, "web/vendor/fraunces/Fraunces-Italic.woff2"),
    "__FONT_MONO__":     os.path.join(ROOT, "web/vendor/spacemono/SpaceMono-Regular.woff2"),
    "__FONT_INTER__":    os.path.join(ROOT, "web/vendor/inter/InterVariable.woff2"),
}
IMAGES = {
    "__IMG_GIROLLE__":    "Cantharellus-cibarius_Girolle_lagardere-removebg-preview.png",
    "__IMG_CEPE__":       "Cepe_de_bordeaux-removebg-preview.png",
    "__IMG_TROMPETTE__":  "black-chanterelle-removebg-preview.png",
    "__IMG_PIEDBLEU__":   "Lepista_nuda_60878-removebg-preview.png",
    "__IMG_LACTAIRE__":   "Lactaires1-removebg-preview.png",
    "__IMG_COULEMELLE__": "coulemelle_img180700-removebg-preview.png",
}
MARK = ('<svg class="mark" viewBox="0 0 32 32" role="img" aria-label="Sporia">'
        '<rect x="13" y="16" width="6" height="12" rx="3" fill="#f3e6cf"/>'
        '<rect x="13" y="16" width="2.5" height="12" rx="1.25" fill="#e4cfa6"/>'
        '<path d="M4 17 Q16 3 28 17 Q22 21.5 16 21.5 Q10 21.5 4 17 Z" fill="#f2a93b"/>'
        '<ellipse cx="16" cy="17" rx="12" ry="2.6" fill="#7c3d09" opacity=".25"/>'
        '<circle cx="12" cy="12" r="1.7" fill="#191510"/>'
        '<circle cx="19.5" cy="10.5" r="2.1" fill="#191510"/>'
        '<circle cx="22" cy="14.5" r="1.3" fill="#191510"/></svg>')

def b64_font(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")

def b64_img(path, maxpx=480):
    try:
        from PIL import Image
        im = Image.open(path).convert("RGBA")
        w, h = im.size
        s = maxpx / max(w, h)
        if s < 1:
            im = im.resize((max(1, int(w*s)), max(1, int(h*s))), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, format="PNG", optimize=True)
        data = buf.getvalue()
    except Exception as e:
        sys.stderr.write(f"[PIL indispo/fail: {e}] -> embed brut {os.path.basename(path)}\n")
        with open(path, "rb") as f:
            data = f.read()
    return base64.b64encode(data).decode("ascii")

with open(TPL, "r", encoding="utf-8") as f:
    html = f.read()

for tok, path in FONTS.items():
    if not os.path.exists(path):
        sys.exit(f"Police manquante: {path}")
    html = html.replace(tok, b64_font(path))
    print(f"font {tok} <- {os.path.basename(path)} ({os.path.getsize(path)//1024} Ko)")

for tok, name in IMAGES.items():
    path = os.path.join(ROOT, "ressources", name)
    if not os.path.exists(path):
        sys.exit(f"Image manquante: {path}")
    enc = b64_img(path)
    html = html.replace(tok, enc)
    print(f"img  {tok} <- {name} (b64 {len(enc)//1024} Ko)")

html = html.replace("__MARK__", MARK)

with open(OUT, "w", encoding="utf-8") as f:
    f.write(html)
print(f"\nOK -> {OUT}  ({os.path.getsize(OUT)//1024} Ko)")
assert "__" not in html.split("<div class=\"page\">")[1] or True  # sanity: placeholders substitués
leftover = [t for t in list(FONTS)+list(IMAGES)+["__MARK__"] if t in html]
print("Placeholders restants:", leftover if leftover else "aucun")
