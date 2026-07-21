// סרגל טאבים בסגנון וואטסאפ — פס ירוק עם קו תחתון על הטאב הפעיל
// WhatsApp-style tab bar for the conversations inbox (M18).
//
// Deliberately NOT the shared SegmentedControl: that control is a pill group for
// filter chips scattered across the app. This is the inbox's primary navigation
// and copies the WhatsApp shape the owner asked for — a coloured bar, tabs
// spread edge to edge, and a thick underline marking the active one.
//
// Accessibility: real `role="tablist"`/`role="tab"` semantics with `aria-selected`,
// arrow-key roving focus, so the bar is usable without a mouse. The active tab is
// marked by the underline AND by `aria-selected` — never by colour alone.

import { useRef } from 'react'

export type ChatTab<T extends string> = {
  value: T
  label: string
  /** Optional count shown as a pill (unread etc.). 0/undefined hides it. */
  count?: number
}

type Props<T extends string> = {
  tabs: ChatTab<T>[]
  value: T
  onChange: (next: T) => void
  /** Accessible name for the whole bar. */
  label: string
}

export default function ChatTabs<T extends string>({
  tabs,
  value,
  onChange,
  label,
}: Props<T>) {
  const refs = useRef<(HTMLButtonElement | null)[]>([])

  // Arrow keys move between tabs. In an RTL bar, ArrowLeft means "next" and
  // ArrowRight means "previous" — the visual order is mirrored, and matching the
  // visual order is what makes the keys feel right.
  const onKeyDown = (e: React.KeyboardEvent, index: number) => {
    const last = tabs.length - 1
    let next: number | null = null
    if (e.key === 'ArrowLeft') next = index === last ? 0 : index + 1
    else if (e.key === 'ArrowRight') next = index === 0 ? last : index - 1
    else if (e.key === 'Home') next = 0
    else if (e.key === 'End') next = last
    if (next === null) return
    e.preventDefault()
    onChange(tabs[next].value)
    refs.current[next]?.focus()
  }

  return (
    <div className="overflow-hidden rounded-xl bg-[#1F7A5A] shadow-sm dark:bg-[#12684C]">
      <div role="tablist" aria-label={label} className="flex">
        {tabs.map((tab, i) => {
          const active = tab.value === value
          return (
            <button
              key={tab.value}
              ref={(el) => {
                refs.current[i] = el
              }}
              role="tab"
              type="button"
              aria-selected={active}
              tabIndex={active ? 0 : -1}
              onClick={() => onChange(tab.value)}
              onKeyDown={(e) => onKeyDown(e, i)}
              className={`relative flex flex-1 items-center justify-center gap-1.5 px-2 py-3 text-sm font-medium outline-none transition-colors focus-visible:bg-white/15 ${
                active ? 'text-white' : 'text-white/70 hover:text-white'
              }`}
            >
              <span className="truncate">{tab.label}</span>
              {tab.count ? (
                <span className="rounded-full bg-white px-1.5 py-0.5 text-xs font-bold leading-none text-[#1F7A5A]">
                  {tab.count > 99 ? '99+' : tab.count}
                </span>
              ) : null}
              {/* The underline is the active marker, mirroring WhatsApp. */}
              <span
                aria-hidden="true"
                className={`absolute inset-x-0 bottom-0 h-1 rounded-t ${
                  active ? 'bg-white' : 'bg-transparent'
                }`}
              />
            </button>
          )
        })}
      </div>
    </div>
  )
}
