// A single KPI / funnel metric card (the prototype's `.mc`): a coloured icon
// chip, a big value, and a label. The chip colour is decorative; the value +
// label carry the meaning, so a screen reader reads e.g. "12 לידים שהתחילו".

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
    <div className="flex flex-col gap-2 rounded-xl border border-black/10 bg-white p-3 dark:border-white/10 dark:bg-slate-800">
      <span
        aria-hidden="true"
        className={`flex h-8 w-8 items-center justify-center rounded-lg text-white ${chipClassName}`}
      >
        <Icon name={icon} size={18} />
      </span>
      <span className="text-2xl font-medium leading-none text-slate-900 dark:text-slate-100">{value}</span>
      <span className="text-xs text-slate-500 dark:text-slate-400">{label}</span>
    </div>
  )
}
