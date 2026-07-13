# Générateurs du kit réseaux Sporia

Scripts qui produisent les visuels réseaux (DA « Girolle × Cèpe »). Nécessitent Python + Pillow,
les polices dans `web/vendor/`, et les photos détourées dans `ressources/` (non versionné — dossier
de travail local).

- **`build_svg.py`** — génère les SVG natifs éditables dans `brand/templates/social/`.
  Données des visuels (accroches, accents, photos, extras) définies dans les listes `LOT1`, `LOT2`,
  `METEO`. Usage : `python build_svg.py [all|lot1|lot2|meteo|<id>]`.
  Pour ajuster un placement : modifier la donnée du visuel puis relancer sur son id.
- **`build_gallery.py`** — assemble les galeries HTML de validation à partir d'un template
  (`social_gallery_template.html`, `social_gallery2_template.html`, `meteo_template.html`).
  Usage : `python build_gallery.py <template.html> <sortie.html>`.
- **`assemble_svg_preview.py`** — construit une page d'aperçu qui inline les `.svg`
  (dédoublonne les `@font-face`). Usage : `python assemble_svg_preview.py <sortie.html> "<glob>" "<titre>"`.

Les chemins pointent vers la racine du repo en absolu (`ROOT`) — à adapter si le repo est déplacé.
Règle contenu : aucun chiffre/citation inventé ; les champs `__ mm`, `[secteur]`… sont à remplir
avec une donnée réelle et sourcée avant publication.
