// The small-screen half of the owner-app shell (below `lg` / 1024px).
//
// Why this exists: the desktop sidebar is a fixed 160px column. On a 390px
// phone that is 41% of the screen, which left every page rendering into ~230px
// — unusable. Below `lg` the sidebar is hidden and replaced by this compact top
// bar; the same nav items move into a drawer that slides in from the RIGHT,
// because the app is dir="rtl" and a left-side drawer would come from the
// "back" edge here.
//
// Accessibility contract this component keeps:
//   • the trigger has a real name ("פתיחת תפריט") + aria-expanded/aria-controls
//   • focus moves into the drawer on open and is trapped there while it is open
//   • Escape, a backdrop click, or a route change all close it
//   • closing returns focus to the trigger
//   • body scroll is locked while it is open
//   • the slide is a CSS transition, so the global prefers-reduced-motion rule
//     in index.css (transition-duration: 0.01ms) already flattens it

import { useEffect, useId, useRef, useState } from 'react'
import { useLocation } from 'react-router-dom'
import Icon from '../ui/Icon'
import { NavBody, type NavSpec } from './navItems'

/** Everything that can take focus inside the drawer panel. */
const FOCUSABLE = 'a[href], button:not([disabled]), input, select, textarea, [tabindex]:not([tabindex="-1"])'

export default function MobileNav({
  items,
  unreadTotal,
  onLogout,
}: {
  items: NavSpec[]
  unreadTotal: number
  onLogout: () => void
}) {
  const [open, setOpen] = useState(false)
  // `showPanel` lags `open` on the way DOWN only. The panel must become visible
  // in the same commit that starts the slide (otherwise focus() is a no-op on a
  // still-hidden element), but it must stay visible for the length of the
  // slide-out before we hide it again. Never transition `visibility` itself:
  // CSS interpolates it discretely and holds the old value for half the
  // duration, which left the drawer unfocusable and untappable for 100ms.
  const [showPanel, setShowPanel] = useState(false)
  const location = useLocation()
  const panelId = useId()
  const panelRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  // Tracks whether the drawer was open on the previous render, so we only steal
  // focus back to the trigger on a real open→close transition (not on mount).
  const wasOpen = useRef(false)

  // Close on navigation. Without this the drawer stays open on top of the page
  // the user just chose, which reads as "the tap did nothing".
  useEffect(() => {
    setOpen(false)
  }, [location.pathname])

  useEffect(() => {
    if (open) {
      setShowPanel(true)
      return
    }
    // Matches the 200ms slide-out below; after it the panel goes `invisible`,
    // which is what takes its links back out of the tab order.
    const timer = window.setTimeout(() => setShowPanel(false), 200)
    return () => window.clearTimeout(timer)
  }, [open])

  // While open: lock body scroll, listen for Escape, and put focus in the panel.
  useEffect(() => {
    if (!open) {
      if (wasOpen.current) {
        wasOpen.current = false
        triggerRef.current?.focus()
      }
      return
    }
    wasOpen.current = true

    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        setOpen(false)
        return
      }
      if (event.key !== 'Tab') return

      // Focus trap: cycle Tab / Shift+Tab inside the panel.
      const panel = panelRef.current
      if (!panel) return
      const focusable = Array.from(panel.querySelectorAll<HTMLElement>(FOCUSABLE))
      if (focusable.length === 0) return
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      const active = document.activeElement

      if (event.shiftKey && (active === first || !panel.contains(active))) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && (active === last || !panel.contains(active))) {
        event.preventDefault()
        first.focus()
      }
    }

    document.addEventListener('keydown', onKeyDown)

    // Land on the close button — the first thing a keyboard/SR user wants.
    // This waits a frame on purpose: the panel is `invisible` until the open
    // class lands, and focus() is a no-op on an element that is still
    // visibility:hidden at the moment it is called.
    const frame = requestAnimationFrame(() => {
      panelRef.current?.querySelector<HTMLElement>(FOCUSABLE)?.focus()
    })

    return () => {
      cancelAnimationFrame(frame)
      document.removeEventListener('keydown', onKeyDown)
      document.body.style.overflow = previousOverflow
    }
  }, [open])

  // Label shown next to the logo in the top bar: the current tab's name, so the
  // user still knows where they are once the sidebar is gone.
  const current = items.find((item) =>
    item.to === '/' ? location.pathname === '/' : location.pathname.startsWith(item.to),
  )

  return (
    <>
      {/* --- compact top bar (below lg only) --- */}
      <div className="flex items-center gap-3 border-b border-leaf-dark/20 bg-leaf-dark px-4 py-2 lg:hidden">
        <button
          ref={triggerRef}
          type="button"
          aria-label="פתיחת תפריט"
          aria-expanded={open}
          aria-controls={panelId}
          onClick={() => setOpen(true)}
          className="relative inline-flex h-11 w-11 items-center justify-center rounded-xl text-leaf-light transition hover:bg-white/10 hover:text-white"
        >
          <Icon name="menu" size={22} />
          {/* Unread indicator: with the sidebar collapsed the "שיחות" count has
              nowhere to live, so it surfaces here as a dot on the hamburger. The
              exact number stays on the item itself inside the drawer. */}
          {unreadTotal > 0 ? (
            <span
              aria-hidden="true"
              className="absolute end-2 top-2 h-2.5 w-2.5 rounded-full bg-brand-light ring-2 ring-leaf-dark"
            />
          ) : null}
        </button>

        {/* Announced separately from the button so the trigger's accessible name
            stays exactly "פתיחת תפריט". */}
        {unreadTotal > 0 ? (
          <span role="status" className="sr-only">
            {`${unreadTotal} הודעות שלא נקראו`}
          </span>
        ) : null}

        <img src="/botik-icon.png" alt="Botik" className="h-8 w-auto" />
        <span className="truncate text-sm font-medium text-white">{current?.label ?? 'Botik'}</span>
      </div>

      {/* --- backdrop --- */}
      <div
        aria-hidden="true"
        onClick={() => setOpen(false)}
        className={`fixed inset-0 z-40 bg-black/50 transition-opacity duration-200 lg:hidden ${
          open ? 'opacity-100' : 'pointer-events-none opacity-0'
        } ${showPanel ? 'visible' : 'invisible'}`}
      />

      {/* --- the drawer itself (right edge = the "forward" edge in RTL) ---
          It stays mounted so the slide can animate; `invisible` when closed both
          hides it and takes every link out of the tab order. */}
      <div
        id={panelId}
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label="ניווט ראשי"
        className={`fixed inset-y-0 right-0 z-50 flex w-64 max-w-[85vw] flex-col gap-1 overflow-y-auto bg-leaf-dark p-3 shadow-2xl transition-transform duration-200 ease-out lg:hidden ${
          open ? 'translate-x-0' : 'translate-x-full'
        } ${showPanel ? 'visible' : 'invisible'}`}
      >
        <button
          type="button"
          aria-label="סגירת תפריט"
          onClick={() => setOpen(false)}
          className="absolute start-2 top-2 inline-flex h-10 w-10 items-center justify-center rounded-xl text-leaf-light transition hover:bg-white/10 hover:text-white"
        >
          <Icon name="x" size={20} />
        </button>

        <NavBody items={items} unreadTotal={unreadTotal} onLogout={onLogout} />
      </div>
    </>
  )
}
