/* Sporia — frontend (Leaflet + Tailwind). Parle à l'API FastAPI (server.py). */
"use strict";

import { API } from "./api.js";
import {
  state, MONTHS, CMAP, LEVEL, FACTOR_CLR, LAYER_NAMES,
  CONF_BADGE, FOREST_TFV,
} from "./state.js";
import { escapeHtml, valFmt, fmtNum, pct, monthNum } from "./util.js";

/* Calques exclusifs (un seul affiché à la fois). def.refresh (re)construit
   state.layers[key] ; def.weather = dépend de la période. Défini ici (et non dans
   state.js) pour éviter un import circulaire avec les fonctions refresh*. */
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

/* ---------- Auth ---------- */
async function boot() {
  // Navigation accueil <-> connexion
  document.querySelectorAll(".open-login").forEach((b) => b.addEventListener("click", showLoginPage));
  document.querySelectorAll(".back-landing").forEach((b) => b.addEventListener("click", showLanding));
  setupLandingNav();
  // Retour depuis Stripe Checkout
  const params = new URLSearchParams(location.search);
  const justPaid = params.get("checkout") === "success";
  if (params.has("checkout")) history.replaceState({}, "", location.pathname);
  try {
    const me = await API.get("/api/me");
    applyPriceLabel(me.price_label);
    if (me.authenticated) {
      state.name = me.name;
      state.role = me.role;
      state.access = me.access;
      if (me.subscribed) { startApp(); return; }
      showPaywall(justPaid);
      return;
    }
  } catch (e) { /* ignore */ }
  showLanding();
}

function applyPriceLabel(label) {
  if (!label) return;
  state.priceLabel = label;
  document.querySelectorAll("[data-price-label]").forEach((el) => { el.textContent = label; });
}

function showPaywall(justPaid) {
  document.getElementById("landing-screen").classList.add("hidden");
  document.getElementById("login-screen").classList.add("hidden");
  document.getElementById("app-screen").classList.add("hidden");
  document.getElementById("paywall-screen").classList.remove("hidden");
  if (justPaid) {
    const note = document.getElementById("paywall-note");
    note.textContent = "Paiement reçu — activation en cours, actualisez dans un instant.";
    note.classList.remove("hidden");
  }
}

async function routeAfterAuth() {
  try {
    const me = await API.get("/api/me");
    applyPriceLabel(me.price_label);
    state.role = me.role;
    state.access = me.access;
    if (me.subscribed) { startApp(); return; }
  } catch (e) { /* ignore */ }
  showPaywall(false);
}

async function subscribe(btn) {
  if (btn) btn.disabled = true;
  try {
    const r = await API.post("/api/billing/checkout");
    location.href = r.url;
  } catch (e) {
    if (e && e.unauth) { showLoginPage(); return; }
    alert(e.message || "Abonnement indisponible pour le moment.");
    if (btn) btn.disabled = false;
  }
}

async function openPortal() {
  try {
    const r = await API.post("/api/billing/portal");
    location.href = r.url;
  } catch (e) {
    alert(e.message || "Portail indisponible.");
  }
}

async function deleteAccount() {
  if (!confirm("Supprimer définitivement votre compte, vos préférences et vos spots ? " +
               "Votre abonnement sera résilié. Cette action est irréversible.")) return;
  try {
    await API.del("/api/account");
  } catch (e) { /* on recharge quand même */ }
  location.reload();
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
  ["hero", "apercu", "sec-fiche", "sec-spots", "sec-mobile", "contact"].forEach((id) => {
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
  setAuthMode("login");
  setTimeout(() => document.getElementById("login-user").focus(), 50);
}

// Bascule Connexion / Créer un compte sur l'écran d'auth unifié
function setAuthMode(mode) {
  const login = mode !== "register";
  document.getElementById("login-form").classList.toggle("hidden", !login);
  document.getElementById("register-form").classList.toggle("hidden", login);
  document.querySelectorAll(".auth-tab").forEach((t) => {
    const on = t.dataset.authMode === mode;
    t.classList.toggle("bg-girolle", on);
    t.classList.toggle("text-sousbois", on);
    t.classList.toggle("text-os/60", !on);
  });
}
document.querySelectorAll(".auth-tab").forEach((t) =>
  t.addEventListener("click", () => setAuthMode(t.dataset.authMode)));
// Lien « Devenir bêta-testeur » depuis l'écran d'auth → retour landing, section contact
document.querySelectorAll(".goto-beta").forEach((b) =>
  b.addEventListener("click", () => {
    showLanding();
    setTimeout(() => document.getElementById("contact")?.scrollIntoView({ behavior: "smooth" }), 60);
  }));

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
    await routeAfterAuth();
  } catch (e) {
    err.textContent = e.message || "Échec de connexion.";
    err.classList.remove("hidden");
  }
});

document.getElementById("logout-btn").addEventListener("click", async () => {
  try { await API.post("/api/logout"); } catch (e) {}
  location.reload();
});

// Abonnement : paywall + portail
document.getElementById("subscribe-btn")?.addEventListener("click", (ev) => subscribe(ev.currentTarget));
document.getElementById("paywall-logout")?.addEventListener("click", async () => {
  try { await API.post("/api/logout"); } catch (e) {}
  location.reload();
});
document.getElementById("manage-sub")?.addEventListener("click", openPortal);
document.querySelectorAll(".subscribe-cta").forEach((b) =>
  b.addEventListener("click", (ev) => subscribe(ev.currentTarget)));
document.getElementById("delete-account")?.addEventListener("click", deleteAccount);
document.getElementById("retract-consent")?.addEventListener("change", (ev) => {
  const btn = document.getElementById("subscribe-btn");
  if (btn) btn.disabled = !ev.currentTarget.checked;
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

// Inscription (landing) → POST /api/register → connecté directement
document.getElementById("register-form")?.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const msg = document.getElementById("reg-msg");
  const btn = ev.target.querySelector("button[type=submit]");
  msg.classList.add("hidden");
  btn.disabled = true;
  try {
    const res = await API.post("/api/register", {
      email: document.getElementById("reg-email").value.trim(),
      password: document.getElementById("reg-pass").value,
      name: document.getElementById("reg-name").value.trim(),
    });
    state.name = res.name;
    await routeAfterAuth();
  } catch (e) {
    msg.textContent = e.message || "Inscription impossible.";
    msg.className = "text-sm font-semibold text-red-600";
    msg.classList.remove("hidden");
  } finally {
    btn.disabled = false;
  }
});

// Mot de passe oublié → POST /api/password/forgot (réponse neutre)
document.getElementById("forgot-link")?.addEventListener("click", async () => {
  const email = prompt("Votre email pour réinitialiser le mot de passe :");
  if (!email) return;
  try { await API.post("/api/password/forgot", { email: email.trim() }); } catch (e) {}
  alert("Si un compte existe, un email de réinitialisation a été envoyé.");
});

// Lien de reset (?reset=TOKEN dans l'URL) → nouveau mot de passe
(async () => {
  const tok = new URLSearchParams(location.search).get("reset");
  if (!tok) return;
  const pw = prompt("Nouveau mot de passe (min 8) :");
  if (!pw) return;
  try {
    await API.post("/api/password/reset", { token: tok, password: pw });
    alert("Mot de passe modifié. Connectez-vous.");
    location.href = "/";
  } catch (e) { alert("Lien invalide ou expiré."); }
})();

/* ---------- App ---------- */
async function startApp() {
  document.getElementById("landing-screen").classList.add("hidden");
  document.getElementById("login-screen").classList.add("hidden");
  document.getElementById("app-screen").classList.remove("hidden");
  document.getElementById("paywall-screen")?.classList.add("hidden");
  document.getElementById("nav-user").textContent = state.name || "";
  const profilUser = document.getElementById("profil-user");
  if (profilUser) profilUser.textContent = state.name ? `Connecté : ${state.name}` : "";
  // Un bêta-testeur n'a rien à gérer chez Stripe : on lui dit que l'accès est offert.
  const isBeta = state.access === "beta";
  document.getElementById("manage-sub")?.classList.toggle("hidden", isBeta);
  document.getElementById("beta-badge")?.classList.toggle("hidden", !isBeta);
  document.querySelector('.profil-act[data-target="manage-sub"]')?.classList.toggle("hidden", isBeta);
  document.getElementById("beta-badge-mobile")?.classList.toggle("hidden", !isBeta);
  if (state.role === "admin")
    document.querySelectorAll(".admin-only").forEach((el) => el.classList.remove("hidden"));

  const d = await API.get("/api/dates");
  state.dates = d.dates;
  computeSelectedDates();
  buildDateSlider();
  initMap();
  await loadPreferences();
  wireControls();
  // Hauteur réelle de la barre d'onglets basse → le bottom-sheet se cale juste au-dessus.
  const syncTabbarH = () =>
    document.documentElement.style.setProperty(
      "--tabbar-h", (document.getElementById("tabbar")?.offsetHeight || 0) + "px");
  const onResize = () => { syncTabbarH(); layoutChips(); };
  onResize();
  setTimeout(layoutChips, 250);   // recalcul après stabilisation des largeurs (police chargée)
  window.addEventListener("resize", onResize);
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
  // Deux fonds CARTO (même hôte → aucun ajout CSP) : clair par défaut, sombre en option.
  // Depuis 2026-09 les tuiles raster exigent une clé (`?key=`), sinon filigrane
  // « API key required ». Clé injectée par le serveur (env CARTO_API_KEY) via <meta>.
  const cartoKey = document.querySelector('meta[name="sporia:carto-key"]')?.content || "";
  const cartoUrl = (style) =>
    `https://{s}.basemaps.cartocdn.com/${style}/{z}/{x}/{y}{r}.png` +
    (cartoKey ? `?key=${encodeURIComponent(cartoKey)}` : "");
  // Attribution CARTO + OSM obligatoire : c'est la contrepartie du palier gratuit.
  const baseOpts = { attribution: "&copy; OpenStreetMap, &copy; CARTO", subdomains: "abcd", maxZoom: 19 };
  state.baseLight = L.tileLayer(cartoUrl("light_all"), baseOpts);
  state.baseDark = L.tileLayer(cartoUrl("dark_all"), baseOpts);
  try { state.darkMap = localStorage.getItem("sporia:darkmap") === "1"; } catch (e) { state.darkMap = false; }
  (state.darkMap ? state.baseDark : state.baseLight).addTo(state.map);
  document.body.classList.toggle("map-dark", state.darkMap);
  L.control.scale({ metric: true, imperial: false, position: "bottomright" }).addTo(state.map);

  // Bouton bascule fond clair / sombre (contrôle Leaflet → s'empile sous le zoom).
  const BasemapCtl = L.control({ position: "topright" });
  BasemapCtl.onAdd = () => {
    const b = L.DomUtil.create("button", "basemap-toggle-btn");
    b.id = "basemap-toggle";
    b.type = "button";
    b.innerHTML = state.darkMap ? "☀" : "☾";
    b.setAttribute("aria-label", "Basculer le fond de carte clair / sombre");
    b.title = state.darkMap ? "Fond clair" : "Fond sombre";
    L.DomEvent.disableClickPropagation(b);
    L.DomEvent.on(b, "click", () => setBasemap(!state.darkMap));
    return b;
  };
  BasemapCtl.addTo(state.map);

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

/* Bascule du fond de carte clair ↔ sombre (CARTO). Persiste le choix. */
function setBasemap(dark) {
  state.darkMap = dark;
  const add = dark ? state.baseDark : state.baseLight;
  const rem = dark ? state.baseLight : state.baseDark;
  if (state.map.hasLayer(rem)) state.map.removeLayer(rem);
  if (!state.map.hasLayer(add)) add.addTo(state.map);
  add.bringToBack();                                  // le fond reste sous les calques de données
  document.body.classList.toggle("map-dark", dark);   // hook overlays (lisibilité sur fond sombre)
  try { localStorage.setItem("sporia:darkmap", dark ? "1" : "0"); } catch (e) { /* mode privé */ }
  const btn = document.getElementById("basemap-toggle");
  if (btn) { btn.innerHTML = dark ? "☀" : "☾"; btn.title = dark ? "Fond clair" : "Fond sombre"; }
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

/* Curseur de dates à deux poignées (du…au…) : écrit directement state.selectedDates.
   oninput = MAJ live des libellés/remplissage ; onchange (relâchement) = recharge le calque. */
function buildDateSlider() {
  const n = (state.dates || []).length;
  const s = document.getElementById("dr-start");
  const e = document.getElementById("dr-end");
  if (!n || !s || !e) return;
  s.min = e.min = "0"; s.max = e.max = String(n - 1);
  s.value = String(n - 1); e.value = String(n - 1);   // défaut : dernier jour
  const fmt = (i) => { const d = state.dates[i]; return `${d.slice(6, 8)}/${d.slice(4, 6)}`; };
  const paint = () => {
    let a = +s.value, b = +e.value;
    if (a > b) [a, b] = [b, a];
    document.getElementById("dr-from").textContent = fmt(a);
    document.getElementById("dr-to").textContent = fmt(b);
    const pc = (v) => (n > 1 ? (v / (n - 1)) * 100 : 0);
    const fill = document.getElementById("dr-fill");
    fill.style.left = pc(a) + "%";
    fill.style.right = (100 - pc(b)) + "%";
    return [a, b];
  };
  const apply = () => {
    const [a, b] = paint();
    state.selectedDates = state.dates.slice(a, b + 1);
    if (state.activeLayer === "temp" || state.activeLayer === "precip") setActiveLayer(state.activeLayer);
  };
  s.oninput = paint; e.oninput = paint;
  s.onchange = apply; e.onchange = apply;
  paint();
}

function _setOverlay(key, res, opacity) {
  const b = res.bounds;
  if (state.layers[key]) state.map.removeLayer(state.layers[key]);
  state.layers[key] = L.imageOverlay(res.url, [[b.bottom, b.left], [b.top, b.right]],
                                      { opacity, interactive: false });
  if (state.activeLayer === key) state.layers[key].addTo(state.map);  // calque exclusif
}

/* Calques météo séparés : 'T' (température moyenne) et 'RR' (précipitations). */
export async function refreshWeatherLayer(varName) {
  if (!state.selectedDates.length) return;   // state.selectedDates piloté par le curseur de dates
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
export async function refreshRadar() {
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

export async function refreshSoil() {
  try {
    const res = await API.get("/api/soil");
    _setOverlay("soil", res, 0.8);
    state.legendData.soil = res.legend || [];
  } catch (e) { console.warn("soil", e); }
}

export async function refreshSoilMoisture() {
  try {
    const res = await API.get(`/api/soil-moisture?date=${state.dates[state.dates.length - 1] || ""}`);
    _setOverlay("soilmoist", res, 0.78);
  } catch (e) { console.warn("soilmoist", e); }
}

export async function refreshAltitude() {
  try {
    const res = await API.get("/api/altitude");
    _setOverlay("altitude", res, 0.7);
  } catch (e) { console.warn("altitude", e); }
}

export async function refreshAspect() {
  try {
    const res = await API.get("/api/aspect");
    _setOverlay("aspect", res, 0.75);
  } catch (e) { console.warn("aspect", e); }
}

/* ---------- Légende (calque actif) ---------- */
function _grad(colors) {
  return `<div class="h-2.5 rounded-sm mb-1" style="background:linear-gradient(to right, ${colors.join(",")})"></div>`;
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
  const legEl = document.getElementById("active-legend");   // légende du volet (peut être supprimée)
  if (legEl) legEl.innerHTML = html;
  const wrap = document.getElementById("active-legend-wrap");
  if (wrap) wrap.classList.toggle("hidden", !html);
  const capt = document.getElementById("map-legend");   // légende en étiquette sur la carte (direction A)
  if (capt) { capt.innerHTML = html; capt.classList.toggle("hidden", !html); }
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

function updateActiveLayerName() {
  const el = document.getElementById("active-layer-name");
  if (!el) return;
  el.textContent = LAYER_NAMES[state.activeLayer] || "";
  el.classList.toggle("hidden", !el.textContent);   // titre TOUJOURS visible (sauf si vide)
}

/* Priority+ : affiche autant de puces de calques que la largeur le permet ;
   les puces qui débordent basculent dans le menu « ＋ Plus ». Recalculé au resize. */
function layoutChips() {
  const row = document.getElementById("chips-row");
  const bar = document.getElementById("layer-chips");
  const moreWrap = document.getElementById("more-wrap");
  if (!row || !bar || !moreWrap) return;
  const chips = Array.from(bar.querySelectorAll(".layer-chip"));
  if (!chips.length) return;
  const GAP = 6;
  chips.forEach((c) => c.classList.remove("hidden"));   // tout afficher pour mesurer
  moreWrap.classList.remove("hidden");
  const rowW = row.clientWidth;
  if (!rowW) return;                                    // onglet Carte masqué → recalcul à l'affichage
  const moreW = moreWrap.offsetWidth + GAP;
  const w = chips.map((c) => c.offsetWidth);
  const total = w.reduce((a, x, i) => a + x + (i ? GAP : 0), 0);
  let fit;
  if (total <= rowW) {
    fit = chips.length;                                 // tout rentre → pas de « ＋ Plus »
  } else {
    let used = 0; fit = 0;
    for (let i = 0; i < chips.length; i++) {
      const need = w[i] + (i ? GAP : 0);
      if (used + need <= rowW - moreW) { used += need; fit++; } else break;
    }
    fit = Math.max(1, fit);                             // au moins « Radar »
  }
  let overflowActive = false;
  chips.forEach((c, i) => {
    const inBar = i < fit;
    c.classList.toggle("hidden", !inBar);
    const item = document.querySelector(`.more-item[data-layer="${c.dataset.layer}"]`);
    if (item) item.classList.toggle("hidden", inBar);   // more-item visible ⇔ puce débordée
    if (!inBar && c.dataset.layer === state.activeLayer) overflowActive = true;
  });
  moreWrap.classList.toggle("hidden", fit >= chips.length);
  const mb = document.getElementById("more-layers-btn");
  if (mb) {   // « ＋ Plus » surligné si le calque actif est rangé dedans
    mb.classList.toggle("bg-girolle", overflowActive);
    mb.classList.toggle("text-sousbois", overflowActive);
    mb.classList.toggle("bg-sousbois", !overflowActive);
    mb.classList.toggle("text-os", !overflowActive);
  }
}

/* ---------- Calques exclusifs (un seul affiché à la fois) ---------- */
async function setActiveLayer(key) {
  state.activeLayer = key;
  // Sync des contrôles : puces (carte) + radios (volet)
  document.querySelectorAll(".layer-chip").forEach((c) => {
    const on = c.dataset.layer === key;
    c.classList.toggle("bg-girolle", on);
    c.classList.toggle("text-sousbois", on);
    c.classList.toggle("bg-sousbois", !on);
    c.classList.toggle("text-os", !on);
  });
  document.querySelectorAll('input[name="layer"]').forEach((r) => { r.checked = (r.value === key); });
  // « ＋ Plus » surligné si le calque actif est rangé dans le menu (puce débordée)
  const moreB = document.getElementById("more-layers-btn");
  if (moreB) {
    const chip = document.querySelector(`#layer-chips .layer-chip[data-layer="${key}"]`);
    const inMenu = !!chip && chip.classList.contains("hidden");
    moreB.classList.toggle("bg-girolle", inMenu);
    moreB.classList.toggle("text-sousbois", inMenu);
    moreB.classList.toggle("bg-sousbois", !inMenu);
    moreB.classList.toggle("text-os", !inMenu);
  }
  // Période : utile seulement pour les calques météo (température / précipitations) → masquée sinon
  const pb = document.getElementById("period-block");
  if (pb) pb.classList.toggle("hidden", !(key === "temp" || key === "precip"));
  const dr = document.getElementById("date-range");   // curseur de dates : Température / Pluie
  if (dr) dr.classList.toggle("hidden", !(key === "temp" || key === "precip"));
  const rs = document.getElementById("radar-species");  // masquer tout de suite hors radar (sans attendre le refresh async)
  if (rs && key !== "radar") rs.classList.add("hidden");
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
  // Puces de calques (direction A) : switch rapide depuis la carte
  document.querySelectorAll(".layer-chip").forEach((c) =>
    c.addEventListener("click", () => setActiveLayer(c.dataset.layer)));
  // « ＋ Plus » : menu des calques secondaires
  const moreBtn = document.getElementById("more-layers-btn");
  const morePop = document.getElementById("more-layers");
  moreBtn?.addEventListener("click", (e) => { e.stopPropagation(); morePop.classList.toggle("hidden"); });
  document.querySelectorAll(".more-item").forEach((b) =>
    b.addEventListener("click", () => morePop.classList.add("hidden")));
  document.addEventListener("click", (e) => {
    if (morePop && !morePop.classList.contains("hidden") && !morePop.contains(e.target) && e.target !== moreBtn)
      morePop.classList.add("hidden");
  });
  // Espèces du radar : popover depuis le bouton « 🍄 Espèces »
  const rsBtn = document.getElementById("radar-species-btn");
  const rsPop = document.getElementById("radar-species-pop");
  rsBtn?.addEventListener("click", (e) => { e.stopPropagation(); rsPop.classList.toggle("hidden"); });
  document.addEventListener("click", (e) => {
    if (rsPop && !rsPop.classList.contains("hidden") && !rsPop.contains(e.target) && !rsBtn.contains(e.target))
      rsPop.classList.add("hidden");
  });
  // « Tout / Aucun » : coche/décoche toutes les espèces du radar
  document.getElementById("radar-all-toggle")?.addEventListener("click", () => {
    const boxes = Array.from(document.querySelectorAll("#radar-species-list .radar-check"));
    const allChecked = boxes.length > 0 && boxes.every((b) => b.checked);
    state.radarSpecies = allChecked ? [] : null;   // tout coché → tout décocher (sous-ensemble vide) ; sinon tout cocher (null)
    refreshRadar();   // updateLegend rappelle updateRadarSpecies → cases resynchronisées
  });

  // Période → recharge le calque météo actif
  document.querySelectorAll(".period-btn").forEach((b) =>
    b.addEventListener("click", () => {
      document.querySelectorAll(".period-btn").forEach((x) => x.setAttribute("aria-selected", "false"));
      b.setAttribute("aria-selected", "true");
      state.period = b.dataset.period;
      computeSelectedDates();
      if (state.activeLayer === "temp" || state.activeLayer === "precip") setActiveLayer(state.activeLayer);
    }));

  // Bouton « Fou des champignons » (volet, si présent) : déplie/replie le panneau calques
  document.getElementById("godmode-btn")?.addEventListener("click", () => {
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

  // Modale « Demandes d'accès » (admin)
  document.getElementById("admin-requests-btn").addEventListener("click", openAccessRequests);
  document.getElementById("areq-close").addEventListener("click", closeAccessRequests);
  document.getElementById("areq-backdrop").addEventListener("click", closeAccessRequests);

  // Modale « Comptes » (admin)
  document.getElementById("admin-accounts-btn")?.addEventListener("click", openAccounts);
  document.getElementById("acct-close")?.addEventListener("click", closeAccounts);
  document.getElementById("acct-backdrop")?.addEventListener("click", closeAccounts);
  document.getElementById("acct-filter")?.addEventListener("input", (e) => {
    renderAccounts(state.accounts || [], e.target.value);
  });

  document.querySelectorAll(".tab-btn, .tabbar-btn").forEach((b) =>
    b.addEventListener("click", () => setTab(b.dataset.tab)));
  // Onglet Profil (mobile) : chaque bouton relaie vers l'action correspondante du top-nav.
  document.querySelectorAll(".profil-act").forEach((b) =>
    b.addEventListener("click", () => document.getElementById(b.dataset.target)?.click()));
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

  // Replier / déployer la barre latérale (si le volet existe encore)
  document.getElementById("sidebar-toggle")?.addEventListener("click", toggleSidebar);

  // Menu compte (desktop) : ouvre/ferme le dropdown ; referme après une action ou clic extérieur.
  const accBtn = document.getElementById("account-btn");
  const accMenu = document.getElementById("account-menu");
  accBtn?.addEventListener("click", (e) => { e.stopPropagation(); toggleNotifPanel(false); accMenu.classList.toggle("hidden"); });
  accMenu?.addEventListener("click", () => accMenu.classList.add("hidden"));
  document.addEventListener("click", (e) => {
    if (accMenu && !accMenu.classList.contains("hidden") && !accMenu.contains(e.target) && !accBtn.contains(e.target))
      accMenu.classList.add("hidden");
  });

  // Cloche de notifications (spots propices)
  document.getElementById("notif-btn").addEventListener("click", (e) => { e.stopPropagation(); accMenu?.classList.add("hidden"); toggleNotifPanel(); });
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

function confidenceBadge(conf) {
  const cls = CONF_BADGE[conf] || CONF_BADGE["modérée"];
  return `<span class="shrink-0 text-[10px] font-semibold px-1.5 py-0.5 rounded-sm ${cls}" title="Fiabilité de la carte d'habitat">${conf || "modérée"}</span>`;
}

function openSpeciesModal() {
  const sel = new Set(state.species || state.allSpecies.map((s) => s.latin));
  const legend = `<p class="text-[11px] text-os/50 mb-1 px-1">Badge = fiabilité de la carte d'habitat (<span class="text-green-400 font-semibold">élevée</span> · <span class="text-amber-400 font-semibold">bonne</span> · <span class="text-os/60 font-semibold">modérée</span>).</p>`;
  document.getElementById("species-list").innerHTML = legend + state.allSpecies.map((s) =>
    `<label class="flex items-center gap-2 p-2 rounded-sm border border-os/10 hover:bg-os/10 cursor-pointer">
       <input type="checkbox" class="sp-check accent-girolle" value="${s.latin}" ${sel.has(s.latin) ? "checked" : ""}>
       <span class="inline-block w-3 h-3 rounded-full shrink-0" style="background:${s.color}"></span>
       <span class="text-sm truncate flex-1">${s.nom}</span>
       ${confidenceBadge(s.confidence)}
     </label>`).join("");
  document.querySelectorAll("#species-list .sp-check").forEach((c) =>
    c.addEventListener("change", updateSpeciesCount));
  updateSpeciesCount();
  document.getElementById("species-modal").classList.remove("hidden");
}

function closeSpeciesModal() { document.getElementById("species-modal").classList.add("hidden"); }

/* ---------- Demandes d'accès (admin) ---------- */
async function openAccessRequests() {
  const list = document.getElementById("areq-list");
  list.innerHTML = `<div class="text-sm text-os/50 text-center py-6">Chargement…</div>`;
  document.getElementById("access-requests-modal").classList.remove("hidden");
  try {
    const r = await API.get("/api/access-requests");
    renderAccessRequests(r.requests || []);
  } catch (e) {
    list.innerHTML = `<div class="text-sm text-red-400 text-center py-6">Erreur de chargement.</div>`;
  }
}

function closeAccessRequests() {
  document.getElementById("access-requests-modal").classList.add("hidden");
}

function renderAccessRequests(reqs) {
  const list = document.getElementById("areq-list");
  if (!reqs.length) {
    list.innerHTML = `<div class="text-sm text-os/50 text-center py-6">Aucune demande pour le moment.</div>`;
    return;
  }
  // list_requests() renvoie les plus anciennes d'abord → on affiche les plus récentes en haut.
  list.innerHTML = reqs.slice().reverse().map((r) => {
    const date = r.created ? new Date(r.created * 1000).toLocaleDateString("fr-FR") : "";
    return `<div class="rounded-sm border border-os/10 bg-os/5 p-3" data-id="${escapeHtml(r.id)}">
      <div class="flex items-start justify-between gap-2">
        <div class="min-w-0">
          <div class="font-semibold text-sm text-os truncate">${escapeHtml(r.name)}</div>
          <div class="text-xs text-os/60 truncate">${escapeHtml(r.email)}</div>
        </div>
        <span class="text-[11px] text-os/50 shrink-0">${date}</span>
      </div>
      <div class="mt-2 text-sm text-os/70 whitespace-pre-line break-words">${escapeHtml(r.message)}</div>
      <div class="areq-action mt-3 flex gap-2">
        <button class="areq-create px-3 py-1.5 rounded-sm bg-girolle hover:bg-lactaire text-sousbois text-xs font-bold shadow-card transition">Créer le compte</button>
        <button class="areq-reject px-3 py-1.5 rounded-sm bg-transparent border border-os/20 text-os/60 hover:text-red-400 hover:border-red-400/40 text-xs font-bold transition">Refuser</button>
      </div>
    </div>`;
  }).join("");
  list.querySelectorAll("[data-id]").forEach((card) => {
    card.querySelector(".areq-create").addEventListener("click", () => createFromRequest(card));
    card.querySelector(".areq-reject").addEventListener("click", () => rejectRequest(card));
  });
}

async function createFromRequest(card) {
  const box = card.querySelector(".areq-action");
  box.innerHTML = `<span class="text-xs text-os/50">Création…</span>`;
  try {
    const r = await API.post("/api/admin/accounts/from-request", { request_id: card.dataset.id });
    card.classList.add("opacity-70");
    box.innerHTML =
      `<div class="text-xs font-semibold text-green-400">✓ Compte créé — ${escapeHtml(r.email)}</div>
       <div class="mt-1 text-[11px] text-os/60">Lien d'invitation (aussi envoyé par email) :</div>
       <div class="mt-1 flex items-center gap-1.5">
         <input class="areq-link flex-1 min-w-0 text-[11px] px-2 py-1 rounded border border-os/20 bg-os/10 text-os" readonly value="${escapeHtml(r.invite_url)}">
         <button class="areq-copy px-2 py-1 rounded bg-os/10 hover:bg-os/20 text-os text-[11px] font-semibold shrink-0">Copier</button>
       </div>`;
    box.querySelector(".areq-copy").addEventListener("click", () => {
      const inp = box.querySelector(".areq-link");
      inp.select();
      navigator.clipboard?.writeText(inp.value);
    });
  } catch (e) {
    box.innerHTML = `<div class="text-xs text-red-400">${escapeHtml(e.message || "Échec de la création.")}</div>`;
  }
}

async function rejectRequest(card) {
  const box = card.querySelector(".areq-action");
  box.innerHTML = `<span class="text-xs text-os/50">Suppression…</span>`;
  try {
    await API.del(`/api/access-requests/${encodeURIComponent(card.dataset.id)}`);
    const list = card.parentElement;
    card.remove();
    if (!list.querySelector("[data-id]"))
      list.innerHTML = `<div class="text-sm text-os/50 text-center py-6">Aucune demande pour le moment.</div>`;
  } catch (e) {
    box.innerHTML = `<div class="text-xs text-red-400">${escapeHtml(e.message || "Échec de la suppression.")}</div>`;
  }
}

/* ---------- Comptes (admin) ---------- */
const ACCESS_LABEL = {
  admin: ["Admin", "text-girolle"],
  beta: ["Bêta — offert", "text-green-300"],
  active: ["Abonné", "text-green-300"],
  none: ["Aucun accès", "text-os/50"],
};

function accountKind(a) {
  if (a.role === "admin") return "admin";
  if (a.subscription_status === "beta") return "beta";
  if (a.subscription_status === "active") return "active";
  if (a.current_period_end && a.current_period_end * 1000 > Date.now()) return "active";
  return "none";
}

async function openAccounts() {
  const list = document.getElementById("acct-list");
  list.innerHTML = `<div class="text-sm text-os/50 text-center py-6">Chargement…</div>`;
  document.getElementById("accounts-modal").classList.remove("hidden");
  try {
    const r = await API.get("/api/admin/accounts");
    state.accounts = r.accounts || [];
    state.accountsTruncated = !!r.truncated;
    renderAccounts(state.accounts, document.getElementById("acct-filter").value);
  } catch (e) {
    list.innerHTML = `<div class="text-sm text-red-400 text-center py-6">Erreur de chargement.</div>`;
  }
}

function closeAccounts() {
  document.getElementById("accounts-modal").classList.add("hidden");
}

function renderAccounts(accounts, filter) {
  const list = document.getElementById("acct-list");
  const q = (filter || "").trim().toLowerCase();
  const rows = q
    ? accounts.filter((a) => `${a.email} ${a.name || ""}`.toLowerCase().includes(q))
    : accounts;
  if (!rows.length) {
    list.innerHTML = `<div class="text-sm text-os/50 text-center py-6">Aucun compte.</div>`;
    return;
  }
  const banner = state.accountsTruncated
    ? `<div class="text-xs text-amber-300 pb-2">Liste plafonnée aux 500 comptes les plus récents.</div>`
    : "";
  list.innerHTML = banner + rows.map((a) => {
    const kind = accountKind(a);
    const [label, cls] = ACCESS_LABEL[kind];
    const date = a.created_at ? new Date(a.created_at * 1000).toLocaleDateString("fr-FR") : "";
    const locked = kind === "admin" || kind === "active";
    const btn = locked
      ? `<span class="text-[11px] text-os/40 shrink-0" title="${kind === "admin" ? "Le rôle admin donne déjà l'accès." : "Statut géré par Stripe."}">non modifiable</span>`
      : `<button class="acct-toggle px-3 py-1.5 rounded-sm bg-girolle hover:bg-lactaire text-sousbois text-xs font-bold shadow-card transition shrink-0" data-next="${kind === "beta" ? "none" : "beta"}">${kind === "beta" ? "Retirer la bêta" : "Passer en bêta"}</button>`;
    return `<div class="rounded-sm border border-os/10 bg-os/5 p-3 flex items-center justify-between gap-3" data-email="${escapeHtml(a.email)}">
      <div class="min-w-0">
        <div class="font-semibold text-sm text-os truncate">${escapeHtml(a.name || a.email)}</div>
        <div class="text-xs text-os/60 truncate">${escapeHtml(a.email)}</div>
        <div class="text-[11px] mt-0.5 ${cls}">${label}${date ? ` · inscrit le ${date}` : ""}</div>
      </div>
      ${btn}
    </div>`;
  }).join("");
  list.querySelectorAll(".acct-toggle").forEach((b) => {
    b.addEventListener("click", () => toggleAccountAccess(b));
  });
}

async function toggleAccountAccess(btn) {
  const email = btn.closest("[data-email]").dataset.email;
  btn.disabled = true;
  try {
    await API.post("/api/admin/accounts/access", { email, status: btn.dataset.next });
    await openAccounts();   // recharge : le statut vient toujours du serveur
  } catch (e) {
    btn.disabled = false;
    alert(e.message || "Bascule impossible.");
  }
}

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
      `<button data-i="${i}" class="city-pick w-full text-left text-sm px-3 py-1.5 rounded-sm hover:bg-os/10 border border-transparent hover:border-os/20">${r.label}</button>`
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
    b.classList.toggle("bg-girolle", active);
    b.classList.toggle("text-sousbois", active);
    b.classList.toggle("text-os/70", !active);
  });
  document.querySelectorAll(".tabbar-btn").forEach((b) => {
    const active = b.dataset.tab === tab;
    b.classList.toggle("text-girolle", active);
    b.classList.toggle("text-os/50", !active);
  });
  state.tab = tab;
  document.getElementById("view-carte").classList.toggle("hidden", tab !== "carte");
  document.getElementById("view-guide").classList.toggle("hidden", tab !== "guide");
  document.getElementById("view-spots").classList.toggle("hidden", tab !== "spots");
  document.getElementById("view-profil").classList.toggle("hidden", tab !== "profil");
  applySidebar(true);   // barre latérale : visible seulement sur Carte, et selon repli
  if (tab === "carte") setTimeout(layoutChips, 60);   // la largeur des puces n'existe que la vue Carte visible
  if (tab === "guide") renderGuide();
  if (tab === "spots") renderSpots();
}

/* Barre latérale (recherche + calques) : visible uniquement sur l'onglet Carte
   et si non repliée. Le bouton de bascule n'apparaît que sur Carte. */
function applySidebar(resize) {
  const onMap = state.tab === "carte";
  const sb = document.getElementById("sidebar");   // volet (peut être supprimé)
  if (sb) {
    sb.classList.toggle("hidden", !onMap);                          // pas de barre hors Carte
    if (!onMap) sb.classList.remove("sheet-open");                  // referme la feuille Calques (mobile)
    sb.classList.toggle("-translate-x-full", state.sidebarCollapsed); // repli = glissement CSS
    const icon = document.getElementById("sidebar-toggle-icon");
    if (icon) icon.textContent = state.sidebarCollapsed ? "»" : "«";
  }
  // invalidateSize au changement d'onglet (la carte (ré)apparaît).
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
  return `<div class="${c} border rounded-sm px-2 py-1.5 text-center">
    <div class="text-base font-extrabold">${big}</div><div class="text-[10px] opacity-70">${small}</div></div>`;
}
/* Pastille d'adéquation du pH du sol pour une espèce. */
function phBadge(soilPh) {
  if (soilPh === "ok") return '<span class="text-[10px] font-bold px-2 py-0.5 rounded-sm text-green-300 bg-green-500/15">pH favorable</span>';
  if (soilPh === "mid") return '<span class="text-[10px] font-bold px-2 py-0.5 rounded-sm text-amber-300 bg-amber-500/15">pH acceptable</span>';
  if (soilPh === "no") return '<span class="text-[10px] font-bold px-2 py-0.5 rounded-sm text-red-300 bg-red-500/15">pH inadapté</span>';
  return "";
}

function hostDot(host) {
  if (host === "ok") return '<span class="text-[10px] font-bold text-green-400">· hôte présent</span>';
  if (host === "no") return '<span class="text-[10px] font-bold text-red-400">· hôte absent</span>';
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
    ? `<span class="font-semibold">${r.soil.texture_fr}</span> <span class="text-os/50">· pH ${fmtNum(r.soil.ph)}${r.soil.ph_class ? " (" + r.soil.ph_class + ")" : ""}</span>`
    : "";
  const terrainLine = r.terrain && r.terrain.altitude != null
    ? `<span class="font-semibold">${Math.round(r.terrain.altitude)} m</span> <span class="text-os/50">· ${r.terrain.exposition || ""}</span>`
    : "";
  const spot = state.lastSpot;
  const titleHtml = spot
    ? `<input class="pc-title font-bold text-os leading-tight bg-transparent w-full border-b border-dashed border-os/30 focus:border-solid focus:border-girolle outline-none" value="${escapeHtml(spot.name)}" title="Cliquez pour renommer">`
    : `<div class="font-bold text-os leading-tight">${r.commune || "Point sélectionné"}</div>`;
  // Aperçu (P2) : espèces favorables (level « good ») → badge + pastilles ; repli du détail sur mobile.
  const favs = r.mushrooms.filter((m) => m.level === "good" && m.selected !== false);
  const chipList = (favs.length ? favs : top).slice(0, 4);
  const chips = chipList.length
    ? chipList.map((m) => {
        const [, fg, bg] = LEVEL[m.level];
        return `<span class="inline-flex items-center text-[11px] font-semibold px-2 py-0.5 rounded-sm ${fg} ${bg}">${m.nom}</span>`;
      }).join("")
    : '<span class="text-xs text-os/50">Aucune espèce en saison ici.</span>';
  const peekBadge = favs.length
    ? `<span class="text-[11px] font-bold px-2 py-0.5 rounded-sm text-green-300 bg-green-500/15">${favs.length} favorable${favs.length > 1 ? "s" : ""}</span>`
    : "";
  const card = document.getElementById("point-card");
  card.classList.remove("expanded");
  card.innerHTML = `
    <div class="pc-handle"></div>
    <div class="flex items-start justify-between gap-2">
      <div class="min-w-0">${titleHtml}<div class="mt-1">${peekBadge}</div></div>
      <button class="pc-close text-os/50 hover:text-os -mt-1 -mr-1 text-lg leading-none shrink-0">×</button>
    </div>
    <div class="mt-1.5 flex flex-wrap gap-1.5">${chips}</div>
    <button class="pc-expand mt-2 w-full py-1.5 rounded-sm bg-os/10 text-os/80 text-sm font-semibold hover:bg-os/20">Voir le détail ▾</button>
    <div class="pc-detail mt-2">
      <div class="text-[11px] text-os/50 mb-2">${r.lat.toFixed(3)}°N · ${r.lon.toFixed(3)}°E · dalle 1 km</div>
      <div class="grid grid-cols-2 gap-2 mb-2">
        ${miniStat(valFmt(r.t, "°C"), "température air", factorLevel("temp", r.t))}
        ${miniStat(valFmt(r.rr, "mm"), "pluie / jour")}
        ${miniStat(pct(r.soil_moisture), "humidité du sol", factorLevel("soil_moisture", r.soil_moisture))}
        ${miniStat(valFmt(r.soil_temp, "°C"), "T° du sol", factorLevel("temp", r.soil_temp))}
      </div>
      <div class="text-xs mb-1.5 pc-forest">${forestLine}</div>
      ${soilLine ? `<div class="text-xs mb-1.5 text-os/70">${soilLine}</div>` : ""}
      ${terrainLine ? `<div class="text-xs mb-2 text-os/70">${terrainLine}</div>` : ""}
      <div class="text-[11px] font-bold uppercase tracking-wide text-os/50 mb-1">Probables ici</div>
      <div class="space-y-1 mb-1">
        ${top.length ? top.map((m) => {
          const [, fg, bg] = LEVEL[m.level];
          return `<div class="flex items-center gap-2 text-sm">
            <span class="flex-1 truncate">${m.nom} ${hostDot(m.host)}</span>
            <span class="text-[10px] font-bold px-2 py-0.5 rounded-sm ${fg} ${bg}">${m.label}${m.score_pct != null ? " · " + m.score_pct + "%" : ""}</span></div>`;
        }).join("") : '<div class="text-xs text-os/50">Aucune espèce en saison.</div>'}
      </div>
      <button class="pc-guide mt-2 w-full py-1.5 rounded-sm bg-girolle text-sousbois text-sm font-bold hover:bg-lactaire transition">Voir le guide complet</button>
      ${spot
        ? `<button class="pc-delete mt-1.5 w-full py-1.5 rounded-sm border border-red-400/40 text-red-400 text-sm font-semibold hover:bg-red-500/10 transition">🗑 Supprimer ce spot</button>`
        : `<button class="pc-save mt-1.5 w-full py-1.5 rounded-sm border border-girolle/50 text-girolle text-sm font-semibold hover:bg-os/10 transition">📍 Enregistrer ce spot</button>`}
    </div>`;
  card.classList.remove("hidden");
  positionPointCard();
  const expandBtn = card.querySelector(".pc-expand");
  if (expandBtn) expandBtn.onclick = () => {
    const exp = card.classList.toggle("expanded");
    expandBtn.textContent = exp ? "Réduire ▴" : "Voir le détail ▾";
  };
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
  // Mobile : bottom-sheet ancré en bas (CSS) → pas de positionnement au pixel.
  if (window.matchMedia("(max-width: 1023px)").matches) { card.style.left = ""; card.style.top = ""; return; }
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
      style="background:${active ? color : "rgba(239,230,211,.08)"};color:${active ? "#fff" : "rgba(239,230,211,.4)"};
      ${cur ? "box-shadow:inset 0 0 0 2px #efe6d3;" : ""}">${mn}</div>`;
  }).join("") + `</div>`;
}

function renderGuide() {
  const box = document.getElementById("guide-content");
  const r = state.lastPoint;
  if (!r) {
    box.innerHTML = `<div class="bg-os/5 border border-os/10 rounded-sm p-6 text-os/70 max-w-xl">
      <div class="mb-3">Aucun point sélectionné. Cliquez sur la carte (onglet Carte) ou cherchez une ville.</div>
      <input id="guide-city-input" type="text" placeholder="Ville ou code postal…"
             class="w-full px-3 py-2 rounded-sm bg-transparent text-os placeholder:text-os/40 border border-os/20 focus:border-girolle focus:ring-2 focus:ring-girolle/30 outline-none text-sm" />
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
    ? `<div class="bg-os/5 border-l-4 border-green-600 border border-os/10 rounded-sm p-4 mb-4 shadow-soft">
         <div class="font-bold">${r.forest.tfv}</div>
         <div class="text-sm text-os/70 mt-0.5">Essence dominante : <strong>${r.forest.essence || "—"}</strong> ·
         famille d'hôte : <strong>${fam[r.family] || r.family || "?"}</strong> — les espèces dont l'arbre-hôte
         est présent sont mises en avant (BD&nbsp;Forêt® V2, IGN).</div></div>`
    : (famTitle
      ? `<div class="bg-os/5 border-l-4 border-green-600 border border-os/10 rounded-sm p-4 mb-4 shadow-soft">
           <div class="font-bold">${famTitle}</div>
           <div class="text-sm text-os/70 mt-0.5">Famille d'hôte : <strong>${fam[r.family] || r.family || "?"}</strong> —
           les espèces dont l'arbre-hôte est présent sont mises en avant (BD&nbsp;Forêt® V2, IGN).</div></div>`
      : `<div class="bg-os/5 border-l-4 border-os/40 border border-os/10 rounded-sm p-4 mb-4 shadow-soft">
           <div class="font-bold">Hors forêt cartographiée</div>
           <div class="text-sm text-os/70 mt-0.5">Privilégiez les espèces de prés/lisières, ou cliquez sur une forêt voisine.</div></div>`);

  const soil = r.soil || {};
  const texSeg = (label, v, color) => (v == null ? "" :
    `<div style="width:${v}%;background:${color}" title="${label} ${fmtNum(v)} %"></div>`);
  const soilBanner = soil.texture_fr
    ? `<div class="bg-os/5 border-l-4 border-amber-700 border border-os/10 rounded-sm p-4 mb-4 shadow-soft">
         <div class="font-bold">Sol : ${soil.texture_fr}
           ${soil.ph != null ? `<span class="text-sm font-normal text-os/50">· pH ${fmtNum(soil.ph)} (${soil.ph_class || ""})</span>` : ""}</div>
         <div class="flex h-2.5 rounded-sm overflow-hidden my-2 border border-os/20">
           ${texSeg("Sable", soil.sand, "#eab308")}${texSeg("Limon", soil.silt, "#84cc16")}${texSeg("Argile", soil.clay, "#b45309")}</div>
         <div class="text-sm text-os/70">Sable ${fmtNum(soil.sand)} % · Limon ${fmtNum(soil.silt)} % · Argile ${fmtNum(soil.clay)} %
           — humidité <strong>${pct(r.soil_moisture)}</strong>, T° du sol <strong>${valFmt(r.soil_temp, "°C")}</strong>.
           <span class="text-os/50">(SoilGrids® ISRIC + Open-Meteo)</span></div></div>`
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
      ? `<span class="text-[10px] font-bold px-2 py-0.5 rounded-sm text-green-300 bg-green-500/15">hôte présent</span>`
      : (m.host === "no" ? `<span class="text-[10px] font-bold px-2 py-0.5 rounded-sm text-red-300 bg-red-500/15">hôte absent ici</span>` : "");
    return `<div class="bg-os/5 border border-os/10 rounded-sm p-4 shadow-soft">
      <div class="flex items-center gap-2">
        <span class="font-bold flex-1">${m.nom}</span>
        <span class="text-[10px] font-bold px-2 py-0.5 rounded-sm ${fg} ${bg}">${m.label}${m.score_pct != null ? " · " + m.score_pct + "%" : ""}</span>
        ${hostBadge}
      </div>
      <div class="text-xs italic text-os/50">${m.latin}</div>
      ${monthStrip(m.months, m.color, monthNum(r.month))}
      <div class="text-xs text-os/70">T° ${m.t_min}–${m.t_max} °C&nbsp;&nbsp;·&nbsp;&nbsp;pluie ${m.rain_lag[0]}–${m.rain_lag[1]} j après</div>
      <div class="text-xs text-os/50 mt-1.5">${m.habitat}</div>
      ${(m.soil_pref || phBadge(m.soil_ph)) ? `<div class="flex items-center gap-1.5 flex-wrap mt-1.5 pt-1.5 border-t border-os/10">
        ${phBadge(m.soil_ph)}<span class="text-xs text-os/60">${m.soil_pref || ""}</span></div>` : ""}
    </div>`;
  }).join("");

  box.innerHTML = `
    <div class="bg-os/5 border border-os/10 rounded-sm p-4 mb-4 shadow-soft">
      <div class="font-bold">${r.commune || "Point sélectionné"}
        <span class="text-xs font-normal text-os/50">${r.lat.toFixed(3)}°N · ${r.lon.toFixed(3)}°E · dalle 1 km</span></div>
    </div>
    ${banner}${soilBanner}${summary}
    <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">${cards}</div>`;
}

function chip(big, small, level) {
  const c = level ? FACTOR_CLR[level] + " border" : "bg-os/5 border border-os/10 text-os";
  return `<div class="${c} rounded-sm px-3 py-2 text-center shadow-soft">
    <div class="font-extrabold">${big}</div><div class="text-[11px] opacity-70">${small}</div></div>`;
}
/* ---------- Spots enregistrés + notifications « propice » ---------- */
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
    panel.innerHTML = `<div class="p-3 text-sm text-os/60">Aucun spot enregistré.<br>Cliquez sur la carte puis « Enregistrer ce spot ».</div>`;
    return;
  }
  if (!propices.length) {
    panel.innerHTML = `<div class="p-3 text-sm text-os/60">Aucun de vos ${state.spots.length} spot(s) n'est particulièrement propice aujourd'hui.</div>`;
    return;
  }
  panel.innerHTML =
    `<div class="px-3 pt-2 pb-1 text-[11px] font-bold uppercase tracking-wide text-os/50">Propices en ce moment</div>` +
    propices.map((s) =>
      `<button class="notif-item w-full text-left px-3 py-2 rounded-sm hover:bg-os/10 flex items-center gap-2" data-id="${s.id}">
         <span class="text-lg leading-none">🍄</span>
         <span class="flex-1 min-w-0">
           <span class="block font-semibold text-os truncate">${escapeHtml(s.name)}</span>
           <span class="block text-[11px] text-green-400 font-semibold">Très propice · indice ${s.score_pct} %</span>
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
    box.innerHTML = `<div class="bg-os/5 border border-os/10 rounded-sm p-6 text-os/70 max-w-xl shadow-soft">
      Aucun spot enregistré. Sur l'onglet <strong>Carte</strong>, cliquez sur un endroit puis « 📍 Enregistrer ce spot ».</div>`;
    return;
  }
  box.innerHTML = `<div class="grid grid-cols-1 sm:grid-cols-2 gap-3">` + state.spots.map((s) => {
    const status = s.propice
      ? `<span class="text-green-400 font-semibold">🟢 Très propice · indice ${s.score_pct} %</span>`
      : (s.score_pct != null
          ? `<span class="text-os/60">Indice du jour : <strong>${s.score_pct} %</strong></span>`
          : `<span class="text-os/50">Hors zone modélisée</span>`);
    return `<div class="bg-os/5 border border-os/10 rounded-sm p-4 shadow-soft">
      <input class="spot-name w-full font-bold text-os bg-transparent border-b border-dashed border-os/30 hover:border-os/50 focus:border-solid focus:border-girolle outline-none" value="${escapeHtml(s.name)}" data-id="${s.id}" title="Cliquez pour renommer">
      <div class="text-[11px] text-os/50 mt-0.5">${s.lat.toFixed(3)}°N · ${s.lon.toFixed(3)}°E</div>
      <div class="text-sm mt-2">${status}</div>
      <div class="flex gap-2 mt-3">
        <button class="spot-map flex-1 py-1.5 rounded-sm bg-girolle text-sousbois text-sm font-bold hover:bg-lactaire transition" data-id="${s.id}">Voir sur la carte</button>
        <button class="spot-del py-1.5 px-3 rounded-sm text-red-400 text-sm font-semibold hover:bg-red-500/10 transition" data-id="${s.id}">Supprimer</button>
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

/* ---------- PWA (coquille seule) ---------- */
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => navigator.serviceWorker.register("/sw.js").catch(() => {}));
}
// Prompt d'installation (Android/Chrome) → bouton « Installer » dans Profil
let deferredInstall = null;
window.addEventListener("beforeinstallprompt", (e) => {
  e.preventDefault();
  deferredInstall = e;
  document.getElementById("install-btn")?.classList.remove("hidden");
});
document.getElementById("install-btn")?.addEventListener("click", async () => {
  if (!deferredInstall) return;
  deferredInstall.prompt();
  await deferredInstall.userChoice;
  deferredInstall = null;
  document.getElementById("install-btn")?.classList.add("hidden");
});
// Bandeau hors-ligne
function updateOnline() {
  document.getElementById("offline-banner")?.classList.toggle("hidden", navigator.onLine);
}
window.addEventListener("online", updateOnline);
window.addEventListener("offline", updateOnline);
updateOnline();
