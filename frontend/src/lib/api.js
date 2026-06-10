/* Scuffed OS — backend API client.
   In dev, calls go to same-origin /api/* which Vite proxies to the FastAPI
   server on :8000 (see vite.config.js). Set VITE_API_URL to point elsewhere
   (e.g. a deployed backend). Every caller is expected to handle failure
   gracefully (the UI falls back to local behavior when the backend is down). */
const BASE = import.meta.env.VITE_API_URL || ''

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) throw new Error(`API ${res.status} on ${path}`)
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
