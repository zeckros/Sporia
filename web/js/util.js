import { FR_MONTHS } from "./state.js";

export function escapeHtml(s) {
  return (s || "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

export function valFmt(v, u) { return v === null || v === undefined ? "n.d." : `${v.toFixed(1)} ${u}`; }
export function fmtNum(v) { return v === null || v === undefined ? "—" : v.toFixed(1); }
export function pct(v) { return v === null || v === undefined ? "n.d." : `${Math.round(v * 100)} %`; }

export function monthNum(frName) { const i = FR_MONTHS.indexOf((frName || "").toLowerCase()); return i >= 0 ? i + 1 : 0; }
