export const MONTHS = ["J","F","M","A","M","J","J","A","S","O","N","D"];
export const CMAP = {
  T:  ["#313695","#74add1","#fee090","#f46d43","#a50026"],   // RdYlBu_r
  RR: ["#ffffcc","#a1dab4","#41b6c4","#2c7fb8","#253494"],   // YlGnBu
  fav:["#ffffe5","#d9f0a3","#78c679","#238443","#004529"],   // YlGn
  sm: ["#8c510a","#d8b365","#f6e8c3","#c7eae5","#5ab4ac","#01665e"], // BrBG (sec→humide)
  alt:["#3a7d3a","#a6cf6a","#f1e0a0","#b08040","#8b5a2b","#ffffff"], // hypsométrique
  fruit:["#ffffb2","#fecc5c","#fd8d3c","#f03b20","#bd0026"],         // YlOrRd (indice de pousse)
};
export const LEVEL = {
  good: ["Favorable", "text-green-700", "bg-green-100"],
  mid:  ["Conditions partielles", "text-amber-700", "bg-amber-100"],
  bad:  ["Peu probable", "text-red-700", "bg-red-100"],
  off:  ["Hors saison", "text-slate-500", "bg-slate-100"],
};

export const state = {
  dates: [], period: "jour", selectedDates: [],
  map: null, layers: {}, lastPoint: null, name: null,
  species: null, allSpecies: [], godmode: false, activeLayer: "radar", legendData: {}, legendMaxH: 0,
  spots: [], spotLayer: null, lastSpot: null,
  radarSpecies: null,   // sous-ensemble actif sur le calque radar (null = toute la pré-sélection)
  tab: "carte",
  // replié par défaut sur petit écran (téléphone) pour laisser la carte en plein
  sidebarCollapsed: !!(window.matchMedia && window.matchMedia("(max-width: 1023px)").matches),
};

// Coloration des facteurs météo de la fiche : vert = favorable, orange = limite,
// rouge = défavorable (atténue). Seuils « grand public » (pas par espèce).
// Tuiles sur fiches sombres (DA) : fond os/5 relevé, code couleur porté par
// le texte + le liseré (vert/ambre/rouge) ; neutre = os.
export const FACTOR_CLR = {
  good: "bg-green-500/10 border-green-500/30 text-green-300",
  mid:  "bg-amber-500/10 border-amber-500/30 text-amber-300",
  bad:  "bg-red-500/10 border-red-500/30 text-red-300",
  off:  "bg-os/5 border-os/10 text-os",
};

// Noms lisibles des calques (pour le titre affiché quand le volet est replié).
export const LAYER_NAMES = {
  radar: "🍄 Radar à champignons", temp: "Température moyenne", precip: "Précipitations",
  forest: "Forêts — BD Forêt® IGN", soil: "Type de sol — SoilGrids®",
  soilmoist: "Humidité du sol", altitude: "Altitude / relief", aspect: "Exposition (versants)",
};

export const CONF_BADGE = {
  "élevée": "bg-green-100 text-green-700",
  "bonne": "bg-amber-100 text-amber-700",
  "modérée": "bg-slate-100 text-slate-500",
};

/* ---------- Légende (calque actif) ---------- */
// BD Forêt® V2 (IGN) — 32 types de formation végétale, couleurs exactes du calque
// (échantillonnées sur la légende officielle IGN). [couleur, libellé court, libellé complet].
export const FOREST_TFV = [
  ["#e5c45d", "Sans couvert arboré", "Forêt fermée sans couvert arboré"],
  ["#008c4d", "Feuillus en îlots", "Forêt fermée de feuillus purs en îlots"],
  ["#004d2e", "Chênes décidus", "Forêt fermée de chênes décidus purs"],
  ["#668040", "Chênes sempervirents", "Forêt fermée de chênes sempervirents purs"],
  ["#00ff80", "Hêtre", "Forêt fermée de hêtre pur"],
  ["#40ff1c", "Châtaignier", "Forêt fermée de châtaignier pur"],
  ["#915633", "Robinier", "Forêt fermée de robinier pur"],
  ["#afca59", "Autre feuillu", "Forêt fermée d'un autre feuillu pur"],
  ["#00d92f", "Mélange feuillus", "Forêt fermée à mélange de feuillus"],
  ["#8080ff", "Conifères en îlots", "Forêt fermée de conifères purs en îlots"],
  ["#bf26ff", "Pin maritime", "Forêt fermée de pin maritime pur"],
  ["#9926ff", "Pin sylvestre", "Forêt fermée de pin sylvestre pur"],
  ["#4d33ff", "Pin laricio / noir", "Forêt fermée de pin laricio ou pin noir pur"],
  ["#ff1aff", "Pin d'Alep", "Forêt fermée de pin d'Alep pur"],
  ["#734de6", "Pin à crochets / cembro", "Forêt fermée de pin à crochets ou pin cembro pur"],
  ["#a666ff", "Autre pin", "Forêt fermée d'un autre pin pur"],
  ["#d999ff", "Mélange de pins", "Forêt fermée à mélange de pins purs"],
  ["#1ae6e6", "Sapin / épicéa", "Forêt fermée de sapin ou épicéa"],
  ["#4d80ff", "Mélèze", "Forêt fermée de mélèze pur"],
  ["#3399ff", "Douglas", "Forêt fermée de douglas pur"],
  ["#00929f", "Mélange autres conifères", "Forêt fermée à mélange d'autres conifères"],
  ["#59ffff", "Autre conifère", "Forêt fermée d'un autre conifère pur autre que pin"],
  ["#404dff", "Mélange conifères", "Forêt fermée à mélange de conifères"],
  ["#ff6633", "Feuillus + conifères", "Forêt fermée à mélange de feuillus prépondérants et conifères"],
  ["#ff4033", "Conifères + feuillus", "Forêt fermée à mélange de conifères prépondérants et feuillus"],
  ["#b3b3b3", "Ouverte : sans couvert", "Forêt ouverte sans couvert arboré"],
  ["#ccffbf", "Ouverte : feuillus", "Forêt ouverte de feuillus purs"],
  ["#99b3cc", "Ouverte : conifères", "Forêt ouverte de conifères purs"],
  ["#ffd138", "Ouverte : mixte", "Forêt ouverte à mélange de feuillus et conifères"],
  ["#ffff00", "Peupleraie", "Peupleraie"],
  ["#ffe6bf", "Lande", "Lande"],
  ["#fff9a5", "Formation herbacée", "Formation herbacée"],
];

export const FR_MONTHS = ["janvier","février","mars","avril","mai","juin","juillet","août","septembre","octobre","novembre","décembre"];
