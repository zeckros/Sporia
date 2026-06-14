/* Sporia — frontend (Leaflet + Tailwind). Parle à l'API FastAPI (server.py). */
"use strict";

const API = {
  async get(url) {
    const r = await fetch(url, { credentials: "include" });
    if (r.status === 401) throw { unauth: true };
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
    return r.json();
  },
  async post(url, body) {
    const r = await fetch(url, {
      method: "POST", credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
    return r.json();
  },
  async del(url) {
    const r = await fetch(url, { method: "DELETE", credentials: "include" });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
    return r.json();
  },
  async patch(url, body) {
    const r = await fetch(url, {
      method: "PATCH", credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
    return r.json();
  },
};

const MONTHS = ["J","F","M","A","M","J","J","A","S","O","N","D"];
const CMAP = {
  T:  ["#313695","#74add1","#fee090","#f46d43","#a50026"],   // RdYlBu_r
  RR: ["#ffffcc","#a1dab4","#41b6c4","#2c7fb8","#253494"],   // YlGnBu
  fav:["#ffffe5","#d9f0a3","#78c679","#238443","#004529"],   // YlGn
  sm: ["#8c510a","#d8b365","#f6e8c3","#c7eae5","#5ab4ac","#01665e"], // BrBG (sec→humide)
  alt:["#3a7d3a","#a6cf6a","#f1e0a0","#b08040","#8b5a2b","#ffffff"], // hypsométrique
  fruit:["#ffffb2","#fecc5c","#fd8d3c","#f03b20","#bd0026"],         // YlOrRd (indice de pousse)
};
const LEVEL = {
  good: ["Favorable", "text-green-700", "bg-green-100"],
  mid:  ["Conditions partielles", "text-amber-700", "bg-amber-100"],
  bad:  ["Peu probable", "text-red-700", "bg-red-100"],
  off:  ["Hors saison", "text-slate-500", "bg-slate-100"],
};

const state = {
  dates: [], period: "jour", selectedDates: [],
  map: null, layers: {}, lastPoint: null, name: null,
  species: null, allSpecies: [], godmode: false, activeLayer: "radar", legendData: {}, legendMaxH: 0,
  spots: [], spotLayer: null, lastSpot: null,
  radarSpecies: null,   // sous-ensemble actif sur le calque radar (null = toute la pré-sélection)
  tab: "carte",
  // replié par défaut sur petit écran (téléphone) pour laisser la carte en plein
  sidebarCollapsed: !!(window.matchMedia && window.matchMedia("(max-width: 767px)").matches),
};

/* ---------- Auth ---------- */
async function boot() {
  // Navigation accueil <-> connexion
  document.querySelectorAll(".open-login").forEach((b) => b.addEventListener("click", showLoginPage));
  document.querySelectorAll(".back-landing").forEach((b) => b.addEventListener("click", showLanding));
  setupLandingNav();
  try {
    const me = await API.get("/api/me");
    if (me.authenticated) { state.name = me.name; startApp(); return; }
  } catch (e) { /* ignore */ }
  showLanding();
}

function showLanding() {
  document.getElementById("landing-screen").classList.remove("hidden");
  document.getElementById("login-screen").classList.add("hidden");
  document.getElementById("app-screen").classList.add("hidden");
}

// Surligne le point de navigation de la section visible (slider de l'accueil).
function setupLandingNav() {
  const root = document.getElementById("landing-screen");
  const dots = Array.from(document.querySelectorAll("[data-dot]"));
  if (!root || !dots.length || !("IntersectionObserver" in window)) return;
  const setActive = (id) => dots.forEach((d) => {
    const on = d.dataset.dot === id;
    d.classList.toggle("bg-brand-500", on);
    d.classList.toggle("scale-150", on);
    d.classList.toggle("bg-slate-300/80", !on);
  });
  const io = new IntersectionObserver((entries) => {
    entries.forEach((e) => { if (e.isIntersecting) setActive(e.target.id); });
  }, { root, threshold: 0.5 });
  ["hero", "apercu", "contact"].forEach((id) => {
    const el = document.getElementById(id); if (el) io.observe(el);
  });
  setActive("hero");
}

// Modale CGU (pied de page de l'accueil)
document.querySelectorAll(".open-cgu").forEach((b) =>
  b.addEventListener("click", () => document.getElementById("cgu-modal").classList.remove("hidden")));
document.querySelectorAll(".cgu-close").forEach((b) =>
  b.addEventListener("click", () => document.getElementById("cgu-modal").classList.add("hidden")));

function showLoginPage() {
  document.getElementById("landing-screen").classList.add("hidden");
  document.getElementById("login-screen").classList.remove("hidden");
  document.getElementById("app-screen").classList.add("hidden");
  setTimeout(() => document.getElementById("login-user").focus(), 50);
}

document.getElementById("login-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const err = document.getElementById("login-error");
  err.classList.add("hidden");
  try {
    const res = await API.post("/api/login", {
      username: document.getElementById("login-user").value.trim(),
      password: document.getElementById("login-pass").value,
    });
    state.name = res.name;
    startApp();
  } catch (e) {
    err.textContent = e.message || "Échec de connexion.";
    err.classList.remove("hidden");
  }
});

document.getElementById("logout-btn").addEventListener("click", async () => {
  try { await API.post("/api/logout"); } catch (e) {}
  location.reload();
});

// Demande d'accès (landing, public) → POST /api/access-request
document.getElementById("access-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const msg = document.getElementById("access-msg");
  const btn = ev.target.querySelector("button[type=submit]");
  const show = (text, ok) => {
    msg.textContent = text;
    msg.className = "text-sm font-semibold " + (ok ? "text-green-600" : "text-red-600");
  };
  btn.disabled = true;
  try {
    await API.post("/api/access-request", {
      name: document.getElementById("ac-name").value.trim(),
      email: document.getElementById("ac-email").value.trim(),
      message: document.getElementById("ac-message").value.trim(),
      hp: document.getElementById("ac-hp").value,
    });
    ev.target.reset();
    show("Merci ! Votre demande a bien été envoyée — on vous recontacte vite.", true);
  } catch (e) {
    show(e.message || "Échec de l'envoi. Réessayez.", false);
  } finally {
    btn.disabled = false;
  }
});

/* ---------- App ---------- */
async function startApp() {
  document.getElementById("landing-screen").classList.add("hidden");
  document.getElementById("login-screen").classList.add("hidden");
  document.getElementById("app-screen").classList.remove("hidden");
  document.getElementById("nav-user").textContent = state.name || "";

  const d = await API.get("/api/dates");
  state.dates = d.dates;
  computeSelectedDates();
  initMap();
  await loadPreferences();
  wireControls();
  await setActiveLayer("radar");   // « Radar à champignons » par défaut
  setTab("carte");
  // contour France (léger)
  try {
    const gj = await API.get("/api/outline");
    if (gj && gj.type) L.geoJSON(gj, { style: { color: "#475569", weight: 1, fill: false }, interactive: false }).addTo(state.map);
  } catch (e) {}
  await loadSpots();               // spots enregistrés + alerte « propice »
}

function initMap() {
  // Contrôles à DROITE : la barre latérale (tiroir absolu à gauche) ne les couvre
  // jamais, même ouverte (et sur mobile le bandeau droit reste visible).
  state.map = L.map("map", { zoomControl: false, preferCanvas: true }).setView([46.6, 2.5], 6);
  L.control.zoom({ position: "topright" }).addTo(state.map);
  L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png", {
    attribution: "&copy; OpenStreetMap, &copy; CARTO", subdomains: "abcd", maxZoom: 19,
  }).addTo(state.map);
  L.control.scale({ metric: true, imperial: false, position: "bottomright" }).addTo(state.map);

  // WMTS (tuiles pré-calculées en cache) plutôt que WMS (rendu à la volée, lent aux
  // zooms serrés). Le cache BD Forêt® va jusqu'à z16 → au-delà, Leaflet sur-échantillonne
  // la tuile z16 (instantané, légèrement adouci) au lieu d'attendre un rendu serveur.
  state.layers.forest = L.tileLayer(
    "https://data.geopf.fr/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0" +
    "&LAYER=LANDCOVER.FORESTINVENTORY.V2&STYLE=normal&TILEMATRIXSET=PM&FORMAT=image/png" +
    "&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}",
    { opacity: 0.6, attribution: "IGN — BD Forêt® V2",
      maxZoom: 19, maxNativeZoom: 16 });

  state.map.on("click", (e) => loadPoint(e.latlng.lat, e.latlng.lng));
  // La carte d'info reste ancrée au point cliqué quand on déplace/zoome la carte.
  state.map.on("move zoom resize", positionPointCard);
}

function computeSelectedDates() {
  const ds = state.dates;
  if (!ds.length) { state.selectedDates = []; return; }
  if (state.period === "jour") state.selectedDates = [ds[ds.length - 1]];
  else {
    const n = parseInt(state.period, 10);
    state.selectedDates = ds.slice(Math.max(0, ds.length - n));
  }
  const fmt = (s) => `${s.slice(6,8)}/${s.slice(4,6)}`;
  const sd = state.selectedDates;
  const lbl = document.getElementById("period-label");
  if (lbl) lbl.textContent =
    sd.length === 1 ? `${fmt(sd[0])}/${sd[0].slice(0,4)} · jour`
                    : `${fmt(sd[0])} → ${fmt(sd[sd.length-1])} · ${sd.length} j`;
}

function _setOverlay(key, res, opacity) {
  const b = res.bounds;
  if (state.layers[key]) state.map.removeLayer(state.layers[key]);
  state.layers[key] = L.imageOverlay(res.url, [[b.bottom, b.left], [b.top, b.right]],
                                      { opacity, interactive: false });
  if (state.activeLayer === key) state.layers[key].addTo(state.map);  // calque exclusif
}

/* Calques météo séparés : 'T' (température moyenne) et 'RR' (précipitations). */
async function refreshWeatherLayer(varName) {
  computeSelectedDates();
  if (!state.selectedDates.length) return;
  const key = varName === "RR" ? "precip" : "temp";
  try {
    const res = await API.get(`/api/overlay?var=${varName}&dates=${state.selectedDates.join(",")}`);
    _setOverlay(key, res, 0.85);
    state.legendData[key] = { vmin: res.vmin, vmax: res.vmax, unit: res.unit || "" };
  } catch (e) { console.warn("weather", e); }
}

// Espèces réellement affichées sur le radar = sous-ensemble coché (state.radarSpecies)
// de la pré-sélection « Mes champignons » (state.species). null = toutes.
function radarActiveSpecies() {
  return (state.radarSpecies || state.species || []);
}

// Radar à champignons : calque de TUILES (habitat × pousse du jour, clippé au contour
// forêt exact côté serveur). Sur les espèces cochées du calque (parmi « Mes champignons »).
async function refreshRadar() {
  const active = radarActiveSpecies();
  if (state.layers.radar) { state.map.removeLayer(state.layers.radar); state.layers.radar = null; }
  // Aucune espèce cochée (alors qu'une pré-sélection existe) → rien à afficher.
  if (state.species && state.species.length && !active.length) {
    state.legendData.radar = { species: [] };
    if (state.activeLayer === "radar") updateLegend();
    return;
  }
  const d = (state.dates && state.dates.length) ? state.dates[state.dates.length - 1] : "";
  const spq = active.length ? "&sp=" + active.map(encodeURIComponent).join(",") : "";
  // maxNativeZoom=13 : contours forêt pré-stockés jusqu'à z13 (cache disque, rendu net sans
  // réseau) ; au-delà Leaflet sur-échantillonne la tuile z13 (la donnée radar est en mailles
  // de 1 km, donc on ne perd quasi rien, et on évite les z14-16 = des Go de tuiles forêt).
  state.layers.radar = L.tileLayer(`/api/radar/tiles/{z}/{x}/{y}.png?d=${d}${spq}`,
    { opacity: 1, tileSize: 256, maxZoom: 19, maxNativeZoom: 13,
      // updateWhenZooming:false → on ne réclame pas de tuiles pendant l'animation de zoom
      // (elles apparaissent une fois le zoom posé → geste fluide). keepBuffer élargi → on
      // garde plus de tuiles hors écran en cache → moins de rechargements en déplaçant.
      keepBuffer: 4, updateWhenIdle: false, updateWhenZooming: false });
  if (state.activeLayer === "radar") state.layers.radar.addTo(state.map);
  try {
    const q = active.length ? "?species=" + active.map(encodeURIComponent).join(",") : "";
    const meta = await API.get(`/api/radar/meta${q}`);
    state.legendData.radar = { species: meta.species || [] };
  } catch (e) { state.legendData.radar = { species: [] }; }
  if (state.activeLayer === "radar") updateLegend();
}

async function refreshSoil() {
  try {
    const res = await API.get("/api/soil");
    _setOverlay("soil", res, 0.8);
    state.legendData.soil = res.legend || [];
  } catch (e) { console.warn("soil", e); }
}

async function refreshSoilMoisture() {
  try {
    const res = await API.get(`/api/soil-moisture?date=${state.dates[state.dates.length - 1] || ""}`);
    _setOverlay("soilmoist", res, 0.78);
  } catch (e) { console.warn("soilmoist", e); }
}

async function refreshAltitude() {
  try {
    const res = await API.get("/api/altitude");
    _setOverlay("altitude", res, 0.7);
  } catch (e) { console.warn("altitude", e); }
}

async function refreshAspect() {
  try {
    const res = await API.get("/api/aspect");
    _setOverlay("aspect", res, 0.75);
  } catch (e) { console.warn("aspect", e); }
}

/* ---------- Légende (calque actif) ---------- */
// BD Forêt® V2 (IGN) — 32 types de formation végétale, couleurs exactes du calque
// (échantillonnées sur la légende officielle IGN). [couleur, libellé court, libellé complet].
const FOREST_TFV = [
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

function _grad(colors) {
  return `<div class="h-2.5 rounded-full mb-1" style="background:linear-gradient(to right, ${colors.join(",")})"></div>`;
}
function _swatch(label, color) {
  return `<div class="flex items-center gap-2"><span class="inline-block w-3.5 h-3.5 rounded-sm border border-slate-300" style="background:${color}"></span><span>${label}</span></div>`;
}

// Liste « Radar à champignons » (sidebar) : espèces de la pré-sélection « Mes champignons »,
// cochées si affichées. Filtre l'affichage du radar sans toucher aux prefs enregistrées.
// Liste COMPLÈTE (sans scroll), hors de la légende ; visible quand le calque radar est actif.
function updateRadarSpecies() {
  const wrap = document.getElementById("radar-species");
  const list = document.getElementById("radar-species-list");
  if (!wrap || !list) return;
  const sel = state.species || [];
  if (state.activeLayer !== "radar" || !sel.length) {
    wrap.classList.add("hidden");
    list.innerHTML = "";
    return;
  }
  const meta = {}; (state.allSpecies || []).forEach((s) => { meta[s.latin] = s; });
  const active = new Set(radarActiveSpecies());
  list.innerHTML = sel.map((latin) => {
    const m = meta[latin] || { nom: latin, color: "#999" };
    return `<label class="flex items-center gap-2 text-sm cursor-pointer py-0.5">
      <input type="checkbox" class="radar-check accent-brand-500 w-3.5 h-3.5" value="${latin}" ${active.has(latin) ? "checked" : ""}>
      <span class="inline-block w-2.5 h-2.5 rounded-full shrink-0" style="background:${m.color}"></span>
      <span class="truncate">${m.nom}</span></label>`;
  }).join("");
  wrap.classList.remove("hidden");
  list.querySelectorAll(".radar-check").forEach((c) => c.addEventListener("change", () => {
    const checked = Array.from(list.querySelectorAll(".radar-check:checked")).map((x) => x.value);
    // tout coché → null (toute la pré-sélection) ; sinon le sous-ensemble (éventuellement vide)
    state.radarSpecies = (checked.length === sel.length) ? null : checked;
    refreshRadar();   // re-fetch overlay + légende ; updateLegend rappelle updateRadarSpecies
  }));
}

function legendFor(key) {
  const d = state.legendData || {};
  if (key === "radar") {
    const sp = (d.radar && d.radar.species && d.radar.species.length)
      ? d.radar.species.join(", ") : "aucune espèce cochée";
    return `${_grad(CMAP.fav)}
      <div>Vert soutenu = bon coin <strong>et</strong> conditions favorables en ce moment. Pour : <strong>${sp}</strong>.</div>
      <div class="text-[10px] text-slate-400 mt-1.5">Habitat (essence/sol/relief/climat) × pousse du jour (météo des ~21 j).</div>`;
  }
  if (key === "temp" || key === "precip") {
    const w = d[key]; if (!w) return "";
    const cm = key === "precip" ? CMAP.RR : CMAP.T;
    return `<div class="font-semibold text-slate-600 mb-1">${key === "precip" ? "Précipitations (mm)" : "Température moyenne (°C)"}</div>${_grad(cm)}
      <div class="flex justify-between text-[10px] text-slate-400">${[w.vmin, (w.vmin + w.vmax) / 2, w.vmax].map((v) => `<span>${v.toFixed(1)} ${w.unit}</span>`).join("")}</div>`;
  }
  if (key === "forest") {
    const rows = FOREST_TFV.map(([c, short, full]) =>
      `<div class="flex items-center gap-1.5 min-w-0" title="${full}">
         <span class="inline-block w-3 h-3 rounded-sm border border-slate-300 shrink-0" style="background:${c}"></span>
         <span class="truncate">${short}</span></div>`).join("");
    return `<div class="font-semibold text-slate-600 mb-1.5">Essences forestières — BD Forêt® V2 (IGN)</div>
      <div class="grid grid-cols-1 sm:grid-cols-2 gap-x-3 gap-y-1 text-[10px] leading-tight">${rows}</div>
      <div class="text-[10px] text-slate-400 mt-1.5">32 types (IGN) · essence précise au clic.</div>`;
  }
  if (key === "soil") {
    const cls = d.soil || [];
    return `<div class="font-semibold text-slate-600 mb-1.5">Type de sol (texture)</div>
      <div class="grid grid-cols-1 gap-1">${cls.map((c) => _swatch(c.label, c.color)).join("")}</div>
      <div class="text-[10px] text-slate-400 mt-1.5">SoilGrids® 250 m (ISRIC), horizon 0–15 cm.</div>`;
  }
  if (key === "soilmoist") {
    return `<div class="font-semibold text-slate-600 mb-1">Humidité du sol</div>${_grad(CMAP.sm)}
      <div class="flex justify-between text-[10px] text-slate-400"><span>sec</span><span>humide</span></div>`;
  }
  if (key === "altitude") {
    return `<div class="font-semibold text-slate-600 mb-1">Altitude (m)</div>${_grad(CMAP.alt)}
      <div class="flex justify-between text-[10px] text-slate-400"><span>0</span><span>2200+</span></div>`;
  }
  if (key === "aspect") {
    return `<div class="font-semibold text-slate-600 mb-1">Exposition (versants)</div>
      <div class="flex items-center gap-2 flex-wrap">${_swatch("Sud (chaud)", "#b2182b")}${_swatch("Nord (frais)", "#2166ac")}</div>`;
  }
  return "";
}

// Affiche la légende du calque actif : dans le panneau s'il est ouvert, sinon en haut.
function updateLegend() {
  // Une seule légende, TOUJOURS en bas de la barre (volet calques ouvert comme replié).
  const html = legendFor(state.activeLayer);
  const wrap = document.getElementById("active-legend-wrap");
  document.getElementById("active-legend").innerHTML = html;
  wrap.classList.toggle("hidden", !html);
  updateRadarSpecies();      // liste des espèces du radar (peuple #radar-species)
  updateActiveLayerName();   // titre du calque (toujours visible)
  // Hauteur de la zone légende = la PLUS GRANDE hauteur de contenu observée (légende +
  // sélecteur d'espèces du radar = le plus haut) → empreinte fixe, le bouton ne bouge pas.
  // On mesure le contenu réel du calque courant et on ne garde que le max (jamais réduit).
  const region = document.getElementById("legend-region");
  if (region) {
    region.style.height = "auto";                 // libère pour mesurer le contenu réel
    state.legendMaxH = Math.max(state.legendMaxH || 0, region.scrollHeight);
    region.style.height = (state.legendMaxH + 12) + "px";   // +12 : absorbe arrondis / gouttière → pas de scroll
  }
}

// Noms lisibles des calques (pour le titre affiché quand le volet est replié).
const LAYER_NAMES = {
  radar: "🍄 Radar à champignons", temp: "Température moyenne", precip: "Précipitations",
  forest: "Forêts — BD Forêt® IGN", soil: "Type de sol — SoilGrids®",
  soilmoist: "Humidité du sol", altitude: "Altitude / relief", aspect: "Exposition (versants)",
};
function updateActiveLayerName() {
  const el = document.getElementById("active-layer-name");
  if (!el) return;
  el.textContent = LAYER_NAMES[state.activeLayer] || "";
  el.classList.toggle("hidden", !el.textContent);   // titre TOUJOURS visible (sauf si vide)
}

/* ---------- Calques exclusifs (un seul affiché à la fois) ---------- */
// def.refresh (re)construit state.layers[key] ; def.weather = dépend de la période.
const LAYER_DEFS = {
  radar:     { refresh: () => refreshRadar(), weather: true },  // défaut : habitat × pousse du jour
  temp:      { refresh: () => refreshWeatherLayer("T"),  weather: true },
  precip:    { refresh: () => refreshWeatherLayer("RR"), weather: true },
  forest:    { refresh: null },                          // WMS construit dans initMap
  soil:      { refresh: () => refreshSoil() },
  soilmoist: { refresh: () => refreshSoilMoisture() },
  altitude:  { refresh: () => refreshAltitude() },
  aspect:    { refresh: () => refreshAspect() },
};
const LAYER_KEYS = Object.keys(LAYER_DEFS);

async function setActiveLayer(key) {
  state.activeLayer = key;
  // Période : utile seulement pour les calques météo (température / précipitations) → masquée sinon
  const pb = document.getElementById("period-block");
  if (pb) pb.classList.toggle("hidden", !(key === "temp" || key === "precip"));
  // calques exclusifs : on retire tout, puis on (ré)affiche le calque choisi
  LAYER_KEYS.forEach((k) => { if (state.layers[k]) state.map.removeLayer(state.layers[k]); });
  const def = LAYER_DEFS[key];
  if (!def) return;
  // météo/radar : dépend de la période/sélection → toujours recharger ; autres : lazy-load une fois
  if (def.refresh && (!state.layers[key] || def.weather)) await def.refresh();
  if (state.layers[key]) state.layers[key].addTo(state.map);
  updateLegend();
}

/* ---------- Contrôles ---------- */
function wireControls() {
  // Switch de calque (radio) : un seul calque à la fois
  document.querySelectorAll('input[name="layer"]').forEach((r) =>
    r.addEventListener("change", () => { if (r.checked) setActiveLayer(r.value); }));

  // Période → recharge le calque météo actif
  document.querySelectorAll(".period-btn").forEach((b) =>
    b.addEventListener("click", () => {
      document.querySelectorAll(".period-btn").forEach((x) => x.setAttribute("aria-selected", "false"));
      b.setAttribute("aria-selected", "true");
      state.period = b.dataset.period;
      computeSelectedDates();
      if (state.activeLayer === "temp" || state.activeLayer === "precip") setActiveLayer(state.activeLayer);
    }));

  // Bouton « Fou des champignons » : déplie/replie le panneau calques
  document.getElementById("godmode-btn").addEventListener("click", () => {
    state.godmode = !state.godmode;
    document.getElementById("layers-panel").classList.toggle("hidden", !state.godmode);
    document.getElementById("godmode-label").textContent =
      state.godmode ? "Réduire les calques" : "Fou des champignons";
    if (!state.godmode) {
      // Réduire : on garde affiché EXCLUSIVEMENT le calque sélectionné (sans re-télécharger)
      LAYER_KEYS.forEach((k) => {
        const lyr = state.layers[k];
        if (!lyr) return;
        if (k === state.activeLayer) { if (!state.map.hasLayer(lyr)) lyr.addTo(state.map); }
        else if (state.map.hasLayer(lyr)) state.map.removeLayer(lyr);
      });
    }
    updateLegend();   // légende toujours en bas
  });

  // Modale « Mes champignons »
  document.getElementById("species-btn").addEventListener("click", openSpeciesModal);
  document.getElementById("species-close").addEventListener("click", closeSpeciesModal);
  document.getElementById("species-cancel").addEventListener("click", closeSpeciesModal);
  document.getElementById("species-backdrop").addEventListener("click", closeSpeciesModal);
  document.getElementById("species-save").addEventListener("click", saveSpecies);
  document.getElementById("species-all").addEventListener("click", () => setAllSpeciesChecks(true));
  document.getElementById("species-none").addEventListener("click", () => setAllSpeciesChecks(false));

  document.querySelectorAll(".tab-btn").forEach((b) =>
    b.addEventListener("click", () => setTab(b.dataset.tab)));

  // Menu sandwich (mobile) : ouvre/ferme le tiroir de navigation
  const navToggle = document.getElementById("nav-toggle");
  const navMenu = document.getElementById("nav-menu");
  const closeNavMenu = () => { navMenu.classList.remove("mobile-open"); navToggle.setAttribute("aria-expanded", "false"); };
  navToggle.addEventListener("click", (e) => {
    e.stopPropagation();
    const open = navMenu.classList.toggle("mobile-open");
    navToggle.setAttribute("aria-expanded", open ? "true" : "false");
  });
  // Referme après une action de navigation (onglet, espèces, déconnexion) — pas sur la cloche
  navMenu.addEventListener("click", (e) => {
    if (e.target.closest(".tab-btn, #species-btn, #logout-btn")) closeNavMenu();
  });
  // Referme si on clique ailleurs
  document.addEventListener("click", (e) => {
    if (navMenu.classList.contains("mobile-open") && !navMenu.contains(e.target) && !navToggle.contains(e.target)) closeNavMenu();
  });

  // Replier / déployer la barre latérale (pratique sur téléphone)
  document.getElementById("sidebar-toggle").addEventListener("click", toggleSidebar);

  // Cloche de notifications (spots propices)
  document.getElementById("notif-btn").addEventListener("click", (e) => { e.stopPropagation(); toggleNotifPanel(); });
  document.addEventListener("click", (e) => {
    const panel = document.getElementById("notif-panel");
    const btn = document.getElementById("notif-btn");
    if (!panel.classList.contains("hidden") && !panel.contains(e.target) && !btn.contains(e.target)) toggleNotifPanel(false);
  });

  let timer = null;
  const input = document.getElementById("city-input");
  input.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(() => searchCity(input.value), 250);
  });

  // Géolocalisation (pratique sur téléphone : se situer pour poser un spot)
  document.getElementById("geolocate-btn").addEventListener("click", geolocateMe);
}

function geolocateMe() {
  if (!navigator.geolocation) { alert("Géolocalisation non disponible sur cet appareil."); return; }
  const btn = document.getElementById("geolocate-btn");
  btn.disabled = true; btn.classList.add("opacity-50");
  navigator.geolocation.getCurrentPosition(
    (pos) => {
      btn.disabled = false; btn.classList.remove("opacity-50");
      const { latitude, longitude, accuracy } = pos.coords;
      setTab("carte");
      // Zoom calé sur la précision renvoyée : GPS fin → rue ; position IP/Wi-Fi
      // (ordinateur sans GPS) grossière → vue régionale, pour ne pas faire croire à
      // une précision qu'on n'a pas.
      const z = accuracy > 50000 ? 7 : accuracy > 5000 ? 10 : accuracy > 500 ? 13 : 15;
      state.map.setView([latitude, longitude], z);
      loadPoint(latitude, longitude);
      if (accuracy > 5000) {
        alert("Position approximative (~" + Math.round(accuracy / 1000) + " km).\n"
          + "Sans GPS, le navigateur estime la position via l'adresse IP / le Wi-Fi "
          + "(souvent fausse sur ordinateur). Sur téléphone, le GPS est précis.");
      }
    },
    (err) => {
      btn.disabled = false; btn.classList.remove("opacity-50");
      const msg = err && err.code === 1 ? "autorisation refusée" : (err && err.message) || "position indisponible";
      alert("Impossible de vous localiser (" + msg + ").");
    },
    { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 }
  );
}

/* ---------- Sélection de champignons (compte) ---------- */
async function loadPreferences() {
  try {
    const res = await API.get("/api/preferences");
    state.allSpecies = res.all || [];
    state.species = res.species || state.allSpecies.map((s) => s.latin);
  } catch (e) { state.allSpecies = []; state.species = null; }
}

function openSpeciesModal() {
  const sel = new Set(state.species || state.allSpecies.map((s) => s.latin));
  document.getElementById("species-list").innerHTML = state.allSpecies.map((s) =>
    `<label class="flex items-center gap-2 p-2 rounded-lg border border-slate-200 hover:bg-slate-50 cursor-pointer">
       <input type="checkbox" class="sp-check accent-brand-500" value="${s.latin}" ${sel.has(s.latin) ? "checked" : ""}>
       <span class="inline-block w-3 h-3 rounded-full shrink-0" style="background:${s.color}"></span>
       <span class="text-sm truncate">${s.nom}</span>
     </label>`).join("");
  document.querySelectorAll("#species-list .sp-check").forEach((c) =>
    c.addEventListener("change", updateSpeciesCount));
  updateSpeciesCount();
  document.getElementById("species-modal").classList.remove("hidden");
}

function closeSpeciesModal() { document.getElementById("species-modal").classList.add("hidden"); }
function setAllSpeciesChecks(v) {
  document.querySelectorAll("#species-list .sp-check").forEach((c) => { c.checked = v; });
  updateSpeciesCount();
}
function updateSpeciesCount() {
  const n = document.querySelectorAll("#species-list .sp-check:checked").length;
  const t = document.querySelectorAll("#species-list .sp-check").length;
  document.getElementById("species-count").textContent = `${n}/${t} sélectionné(s)`;
}

async function saveSpecies() {
  const chosen = Array.from(document.querySelectorAll("#species-list .sp-check:checked")).map((c) => c.value);
  if (!chosen.length) { alert("Sélectionnez au moins une espèce."); return; }
  try {
    await API.post("/api/preferences", { species: chosen });
    state.species = chosen;
    state.radarSpecies = null;                            // la pré-sélection a changé → toutes les cases recochées
    closeSpeciesModal();
    await refreshRadar();                                 // re-render le radar (dépend de la sélection)
    if (state.activeLayer === "radar" && state.layers.radar) state.layers.radar.addTo(state.map);
    if (state.lastPoint) loadPoint(state.lastPoint.lat, state.lastPoint.lon);  // re-filtre la fiche
    loadSpots();                                          // la propiceté des spots dépend de la sélection
  } catch (e) { alert("Échec de l'enregistrement de la sélection."); }
}

async function doCitySearch(q, box, inputEl) {
  if (!q || q.trim().length < 2) { box.innerHTML = ""; return; }
  try {
    const res = await API.get(`/api/cities?q=${encodeURIComponent(q)}`);
    box.innerHTML = res.results.map((r, i) =>
      `<button data-i="${i}" class="city-pick w-full text-left text-sm px-3 py-1.5 rounded-lg hover:bg-brand-50 border border-transparent hover:border-brand-100">${r.label}</button>`
    ).join("");
    box.querySelectorAll(".city-pick").forEach((btn) =>
      btn.addEventListener("click", () => {
        const r = res.results[+btn.dataset.i];
        state.map.setView([r.lat, r.lon], 11);
        loadPoint(r.lat, r.lon);
        box.innerHTML = "";
        if (inputEl) inputEl.value = r.name;
      }));
  } catch (e) {}
}

function searchCity(q) {
  return doCitySearch(q, document.getElementById("city-results"), document.getElementById("city-input"));
}

function setTab(tab) {
  document.querySelectorAll(".tab-btn").forEach((b) => {
    const active = b.dataset.tab === tab;
    b.classList.toggle("bg-brand-500", active);
    b.classList.toggle("text-white", active);
    b.classList.toggle("text-slate-600", !active);
  });
  state.tab = tab;
  document.getElementById("view-carte").classList.toggle("hidden", tab !== "carte");
  document.getElementById("view-guide").classList.toggle("hidden", tab !== "guide");
  document.getElementById("view-spots").classList.toggle("hidden", tab !== "spots");
  applySidebar(true);   // barre latérale : visible seulement sur Carte, et selon repli
  if (tab === "guide") renderGuide();
  if (tab === "spots") renderSpots();
}

/* Barre latérale (recherche + calques) : visible uniquement sur l'onglet Carte
   et si non repliée. Le bouton de bascule n'apparaît que sur Carte. */
function applySidebar(resize) {
  const onMap = state.tab === "carte";
  const sb = document.getElementById("sidebar");
  sb.classList.toggle("hidden", !onMap);                          // pas de barre hors Carte
  sb.classList.toggle("-translate-x-full", state.sidebarCollapsed); // repli = glissement CSS
  const icon = document.getElementById("sidebar-toggle-icon");
  if (icon) icon.textContent = state.sidebarCollapsed ? "»" : "«";
  // Tiroir absolu : la carte ne change plus de taille au repli → invalidateSize
  // seulement au changement d'onglet (la carte (ré)apparaît).
  if (resize && state.map && onMap) setTimeout(() => state.map.invalidateSize(), 60);
}

function toggleSidebar() {
  state.sidebarCollapsed = !state.sidebarCollapsed;
  applySidebar(false);   // simple glissement, pas de resize de carte
}

/* ---------- Point + guide ---------- */
async function loadPoint(lat, lon, spot) {
  const date = state.dates[state.dates.length - 1];
  try {
    const r = await API.get(`/api/point?lat=${lat}&lon=${lon}&date=${date}`);
    state.lastPoint = r;
    // Spot enregistré correspondant (passé explicitement, sinon détecté aux coords).
    state.lastSpot = spot
      || state.spots.find((s) => Math.abs(s.lat - lat) < 1e-4 && Math.abs(s.lon - lon) < 1e-4)
      || null;
    showPointCard(lat, lon, r);
    if (!document.getElementById("view-guide").classList.contains("hidden")) renderGuide();
    fetchForestDetail(lat, lon);   // essence précise (WMS) en différé, non bloquant
  } catch (e) { console.warn("point", e); }
}

function valFmt(v, u) { return v === null || v === undefined ? "n.d." : `${v.toFixed(1)} ${u}`; }
function fmtNum(v) { return v === null || v === undefined ? "—" : v.toFixed(1); }
function pct(v) { return v === null || v === undefined ? "n.d." : `${Math.round(v * 100)} %`; }

// Coloration des facteurs météo de la fiche : vert = favorable, orange = limite,
// rouge = défavorable (atténue). Seuils « grand public » (pas par espèce).
const FACTOR_CLR = {
  good: "bg-green-50 border-green-200 text-green-800",
  mid:  "bg-amber-50 border-amber-200 text-amber-800",
  bad:  "bg-red-50 border-red-200 text-red-800",
  off:  "bg-slate-50 border-slate-200 text-slate-800",
};
function factorLevel(key, v) {
  if (v === null || v === undefined) return key === "days_since_rain" ? "bad" : "off";
  switch (key) {
    case "rain7":  return v >= 15 ? "good" : v >= 5 ? "mid" : "bad";
    case "rain14": return v >= 25 ? "good" : v >= 10 ? "mid" : "bad";
    case "days_since_rain": return (v >= 3 && v <= 14) ? "good" : (v <= 21 ? "mid" : "bad");
    case "temp":   return (v >= 8 && v <= 20) ? "good" : (v >= 5 && v <= 24) ? "mid" : "bad";
    case "soil_moisture": return v >= 0.25 ? "good" : v >= 0.18 ? "mid" : "bad";
    default: return "off";
  }
}
function miniStat(big, small, level) {
  const c = FACTOR_CLR[level] || FACTOR_CLR.off;
  return `<div class="${c} border rounded-lg px-2 py-1.5 text-center">
    <div class="text-base font-extrabold">${big}</div><div class="text-[10px] opacity-70">${small}</div></div>`;
}
/* Pastille d'adéquation du pH du sol pour une espèce. */
function phBadge(soilPh) {
  if (soilPh === "ok") return '<span class="text-[10px] font-bold px-2 py-0.5 rounded-full text-green-700 bg-green-100">pH favorable</span>';
  if (soilPh === "mid") return '<span class="text-[10px] font-bold px-2 py-0.5 rounded-full text-amber-700 bg-amber-100">pH acceptable</span>';
  if (soilPh === "no") return '<span class="text-[10px] font-bold px-2 py-0.5 rounded-full text-red-700 bg-red-100">pH inadapté</span>';
  return "";
}

function hostDot(host) {
  if (host === "ok") return '<span class="text-[10px] font-bold text-green-700">· hôte présent</span>';
  if (host === "no") return '<span class="text-[10px] font-bold text-red-600">· hôte absent</span>';
  return "";
}

/* Libellé forêt : essence précise (WMS, si déjà chargée) sinon famille bakée. */
function familyLabel(fam) {
  return ({ feuillus: "Forêt de feuillus", coniferes: "Forêt de conifères",
            mixte: "Forêt mixte", peupleraie: "Peupleraie", ouvert: "Milieu ouvert" })[fam] || null;
}
function forestLineHtml(forest) {
  if (forest && forest.tfv)
    return `<span class="font-semibold">${forest.tfv}</span> <span class="text-slate-400">(${forest.essence || "—"})</span>`;
  const fam = forest && familyLabel(forest.family);
  return fam ? `<span class="font-semibold">${fam}</span>`
             : `<span class="text-slate-400">Hors forêt cartographiée</span>`;
}

/* Essence précise (WMS) chargée APRÈS le clic, hors chemin critique : enrichit la
   fiche/guide sans bloquer. Garde : n'agit que si la fiche montre toujours ce point. */
async function fetchForestDetail(lat, lon) {
  try {
    const f = await API.get(`/api/forest?lat=${lat}&lon=${lon}`);
    if (!state.cardLatLng || state.cardLatLng.lat !== lat || state.cardLatLng.lng !== lon) return;
    if (!f || !f.tfv) return;
    if (state.lastPoint && state.lastPoint.forest) {
      state.lastPoint.forest.tfv = f.tfv;
      state.lastPoint.forest.essence = f.essence;
      if (f.family) state.lastPoint.forest.family = f.family;
    }
    const el = document.querySelector("#point-card .pc-forest");
    if (el) el.innerHTML = forestLineHtml(f);
    if (!document.getElementById("view-guide").classList.contains("hidden")) renderGuide();
  } catch (e) { /* réseau coupé / hors forêt → on garde le libellé famille */ }
}

/* Carte d'info ancrée au pixel du point cliqué + petit marqueur. Suit la carte. */
function showPointCard(lat, lon, r) {
  state.cardLatLng = L.latLng(lat, lon);
  if (state.clickMarker) state.map.removeLayer(state.clickMarker);
  state.clickMarker = L.circleMarker([lat, lon], {
    radius: 6, color: "#1d4ed8", weight: 2, fillColor: "#3b82f6", fillOpacity: 0.9,
  }).addTo(state.map);

  const top = r.mushrooms.filter((m) => m.level !== "off" && m.selected !== false).slice(0, 3);
  const forestLine = forestLineHtml(r.forest);
  const soilLine = r.soil && r.soil.texture_fr
    ? `<span class="font-semibold">${r.soil.texture_fr}</span> <span class="text-slate-400">· pH ${fmtNum(r.soil.ph)}${r.soil.ph_class ? " (" + r.soil.ph_class + ")" : ""}</span>`
    : "";
  const terrainLine = r.terrain && r.terrain.altitude != null
    ? `<span class="font-semibold">${Math.round(r.terrain.altitude)} m</span> <span class="text-slate-400">· ${r.terrain.exposition || ""}</span>`
    : "";
  const spot = state.lastSpot;
  const titleHtml = spot
    ? `<input class="pc-title font-bold text-slate-800 leading-tight bg-transparent w-full border-b border-dashed border-slate-300 focus:border-solid focus:border-brand-500 outline-none" value="${escapeHtml(spot.name)}" title="Cliquez pour renommer">`
    : `<div class="font-bold text-slate-800 leading-tight">${r.commune || "Point sélectionné"}</div>`;
  const card = document.getElementById("point-card");
  card.innerHTML = `
    <div class="flex items-start justify-between gap-2">
      ${titleHtml}
      <button class="pc-close text-slate-400 hover:text-slate-700 -mt-1 -mr-1 text-lg leading-none shrink-0">×</button>
    </div>
    <div class="text-[11px] text-slate-400 mb-2">${r.lat.toFixed(3)}°N · ${r.lon.toFixed(3)}°E · dalle 1 km</div>
    <div class="grid grid-cols-2 gap-2 mb-2">
      ${miniStat(valFmt(r.t, "°C"), "température air", factorLevel("temp", r.t))}
      ${miniStat(valFmt(r.rr, "mm"), "pluie / jour")}
      ${miniStat(pct(r.soil_moisture), "humidité du sol", factorLevel("soil_moisture", r.soil_moisture))}
      ${miniStat(valFmt(r.soil_temp, "°C"), "T° du sol", factorLevel("temp", r.soil_temp))}
    </div>
    <div class="text-xs mb-1.5 pc-forest">${forestLine}</div>
    ${soilLine ? `<div class="text-xs mb-1.5 text-slate-600">${soilLine}</div>` : ""}
    ${terrainLine ? `<div class="text-xs mb-2 text-slate-600">${terrainLine}</div>` : ""}
    <div class="text-[11px] font-bold uppercase tracking-wide text-slate-400 mb-1">Probables ici</div>
    <div class="space-y-1 mb-1">
      ${top.length ? top.map((m) => {
        const [, fg, bg] = LEVEL[m.level];
        return `<div class="flex items-center gap-2 text-sm">
          <span class="flex-1 truncate">${m.nom} ${hostDot(m.host)}</span>
          <span class="text-[10px] font-bold px-2 py-0.5 rounded-full ${fg} ${bg}">${m.label}${m.score_pct != null ? " · " + m.score_pct + "%" : ""}</span></div>`;
      }).join("") : '<div class="text-xs text-slate-400">Aucune espèce en saison.</div>'}
    </div>
    <button class="pc-guide mt-2 w-full py-1.5 rounded-lg bg-brand-50 text-brand-700 text-sm font-semibold hover:bg-brand-100">Voir le guide complet</button>
    ${spot
      ? `<button class="pc-delete mt-1.5 w-full py-1.5 rounded-lg border border-red-200 text-red-600 text-sm font-semibold hover:bg-red-50">🗑 Supprimer ce spot</button>`
      : `<button class="pc-save mt-1.5 w-full py-1.5 rounded-lg border border-brand-200 text-brand-700 text-sm font-semibold hover:bg-brand-50">📍 Enregistrer ce spot</button>`}`;
  card.classList.remove("hidden");
  positionPointCard();
  card.querySelector(".pc-close").onclick = () => hidePointCard();
  card.querySelector(".pc-guide").onclick = () => setTab("guide");
  if (spot) {
    const t = card.querySelector(".pc-title");
    if (t) {
      const commit = () => renameSpot(spot.id, t.value);
      t.addEventListener("blur", commit);
      t.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); t.blur(); } });
      t.addEventListener("click", (e) => e.stopPropagation());
    }
    card.querySelector(".pc-delete").onclick = () => deleteSpot(spot.id);
  } else {
    card.querySelector(".pc-save").onclick = () => saveSpot(lat, lon, r.commune);
  }
}

function positionPointCard() {
  const card = document.getElementById("point-card");
  if (!state.cardLatLng || card.classList.contains("hidden")) return;
  const p = state.map.latLngToContainerPoint(state.cardLatLng);
  const cont = state.map.getContainer();
  const cw = card.offsetWidth || 256, ch = card.offsetHeight || 220;
  let x = p.x + 14, y = p.y - ch / 2;
  if (x + cw > cont.clientWidth - 8) x = p.x - cw - 14;     // bascule à gauche si déborde
  if (x < 8) x = 8;
  y = Math.max(8, Math.min(y, cont.clientHeight - ch - 8)); // clamp vertical
  card.style.left = x + "px";
  card.style.top = y + "px";
}

function hidePointCard() {
  document.getElementById("point-card").classList.add("hidden");
  state.cardLatLng = null;
  if (state.clickMarker) { state.map.removeLayer(state.clickMarker); state.clickMarker = null; }
}

function monthStrip(months, color, current) {
  const set = new Set(months);
  return `<div class="flex gap-0.5 my-2">` + MONTHS.map((mn, i) => {
    const m = i + 1, active = set.has(m), cur = m === current;
    return `<div class="flex-1 text-center text-[9px] font-bold py-0.5 rounded"
      style="background:${active ? color : "#f1f5f9"};color:${active ? "#fff" : "#cbd5e1"};
      ${cur ? "box-shadow:inset 0 0 0 2px #0f172a;" : ""}">${mn}</div>`;
  }).join("") + `</div>`;
}

function renderGuide() {
  const box = document.getElementById("guide-content");
  const r = state.lastPoint;
  if (!r) {
    box.innerHTML = `<div class="bg-white border border-slate-200 rounded-2xl p-6 text-slate-500 max-w-xl">
      <div class="mb-3">Aucun point sélectionné. Cliquez sur la carte (onglet Carte) ou cherchez une ville.</div>
      <input id="guide-city-input" type="text" placeholder="Ville ou code postal…"
             class="w-full px-3 py-2 rounded-xl border border-slate-200 focus:border-brand-500 focus:ring-2 focus:ring-brand-100 outline-none text-sm" />
      <div id="guide-city-results" class="mt-1 space-y-1"></div></div>`;
    const gi = document.getElementById("guide-city-input");
    const gr = document.getElementById("guide-city-results");
    let gt = null;
    gi.addEventListener("input", () => {
      clearTimeout(gt);
      gt = setTimeout(() => doCitySearch(gi.value, gr, gi), 250);
    });
    return;
  }
  const fam = { feuillus: "feuillus", coniferes: "conifères", mixte: "mixte", peupleraie: "peupleraie", ouvert: "milieu ouvert" };
  const famTitle = r.forest && familyLabel(r.forest.family);
  const banner = r.forest && r.forest.tfv
    ? `<div class="bg-white border-l-4 border-green-600 border border-slate-200 rounded-xl p-4 mb-4 shadow-soft">
         <div class="font-bold">${r.forest.tfv}</div>
         <div class="text-sm text-slate-500 mt-0.5">Essence dominante : <strong>${r.forest.essence || "—"}</strong> ·
         famille d'hôte : <strong>${fam[r.family] || r.family || "?"}</strong> — les espèces dont l'arbre-hôte
         est présent sont mises en avant (BD&nbsp;Forêt® V2, IGN).</div></div>`
    : (famTitle
      ? `<div class="bg-white border-l-4 border-green-600 border border-slate-200 rounded-xl p-4 mb-4 shadow-soft">
           <div class="font-bold">${famTitle}</div>
           <div class="text-sm text-slate-500 mt-0.5">Famille d'hôte : <strong>${fam[r.family] || r.family || "?"}</strong> —
           les espèces dont l'arbre-hôte est présent sont mises en avant (BD&nbsp;Forêt® V2, IGN).</div></div>`
      : `<div class="bg-white border-l-4 border-slate-400 border border-slate-200 rounded-xl p-4 mb-4 shadow-soft">
           <div class="font-bold">Hors forêt cartographiée</div>
           <div class="text-sm text-slate-500 mt-0.5">Privilégiez les espèces de prés/lisières, ou cliquez sur une forêt voisine.</div></div>`);

  const soil = r.soil || {};
  const texSeg = (label, v, color) => (v == null ? "" :
    `<div style="width:${v}%;background:${color}" title="${label} ${fmtNum(v)} %"></div>`);
  const soilBanner = soil.texture_fr
    ? `<div class="bg-white border-l-4 border-amber-700 border border-slate-200 rounded-xl p-4 mb-4 shadow-soft">
         <div class="font-bold">Sol : ${soil.texture_fr}
           ${soil.ph != null ? `<span class="text-sm font-normal text-slate-400">· pH ${fmtNum(soil.ph)} (${soil.ph_class || ""})</span>` : ""}</div>
         <div class="flex h-2.5 rounded-full overflow-hidden my-2 border border-slate-200">
           ${texSeg("Sable", soil.sand, "#eab308")}${texSeg("Limon", soil.silt, "#84cc16")}${texSeg("Argile", soil.clay, "#b45309")}</div>
         <div class="text-sm text-slate-500">Sable ${fmtNum(soil.sand)} % · Limon ${fmtNum(soil.silt)} % · Argile ${fmtNum(soil.clay)} %
           — humidité <strong>${pct(r.soil_moisture)}</strong>, T° du sol <strong>${valFmt(r.soil_temp, "°C")}</strong>.
           <span class="text-slate-400">(SoilGrids® ISRIC + Open-Meteo)</span></div></div>`
    : "";

  const summary = `<div class="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-5">
    ${chip(valFmt(r.rain7, "mm"), "pluie 7 j", factorLevel("rain7", r.rain7))}
    ${chip(valFmt(r.rain14, "mm"), "pluie 14 j", factorLevel("rain14", r.rain14))}
    ${chip(r.days_since_rain != null ? r.days_since_rain + " j" : "n.d.", "depuis pluie ≥8 mm", factorLevel("days_since_rain", r.days_since_rain))}
    ${chip(valFmt(r.temp_mean, "°C"), "T° air récente", factorLevel("temp", r.temp_mean))}
    ${chip(pct(r.soil_moisture), "humidité du sol", factorLevel("soil_moisture", r.soil_moisture))}
    ${chip(valFmt(r.soil_temp, "°C"), "T° du sol", factorLevel("temp", r.soil_temp))}
    ${chip(soil.ph != null ? fmtNum(soil.ph) : "n.d.", "pH du sol")}
    ${chip(r.terrain && r.terrain.altitude != null ? Math.round(r.terrain.altitude) + " m" : "n.d.", "altitude")}
    ${chip(r.terrain && r.terrain.exposition ? r.terrain.exposition.replace("Versant ", "") : "n.d.", "exposition")}
    ${chip(r.month, "mois")}
  </div>`;

  const cards = r.mushrooms.filter((m) => m.selected !== false).map((m) => {
    const [, fg, bg] = LEVEL[m.level];
    const hostBadge = m.host === "ok"
      ? `<span class="text-[10px] font-bold px-2 py-0.5 rounded-full text-green-700 bg-green-100">hôte présent</span>`
      : (m.host === "no" ? `<span class="text-[10px] font-bold px-2 py-0.5 rounded-full text-red-700 bg-red-100">hôte absent ici</span>` : "");
    return `<div class="bg-white border border-slate-200 rounded-2xl p-4 shadow-soft">
      <div class="flex items-center gap-2">
        <span class="font-bold flex-1">${m.nom}</span>
        <span class="text-[10px] font-bold px-2 py-0.5 rounded-full ${fg} ${bg}">${m.label}${m.score_pct != null ? " · " + m.score_pct + "%" : ""}</span>
        ${hostBadge}
      </div>
      <div class="text-xs italic text-slate-400">${m.latin}</div>
      ${monthStrip(m.months, m.color, monthNum(r.month))}
      <div class="text-xs text-slate-600">T° ${m.t_min}–${m.t_max} °C&nbsp;&nbsp;·&nbsp;&nbsp;pluie ${m.rain_lag[0]}–${m.rain_lag[1]} j après</div>
      <div class="text-xs text-slate-400 mt-1.5">${m.habitat}</div>
      ${(m.soil_pref || phBadge(m.soil_ph)) ? `<div class="flex items-center gap-1.5 flex-wrap mt-1.5 pt-1.5 border-t border-slate-100">
        ${phBadge(m.soil_ph)}<span class="text-xs text-slate-500">${m.soil_pref || ""}</span></div>` : ""}
    </div>`;
  }).join("");

  box.innerHTML = `
    <div class="bg-white border border-slate-200 rounded-xl p-4 mb-4 shadow-soft">
      <div class="font-bold">${r.commune || "Point sélectionné"}
        <span class="text-xs font-normal text-slate-400">${r.lat.toFixed(3)}°N · ${r.lon.toFixed(3)}°E · dalle 1 km</span></div>
    </div>
    ${banner}${soilBanner}${summary}
    <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">${cards}</div>`;
}

function chip(big, small, level) {
  const c = level ? FACTOR_CLR[level] + " border" : "bg-white border border-slate-200 text-slate-800";
  return `<div class="${c} rounded-xl px-3 py-2 text-center shadow-soft">
    <div class="font-extrabold">${big}</div><div class="text-[11px] opacity-70">${small}</div></div>`;
}
const FR_MONTHS = ["janvier","février","mars","avril","mai","juin","juillet","août","septembre","octobre","novembre","décembre"];
function monthNum(frName) { const i = FR_MONTHS.indexOf((frName || "").toLowerCase()); return i >= 0 ? i + 1 : 0; }

/* ---------- Spots enregistrés + notifications « propice » ---------- */
function escapeHtml(s) {
  return (s || "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

async function loadSpots() {
  try {
    const res = await API.get("/api/spots");
    state.spots = res.spots || [];
  } catch (e) { state.spots = []; }
  renderSpotMarkers();
  updateNotifications();
  if (!document.getElementById("view-spots").classList.contains("hidden")) renderSpots();
}

function spotIcon(propice) {
  const color = propice ? "#16a34a" : "#c2620e";
  const glow = propice
    ? "box-shadow:0 0 0 5px rgba(22,163,74,.25),0 1px 4px rgba(0,0,0,.3);"
    : "box-shadow:0 1px 4px rgba(0,0,0,.3);";
  return L.divIcon({
    className: "",
    html: `<div style="width:24px;height:24px;border-radius:50%;background:#fff;border:2px solid ${color};${glow}display:flex;align-items:center;justify-content:center;font-size:13px;line-height:1">🍄</div>`,
    iconSize: [24, 24], iconAnchor: [12, 12], popupAnchor: [0, -13],
  });
}

function renderSpotMarkers() {
  if (!state.map) return;
  if (!state.spotLayer) state.spotLayer = L.layerGroup().addTo(state.map);
  state.spotLayer.clearLayers();
  state.spots.forEach((s) => {
    const m = L.marker([s.lat, s.lon], { icon: spotIcon(s.propice), title: s.name });
    // Clic sur le spot → fiche directe (titre éditable + Supprimer), pas de popup.
    m.on("click", () => loadPoint(s.lat, s.lon, s));
    state.spotLayer.addLayer(m);
  });
}

async function saveSpot(lat, lon, name) {
  try {
    const res = await API.post("/api/spots", { lat, lon, name: name || "" });
    await loadSpots();
    // bascule la fiche en mode « spot enregistré » : titre éditable + bouton Supprimer.
    state.lastSpot = state.spots.find((s) => s.id === res.spot.id) || res.spot;
    if (state.lastPoint) showPointCard(lat, lon, state.lastPoint);
  } catch (e) { alert("Échec de l'enregistrement du spot."); }
}

async function renameSpot(id, name) {
  const spot = state.spots.find((s) => s.id === id);
  const newName = (name || "").trim();
  if (!spot || !newName || newName === spot.name) return;
  try {
    await API.patch(`/api/spots/${id}`, { name: newName });
    spot.name = newName;
    if (state.lastSpot && state.lastSpot.id === id) state.lastSpot.name = newName;
    renderSpotMarkers();
    updateNotifications();
    if (!document.getElementById("view-spots").classList.contains("hidden")) renderSpots();
  } catch (e) { alert("Échec du renommage du spot."); }
}

async function deleteSpot(id) {
  try {
    await API.del(`/api/spots/${id}`);
    if (state.lastSpot && state.lastSpot.id === id) { state.lastSpot = null; hidePointCard(); }
    await loadSpots();
  } catch (e) { alert("Échec de la suppression du spot."); }
}

function toggleNotifPanel(force) {
  const panel = document.getElementById("notif-panel");
  const show = force === undefined ? panel.classList.contains("hidden") : force;
  panel.classList.toggle("hidden", !show);
}

function updateNotifications() {
  const propices = state.spots.filter((s) => s.propice);
  const badge = document.getElementById("notif-badge");
  if (propices.length) { badge.textContent = propices.length; badge.classList.remove("hidden"); }
  else badge.classList.add("hidden");

  const panel = document.getElementById("notif-panel");
  if (!state.spots.length) {
    panel.innerHTML = `<div class="p-3 text-sm text-slate-500">Aucun spot enregistré.<br>Cliquez sur la carte puis « Enregistrer ce spot ».</div>`;
    return;
  }
  if (!propices.length) {
    panel.innerHTML = `<div class="p-3 text-sm text-slate-500">Aucun de vos ${state.spots.length} spot(s) n'est particulièrement propice aujourd'hui.</div>`;
    return;
  }
  panel.innerHTML =
    `<div class="px-3 pt-2 pb-1 text-[11px] font-bold uppercase tracking-wide text-slate-400">Propices en ce moment</div>` +
    propices.map((s) =>
      `<button class="notif-item w-full text-left px-3 py-2 rounded-xl hover:bg-green-50 flex items-center gap-2" data-id="${s.id}">
         <span class="text-lg leading-none">🍄</span>
         <span class="flex-1 min-w-0">
           <span class="block font-semibold text-slate-800 truncate">${escapeHtml(s.name)}</span>
           <span class="block text-[11px] text-green-700 font-semibold">Très propice · indice ${s.score_pct} %</span>
         </span>
       </button>`).join("");
  panel.querySelectorAll(".notif-item").forEach((b) => b.onclick = () => {
    const s = state.spots.find((x) => x.id === b.dataset.id);
    if (!s) return;
    setTab("carte");
    state.map.setView([s.lat, s.lon], Math.max(state.map.getZoom(), 11));
    loadPoint(s.lat, s.lon, s);
    toggleNotifPanel(false);
  });
}

/* Onglet « Mes spots » : liste éditable (renommer / voir sur la carte / supprimer). */
function renderSpots() {
  const box = document.getElementById("spots-content");
  if (!box) return;
  if (!state.spots.length) {
    box.innerHTML = `<div class="bg-white border border-slate-200 rounded-2xl p-6 text-slate-500 max-w-xl shadow-soft">
      Aucun spot enregistré. Sur l'onglet <strong>Carte</strong>, cliquez sur un endroit puis « 📍 Enregistrer ce spot ».</div>`;
    return;
  }
  box.innerHTML = `<div class="grid grid-cols-1 sm:grid-cols-2 gap-3">` + state.spots.map((s) => {
    const status = s.propice
      ? `<span class="text-green-700 font-semibold">🟢 Très propice · indice ${s.score_pct} %</span>`
      : (s.score_pct != null
          ? `<span class="text-slate-500">Indice du jour : <strong>${s.score_pct} %</strong></span>`
          : `<span class="text-slate-400">Hors zone modélisée</span>`);
    return `<div class="bg-white border border-slate-200 rounded-2xl p-4 shadow-soft">
      <input class="spot-name w-full font-bold text-slate-800 bg-transparent border-b border-dashed border-slate-300 hover:border-slate-400 focus:border-solid focus:border-brand-500 outline-none" value="${escapeHtml(s.name)}" data-id="${s.id}" title="Cliquez pour renommer">
      <div class="text-[11px] text-slate-400 mt-0.5">${s.lat.toFixed(3)}°N · ${s.lon.toFixed(3)}°E</div>
      <div class="text-sm mt-2">${status}</div>
      <div class="flex gap-2 mt-3">
        <button class="spot-map flex-1 py-1.5 rounded-lg bg-brand-50 text-brand-700 text-sm font-semibold hover:bg-brand-100" data-id="${s.id}">Voir sur la carte</button>
        <button class="spot-del py-1.5 px-3 rounded-lg text-red-600 text-sm font-semibold hover:bg-red-50" data-id="${s.id}">Supprimer</button>
      </div></div>`;
  }).join("") + `</div>`;

  box.querySelectorAll(".spot-name").forEach((inp) => {
    inp.addEventListener("blur", () => renameSpot(inp.dataset.id, inp.value));
    inp.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); inp.blur(); } });
  });
  box.querySelectorAll(".spot-map").forEach((b) => b.onclick = () => {
    const s = state.spots.find((x) => x.id === b.dataset.id);
    if (!s) return;
    setTab("carte");
    state.map.setView([s.lat, s.lon], Math.max(state.map.getZoom(), 12));
    loadPoint(s.lat, s.lon, s);
  });
  box.querySelectorAll(".spot-del").forEach((b) => b.onclick = () => deleteSpot(b.dataset.id));
}

boot();
