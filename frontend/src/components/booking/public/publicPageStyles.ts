// ה-CSS המוטמע של העמוד העסקי הפומבי — אנימציות כניסה ורשת הפסיפס.
//
// A single embedded <style> block, the same pattern LandingPage.tsx already uses
// for the marketing page: things Tailwind utilities cannot express (@keyframes,
// a named mosaic grid) live here instead of leaking into tailwind.config.js.
//
// 🔴 The animation contract — content must NEVER be able to get stuck invisible:
//   * `.bp-reveal` animates opacity 0→1 and a small rise, with `animation-fill-mode:
//     both`. The FINAL keyframe is the element's normal, unstyled state, so if the
//     animation never runs (JS-less render, an old browser, a dropped stylesheet)
//     the element simply shows. Nothing is hidden by a base rule.
//   * `prefers-reduced-motion: reduce` sets `animation: none` — the element paints
//     immediately at its final state. This matches the project-wide rule already in
//     `index.css`, which additionally collapses any animation duration to 0.01ms.

export const PUBLIC_PAGE_CSS = `
/* --- entry animation: staggered fade + rise ------------------------------- */
@keyframes bp-rise {
  from { opacity: 0; transform: translateY(16px); }
  to   { opacity: 1; transform: none; }
}

.bp-reveal {
  /* "both" so the delayed start holds frame 1 and the end holds the FINAL,
     visible frame — which is also the default look when nothing animates. */
  animation: bp-rise 0.55s cubic-bezier(0.16, 0.8, 0.3, 1) both;
  will-change: opacity, transform;
}

@media (prefers-reduced-motion: reduce) {
  .bp-reveal {
    animation: none;
    opacity: 1;
    transform: none;
  }
}

/* --- gallery mosaic: one large tile + four small -------------------------- */
/* Mobile first: a single tall image. "הצג את כל התמונות" opens the rest in the
   lightbox, so collapsing the grid never hides content from a phone visitor. */
/* The mosaic IS the hero now (M20 revision), so it takes the reference's
   viewport-relative height instead of the old fixed strip. Clamped at both ends:
   never so short it reads as a banner, never so tall it pushes the booking flow
   off a laptop screen. */
.bp-mosaic {
  /* Containing block for the .bp-fog overlay, which is a grid CHILD but sits out
     of flow. Without this it would anchor to the page, not to the photos. */
  position: relative;
  display: grid;
  grid-template-columns: 1fr;
  grid-template-rows: 1fr;
  gap: 8px;
  height: 40vh;
  min-height: 240px;
  max-height: 340px;
}
/* Below the breakpoint only the main tile shows; the rest stay reachable through
   "הצג את כל התמונות" → the lightbox. Threshold lowered 768 → 640 because a
   laptop at 125–150% OS zoom reports well under 768 CSS px and was silently
   getting the one-photo mobile layout on a full-size screen. */
.bp-mosaic > .bp-tile:not(.bp-tile-main) { display: none; }

@media (min-width: 640px) {
  .bp-mosaic {
    grid-template-columns: repeat(4, 1fr);
    grid-template-rows: repeat(2, 1fr);
    height: 50vh;
    min-height: 400px;
    max-height: 560px;
  }
  /* Same selector shape as the mobile rule above — a plainer
     ".bp-mosaic > .bp-tile" loses to it on specificity and the four small tiles
     would stay hidden on desktop. (No backticks in here: this whole block is a
     template literal.) */
  .bp-mosaic > .bp-tile:not(.bp-tile-main) { display: block; }
  .bp-tile-main { grid-column: 1 / 3; grid-row: 1 / 3; }
  .bp-tile-1 { grid-column: 3 / 4; grid-row: 1 / 2; }
  .bp-tile-2 { grid-column: 4 / 5; grid-row: 1 / 2; }
  .bp-tile-3 { grid-column: 3 / 4; grid-row: 2 / 3; }
  .bp-tile-4 { grid-column: 4 / 5; grid-row: 2 / 3; }
}

/* ---------------------------------------------------------------------------
   LAYER 2 — the fog.

   The masthead is three stacked layers, per the owner's brief:
     1. the eight photos (.bp-mosaic)
     2. THIS: soft edges that melt the photos into the page background and
        gently cover part of them
     3. the logo + name + contact row, sitting in the pale part of layer 2 and
        biting slightly into the photos

   The first gradient is the one that matters. It is a radial ellipse anchored
   BELOW the frame, so the background colour rises highest in the CENTRE and
   falls away to the sides — a soft mound rather than a flat horizontal band.
   That shape exists to cradle the logo: the logo lands on the peak, where the
   fog is thickest, so it never sits on a busy photo.

   The other two gradients feather the bottom edge overall and the left/right
   edges, which is what removes the hard rectangle and gives the soft corners.

   Colours are palette variables, so the fog is always exactly the page's own
   background and the blend is seamless in every palette. pointer-events:none
   keeps the tiles underneath clickable.
--------------------------------------------------------------------------- */
.bp-fog {
  position: absolute;
  inset: 0;
  pointer-events: none;
  border-radius: var(--bp-radius);
  background:
    radial-gradient(115% 58% at 50% 116%,
      var(--bp-bg) 34%,
      color-mix(in srgb, var(--bp-bg) 62%, transparent) 58%,
      transparent 76%),
    linear-gradient(to top, var(--bp-bg) 0%, transparent 30%),
    linear-gradient(to right, var(--bp-bg) 0%, transparent 12%, transparent 88%, var(--bp-bg) 100%);
}
`
