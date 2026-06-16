/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx,ts,tsx}'],
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
        ok: '#15803d', // green-700 — AA-safe success text
        bad: '#b91c1c', // red-700  — AA-safe error text
      },
    },
  },
  plugins: [],
}
