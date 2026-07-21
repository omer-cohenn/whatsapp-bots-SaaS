// אווטאר ראשי-תיבות משותף — עיגול צבעוני עם האותיות הראשונות של השם
// Shared initials avatar (M18).
//
// The colour is DECORATIVE only — it is derived from the name so the same person
// keeps the same colour between renders, but it never carries meaning on its own
// (the name sits right next to it). That is why the circle is aria-hidden: a
// screen reader would otherwise read two loose Hebrew letters before the name.
//
// Extracted from ActivityFeed, which grew this pattern first; LeadCard has its
// own near-identical copy. Anything new should import THIS one rather than add a
// fourth variant.
//
// NOT a profile photo. Real WhatsApp profile pictures are a separate, larger
// piece of work — they are personal images of end customers who never signed up
// to our system, so they would need the same encryption + tenant isolation +
// deletion policy as lead files. Tracked in STATUS.md.

// All five pass AA against white text.
const AVATAR_COLORS = [
  'bg-leaf', // green
  'bg-[#378ADD]', // blue
  'bg-[#D85A30]', // red-orange
  'bg-amber-600', // amber
  'bg-violet-600', // violet
]

/** Stable colour per name: sum of code points → palette index. */
export function avatarColor(name: string): string {
  let sum = 0
  for (const ch of name) sum = (sum + (ch.codePointAt(0) ?? 0)) % 9973
  return AVATAR_COLORS[sum % AVATAR_COLORS.length]
}

/** Up to two initials: first letter of each of the first two words. */
export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean)
  if (parts.length === 0) return '·'
  if (parts.length === 1) return parts[0].slice(0, 2)
  return `${parts[0][0]}${parts[1][0]}`
}

type Props = {
  /** The display name the initials + colour are derived from. */
  name: string
  /** Tailwind size classes for the circle (default: WhatsApp-ish 48px). */
  className?: string
}

export default function Avatar({ name, className = 'h-12 w-12 text-base' }: Props) {
  return (
    <span
      aria-hidden="true"
      className={`flex shrink-0 items-center justify-center rounded-full font-bold text-white ${avatarColor(
        name,
      )} ${className}`}
    >
      {initials(name)}
    </span>
  )
}
