/* Scuffed OS — backend API client.
   In dev, calls go to same-origin /api/* which Vite proxies to the FastAPI
   server on :8000 (see vite.config.js). Set VITE_API_URL to point elsewhere
   (e.g. a deployed backend). Every caller is expected to handle failure
   gracefully (the UI falls back to local behavior when the backend is down). */
const BASE = import.meta.env.VITE_API_URL || ''

/* Thrown for non-2xx API responses (vs. a network-level TypeError when the
   backend is unreachable — callers use that distinction to decide between
   "surface the error" and "fall back to local behavior"). */
export class ApiError extends Error {
  constructor(message, { status, code } = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }
}

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) {
    let code
    let message = `API ${res.status} on ${path}`
    try {
      const body = await res.json()
      if (body?.error) {
        code = body.error.code
        message = body.error.message
      }
    } catch { /* non-JSON error body — keep the generic message */ }
    throw new ApiError(message, { status: res.status, code })
  }
  if (res.status === 204) return null
  return res.json()
}

export const api = {
  // Assistant — POST a message, get { text, action? } back.
  chat: (message) => request('/api/assistant/chat', { method: 'POST', body: JSON.stringify({ message }) }),

  // Tasks — the simple home/assistant task list.
  listTasks: () => request('/api/tasks'),
  createTask: (label) => request('/api/tasks', { method: 'POST', body: JSON.stringify({ label }) }),
  updateTask: (id, patch) => request(`/api/tasks/${id}`, { method: 'PATCH', body: JSON.stringify(patch) }),

  // Second-brain memories.
  listMemories: () => request('/api/memory'),
  createMemory: (text) => request('/api/memory', { method: 'POST', body: JSON.stringify({ text }) }),
}
