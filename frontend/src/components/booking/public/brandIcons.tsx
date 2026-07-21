// שלושה אייקונים שחסרים ב-Icon המשותף: סיכת מיקום, Waze ו-Instagram.
//
// The shared `ui/Icon` set covers `phone` and `brand-whatsapp` already; these
// three are only needed by the public business page, so they live next to it
// rather than growing the app-wide icon union. Same house style: inline SVG, no
// icon font, no CDN, decorative by default (the surrounding control carries the
// label).

import type { SVGProps } from 'react'

type Props = SVGProps<SVGSVGElement> & { size?: number }

function base(size: number) {
  return {
    width: size,
    height: size,
    viewBox: '0 0 24 24',
    'aria-hidden': true as const,
    focusable: 'false' as const,
  }
}

/** Location pin — the address line in the hero. */
export function MapPinIcon({ size = 20, ...rest }: Props) {
  return (
    <svg
      {...base(size)}
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      {...rest}
    >
      <path d="M12 21s7-5.5 7-11a7 7 0 1 0-14 0c0 5.5 7 11 7 11z" />
      <circle cx="12" cy="10" r="2.5" />
    </svg>
  )
}

/** Waze — the rounded "face" mark, simplified to a single-colour glyph. */
export function WazeIcon({ size = 20, ...rest }: Props) {
  return (
    <svg {...base(size)} fill="currentColor" {...rest}>
      <path d="M12 2.6c-4.7 0-8.6 3.3-8.6 7.6 0 1 .1 1.9-.2 2.6-.3.7-.9 1.2-1.6 1.5-.4.2-.5.7-.2 1 1.5 1.7 4.2 2.9 7.3 3.2a2.6 2.6 0 0 0 5.1.3c2-.3 3.8-1 5.2-2a2.6 2.6 0 0 0 3-3.6c.5-.9.7-1.9.7-3 0-4.3-3.9-7.6-8.7-7.6zm-2.6 6a1.2 1.2 0 1 1 0 2.4 1.2 1.2 0 0 1 0-2.4zm5.2 0a1.2 1.2 0 1 1 0 2.4 1.2 1.2 0 0 1 0-2.4zM8.5 13.1h7a.6.6 0 0 1 .6.7 4.2 4.2 0 0 1-8.2 0 .6.6 0 0 1 .6-.7z" />
    </svg>
  )
}

/** Instagram — rounded square, lens, and the corner dot. */
export function InstagramIcon({ size = 20, ...rest }: Props) {
  return (
    <svg
      {...base(size)}
      fill="none"
      stroke="currentColor"
      strokeWidth={1.9}
      strokeLinecap="round"
      strokeLinejoin="round"
      {...rest}
    >
      <rect x="3" y="3" width="18" height="18" rx="5" />
      <circle cx="12" cy="12" r="4" />
      <circle cx="17" cy="7" r="1.1" fill="currentColor" stroke="none" />
    </svg>
  )
}
