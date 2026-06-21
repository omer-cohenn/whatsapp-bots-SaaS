// Owner appointments area (route /appointments, also /settings/calendar for the
// Google OAuth return). Two tabs: the bookings list and the booking settings
// (working hours, services, availability rules, Meet, Google connect, link).
// Renders inside <DashboardLayout> (sidebar, header, skip-link, <main>). The
// tenant is always server-side from the session — never sent from here.

import { useState } from 'react'
import DashboardLayout from '../components/DashboardLayout'
import Icon from '../components/ui/Icon'
import BookingsPanel from '../components/booking/BookingsPanel'
import BookingSettingsPanel from '../components/booking/BookingSettingsPanel'

type Tab = 'bookings' | 'settings'

export default function AppointmentsPage({ defaultTab = 'bookings' }: { defaultTab?: Tab }) {
  const [tab, setTab] = useState<Tab>(defaultTab)

  const tabs: { id: Tab; label: string }[] = [
    { id: 'bookings', label: 'פגישות' },
    { id: 'settings', label: 'הגדרות תורים' },
  ]

  return (
    <DashboardLayout>
      <div className="mx-auto flex w-full max-w-4xl flex-col gap-6 px-4 py-6 sm:px-6">
        <h1 className="flex items-center gap-2 text-2xl font-bold text-slate-900">
          <Icon name="calendar-event" size={22} className="text-leaf" />
          ניהול פגישות
        </h1>

        {/* Tabs (accessible tablist). */}
        <div role="tablist" aria-label="ניהול פגישות" className="flex gap-1 border-b border-slate-200">
          {tabs.map((t) => {
            const selected = t.id === tab
            return (
              <button
                key={t.id}
                type="button"
                role="tab"
                id={`tab-${t.id}`}
                aria-selected={selected}
                aria-controls={`panel-${t.id}`}
                onClick={() => setTab(t.id)}
                className={`-mb-px border-b-2 px-4 py-2 text-sm font-medium transition ${
                  selected
                    ? 'border-leaf text-leaf-ink'
                    : 'border-transparent text-slate-500 hover:text-slate-800'
                }`}
              >
                {t.label}
              </button>
            )
          })}
        </div>

        <div
          role="tabpanel"
          id={`panel-${tab}`}
          aria-labelledby={`tab-${tab}`}
          tabIndex={0}
        >
          {tab === 'bookings' ? <BookingsPanel /> : <BookingSettingsPanel />}
        </div>
      </div>
    </DashboardLayout>
  )
}
