// Light or dark colors for the new look. Follows the computer's setting until the person picks one,
// which is then kept in this browser. The class goes on <html> so dialogs rendered outside the app
// root are themed too; it is removed when the new look unmounts, so the classic look never sees it.
import { useEffect, useState } from "react";
import { revealFrom, withViewTransition } from "./motion";

export type Theme = "light" | "dark";
const KEY = "crm-theme";
const DARK_QUERY = "(prefers-color-scheme: dark)";
const CHANGE_EVENT = "crm-theme-change";

function savedTheme(): Theme | null {
  try {
    const value = localStorage.getItem(KEY);
    return value === "light" || value === "dark" ? value : null;
  } catch {
    return null;
  }
}

const systemTheme = (): Theme => (window.matchMedia?.(DARK_QUERY).matches ? "dark" : "light");

export function useTheme(): [Theme, (theme: Theme, origin?: Element | null) => void] {
  const [saved, setSaved] = useState(savedTheme);
  const [system, setSystem] = useState(systemTheme);
  const theme = saved || system;

  useEffect(() => {
    const query = window.matchMedia?.(DARK_QUERY);
    if (!query) return;
    const onChange = () => setSystem(query.matches ? "dark" : "light");
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, []);

  useEffect(() => {
    const root = document.documentElement;
    root.classList.toggle("aur-dark", theme === "dark");
    root.style.colorScheme = theme;
    window.dispatchEvent(new Event(CHANGE_EVENT));
    return () => {
      root.classList.remove("aur-dark");
      root.style.colorScheme = "";
      window.dispatchEvent(new Event(CHANGE_EVENT));
    };
  }, [theme]);

  // The new theme opens as a circle growing from the control that was clicked.
  function choose(next: Theme, origin?: Element | null) {
    try { localStorage.setItem(KEY, next); } catch { /* storage unavailable: applies to this visit only */ }
    revealFrom(withViewTransition("theme", () => {
      document.documentElement.classList.toggle("aur-dark", next === "dark");
      document.documentElement.style.colorScheme = next;
      setSaved(next);
    }), origin);
  }

  return [theme, choose];
}

// For pages that compute colors in code (company tints on the calendars).
export const isDarkTheme = () => document.documentElement.classList.contains("aur-dark");

export function useIsDarkTheme() {
  const [dark, setDark] = useState(isDarkTheme);
  useEffect(() => {
    const onChange = () => setDark(isDarkTheme());
    window.addEventListener(CHANGE_EVENT, onChange);
    return () => window.removeEventListener(CHANGE_EVENT, onChange);
  }, []);
  return dark;
}
