import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import './index.css'

const rootEl = document.getElementById('root')
if (!rootEl) throw new Error('Root element #root not found')

// (A dev-only @axe-core/react console reporter can be re-added here once the
// package is installed in the container. The accessibility GATE is ESLint's
// jsx-a11y rules at build time — that stays on regardless.)

ReactDOM.createRoot(rootEl).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
