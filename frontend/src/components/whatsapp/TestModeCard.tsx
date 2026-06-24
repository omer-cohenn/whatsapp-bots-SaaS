// כרטיס "איך בודקים?": מסביר לפרסם את הבוט ולשלוח לעצמך הודעה, עם קישור לבונה הבוט.

import { Link } from 'react-router-dom'
import Card from '../ui/Card'
import Icon from '../ui/Icon'

export default function TestModeCard() {
  return (
    <Card className="border-leaf-soft bg-leaf-soft/40">
      <div className="flex items-start gap-3">
        <span
          aria-hidden="true"
          className="mt-0.5 flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-lg bg-white text-leaf-ink"
        >
          <Icon name="sparkles" size={20} />
        </span>
        <div className="flex flex-col gap-2">
          <h2 className="text-base font-semibold text-leaf-ink">איך בודקים?</h2>
          <p className="text-sm text-slate-700">
            כדי לבדוק: פרסמו את הבוט (בבונה הבוט), ואז שלחו לעצמכם הודעה בוואטסאפ —
            הבוט יענה.
          </p>
          <Link
            to="/bot-builder"
            className="inline-flex w-fit items-center gap-1.5 rounded-lg bg-brand px-4 py-2 text-sm font-medium text-white transition hover:bg-brand-dark"
          >
            <Icon name="robot" size={16} />
            לבונה הבוט ולפרסום
          </Link>
        </div>
      </div>
    </Card>
  )
}
