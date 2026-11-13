import * as React from "react";

import { storage } from "@/lib/storage";

export type ThemePref = "system" | "light" | "dark";

interface ThemeState {
  pref: ThemePref;
  resolved: "light" | "dark";
  setPref: (p: ThemePref) => void;
  toggle: () => void;
}

const ThemeContext = React.createContext<ThemeState | null>(null);

function systemDark() {
  return typeof window !== "undefined" && window.matchMedia("(prefers-color-scheme: dark)").matches;
}

function readPref(): ThemePref {
  const v = storage.get<string>("theme", "system");
  return v === "light" || v === "dark" ? v : "system";
}

export function applyTheme(resolved: "light" | "dark") {
  const root = document.documentElement;
  root.classList.toggle("dark", resolved === "dark");
  root.style.colorScheme = resolved;
}

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [pref, setPrefState] = React.useState<ThemePref>(readPref);
  const [sysDark, setSysDark] = React.useState(systemDark);

  React.useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const on = () => setSysDark(mq.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);

  const resolved: "light" | "dark" = pref === "system" ? (sysDark ? "dark" : "light") : pref;

  React.useEffect(() => {
    applyTheme(resolved);
  }, [resolved]);

  const value = React.useMemo<ThemeState>(
    () => ({
      pref,
      resolved,
      setPref: (p) => {
        storage.set("theme", p === "system" ? null : p);
        setPrefState(p);
      },
      toggle: () => {
        const next = resolved === "dark" ? "light" : "dark";
        storage.set("theme", next);
        setPrefState(next);
      },
    }),
    [pref, resolved],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeState {
  const ctx = React.useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme must be used inside ThemeProvider");
  return ctx;
}
