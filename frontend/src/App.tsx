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

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          {/* Public */}
          <Route path="/login" element={<LoginPage />} />
          <Route path="/terms" element={<TermsPage />} />
          <Route path="/privacy" element={<PrivacyPage />} />

          {/* Protected */}
          <Route
            path="/"
            element={
              <AuthGate>
                <DashboardHome />
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
