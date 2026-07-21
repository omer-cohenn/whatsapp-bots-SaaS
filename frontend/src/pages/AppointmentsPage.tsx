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

import { useState } from 'react'
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

        {/* Tabs (accessible tablist). */}
        <div
          role="tablist"
          aria-label="ניהול פגישות"
          className="flex flex-wrap items-end gap-1 border-b border-slate-200"
        >
          {TABS.map((t, index) => {
            const selected = t.id === tab
            // A thin rule + caption where the day-to-day view ends and setup begins.
            const startsSetup = t.setup && !TABS[index - 1]?.setup
            return (
              <div key={t.id} className="flex items-end">
                {startsSetup ? (
                  <span
                    id="setup-group-label"
                    className="mx-2 mb-2 border-e border-slate-200 pe-3 text-xs text-slate-400"
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
                  className={`-mb-px border-b-2 px-4 py-2 text-sm font-medium transition ${
                    selected
                      ? 'border-leaf text-leaf-ink'
                      : 'border-transparent text-slate-500 hover:text-slate-800'
                  }`}
                >
                  {t.label}
                </button>
              </div>
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
