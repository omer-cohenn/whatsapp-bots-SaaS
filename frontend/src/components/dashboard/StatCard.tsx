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
    <div className="flex flex-col gap-3 rounded-2xl bg-white p-4 shadow-[0_10px_26px_rgba(70,60,35,0.07)] dark:border dark:border-white/10 dark:bg-slate-800 dark:shadow-none">
      <span
        aria-hidden="true"
        className={`flex h-10 w-10 items-center justify-center rounded-xl text-white ${chipClassName}`}
      >
        <Icon name={icon} size={22} />
      </span>
      <span className="text-3xl font-bold leading-none text-slate-900 sm:text-4xl dark:text-slate-100">
        {value}
      </span>
      <span className="text-sm text-slate-500 dark:text-slate-400">{label}</span>
    </div>
  )
}
