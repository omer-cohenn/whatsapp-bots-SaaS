// Owner appointments area (route /appointments, also /settings/calendar for the
// Google OAuth return). Renders inside <DashboardLayout> (sidebar, header,
// skip-link, <main>). The tenant is always server-side from the session — never
// sent from here.
//
// M20 split the old single "הגדרות תורים" tab into the owner's three-step setup
// wizard, so there are now FOUR tabs in one flat tablist:
//
//   פגישות                 — the day-to-day bookings list
//   ─────
//   פרטי העסק וזמינות      ┐
//   תמונות ועיצוב          ├ setup: filled in once, then rarely revisited
//   השירותים שהעסק מציע    ┘
//
// Flat rather than nested (a "setup" tab containing its own tablist), because
// nesting hides the three steps behind a click and gives the owner two tab rows
// to reason about. A separator plus a group label keeps the day-to-day view
// visually distinct from the setup without costing an extra level. Grouping is
// announced too: the setup tabs share an aria-describedby pointing at the group
// caption, so a screen reader hears which of the two groups a tab belongs to.
//
// The `settings` id is kept for the setup's first tab so the Google OAuth return
// URL (/settings/calendar) still lands where it always did.

import { Fragment, useState } from 'react'
import DashboardLayout from '../components/DashboardLayout'
import Icon from '../components/ui/Icon'
import BookingsPanel from '../components/booking/BookingsPanel'
import BookingSettingsPanel from '../components/booking/BookingSettingsPanel'
import DesignPanel from '../components/booking/setup/DesignPanel'

type Tab = 'bookings' | 'settings' | 'design' | 'services'

const TABS: { id: Tab; label: string; setup: boolean }[] = [
  { id: 'bookings', label: 'פגישות', setup: false },
  { id: 'settings', label: 'פרטי העסק וזמינות', setup: true },
  { id: 'design', label: 'תמונות ועיצוב', setup: true },
  { id: 'services', label: 'השירותים שהעסק מציע', setup: true },
]

export default function AppointmentsPage({ defaultTab = 'bookings' }: { defaultTab?: Tab }) {
  const [tab, setTab] = useState<Tab>(defaultTab)

  return (
    <DashboardLayout>
      <div className="mx-auto flex w-full max-w-4xl flex-col gap-6 px-4 py-6 sm:px-6">
        <h1 className="flex items-center gap-2 text-2xl font-bold text-slate-900">
          <Icon name="calendar-event" size={22} className="text-leaf" />
          ניהול פגישות
        </h1>

        {/* Tabs (accessible tablist).
            Two layouts, one markup. Above `sm` it is the original flat row.
            Below it, four full-length Hebrew labels are ~430px of text and the
            row wrapped into a ragged two-line mess with the group caption
            orphaned mid-line. So on a phone the tablist becomes a 3-column
            grid: "פגישות" spans the full first row (it is the day-to-day view
            and deserves the width), the caption gets its own line, and the
            three setup steps sit side by side as equal thirds — labels wrap to
            two short lines rather than being truncated, so nothing is hidden
            and nothing scrolls sideways. */}
        <div
          role="tablist"
          aria-label="ניהול פגישות"
          className="grid grid-cols-3 items-end gap-x-1 border-b border-slate-200 sm:flex sm:flex-wrap"
        >
          {TABS.map((t, index) => {
            const selected = t.id === tab
            // A thin rule + caption where the day-to-day view ends and setup begins.
            // Phone: a full-width caption line. Desktop: the original inline rule.
            const startsSetup = t.setup && !TABS[index - 1]?.setup
            return (
              <Fragment key={t.id}>
                {startsSetup ? (
                  <span
                    id="setup-group-label"
                    className="col-span-3 mt-2 text-xs text-slate-400 sm:col-auto sm:mx-2 sm:mt-0 sm:mb-2 sm:self-end sm:border-e sm:border-slate-200 sm:pe-3"
                  >
                    הקמת העמוד העסקי
                  </span>
                ) : null}
                <button
                  type="button"
                  role="tab"
                  id={`tab-${t.id}`}
                  aria-selected={selected}
                  aria-controls={`panel-${t.id}`}
                  aria-describedby={t.setup ? 'setup-group-label' : undefined}
                  onClick={() => setTab(t.id)}
                  className={`-mb-px flex min-h-[44px] items-center justify-center border-b-2 px-1 text-center text-xs font-medium leading-tight transition sm:block sm:min-h-0 sm:px-4 sm:py-2 sm:text-sm ${
                    t.setup ? '' : 'col-span-3'
                  } ${
                    selected
                      ? 'border-leaf text-leaf-ink'
                      : 'border-transparent text-slate-500 hover:text-slate-800'
                  }`}
                >
                  {t.label}
                </button>
              </Fragment>
            )
          })}
        </div>

        <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`} tabIndex={0}>
          {tab === 'bookings' ? <BookingsPanel /> : null}
          {tab === 'settings' ? <BookingSettingsPanel section="details" /> : null}
          {tab === 'design' ? <DesignPanel /> : null}
          {tab === 'services' ? <BookingSettingsPanel section="services" /> : null}
        </div>
      </div>
    </DashboardLayout>
  )
}
