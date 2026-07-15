/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx,ts,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      fontFamily: {
        // Heebo is the Hebrew brand font; system fonts are the fallback while it loads.
        sans: ['Heebo', 'system-ui', 'Segoe UI', 'Arial', 'sans-serif'],
      },
      colors: {
        // Single consolidated theme (replaces the duplicated palettes in the old app).
        brand: {
          DEFAULT: '#128C7E', // WhatsApp teal-green (passes AA on white)
          light: '#25D366', // WhatsApp bright green (accents only — fails AA as text on white)
          dark: '#075E54',
        },
        // Approved owner-app design palette (docs/prototype/bizzup-prototype.html):
        // a warm leaf-green used for primary actions + the deep-green sidebar.
        leaf: {
          DEFAULT: '#639922', // primary action green (white text on it passes AA)
          dark: '#27500A', // deep-green sidebar background (the "ink" green)
          deep: '#3B6D11', // mid green for links/accents on light surfaces
          light: '#C0DD97', // muted text on the deep-green sidebar
          soft: '#EAF3DE', // success/selected soft background
          ink: '#27500A', // AA-safe green text on light surfaces
        },
        ok: '#15803d', // green-700 — AA-safe success text
        bad: '#b91c1c', // red-700  — AA-safe error text
      },
    },
  },
  plugins: [],
}
