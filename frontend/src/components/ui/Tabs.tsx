// Accessible tab strip following the WAI-ARIA tabs pattern:
//   * the strip is role="tablist", each tab is role="tab" with aria-selected
//   * roving tabindex (only the active tab is in the tab order)
//   * Left/Right arrows move between tabs and activate (RTL-aware: in a
//     dir="rtl" tablist ArrowLeft goes to the NEXT tab, ArrowRight to the
//     previous — the browser flips the visual order, so we follow the visual
//     direction the user sees), Home/End jump to first/last.
//
// This is the generic primitive. The bot-builder flow tabs add rename/delete
// affordances on top, so they compose their own strip but reuse these same
// ARIA semantics (see components/botbuilder/FlowTabs.tsx).

import { useRef, type KeyboardEvent } from 'react'

export type TabItem = {
  id: string
  label: string
}

type TabsProps = {
  items: TabItem[]
  activeId: string
  onChange: (id: string) => void
  /** Accessible name for the tablist (e.g. "מסלולים"). */
  label: string
  className?: string
}

export default function Tabs({ items, activeId, onChange, label, className = '' }: TabsProps) {
  const tabRefs = useRef<Record<string, HTMLButtonElement | null>>({})

  function focusTab(id: string) {
    onChange(id)
    // Move DOM focus to the newly-activated tab (roving tabindex).
    requestAnimationFrame(() => tabRefs.current[id]?.focus())
  }

  function onKeyDown(e: KeyboardEvent<HTMLButtonElement>) {
    const idx = items.findIndex((t) => t.id === activeId)
    if (idx < 0) return
    let next = idx
    // In RTL the visual "next" (right→left) is ArrowLeft.
    if (e.key === 'ArrowLeft') next = idx + 1
    else if (e.key === 'ArrowRight') next = idx - 1
    else if (e.key === 'Home') next = 0
    else if (e.key === 'End') next = items.length - 1
    else return
    e.preventDefault()
    const clamped = (next + items.length) % items.length
    focusTab(items[clamped].id)
  }

  return (
    <div role="tablist" aria-label={label} className={`flex items-center gap-1 ${className}`}>
      {items.map((tab) => {
        const selected = tab.id === activeId
        return (
          <button
            key={tab.id}
            ref={(el) => {
              tabRefs.current[tab.id] = el
            }}
            role="tab"
            type="button"
            id={`tab-${tab.id}`}
            aria-selected={selected}
            aria-controls={`tabpanel-${tab.id}`}
            tabIndex={selected ? 0 : -1}
            onClick={() => onChange(tab.id)}
            onKeyDown={onKeyDown}
            className={`rounded-t-lg border-b-2 px-3 py-2 text-sm transition ${
              selected
                ? 'border-leaf font-medium text-slate-900'
                : 'border-transparent text-slate-500 hover:text-slate-800'
            }`}
          >
            {tab.label}
          </button>
        )
      })}
    </div>
  )
}
