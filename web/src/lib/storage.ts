// localStorage with an "agentcore." prefix that never throws (private mode, quotas).

const PREFIX = "agentcore.";

export const storage = {
  get<T>(key: string, fallback: T): T {
    try {
      const raw = localStorage.getItem(PREFIX + key);
      if (raw === null) return fallback;
      try {
        return JSON.parse(raw) as T;
      } catch {
        return raw as unknown as T;
      }
    } catch {
      return fallback;
    }
  },
  set(key: string, value: unknown) {
    try {
      if (value === null || value === undefined) localStorage.removeItem(PREFIX + key);
      else localStorage.setItem(PREFIX + key, typeof value === "string" ? value : JSON.stringify(value));
    } catch {
      /* ignore */
    }
  },
  remove(key: string) {
    try {
      localStorage.removeItem(PREFIX + key);
    } catch {
      /* ignore */
    }
  },
  /** Remove view preferences, keeping the API key and theme. */
  resetPreferences() {
    try {
      for (const k of Object.keys(localStorage)) {
        if (k.startsWith(PREFIX) && k !== `${PREFIX}apiKey` && k !== `${PREFIX}theme`) localStorage.removeItem(k);
      }
    } catch {
      /* ignore */
    }
  },
};
