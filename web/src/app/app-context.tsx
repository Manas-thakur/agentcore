import * as React from "react";

import type { Health } from "@/lib/types";

export interface AppState {
  health: Health | null;
  offline: boolean;
  refreshHealth: () => void;
  openPalette: () => void;
  openShortcuts: () => void;
  newChat: () => void;
}

export const AppContext = React.createContext<AppState | null>(null);

export function useApp(): AppState {
  const ctx = React.useContext(AppContext);
  if (!ctx) throw new Error("useApp must be used inside the app shell");
  return ctx;
}
