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
