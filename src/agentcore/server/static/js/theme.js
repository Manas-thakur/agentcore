// Theme preference: "system" (default), "light" or "dark". Stored as a plain string.

import { icon } from "./ui.js";

// --- theme --------------------------------------------------------------------------------
const THEME_KEY = "agentcore.theme";
export function getThemePref() {
  try {
    return localStorage.getItem(THEME_KEY) || "system";
  } catch {
    return "system";
  }
}
export function effectiveTheme() {
  const pref = getThemePref();
  if (pref === "light" || pref === "dark") return pref;
  return matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}
export function setThemePref(pref) {
  try {
    if (pref === "system") localStorage.removeItem(THEME_KEY);
    else localStorage.setItem(THEME_KEY, pref);
  } catch {
    /* ignore */
  }
  if (pref === "system") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = pref;
  paintThemeButtons();
  window.dispatchEvent(new CustomEvent("themechange"));
}
function paintThemeButtons() {
  const dark = effectiveTheme() === "dark";
  for (const b of document.querySelectorAll(".theme-btn")) {
    b.innerHTML = icon(dark ? "sun" : "moon");
    b.setAttribute("aria-label", dark ? "Switch to light theme" : "Switch to dark theme");
    b.title = dark ? "Light theme" : "Dark theme";
  }
}
export function toggleTheme() {
  setThemePref(effectiveTheme() === "dark" ? "light" : "dark");
}
export function initTheme() {
  for (const b of document.querySelectorAll(".theme-btn")) {
    b.addEventListener("click", toggleTheme);
  }
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
    paintThemeButtons();
    window.dispatchEvent(new CustomEvent("themechange"));
  });
  paintThemeButtons();
}

