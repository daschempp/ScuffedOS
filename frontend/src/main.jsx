import React from 'react'
import { createRoot } from 'react-dom/client'
import './styles/index.css'
import { App } from './App.jsx'
import { setApiBase } from './lib/api.js'

async function resolveApiBase() {
  // Only inside the Tauri webview: ask Rust for the backend port.
  if (typeof window !== 'undefined' && '__TAURI__' in window) {
    try {
      const { invoke } = await import('@tauri-apps/api/core')
      const port = await invoke('api_port')
      setApiBase(`http://127.0.0.1:${port}`)
    } catch (err) {
      console.error('Failed to resolve Tauri api port; falling back to relative /api', err)
    }
  }
  // In dev (no __TAURI__) BASE stays '' and the Vite proxy handles /api.
}

resolveApiBase().finally(() => {
  createRoot(document.getElementById('root')).render(
    <React.StrictMode>
      <App />
    </React.StrictMode>,
  )
})
