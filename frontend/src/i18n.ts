/** Minimal zh/en i18n. Chinese source strings double as dictionary keys:
 * t() returns the exact source in zh mode (byte-identical rendering) and the
 * English entry in en mode, falling back to the source when untranslated. */

import core from "./locales/en.core";
import groupA from "./locales/en.groupA";
import groupB from "./locales/en.groupB";
import groupC from "./locales/en.groupC";

const en: Record<string, string> = { ...core, ...groupA, ...groupB, ...groupC };

const STORAGE_KEY = "soundleaf-lang";
let current: Lang = localStorage.getItem(STORAGE_KEY) === "en" ? "en" : "zh";
document.documentElement.lang = current === "en" ? "en" : "zh-CN";

const listeners = new Set<() => void>();

export type Lang = "zh" | "en";

export function getLang(): Lang {
  return current;
}

export function setLang(lang: Lang): void {
  if (lang === current) return;
  current = lang;
  localStorage.setItem(STORAGE_KEY, lang);
  document.documentElement.lang = lang === "en" ? "en" : "zh-CN";
  for (const fn of listeners) fn();
}

export function subscribeLang(fn: () => void): () => void {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}

export function t(s: string): string {
  return current === "en" ? (en[s] ?? s) : s;
}

/** Translate a {placeholder} template, then substitute variables. */
export function tf(s: string, vars: Record<string, string | number>): string {
  let out = t(s);
  for (const [k, v] of Object.entries(vars)) {
    out = out.split(`{${k}}`).join(String(v));
  }
  return out;
}
