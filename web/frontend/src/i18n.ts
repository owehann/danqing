import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import en from "./locales/en.json";
import zh from "./locales/zh.json";

const STORAGE_KEY = "danqing_lang";

function detectInitialLang(): "en" | "zh" {
  try {
    const saved = window.localStorage.getItem(STORAGE_KEY);
    if (saved === "en" || saved === "zh") {
      return saved;
    }
  } catch {
    // ignore storage errors
  }
  const nav = (typeof navigator !== "undefined" ? navigator.language : "en").toLowerCase();
  return nav.startsWith("zh") ? "zh" : "en";
}

function syncDocumentLocale(lng: string): void {
  if (typeof document === "undefined") return;
  document.documentElement.lang = lng === "zh" ? "zh-CN" : "en";
  document.title = i18n.t("app.title", { lng });
}

const initialLang = detectInitialLang();

void i18n.use(initReactI18next).init({
  resources: {
    en: { translation: en },
    zh: { translation: zh },
  },
  lng: initialLang,
  fallbackLng: "en",
  interpolation: {
    escapeValue: false,
  },
});

syncDocumentLocale(initialLang);

i18n.on("languageChanged", (lng) => {
  try {
    window.localStorage.setItem(STORAGE_KEY, lng);
  } catch {
    // ignore storage errors
  }
  syncDocumentLocale(lng);
});

export default i18n;
