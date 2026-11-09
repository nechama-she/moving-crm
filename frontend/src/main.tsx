import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { installSessionFetch } from './sessionFetch'
import { installCustomerSessionFetch } from './customerSession'

async function start() {
  // Local review only (npm run dev:demo): invented data instead of the backend. Removed from production builds.
  if (import.meta.env.MODE === 'demo') {
    const { installDemoApi } = await import('./demo/installDemoApi')
    installDemoApi()
  }
  installSessionFetch()
  installCustomerSessionFetch()

  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <App />
    </StrictMode>,
  )
}

start()
