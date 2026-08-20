import antdEn from "antd/locale/en_US";
import antdZh from "antd/locale/zh_CN";
import type { Locale } from "antd/es/locale";
import { en } from "./en";
import { zh } from "./zh";

export type Language = "zh" | "en";
export type ThemeMode = "light" | "dark";
export type Messages = typeof en;

export const LANGUAGE_STORAGE_KEY = "physical-agent-language";
export const THEME_STORAGE_KEY = "physical-agent-theme";
export const TOUR_STORAGE_KEY = "physical-agent-tour-dismissed";

export const messages: Record<Language, Messages> = { en, zh };

export function resolveInitialLanguage(): Language {
  const saved = localStorage.getItem(LANGUAGE_STORAGE_KEY);
  if (saved === "zh" || saved === "en") {
    return saved;
  }
  return navigator.language.toLowerCase().startsWith("en") ? "en" : "zh";
}

export function antdLocale(language: Language): Locale {
  return language === "zh" ? antdZh : antdEn;
}

export function resolveInitialTheme(): ThemeMode {
  const saved = localStorage.getItem(THEME_STORAGE_KEY);
  if (saved === "light" || saved === "dark") {
    return saved;
  }
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}
