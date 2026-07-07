import React from 'react'
import { createRoot } from 'react-dom/client'
import './styles/index.css'
import { App } from './App.jsx'
import { setApiBase } from './lib/api.js'

async function resolveApiBase() {
  const { invoke, isTauri } = await import('@tauri-apps/api/core')
  // Only inside the Tauri webview: ask Rust for the backend port. isTauri()
  // checks globalThis.isTauri, which Tauri v2 injects into every webview
  // regardless of the (default-off) app.withGlobalTauri setting — unlike
  // window.__TAURI__, which is ONLY injected when withGlobalTauri is true.
  if (isTauri()) {
    try {
      const port = await invoke('api_port')
      setApiBase(`http://127.0.0.1:${port}`)
    } catch (err) {
      console.error('Failed to resolve Tauri api port; falling back to relative /api', err)
    }
  }
  // In dev (not Tauri) BASE stays '' and the Vite proxy handles /api.
}

resolveApiBase().finally(() => {
  createRoot(document.getElementById('root')).render(
    <React.StrictMode>
      <App />
    </React.StrictMode>,
  )
})
