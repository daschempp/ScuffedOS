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

/* Stream one assistant turn over SSE. Calls on(event, data) for each event:
   meta {conversation_id} → delta {text}* → tool/action* → done {text, actions}.
   Throws ApiError/TypeError like request() so callers can fall back. */
async function chatStream(message, conversationId, on) {
  const res = await fetch(`${BASE}/api/assistant/chat/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, conversation_id: conversationId }),
  })
  if (!res.ok || !res.body) {
    let code
    try { code = (await res.json())?.error?.code } catch { /* keep undefined */ }
    throw new ApiError(`API ${res.status} on /api/assistant/chat/stream`, { status: res.status, code })
  }
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    let split
    while ((split = buf.indexOf('\n\n')) >= 0) {
      const chunk = buf.slice(0, split)
      buf = buf.slice(split + 2)
      let event = 'message'
      let data = ''
      for (const line of chunk.split('\n')) {
        if (line.startsWith('event: ')) event = line.slice(7)
        else if (line.startsWith('data: ')) data += line.slice(6)
      }
      if (data) on(event, JSON.parse(data))
    }
  }
}

export const api = {
  // Assistant — server-side tool loop over every domain (M2).
  chat: (message, conversationId) => request('/api/assistant/chat', {
    method: 'POST',
    body: JSON.stringify({ message, conversation_id: conversationId }),
  }),
  chatStream,
  latestConversation: () => request('/api/assistant/conversation'),

  // Tasks — the one rich task model (Home, TasksScreen and the assistant
  // all read/write these same rows). Accepts a label string or a full object.
  listTasks: () => request('/api/tasks'),
  createTask: (task) => request('/api/tasks', {
    method: 'POST',
    body: JSON.stringify(typeof task === 'string' ? { label: task } : task),
  }),
  updateTask: (id, patch) => request(`/api/tasks/${id}`, { method: 'PATCH', body: JSON.stringify(patch) }),
  deleteTask: (id) => request(`/api/tasks/${id}`, { method: 'DELETE' }),

  // Second-brain memories.
  listMemories: () => request('/api/memory'),
  createMemory: (text, extras) => request('/api/memory', {
    method: 'POST',
    body: JSON.stringify({ text, ...extras }),
  }),
  updateMemory: (id, patch) => request(`/api/memory/${id}`, { method: 'PATCH', body: JSON.stringify(patch) }),
  deleteMemory: (id) => request(`/api/memory/${id}`, { method: 'DELETE' }),
}
