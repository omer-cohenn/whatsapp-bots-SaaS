// App router. Public routes (/login, /terms, /privacy) are reachable without a
// session; the protected dashboard at "/" is wrapped by <AuthGate>. The whole
// tree sits inside <AuthProvider> so every route can read auth state.

import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AuthProvider } from './auth/AuthContext'
import AuthGate from './components/AuthGate'
import LoginPage from './pages/LoginPage'
import TermsPage from './pages/TermsPage'
import PrivacyPage from './pages/PrivacyPage'
import DashboardHome from './pages/DashboardHome'
import BotBuilderPage from './pages/BotBuilderPage'
import TryMePage from './pages/TryMePage'
import LeadsPage from './pages/LeadsPage'
import ConversationsPage from './pages/ConversationsPage'
import AppointmentsPage from './pages/AppointmentsPage'
import PublicBookingPage from './pages/PublicBookingPage'
import PublicManagePage from './pages/PublicManagePage'

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          {/* Public */}
          <Route path="/login" element={<LoginPage />} />
          <Route path="/terms" element={<TermsPage />} />
          <Route path="/privacy" element={<PrivacyPage />} />

          {/* Public booking (NO auth — tenant resolved server-side from the slug). */}
          <Route path="/book/:slug" element={<PublicBookingPage />} />
          <Route path="/book/:slug/manage/:token" element={<PublicManagePage />} />

          {/* Protected */}
          <Route
            path="/"
            element={
              <AuthGate>
                <DashboardHome />
              </AuthGate>
            }
          />
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
          {/* Google OAuth returns here (?google=connected|error) → settings tab. */}
          <Route
            path="/settings/calendar"
            element={
              <AuthGate>
                <AppointmentsPage defaultTab="settings" />
              </AuthGate>
            }
          />

          {/* Unknown paths → home (AuthGate handles login redirect). */}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  )
}
