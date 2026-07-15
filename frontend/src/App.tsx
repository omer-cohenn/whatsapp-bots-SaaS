// App router. Public routes (/login, /terms, /privacy, /accessibility) are
// reachable without a session. The root "/" renders <Home>, which shows the
// public marketing landing page to visitors and the dashboard to logged-in
// owners. The other dashboard routes stay wrapped by <AuthGate>. The whole tree
// sits inside <AuthProvider> so every route can read auth state.

import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { ThemeProvider } from './lib/ThemeContext'
import { AuthProvider } from './auth/AuthContext'
import { UnreadProvider } from './dashboard/UnreadContext'
import AccessibilityWidget from './components/AccessibilityWidget'
import AuthGate from './components/AuthGate'
import AdminGate from './components/AdminGate'
import LoginPage from './pages/LoginPage'
import TermsPrivacyPage from './pages/TermsPrivacyPage'
import AccessibilityPage from './pages/AccessibilityPage'
import Home from './pages/Home'
import BotBuilderPage from './pages/BotBuilderPage'
import TryMePage from './pages/TryMePage'
import LeadsPage from './pages/LeadsPage'
import ConversationsPage from './pages/ConversationsPage'
import AppointmentsPage from './pages/AppointmentsPage'
import WhatsAppPage from './pages/WhatsAppPage'
import PublicBookingPage from './pages/PublicBookingPage'
import PublicManagePage from './pages/PublicManagePage'
import AdminHome from './pages/admin/AdminHome'
import AdminBilling from './pages/admin/AdminBilling'
import AdminCrm from './pages/admin/AdminCrm'
import BusinessesList from './pages/admin/BusinessesList'
import BusinessDetail from './pages/admin/BusinessDetail'
import SettingsPage from './pages/SettingsPage'

export default function App() {
  return (
    <BrowserRouter>
      <ThemeProvider>
      <AuthProvider>
        {/* Tenant-wide unread count for the "שיחות" nav badge (decision 0021).
            Auth-aware: it only polls once a session exists. */}
        <UnreadProvider>
        {/* Always-available accessibility menu, shown on every page. */}
        <AccessibilityWidget />
        <Routes>
          {/* Public */}
          <Route path="/login" element={<LoginPage />} />
          <Route path="/terms" element={<TermsPrivacyPage />} />
          <Route path="/privacy" element={<TermsPrivacyPage />} />
          <Route path="/accessibility" element={<AccessibilityPage />} />

          {/* Public booking (NO auth — tenant resolved server-side from the slug). */}
          <Route path="/book/:slug" element={<PublicBookingPage />} />
          <Route path="/book/:slug/manage/:token" element={<PublicManagePage />} />

          {/* Root: public landing for visitors, dashboard for logged-in owners. */}
          <Route path="/" element={<Home />} />

          {/* Protected */}
          <Route
            path="/bot-builder"
            element={
              <AuthGate>
                <BotBuilderPage />
              </AuthGate>
            }
          />
          <Route
            path="/try-me"
            element={
              <AuthGate>
                <TryMePage />
              </AuthGate>
            }
          />
          <Route
            path="/leads"
            element={
              <AuthGate>
                <LeadsPage />
              </AuthGate>
            }
          />
          <Route
            path="/conversations"
            element={
              <AuthGate>
                <ConversationsPage />
              </AuthGate>
            }
          />
          <Route
            path="/appointments"
            element={
              <AuthGate>
                <AppointmentsPage />
              </AuthGate>
            }
          />
          <Route
            path="/whatsapp"
            element={
              <AuthGate>
                <WhatsAppPage />
              </AuthGate>
            }
          />
          {/* Google OAuth returns here (?google=connected|error) → settings tab. */}
          <Route
            path="/settings/calendar"
            element={
              <AuthGate>
                <AppointmentsPage defaultTab="settings" />
              </AuthGate>
            }
          />

          {/* Platform-operator back-office (M12). AuthGate ensures a session;
              AdminGate bounces a logged-in non-admin to "/". The server also
              re-checks admin identity on every /api/admin/* call. */}
          <Route
            path="/admin"
            element={
              <AuthGate>
                <AdminGate>
                  <AdminHome />
                </AdminGate>
              </AuthGate>
            }
          />
          <Route
            path="/admin/crm"
            element={
              <AuthGate>
                <AdminGate>
                  <AdminCrm />
                </AdminGate>
              </AuthGate>
            }
          />
          <Route
            path="/admin/billing"
            element={
              <AuthGate>
                <AdminGate>
                  <AdminBilling />
                </AdminGate>
              </AuthGate>
            }
          />
          <Route
            path="/admin/businesses"
            element={
              <AuthGate>
                <AdminGate>
                  <BusinessesList />
                </AdminGate>
              </AuthGate>
            }
          />
          <Route
            path="/admin/businesses/:id"
            element={
              <AuthGate>
                <AdminGate>
                  <BusinessDetail />
                </AdminGate>
              </AuthGate>
            }
          />

          <Route
            path="/settings"
            element={
              <AuthGate>
                <SettingsPage />
              </AuthGate>
            }
          />

          {/* Unknown paths → home (AuthGate handles login redirect). */}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
        </UnreadProvider>
      </AuthProvider>
      </ThemeProvider>
    </BrowserRouter>
  )
}
