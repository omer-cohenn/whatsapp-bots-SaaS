// A tiny, dependency-free emoji picker: a 🙂 toggle button that opens a small
// grid of common emojis. Clicking one calls onPick(emoji); the panel also
// closes on Escape or on an outside click. Kept deliberately simple — no search,
// no categories, no external library.

import { useEffect, useId, useRef, useState } from 'react'

// ~30 friendly, business-appropriate emojis for quick replies.
const EMOJIS = [
  '🙂', '😀', '😁', '😉', '😊', '😍',
  '👍', '👏', '🙏', '💪', '🤝', '✌️',
  '❤️', '🔥', '✨', '🎉', '🎁', '⭐',
  '✅', '❌', '⏰', '📅', '📞', '📍',
  '💬', '📝', '💡', '💯', '😅', '🙌',
]

type Props = {
  /** Called with the chosen emoji character. */
  onPick: (emoji: string) => void
  /** Disable the toggle (e.g. while sending). */
  disabled?: boolean
}

export default function EmojiPicker({ onPick, disabled = false }: Props) {
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)
  const panelId = useId()

  // Close on Escape (keyboard) and on a click outside the picker.
  useEffect(() => {
    if (!open) return

    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false)
    }
    function onPointerDown(e: PointerEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }

    document.addEventListener('keydown', onKeyDown)
    document.addEventListener('pointerdown', onPointerDown)
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      document.removeEventListener('pointerdown', onPointerDown)
    }
  }, [open])

  function choose(emoji: string) {
    onPick(emoji)
    setOpen(false)
  }

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        disabled={disabled}
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="true"
        aria-expanded={open}
        aria-controls={open ? panelId : undefined}
        aria-label="הוספת אימוג׳י"
        className="inline-flex h-9 w-9 items-center justify-center rounded-lg text-lg text-slate-600 transition hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-60"
      >
        <span aria-hidden="true">🙂</span>
      </button>

      {open ? (
        <div
          id={panelId}
          role="menu"
          aria-label="בחירת אימוג׳י"
          className="absolute bottom-11 start-0 z-20 grid w-56 grid-cols-6 gap-1 rounded-xl border border-black/10 bg-white p-2 shadow-lg"
        >
          {EMOJIS.map((emoji) => (
            <button
              key={emoji}
              type="button"
              role="menuitem"
              onClick={() => choose(emoji)}
              aria-label={`הוספת ${emoji}`}
              className="flex h-8 w-8 items-center justify-center rounded-md text-lg transition hover:bg-slate-100"
            >
              <span aria-hidden="true">{emoji}</span>
            </button>
          ))}
        </div>
      ) : null}
    </div>
  )
}
