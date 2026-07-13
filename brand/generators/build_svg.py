#!/usr/bin/env python
# Génère des SVG natifs éditables (1080²/1080×1920) pour les visuels réseaux Sporia.
# Convention alignée sur brand/templates/*.svg : calques nommés, polices embarquées, <text> en px.
import base64, io, os, sys
from xml.sax.saxutils import escape

ROOT = r"d:\champi_pipeline_package"
OUTDIR = os.path.join(ROOT, "brand", "templates", "social")
os.makedirs(OUTDIR, exist_ok=True)

FONT_FILES = {
    "Clash Display": os.path.join(ROOT, "web/vendor/clash/ClashDisplay-Bold.woff2"),
    "Fraunces":      os.path.join(ROOT, "web/vendor/fraunces/Fraunces-Italic.woff2"),
    "Space Mono":    os.path.join(ROOT, "web/vendor/spacemono/SpaceMono-Regular.woff2"),
}
def _b64(p):
    with open(p, "rb") as f: return base64.b64encode(f.read()).decode("ascii")
FONT_FACE = "".join(
    f"@font-face{{font-family:'{fam}';font-display:swap;"
    f"{'font-style:italic;' if fam=='Fraunces' else ''}"
    f"src:url(data:font/woff2;base64,{_b64(p)}) format('woff2')}}"
    for fam, p in FONT_FILES.items())

def img_b64(name, maxpx=440):
    from PIL import Image
    im = Image.open(os.path.join(ROOT, "ressources", name)).convert("RGBA")
    w, h = im.size; s = maxpx / max(w, h)
    if s < 1: im = im.resize((int(w*s), int(h*s)), Image.LANCZOS)
    buf = io.BytesIO(); im.save(buf, "PNG", optimize=True)
    return base64.b64encode(buf.getvalue()).decode("ascii")

CLASH = "'Clash Display','Archivo Black','Arial Black',sans-serif"
FRAU  = "'Fraunces','Iowan Old Style',Georgia,serif"
MONO  = "'Space Mono',ui-monospace,monospace"
BODY  = "'Inter','Segoe UI',system-ui,sans-serif"
OS = "#efe6d3"; SOUSBOIS = "#191510"; PAPER = "#12100b"; MY = "#c6f24e"
G, C, LA = "#f2a93b", "#b9793f", "#d9772e"
PAD = 84

def wrap(txt, maxchars):
    out, line = [], ""
    for w in txt.split():
        if len(line) + len(w) + 1 <= maxchars: line = (line + " " + w).strip()
        else: out.append(line); line = w
    if line: out.append(line)
    return out

def tspans(line, accent):
    # line = list de segments : str (romain/Clash/os) ou (str,'i') (italique Fraunces/accent)
    s = ""
    for seg in line:
        if isinstance(seg, tuple):
            s += (f'<tspan font-family="{FRAU}" font-style="italic" font-weight="400" '
                  f'fill="{accent}" style="text-transform:none">{escape(seg[0])}</tspan>')
        else:
            s += f'<tspan>{escape(seg)}</tspan>'
    return s

def build(v):
    story = v["fmt"] == "story"
    W, H = 1080, (1920 if story else 1080)
    acc = v["accent"]
    u = v["id"].replace("-", "")            # suffixe d'id unique (sûr même inliné)
    gr, sh, gl = f"grain{u}", f"sh{u}", f"glow{u}"
    L = []
    L.append(f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
             f'viewBox="0 0 {W} {H}" width="{W}" height="{H}">')
    L.append(f'<defs><style>{FONT_FACE}</style>'
             f'<filter id="{gr}"><feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="2" stitchTiles="stitch"/><feColorMatrix type="saturate" values="0"/></filter>'
             f'<filter id="{sh}" x="-30%" y="-30%" width="160%" height="160%"><feDropShadow dx="0" dy="18" stdDeviation="16" flood-color="#000" flood-opacity="0.55"/></filter>'
             f'<radialGradient id="{gl}" cx="50%" cy="34%" r="52%"><stop offset="0%" stop-color="{acc}" stop-opacity="0.30"/><stop offset="100%" stop-color="{acc}" stop-opacity="0"/></radialGradient>'
             '</defs>')
    # 01 fond
    L.append(f'<g id="01-fond"><rect width="{W}" height="{H}" fill="{SOUSBOIS}"/></g>')
    # 02 décor / photo (derrière le texte)
    dec = [f'<g id="02-decor">']
    ex = v.get("extra")
    if ex == "glow":
        dec.append(f'<rect width="{W}" height="{H}" fill="url(#{gl})"/>')
    if ex == "ring":
        cx, cy, r = W*0.52, H*0.66, W*0.26
        dec.append(f'<circle cx="{cx:.0f}" cy="{cy:.0f}" r="{r:.0f}" fill="none" stroke="{OS}" '
                   f'stroke-opacity="0.28" stroke-width="10" stroke-dasharray="4 22" stroke-linecap="round"/>')
        import math
        for i in range(7):
            a = -1.3 + i*(2*math.pi/7)
            px, py = cx + r*math.cos(a), cy + r*math.sin(a)
            dec.append(f'<ellipse cx="{px:.0f}" cy="{py:.0f}" rx="17" ry="21" fill="{OS}" opacity="0.55"/>')
    if ex == "net":
        # réseau mycélien (bas de la story)
        oy = H*0.60
        dec.append(f'<g transform="translate(0,{oy:.0f})" stroke="{OS}" stroke-opacity="0.3" stroke-width="5" fill="none">'
                   '<path d="M150 360 L370 235 L625 320 L475 130 L840 195 M625 320 L885 360 M370 235 L215 110"/></g>')
        nodes = [(150,360),(370,235),(625,320),(475,130),(840,195),(885,360),(215,110)]
        g = f'<g transform="translate(0,{oy:.0f})" fill="{acc}">'
        for i,(nx,ny) in enumerate(nodes):
            g += f'<circle cx="{nx}" cy="{ny}" r="{24 if i in (1,2) else 19}"/>'
        dec.append(g + '</g>')
    if v.get("rain"):
        rc = MY if v["rain"] == "cool" else G
        step = 74
        rl = [f'<g stroke="{rc}" stroke-opacity="0.13" stroke-width="9">']
        x = -int(H*0.42)
        while x < W:
            rl.append(f'<line x1="{x+int(H*0.42)}" y1="0" x2="{x}" y2="{H}"/>')
            x += step
        dec.append("".join(rl) + '</g>')
    for p in ([v["photo"]] if v.get("photo") else []) + v.get("photos", []):
        b = img_b64(p["file"])
        s = p["size"]; x = p["x"]; y = p["y"]; rot = p.get("rot", 0)
        dec.append(f'<image xlink:href="data:image/png;base64,{b}" x="{x}" y="{y}" width="{s}" height="{s}" '
                   f'preserveAspectRatio="xMidYMid meet" transform="rotate({rot} {x+s/2:.0f} {y+s/2:.0f})" filter="url(#{sh})"/>')
    dec.append('</g>')
    L.append("".join(dec))
    # 03 grain
    L.append(f'<g id="03-grain"><rect width="{W}" height="{H}" filter="url(#{gr})" opacity="0.07"/></g>')
    # 05 titre (eyebrow + head + éventuel list + stamp + sub)
    T = ['<g id="05-titre">']
    ey = 175
    T.append(f'<text x="{PAD}" y="{ey}" font-family="{MONO}" font-size="27" letter-spacing="5" '
             f'fill="{acc}" style="text-transform:uppercase">{escape(v["eyebrow"])}</text>')
    hsize = 108 if not story else 116
    adv = int(hsize*0.94)
    hy = ey + 128
    for line in v["head"]:
        T.append(f'<text x="{PAD}" y="{hy}" font-family="{CLASH}" font-weight="800" font-size="{hsize}" '
                 f'letter-spacing="-2" fill="{OS}" style="text-transform:uppercase">{tspans(line, acc)}</text>')
        hy += adv
    cur = hy + 20
    if v.get("list"):
        for it in v["list"]:
            T.append(f'<text x="{PAD}" y="{cur}" font-family="{BODY}" font-size="40" fill="{OS}" fill-opacity="0.85">'
                     f'<tspan fill="{acc}" font-weight="700">•</tspan> {escape(it)}</text>')
            cur += 62
        cur += 12
    if v.get("stamp"):
        sx, sy = PAD+6, cur+8
        T.append(f'<g transform="rotate(-6 {sx+120} {sy})">'
                 f'<rect x="{sx}" y="{sy-70}" width="240" height="96" rx="14" fill="none" stroke="{acc}" stroke-width="8"/>'
                 f'<text x="{sx+120}" y="{sy-4}" text-anchor="middle" font-family="{CLASH}" font-weight="800" '
                 f'font-size="72" fill="{acc}" style="text-transform:uppercase">{escape(v["stamp"])}</text></g>')
        cur += 70
    if v.get("bignum"):
        bn = v["bignum"]; num = bn["text"]; unit = bn.get("unit", "")
        bs = 138                                   # taille du chiffre
        numw = len(num) * 0.62 * bs
        unitw = len(unit) * 0.62 * 34
        boxw = int(max(numw, unitw) + 90)
        boxh = bs + (52 if unit else 0) + 76
        top = cur                                  # haut du cadre
        by = top + 40 + bs                         # baseline du chiffre
        T.append(f'<rect x="{PAD}" y="{top}" width="{boxw}" height="{boxh}" rx="24" fill="{MY}" fill-opacity="0.08" '
                 f'stroke="{MY}" stroke-opacity="0.55" stroke-width="4" stroke-dasharray="10 10"/>')
        T.append(f'<text x="{PAD+44}" y="{by}" font-family="{CLASH}" font-weight="800" font-size="{bs}" '
                 f'fill="{MY}">{escape(num)}</text>')
        if unit:
            T.append(f'<text x="{PAD+44}" y="{by+50}" font-family="{MONO}" font-size="34" fill="{OS}" '
                     f'fill-opacity="0.7">{escape(unit)}</text>')
        cur = top + boxh + 34
    sub_y = cur + 66
    for ln in wrap(v["sub"], 44):
        T.append(f'<text x="{PAD}" y="{sub_y}" font-family="{BODY}" font-size="38" fill="{OS}" '
                 f'fill-opacity="0.82">{escape(ln)}</text>')
        sub_y += 52
    tail = sub_y + 4
    if v.get("data"):
        d = v["data"]
        dy = (H - 236) if story else tail       # sur story : ancré en bas
        T.append(f'<rect x="{PAD}" y="{dy-58}" width="732" height="104" rx="20" fill="{MY}" fill-opacity="0.08" '
                 f'stroke="{MY}" stroke-opacity="0.45" stroke-width="4"/>')
        T.append(f'<text x="{PAD+28}" y="{dy+8}" font-family="{MONO}" font-size="44" fill="{MY}">{escape(d["text"])}</text>')
        if d.get("ex"):
            T.append(f'<rect x="{PAD+566}" y="{dy-28}" width="140" height="46" rx="10" fill="{MY}"/>'
                     f'<text x="{PAD+636}" y="{dy+4}" text-anchor="middle" font-family="{MONO}" font-size="24" '
                     f'fill="{SOUSBOIS}" style="text-transform:uppercase">{escape(d["ex"])}</text>')
        if not story: tail += 120
    if v.get("cta"):
        cy = (H - 214) if story else tail       # sur story : ancré en bas
        T.append(f'<rect x="{PAD}" y="{cy-56}" width="560" height="80" rx="16" fill="{acc}"/>'
                 f'<text x="{PAD+34}" y="{cy-4}" font-family="{MONO}" font-size="32" fill="{SOUSBOIS}">{escape(v["cta"])}</text>')
        if not story: tail += 100
    if v.get("radar"):
        ry0 = tail; rh = (H-96-70) - ry0; rw = W-2*PAD
        if rh > 160:
            T.append(f'<rect x="{PAD}" y="{ry0}" width="{rw}" height="{rh}" rx="26" fill="{PAPER}" '
                     f'stroke="{OS}" stroke-opacity="0.1" stroke-width="2"/>')
            for gx in range(1, 5):
                T.append(f'<line x1="{PAD+gx*rw/5:.0f}" y1="{ry0}" x2="{PAD+gx*rw/5:.0f}" y2="{ry0+rh}" stroke="{OS}" stroke-opacity="0.05"/>')
            for gy in range(1, 4):
                T.append(f'<line x1="{PAD}" y1="{ry0+gy*rh/4:.0f}" x2="{PAD+rw}" y2="{ry0+gy*rh/4:.0f}" stroke="{OS}" stroke-opacity="0.05"/>')
            dots = [(0.26,0.32,26,0.95),(0.58,0.55,18,0.8),(0.4,0.72,13,0.6),(0.7,0.28,15,0.5),(0.17,0.6,10,0.45)]
            for fx, fy, rr, op in dots:
                T.append(f'<circle cx="{PAD+fx*rw:.0f}" cy="{ry0+fy*rh:.0f}" r="{rr}" fill="{MY}" opacity="{op}"/>')
    T.append('</g>')
    L.append("".join(T))
    # 06 footer : logo + wordmark + handle
    fy = H - 96
    logo = (f'<g id="06-footer"><g transform="translate({PAD},{fy-34}) scale(1.9)">'
            '<rect x="13" y="16" width="6" height="12" rx="3" fill="#efe6d3"/>'
            '<path d="M4 17 Q16 3 28 17 Q22 21.5 16 21.5 Q10 21.5 4 17 Z" fill="#f2a93b"/>'
            '<circle cx="12" cy="12" r="1.7" fill="#191510"/><circle cx="19.5" cy="10.5" r="2.1" fill="#191510"/>'
            '<circle cx="22" cy="14.5" r="1.3" fill="#191510"/></g>'
            f'<text x="{PAD+72}" y="{fy+6}" font-family="{CLASH}" font-weight="800" font-size="46" '
            f'letter-spacing="-1" fill="{OS}" style="text-transform:uppercase">SPORIA</text>'
            f'<text x="{W-PAD}" y="{fy+2}" text-anchor="end" font-family="{MONO}" font-size="26" '
            f'fill="{OS}" fill-opacity="0.55">{escape(v.get("handle","sporia.duckdns.org"))}</text></g>')
    L.append(logo)
    L.append('</svg>')
    return "".join(L)

i = "i"
G, C, LA, MY = "#f2a93b", "#b9793f", "#d9772e", "#c6f24e"
LOT2 = [
 dict(id="L2-01-chitine", fmt="sq", accent=C, eyebrow="Le saviez-vous",
      head=[["Même matière"],["qu'une ",("carapace",i)],["d'insecte"]],
      sub="La paroi des champignons est faite de chitine — comme l'exosquelette des insectes — et non de cellulose comme les plantes."),
 dict(id="L2-02-digestion", fmt="sq", accent=G, eyebrow="Le saviez-vous",
      head=[["Ils digèrent"],["leur repas"],["de l'",("extérieur",i)]],
      sub="Un champignon sécrète des enzymes, décompose la matière autour de lui, puis absorbe les nutriments. Son estomac, c'est tout son mycélium."),
 dict(id="L2-03-bioluminescence", fmt="story", accent=G, eyebrow="Le saviez-vous", extra="glow",
      head=[["Certains"],["brillent dans"],["le ",("noir",i)]],
      sub="La bioluminescence existe chez plusieurs espèces : le « foxfire », cette lueur du bois en décomposition la nuit."),
 dict(id="L2-04-cordyceps", fmt="sq", accent=LA, eyebrow="Le saviez-vous",
      head=[["Le champignon"],["qui ",("zombifie",i)],["les fourmis"]],
      sub="Le cordyceps parasite l'insecte, manipule son comportement, puis fructifie hors de son corps. Le vrai « champignon zombie »."),
 dict(id="L2-05-ronds-sorciere", fmt="sq", accent=G, eyebrow="Le saviez-vous", extra="ring",
      head=[["Les ",("ronds de",i)],[("sorcière",i)],["ne sont pas"],["magiques"]],
      sub="Ces cercles en pré dessinent la croissance du mycélium, qui avance vers l'extérieur année après année."),
 dict(id="L2-06-champignon-paris", fmt="sq", accent=C, eyebrow="Le saviez-vous",
      head=[["Le plus mangé"],["au monde n'a"],["rien d'",("exotique",i)]],
      sub="C'est le champignon de Paris (Agaricus bisporus), de loin le plus cultivé et consommé sur la planète."),
 dict(id="L2-07-trois-modes", fmt="story", accent=G, eyebrow="Écologie",
      head=[["Trois ",("modes",i)],[("de vie",i)]],
      list=["Mycorhizien — lié à un arbre-hôte.","Saprophyte — sur bois mort, litière.","Parasite — aux dépens d'un hôte vivant."],
      sub="Savoir lequel vous cherchez change tout l'endroit où regarder."),
 dict(id="L2-08-choc-thermique", fmt="sq", accent=LA, eyebrow="Écologie",
      head=[["L'automne,"],["c'est un ",("choc",i)],[("thermique",i)]],
      sub="La baisse des températures avec l'humidité déclenche les grandes poussées. Sol trop sec ou gelé : rien ne sort."),
 dict(id="L2-09-wood-wide-web", fmt="story", accent=G, eyebrow="Écologie", extra="net",
      head=[["Les arbres se"],["parlent par"],["les ",("champignons",i)]],
      sub="Les réseaux mycorhiziens relient les racines de plusieurs arbres — le « wood wide web » — et échangent nutriments et signaux."),
 dict(id="L2-10-cuit-cru", fmt="sq", accent=LA, eyebrow="Sécurité",
      head=[["Comestible"],["cuit, ",("toxique",i)],["cru"]],
      sub="Des espèces prisées comme les morilles sont toxiques crues et ne deviennent comestibles qu'après une cuisson suffisante."),
 dict(id="L2-11-panier", fmt="sq", accent=C, eyebrow="Conseil de cueilleur", extra="photo",
      photo=dict(file="coulemelle_img180700-removebg-preview.png", size=430, x=590, y=470, rot=7),
      head=[["Le ",("panier",i),","],["pas le sac"],["plastique"]],
      sub="Un panier aéré laisse les spores se disperser en chemin et évite que la récolte ne s'écrase et fermente."),
 dict(id="L2-12-mythe-joli", fmt="sq", accent=LA, eyebrow="On déconstruit", stamp="Faux",
      head=[["« Joli et"],["parfumé, donc"],[("comestible",i)," »"]],
      sub="Aucun rapport. Des espèces mortelles sont d'apparence banale et d'odeur agréable — l'aspect ne dit rien de la toxicité."),
]

GIRO="Cantharellus-cibarius_Girolle_lagardere-removebg-preview.png"
CEPEP="Cepe_de_bordeaux-removebg-preview.png"
TROMP="black-chanterelle-removebg-preview.png"
PBLEU="Lepista_nuda_60878-removebg-preview.png"
LACTP="Lactaires1-removebg-preview.png"
COUL="coulemelle_img180700-removebg-preview.png"

LOT1 = [
 dict(id="L1-01-grand-organisme", fmt="sq", accent=G, eyebrow="Le saviez-vous",
      head=[["Le plus grand"],["être vivant"],["est un"],[("champignon",i)]],
      sub="Une armillaire de l'Oregon s'étend sur près de 9 km² sous la forêt, en un seul organisme millénaire."),
 dict(id="L1-02-regne", fmt="sq", accent=C, eyebrow="Ni plante, ni animal",
      photos=[dict(file=GIRO,size=360,x=676,y=250,rot=8), dict(file=CEPEP,size=320,x=470,y=560,rot=-10)],
      head=[["Un ",("règne",i)],["à part"]],
      sub="Génétiquement, les champignons sont plus proches de nous que des végétaux."),
 dict(id="L1-03-la-pointe", fmt="story", accent=LA, eyebrow="Ce que vous cueillez…",
      photos=[dict(file=COUL,size=560,x=496,y=380,rot=-6)],
      head=[["…n'est que"],["la ",("pointe",i)]],
      sub="L'organisme vit sous terre en mycélium toute l'année. Le chapeau n'est que sa fructification."),
 dict(id="L1-04-trompette", fmt="sq", accent=G, eyebrow="Le saviez-vous",
      photos=[dict(file=TROMP,size=430,x=616,y=500,rot=6)],
      head=[["La « trompette"],["de la mort »"],["est un ",("délice",i)]],
      sub="Un nom sinistre pour l'un des meilleurs comestibles d'automne."),
 dict(id="L1-05-pluie-poussee", fmt="story", accent=MY, eyebrow="Après la pluie", rain="cool",
      head=[["Pluie"],["aujourd'hui."],[("Cèpes",i)],["bientôt ?"]],
      sub="La plupart des espèces fructifient plusieurs jours après un bon épisode pluvieux.",
      data=dict(text="+40 mm / 48 h → J+?", ex="exemple")),
 dict(id="L1-06-pluvio-exceptionnelle", fmt="sq", accent=MY, eyebrow="Météo",
      head=[["Épisode"],[("exceptionnel",i)],["ce week-end"]],
      bignum=dict(text="__ mm", unit="/ 48 h"),
      sub="sur [région] — à remplir. La forêt va réagir."),
 dict(id="L1-07-radar", fmt="sq", accent=MY, eyebrow="Sporia", radar=True,
      head=[["Un ",("radar",i)],["à champignons"]],
      sub="Météo, forêt et sol croisés pour estimer les zones propices, jour par jour."),
 dict(id="L1-08-manifeste", fmt="story", accent=G, eyebrow="Sporia",
      photos=[dict(file=PBLEU,size=360,x=30,y=760,rot=-8), dict(file=LACTP,size=320,x=720,y=600,rot=10),
              dict(file=GIRO,size=340,x=650,y=1360,rot=-4)],
      head=[["Les"],["comestibles"],["ne sont pas"],[("beiges",i)]],
      sub="La prospection, en couleurs."),
 dict(id="L1-09-securite", fmt="sq", accent=LA, eyebrow="Sécurité",
      head=[["Un doute ?"],[("On ne mange pas.",i)]],
      sub="Sporia estime les zones propices, jamais l'espèce. Faites toujours valider votre récolte (pharmacien, société mycologique)."),
 dict(id="L1-10-beta", fmt="story", accent=G, eyebrow="Accès anticipé", handle="bêta gratuite",
      photos=[dict(file=GIRO,size=430,x=636,y=1270,rot=7)],
      head=[[("Bêta",i)],["ouverte —"],["gratuit"]],
      sub="Testez le radar à champignons cet automne.", cta="sporia.duckdns.org"),
]

METEO = [
 dict(id="M-01-pluie", fmt="sq", accent=MY, eyebrow="Après la pluie", rain="cool",
      head=[["Il a plu."],["La forêt se"],[("réveille",i)]],
      bignum=dict(text="__ mm", unit="en __ h · [secteur]"),
      sub="Une fenêtre de pousse pourrait s'ouvrir dans les prochains jours — guettez [espèces]."),
 dict(id="M-02-weekend", fmt="sq", accent=G, eyebrow="Météo cueillette", rain="warm",
      head=[["Week-end"],[("propice",i)],["en forêt ?"]],
      sub="Pluie récente __ mm · T° __ °C · sol __ %. Conditions qui s'alignent sur [secteur] — bonne fenêtre pour [espèces]."),
 dict(id="M-03-trop-sec", fmt="sq", accent=C, eyebrow="Patience",
      head=[["Encore"],["trop ",("sec",i)]],
      bignum=dict(text="__ mm", unit="depuis __ j"),
      sub="Sans pluie, pas de poussée. On patiente jusqu'au prochain épisode — et on garde ses spots au chaud."),
 dict(id="M-04-gel", fmt="sq", accent=LA, eyebrow="Fin de saison",
      head=[["Les premières"],[("gelées",i)],["approchent"]],
      sub="Encore quelques jours sur [secteur] pour les dernières [espèces] avant que le sol ne gèle et referme la saison."),
 dict(id="M-05-pluie-story", fmt="story", accent=MY, eyebrow="Après la pluie", rain="cool",
      head=[["Il a plu."],["Ça va"],[("pousser",i)," ?"]],
      bignum=dict(text="__ mm", unit="en __ h"),
      sub="Sur [secteur]. Fenêtre possible dans les prochains jours — on guette [espèces]."),
]

ALL = LOT1 + LOT2 + METEO
import xml.dom.minidom as MD
which = sys.argv[1] if len(sys.argv) > 1 else "all"
sets = {"all": ALL, "lot1": LOT1, "lot2": LOT2, "meteo": METEO}
targets = sets.get(which) or [d for d in ALL if d["id"] == which]
for v in targets:
    svg = build(v)
    MD.parseString(svg)  # valide le XML (lève si mal formé)
    out = os.path.join(OUTDIR, v["id"] + ".svg")
    with open(out, "w", encoding="utf-8") as f: f.write(svg)
    print(f"OK {v['id']}.svg  ({len(svg)//1024} Ko)")
print(f"\n-> {OUTDIR}")
