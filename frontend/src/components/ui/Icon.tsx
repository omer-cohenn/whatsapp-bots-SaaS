// Tiny inline-SVG icon set (no external font/CDN, no new dependency). Each glyph
// is a stroked 24x24 path in the Tabler style used by the approved prototype.
// Icons are decorative by default (aria-hidden) — callers must provide a text
// label or aria-label on the surrounding control.

import type { SVGProps } from 'react'

export type IconName =
  | 'message-circle'
  | 'home'
  | 'robot'
  | 'player-play'
  | 'users'
  | 'calendar-event'
  | 'settings'
  | 'logout'
  | 'sparkles'
  | 'plus'
  | 'trash'
  | 'device-floppy'
  | 'pencil'
  | 'send'
  | 'x'
  | 'chevron-down'
  | 'user-plus'
  | 'checks'
  | 'user-off'
  | 'clock'
  | 'download'
  | 'refresh'
  | 'world'
  | 'eye'
  | 'copy'
  | 'check'
  | 'external-link'
  | 'brand-google'
  | 'mail'
  | 'phone'
  | 'chevron-right'
  | 'chevron-left'
  | 'calendar-off'
  | 'photo'
  | 'menu'
  | 'brand-whatsapp'
  | 'shield'
  | 'building-store'
  | 'currency-shekel'
  | 'activity'

// Path/element markup per icon (stroke-based, inherits currentColor).
const PATHS: Record<IconName, JSX.Element> = {
  'message-circle': (
    <path d="M3 20l1.3-3.9A9 8 0 1 1 8 19l-5 1zM12 12v.01M8 12v.01M16 12v.01" />
  ),
  home: <path d="M5 12H3l9-9 9 9h-2M5 12v7a1 1 0 0 0 1 1h3v-5h4v5h3a1 1 0 0 0 1-1v-7" />,
  robot: (
    <path d="M7 7h10a2 2 0 0 1 2 2v6a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V9a2 2 0 0 1 2-2zM12 7V4M8 16v.01M16 16v.01M9 11v1M15 11v1M3 13h2M19 13h2" />
  ),
  'player-play': <path d="M7 4v16l13-8z" />,
  users: (
    <path d="M9 7a3 3 0 1 0 0 6 3 3 0 0 0 0-6zM3 21v-1a5 5 0 0 1 5-5h2a5 5 0 0 1 5 5v1M16 3.1a3 3 0 0 1 0 5.8M21 21v-1a5 5 0 0 0-3-4.5" />
  ),
  'calendar-event': (
    <path d="M4 7a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V7zM16 3v4M8 3v4M4 11h16M11 15h2v2h-2z" />
  ),
  settings: (
    <path d="M10.3 4.3a1 1 0 0 1 1-.8h1.4a1 1 0 0 1 1 .8l.3 1.4 1.3.7 1.4-.5a1 1 0 0 1 1.2.4l.7 1.2a1 1 0 0 1-.2 1.3l-1.1.9v1.4l1.1.9a1 1 0 0 1 .2 1.3l-.7 1.2a1 1 0 0 1-1.2.4l-1.4-.5-1.3.7-.3 1.4a1 1 0 0 1-1 .8h-1.4a1 1 0 0 1-1-.8l-.3-1.4-1.3-.7-1.4.5a1 1 0 0 1-1.2-.4l-.7-1.2a1 1 0 0 1 .2-1.3l1.1-.9v-1.4l-1.1-.9a1 1 0 0 1-.2-1.3l.7-1.2a1 1 0 0 1 1.2-.4l1.4.5 1.3-.7zM12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6z" />
  ),
  logout: <path d="M14 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2v-2M9 12h12m0 0l-3-3m3 3l-3 3" />,
  sparkles: (
    <path d="M12 3l1.8 4.6L18 9l-4.2 1.4L12 15l-1.8-4.6L6 9l4.2-1.4L12 3zM5 15l.9 2.1L8 18l-2.1.9L5 21l-.9-2.1L2 18l2.1-.9L5 15z" />
  ),
  plus: <path d="M12 5v14M5 12h14" />,
  trash: <path d="M4 7h16M10 11v6M14 11v6M5 7l1 13a1 1 0 0 0 1 1h10a1 1 0 0 0 1-1l1-13M9 7V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v3" />,
  'device-floppy': (
    <path d="M6 4h11l3 3v13a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1zM8 4v5h7V4M8 21v-6a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v6" />
  ),
  pencil: <path d="M4 20h4l10-10a2 2 0 0 0-3-3L5 17v3zM13.5 6.5l3 3" />,
  send: <path d="M12 19V5M5 12l7-7 7 7" />,
  x: <path d="M18 6L6 18M6 6l12 12" />,
  'chevron-down': <path d="M6 9l6 6 6-6" />,
  'user-plus': (
    <path d="M9 7a3 3 0 1 0 0 6 3 3 0 0 0 0-6zM3 21v-1a5 5 0 0 1 5-5h2a5 5 0 0 1 4 2M16 11h6M19 8v6" />
  ),
  checks: <path d="M2 12l5 5 5-5M9 12l5 5L22 7" />,
  'user-off': (
    <path d="M9 7a3 3 0 0 0 0 6M3 21v-1a5 5 0 0 1 5-5h2M3 3l18 18" />
  ),
  clock: <path d="M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 7v5l3 2" />,
  download: <path d="M12 3v12M8 11l4 4 4-4M4 19h16" />,
  refresh: <path d="M20 11a8 8 0 1 0-2.3 5.6M20 5v6h-6" />,
  world: (
    <path d="M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM3 12h18M12 3c2.5 2.5 3.5 5.5 3.5 9s-1 6.5-3.5 9c-2.5-2.5-3.5-5.5-3.5-9s1-6.5 3.5-9z" />
  ),
  eye: <path d="M12 5c-5 0-8.5 4.2-9.5 7 1 2.8 4.5 7 9.5 7s8.5-4.2 9.5-7c-1-2.8-4.5-7-9.5-7zM12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6z" />,
  copy: (
    <path d="M8 8V6a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-2M6 8h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2z" />
  ),
  check: <path d="M5 12l5 5L20 7" />,
  'external-link': (
    <path d="M11 5H7a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-4M14 5h5v5M19 5l-9 9" />
  ),
  // Multicolour Google "G" — overrides stroke with its own fills (see render).
  'brand-google': (
    <>
      <path
        fill="#4285F4"
        stroke="none"
        d="M21.6 12.2c0-.7-.06-1.36-.18-2H12v3.8h5.4a4.6 4.6 0 0 1-2 3v2.5h3.2c1.9-1.74 3-4.3 3-7.3z"
      />
      <path
        fill="#34A853"
        stroke="none"
        d="M12 22c2.7 0 4.96-.9 6.62-2.43l-3.2-2.5c-.9.6-2.04.95-3.42.95-2.62 0-4.84-1.77-5.64-4.15H3.05v2.6A10 10 0 0 0 12 22z"
      />
      <path
        fill="#FBBC05"
        stroke="none"
        d="M6.36 13.87a6 6 0 0 1 0-3.74v-2.6H3.05a10 10 0 0 0 0 8.94l3.31-2.6z"
      />
      <path
        fill="#EA4335"
        stroke="none"
        d="M12 5.98c1.47 0 2.8.5 3.84 1.5l2.84-2.84A10 10 0 0 0 3.05 7.53l3.31 2.6C7.16 7.75 9.38 5.98 12 5.98z"
      />
    </>
  ),
  mail: <path d="M4 6h16a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1zM3 7l9 6 9-6" />,
  phone: (
    <path d="M5 4h3l2 5-2.5 1.5a11 11 0 0 0 5 5L17 13l5 2v3a2 2 0 0 1-2 2A16 16 0 0 1 3 5a2 2 0 0 1 2-1z" />
  ),
  'chevron-right': <path d="M9 6l6 6-6 6" />,
  'chevron-left': <path d="M15 6l-6 6 6 6" />,
  'calendar-off': (
    <path d="M4 7a2 2 0 0 1 2-2h10M20 9v10a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-6M16 3v4M8 3v4M4 11h7M3 3l18 18" />
  ),
  photo: (
    <path d="M5 4h14a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1zM9 9a1 1 0 1 0 0 2 1 1 0 0 0 0-2zM4 16l4-4a2 2 0 0 1 2.8 0L15 16M14 14l1-1a2 2 0 0 1 2.8 0L20 15" />
  ),
  menu: <path d="M4 6h16M4 12h16M4 18h16" />,
  // WhatsApp glyph: speech bubble (tail at the bottom-start) + a handset.
  'brand-whatsapp': (
    <path d="M3 21l1.65-4.8A8 8 0 1 1 7.8 19.3L3 21zM9 9.5c0 3 2.5 5.5 5.5 5.5l1-1c.3-.3.8-.4 1.1-.2l1.4.7c.3.2.5.5.5.9 0 .8-.6 1.4-1.4 1.6C13 17.6 7.4 13 7.4 9.4c.1-.8.8-1.4 1.6-1.4.4 0 .7.2.9.5l.7 1.4c.2.3.1.8-.2 1.1l-1 1z" />
  ),
  // Admin / "control room" shield with a check.
  shield: <path d="M12 3l8 3v5c0 4.5-3 8.3-8 10-5-1.7-8-5.5-8-10V6l8-3zM9 12l2 2 4-4" />,
  // Storefront — used for the businesses table.
  'building-store': (
    <path d="M3 9l1-4h16l1 4M4 9v10a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1V9M4 9a2 2 0 0 0 4 0 2 2 0 0 0 4 0 2 2 0 0 0 4 0 2 2 0 0 0 4 0M9 20v-5h6v5" />
  ),
  // Shekel sign for plan price.
  'currency-shekel': <path d="M7 17V7h5a3 3 0 0 1 3 3v7M17 7v10a3 3 0 0 1-3 3H9" />,
  // Activity pulse for usage charts.
  activity: <path d="M3 12h4l3 8 4-16 3 8h4" />,
}

type IconProps = SVGProps<SVGSVGElement> & {
  name: IconName
  /** px size for width+height (default 20). */
  size?: number
}

export default function Icon({ name, size = 20, className = '', ...rest }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      className={className}
      {...rest}
    >
      {PATHS[name]}
    </svg>
  )
}
