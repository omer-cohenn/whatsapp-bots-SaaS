// i18n foundation (i18next + react-i18next).
//
// SCOPE: this is the groundwork for incremental localization. Right now only the
// `accessibility` namespace is wired up — the rest of the app stays inline-Hebrew
// until pages are migrated one by one. There is no visible language switcher yet;
// the active language is simply read off the document's <html lang> (Hebrew in
// practice), with Hebrew as the fallback.

import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'

// The accessibility widget's strings, kept here so the foundation has a real
// first consumer. He/En keys mirror docs/decisions/0018.
const accessibility = {
  he: {
    button_aria: 'פתח תפריט נגישות',
    button_title: 'נגישות',
    panel_title: 'הגדרות נגישות',
    close_aria: 'סגור תפריט נגישות',
    high_contrast: 'ניגודיות גבוהה',
    high_contrast_desc: 'הגברת הניגודיות לקריאה טובה יותר',
    large_text: 'טקסט גדול',
    large_text_desc: 'הגדלת גודל הטקסט',
    underline_links: 'קו תחתון לקישורים',
    underline_links_desc: 'הוספת קו תחתון לכל הקישורים',
    focus_highlight: 'הדגשת פוקוס',
    focus_highlight_desc: 'הדגשה ברורה יותר של רכיבים בפוקוס',
    stop_animations: 'הפסקת אנימציות',
    stop_animations_desc: 'הפסקת כל האנימציות והמעברים',
    reset: 'איפוס הגדרות נגישות',
  },
  en: {
    button_aria: 'Open accessibility menu',
    button_title: 'Accessibility',
    panel_title: 'Accessibility settings',
    close_aria: 'Close accessibility menu',
    high_contrast: 'High contrast',
    high_contrast_desc: 'Increase contrast for better readability',
    large_text: 'Large text',
    large_text_desc: 'Increase the text size',
    underline_links: 'Underline links',
    underline_links_desc: 'Add an underline to all links',
    focus_highlight: 'Focus highlight',
    focus_highlight_desc: 'Make focused elements clearly visible',
    stop_animations: 'Stop all animations and transitions',
    stop_animations_desc: 'Stop all animations and transitions',
    reset: 'Reset accessibility settings',
  },
}

// Language comes from <html lang="...">; default/fallback is Hebrew.
const documentLang =
  (typeof document !== 'undefined' && document.documentElement.lang) || 'he'

void i18n.use(initReactI18next).init({
  lng: documentLang,
  fallbackLng: 'he',
  // `translation` stays the default namespace so future migrated pages can use
  // it without extra config; the widget opts into `accessibility` explicitly.
  defaultNS: 'translation',
  ns: ['translation', 'accessibility'],
  resources: {
    he: { accessibility: accessibility.he },
    en: { accessibility: accessibility.en },
  },
  interpolation: {
    // React already escapes values, so i18next must not double-escape.
    escapeValue: false,
  },
})

export default i18n
