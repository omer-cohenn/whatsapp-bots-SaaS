// A single KPI / funnel metric card (the prototype's `.mc`): a coloured icon
// chip, a big value, and a label. The chip colour is decorative; the value +
// label carry the meaning, so a screen reader reads e.g. "12 לידים שהתחילו".
//
// שתי פריסות, אותו תוכן — Two layouts, same content:
//  - מתחת ל-`sm` (טלפון): הצ'יפ והמספר יושבים באותה שורה, התווית מתחתיהם.
//    זה מוריד את גובה הכרטיס מ-~150px ל-~80px, כך שרשת של 2×2 (בית) או 3
//    כרטיסים (לידים) נכנסת במסך אחד ועדיין נקראת כלוח מחוונים — ולא כארבע
//    רצועות שגוללים לידן.
//  - מ-`sm` ומעלה: `sm:contents` מעלים את העוטף, והצ'יפ/המספר/התווית חוזרים
//    להיות ילדים ישירים של העמודה — כלומר בדיוק הפריסה שהייתה בדסקטופ.

import Icon, { type IconName } from '../ui/Icon'

type Props = {
  icon: IconName
  /** Tailwind background class for the icon chip (decorative colour). */
  chipClassName: string
  value: number
  label: string
}

export default function StatCard({ icon, chipClassName, value, label }: Props) {
  return (
    <div className="flex flex-col gap-1.5 rounded-2xl bg-white p-3 shadow-[0_10px_26px_rgba(70,60,35,0.07)] sm:gap-3 sm:p-4 dark:border dark:border-white/10 dark:bg-slate-800 dark:shadow-none">
      {/* `sm:contents` — במובייל זו שורה (צ'יפ + מספר), בדסקטופ העוטף נעלם. */}
      <div className="flex min-w-0 items-center gap-2.5 sm:contents">
        <span
          aria-hidden="true"
          className={`flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-xl text-white sm:h-10 sm:w-10 ${chipClassName}`}
        >
          <Icon name={icon} size={22} />
        </span>
        <span className="truncate text-2xl font-bold leading-none text-slate-900 sm:text-3xl lg:text-4xl dark:text-slate-100">
          {value}
        </span>
      </div>
      <span className="text-xs text-slate-500 sm:text-sm dark:text-slate-400">{label}</span>
    </div>
  )
}
