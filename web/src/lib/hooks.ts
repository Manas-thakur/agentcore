import * as React from "react";

import { api } from "@/lib/api";
import { storage } from "@/lib/storage";

export interface FetchState<T> {
  data: T | undefined;
  error: Error | null;
  loading: boolean;
  reload: () => void;
  setData: React.Dispatch<React.SetStateAction<T | undefined>>;
}

/**
 * Tiny data hook: GET `path` (JSON) whenever it changes. `null` skips the request.
 * Keeps the previous data while reloading so views do not flash skeletons.
 */
export function useFetch<T>(path: string | null, deps: React.DependencyList = []): FetchState<T> {
  const [data, setData] = React.useState<T | undefined>(undefined);
  const [error, setError] = React.useState<Error | null>(null);
  const [loading, setLoading] = React.useState(path !== null);
  const [tick, setTick] = React.useState(0);

  React.useEffect(() => {
    if (path === null) return;
    const ctrl = new AbortController();
    setLoading(true);
    api
      .get<T>(path, { signal: ctrl.signal })
      .then((d) => {
        setData(d);
        setError(null);
      })
      .catch((e: Error) => {
        if (e.name !== "AbortError") setError(e);
      })
      .finally(() => {
        if (!ctrl.signal.aborted) setLoading(false);
      });
    return () => ctrl.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, tick, ...deps]);

  const reload = React.useCallback(() => setTick((t) => t + 1), []);
  return { data, error, loading, reload, setData };
}

/** useState mirrored to localStorage. */
export function useStored<T>(key: string, initial: T): [T, (v: T | ((p: T) => T)) => void] {
  const [value, setValue] = React.useState<T>(() => storage.get<T>(key, initial));
  const set = React.useCallback(
    (v: T | ((p: T) => T)) => {
      setValue((prev) => {
        const next = typeof v === "function" ? (v as (p: T) => T)(prev) : v;
        storage.set(key, next);
        return next;
      });
    },
    [key],
  );
  return [value, set];
}

export function useInterval(fn: () => void, ms: number | null) {
  const ref = React.useRef(fn);
  React.useEffect(() => {
    ref.current = fn;
  });
  React.useEffect(() => {
    if (ms === null) return;
    const id = setInterval(() => ref.current(), ms);
    return () => clearInterval(id);
  }, [ms]);
}

export function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = React.useState(value);
  React.useEffect(() => {
    const id = setTimeout(() => setV(value), ms);
    return () => clearTimeout(id);
  }, [value, ms]);
  return v;
}

export function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  const tag = target.tagName;
  if (tag === "TEXTAREA" || tag === "SELECT") return true;
  if (tag === "INPUT") {
    const type = (target as HTMLInputElement).type;
    return !["checkbox", "radio", "button", "submit", "range"].includes(type);
  }
  return false;
}

/**
 * Global keydown handler for view shortcuts. Skips events while typing, with modifiers,
 * or when a modal dialog is open (unless `allowInDialog`).
 */
export function useKeydown(
  handler: (ev: KeyboardEvent) => void,
  opts: { allowTyping?: boolean; allowInDialog?: boolean } = {},
) {
  const ref = React.useRef(handler);
  React.useEffect(() => {
    ref.current = handler;
  });
  const { allowTyping = false, allowInDialog = false } = opts;
  React.useEffect(() => {
    const on = (ev: KeyboardEvent) => {
      if (ev.defaultPrevented || ev.ctrlKey || ev.metaKey || ev.altKey) return;
      if (!allowTyping && isTypingTarget(ev.target)) return;
      if (!allowInDialog && document.querySelector("[role=dialog][data-state=open], [role=alertdialog][data-state=open]"))
        return;
      ref.current(ev);
    };
    document.addEventListener("keydown", on);
    return () => document.removeEventListener("keydown", on);
  }, [allowTyping, allowInDialog]);
}

export function useMediaQuery(query: string): boolean {
  const [match, setMatch] = React.useState(() => typeof window !== "undefined" && window.matchMedia(query).matches);
  React.useEffect(() => {
    const mq = window.matchMedia(query);
    const on = () => setMatch(mq.matches);
    on();
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, [query]);
  return match;
}

export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}
