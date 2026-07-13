/* Scuffed OS — backend API client.
   In dev, calls go to same-origin /api/* which Vite proxies to the FastAPI
   server on :8000 (see vite.config.js). Set VITE_API_URL to point elsewhere
   (e.g. a deployed backend). Every caller is expected to handle failure
   gracefully (the UI falls back to local behavior when the backend is down). */
/* Base URL for backend calls. Precedence:
   1. VITE_API_URL — explicit build/deploy override.
   2. '' — dev, and the initial value in the packaged .app: relative '/api'
      paths hit the Vite proxy in dev; in the .app, main.jsx calls
      setApiBase() with the resolved 127.0.0.1:<port> before first render. */
let BASE = import.meta.env.VITE_API_URL || ''

/* Allow the Tauri bootstrap (main.jsx) to inject the resolved 127.0.0.1:<port>
   base before the first fetch. No trailing slash — paths already begin '/api'. */
export function setApiBase(base) {
  BASE = base ? base.replace(/\/$/, '') : ''
}

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

/* Shared response handling: parse the {error: {code, message}} envelope on
   failure, unwrap JSON (or null for 204) on success. */
async function handleResponse(res, path) {
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

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  return handleResponse(res, path)
}

/* Multipart upload — must NOT set Content-Type (the browser supplies the
   multipart boundary), so this bypasses request() and its JSON header. */
async function uploadFile(path, file) {
  const form = new FormData()
  form.append('file', file)
  const res = await fetch(`${BASE}${path}`, { method: 'POST', body: form })
  return handleResponse(res, path)
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

  // Task reminders (M3) — structured rows, managed via their own endpoints
  // (TaskCreate/TaskUpdate no longer accept a reminders field).
  addTaskReminder: (taskId, remindAtIso, label) => request(`/api/tasks/${taskId}/reminders`, {
    method: 'POST',
    body: JSON.stringify(label != null ? { remind_at: remindAtIso, label } : { remind_at: remindAtIso }),
  }),
  deleteTaskReminder: (taskId, reminderId) =>
    request(`/api/tasks/${taskId}/reminders/${reminderId}`, { method: 'DELETE' }),

  // Task file attachments (M3). uploadTaskFile resolves to the updated Task.
  uploadTaskFile: (taskId, file) => uploadFile(`/api/tasks/${taskId}/files`, file),
  deleteTaskFile: (taskId, fileId) => request(`/api/tasks/${taskId}/files/${fileId}`, { method: 'DELETE' }),
  taskFileUrl: (taskId, fileId) => `${BASE}/api/tasks/${taskId}/files/${fileId}`,

  // Calendar — recurring series are expanded server-side into occurrences.
  // Always pass explicit-offset ISO datetimes (naive is read as UTC).
  listEvents: (fromIso, toIso) =>
    request(`/api/calendar/events?from=${encodeURIComponent(fromIso)}&to=${encodeURIComponent(toIso)}`),
  createEvent: (evt) => request('/api/calendar/events', { method: 'POST', body: JSON.stringify(evt) }),
  updateEvent: (id, patch) => request(`/api/calendar/events/${id}`, { method: 'PATCH', body: JSON.stringify(patch) }),
  // With occurrenceStartIso: delete just that occurrence; without: the whole series.
  deleteEvent: (id, occurrenceStartIso) => request(
    `/api/calendar/events/${id}${occurrenceStartIso ? `?occurrence_start=${encodeURIComponent(occurrenceStartIso)}` : ''}`,
    { method: 'DELETE' },
  ),
  upNext: (limit) => request(`/api/calendar/up-next${limit != null ? `?limit=${limit}` : ''}`),

  // Habits — week is a Monday YYYY-MM-DD; toggle flips one day's checkmark.
  habitsWeek: (weekIsoDate) => request(`/api/habits${weekIsoDate ? `?week=${weekIsoDate}` : ''}`),
  createHabit: (h) => request('/api/habits', { method: 'POST', body: JSON.stringify(h) }),
  toggleHabit: (id, isoDate) => request(`/api/habits/${id}/toggle`, {
    method: 'POST',
    body: JSON.stringify(isoDate ? { date: isoDate } : {}),
  }),
  updateHabit: (id, patch) => request(`/api/habits/${id}`, { method: 'PATCH', body: JSON.stringify(patch) }),
  deleteHabit: (id) => request(`/api/habits/${id}`, { method: 'DELETE' }),

  // Nutrition — day log, water, weekly kcal trend, targets, food search.
  nutritionDay: (isoDate) => request(`/api/nutrition/day${isoDate ? `?date=${isoDate}` : ''}`),
  logMeal: (meal) => request('/api/nutrition/meals', { method: 'POST', body: JSON.stringify(meal) }),
  updateMeal: (id, patch) => request(`/api/nutrition/meals/${id}`, { method: 'PATCH', body: JSON.stringify(patch) }),
  deleteMeal: (id) => request(`/api/nutrition/meals/${id}`, { method: 'DELETE' }),
  addWater: (delta) => request('/api/nutrition/water', {
    method: 'POST',
    body: JSON.stringify({ delta: delta != null ? delta : 1 }),
  }),
  nutritionWeek: (isoDate) => request(`/api/nutrition/week${isoDate ? `?date=${isoDate}` : ''}`),
  getTargets: () => request('/api/nutrition/targets'),
  putTargets: (p) => request('/api/nutrition/targets', { method: 'PUT', body: JSON.stringify(p) }),
  searchFoods: (q) => request(`/api/nutrition/foods?q=${encodeURIComponent(q)}`),

  // Shared OAuth (M5) — connect/status/disconnect are provider-agnostic and
  // live under /api/oauth/*. The fitness DATA reads/writes below stay on
  // /api/fitness/*. Tokens never cross this boundary.
  oauthStatus: () => request('/api/oauth/status'),
  oauthConnect: (provider) => request(`/api/oauth/connect/${provider}`),
  oauthDisconnect: (provider) => request(`/api/oauth/disconnect/${provider}`, { method: 'POST' }),

  // M9 Connectors — unified read model for Settings › Connectors. One card per
  // connector (google/whoop/moodle/plaid) with status + configured + Plaid items.
  getConnectors: () => request('/api/connectors'),

  // Fitness (M4) — normalized reads/writes. Reads never touch a live WHOOP
  // call; they come straight from the normalized tables, so the screen works
  // while sync is mid-flight or WHOOP is down.
  fitnessToday: (isoDate) => request(`/api/fitness/today${isoDate ? `?date=${isoDate}` : ''}`),
  fitnessWeek: (isoDate) => request(`/api/fitness/week${isoDate ? `?date=${isoDate}` : ''}`),
  fitnessWorkouts: (limit) => request(`/api/fitness/workouts${limit != null ? `?limit=${limit}` : ''}`),
  logWorkout: (w) => request('/api/fitness/workouts', { method: 'POST', body: JSON.stringify(w) }),
  deleteWorkout: (id) => request(`/api/fitness/workouts/${id}`, { method: 'DELETE' }),
  fitnessSync: () => request('/api/fitness/sync', { method: 'POST' }),

  // Insights (M10 fitness-insights slice 1) — cached, derived WHOOP-style
  // coaching cards. Reads are pure cache server-side (no live WHOOP call);
  // insightsRefresh regenerates the day's cards from the latest normalized data.
  insights: (isoDate) => request(`/api/insights${isoDate ? `?date=${isoDate}` : ''}`),
  insightsRefresh: () => request('/api/insights/refresh', { method: 'POST' }),

  // Email (M5) — the inbox/detail come straight from the emails table server-
  // side (list never triggers a live Gmail call). Only emailDetail fetches the
  // body live, with a graceful fallback string if Gmail is unreachable. Bodies
  // are never persisted. emailSync kicks a foreground sync pass.
  emailInbox: () => request('/api/email/inbox'),
  emailDetail: (id) => request(`/api/email/${id}`),
  emailSync: () => request('/api/email/sync', { method: 'POST' }),

  // Email writes (M5 slice-2) — confirm-first server-side (Gmail call happens
  // before any local change); gated client-side on can_write_email (see
  // EmailScreen's canWrite banner). emailDraft never persists and only runs on
  // explicit user request (the ✨ button).
  emailSend: (payload) => request('/api/email/send', { method: 'POST', body: JSON.stringify(payload) }),
  emailReply: (id, payload) => request(`/api/email/${id}/reply`, { method: 'POST', body: JSON.stringify(payload) }),
  emailForward: (id, payload) => request(`/api/email/${id}/forward`, { method: 'POST', body: JSON.stringify(payload) }),
  emailTrash: (id) => request(`/api/email/${id}/trash`, { method: 'POST' }),
  emailFlags: (id, payload) => request(`/api/email/${id}/flags`, { method: 'POST', body: JSON.stringify(payload) }),
  emailLabels: (id, payload) => request(`/api/email/${id}/labels`, { method: 'POST', body: JSON.stringify(payload) }),
  emailLabelList: () => request('/api/email/labels'),
  emailDraft: (payload) => request('/api/email/draft', { method: 'POST', body: JSON.stringify(payload) }),

  // School / Moodle (M6) — every read comes straight from the moodle_* tables
  // server-side (a list call never triggers a live Moodle request), so the
  // screen works while a sync is mid-flight or Moodle is down. Only
  // moodleConnect (validate the pasted wstoken) and moodleSync (kick a
  // foreground tick) reach Moodle. The wstoken is pasted once and lives
  // server-side only — it never crosses this boundary again.
  moodleCourses: () => request('/api/moodle/courses'),
  moodleDeadlines: (days) => request(`/api/moodle/deadlines${days ? `?days=${days}` : ''}`),
  moodleGrades: (courseId) => request(`/api/moodle/grades${courseId ? `?course_id=${courseId}` : ''}`),
  moodleAnnouncements: (courseId) => request(`/api/moodle/announcements${courseId ? `?course_id=${courseId}` : ''}`),
  moodleNotifications: () => request('/api/moodle/notifications'),
  moodleSync: () => request('/api/moodle/sync', { method: 'POST' }),
  moodleConnect: (payload) => request('/api/moodle/connect', { method: 'POST', body: JSON.stringify(payload) }),

  // Finance / Plaid (M7) — every read comes straight from the finance_* tables
  // server-side (a read never triggers a live Plaid call), so the screen works
  // while a sync is mid-flight or Plaid is down. Only linkStart/linkComplete
  // (Hosted Link) and sync reach Plaid. Access tokens never cross this boundary.
  financeStatus: () => request('/api/finance/status'),
  financeLinkStart: (kind) => request('/api/finance/link/start', { method: 'POST', body: JSON.stringify({ kind }) }),
  financeLinkComplete: (linkToken) => request('/api/finance/link/complete', { method: 'POST', body: JSON.stringify({ link_token: linkToken }) }),
  financeSummary: (month) => request(`/api/finance/summary${month ? `?month=${month}` : ''}`),
  financeAccounts: () => request('/api/finance/accounts'),
  financeTransactions: ({ days, accountId, category } = {}) => {
    const q = new URLSearchParams()
    if (days != null) q.set('days', days)
    if (accountId) q.set('account_id', accountId)
    if (category) q.set('category', category)
    const qs = q.toString()
    return request(`/api/finance/transactions${qs ? `?${qs}` : ''}`)
  },
  financeHoldings: () => request('/api/finance/holdings'),
  financeBudgets: (month) => request(`/api/finance/budgets${month ? `?month=${month}` : ''}`),
  financeSaveBudgets: (month, budgets) => request('/api/finance/budgets', { method: 'PUT', body: JSON.stringify({ month, budgets }) }),
  financeReallocate: (payload) => request('/api/finance/budgets/reallocate', { method: 'POST', body: JSON.stringify(payload) }),
  financeDisconnect: (itemId) => request(`/api/finance/items/${itemId}/disconnect`, { method: 'POST' }),
  financeSync: () => request('/api/finance/sync', { method: 'POST' }),
  financeSubscriptions: () => request('/api/finance/subscriptions'),
  financeBills: () => request('/api/finance/bills'),
  financeInvestmentTransactions: (days) => request(`/api/finance/investment-transactions${days ? `?days=${days}` : ''}`),
  financeReauthStart: (itemId) => request(`/api/finance/items/${itemId}/reauth/start`, { method: 'POST' }),
  financeReauthComplete: (itemId) => request(`/api/finance/items/${itemId}/reauth/complete`, { method: 'POST' }),

  // Second-brain memories.
  listMemories: () => request('/api/memory'),
  createMemory: (text, extras) => request('/api/memory', {
    method: 'POST',
    body: JSON.stringify({ text, ...extras }),
  }),
  updateMemory: (id, patch) => request(`/api/memory/${id}`, { method: 'PATCH', body: JSON.stringify(patch) }),
  deleteMemory: (id) => request(`/api/memory/${id}`, { method: 'DELETE' }),

  // People / CRM (M10) — real contact rows (macOS Contacts sync + manual).
  listPeople: (params = {}) => {
    const qs = new URLSearchParams()
    if (params.q) qs.set('q', params.q)
    if (params.cursor) qs.set('cursor', params.cursor)
    if (params.limit != null) qs.set('limit', String(params.limit))
    const suffix = qs.toString() ? `?${qs.toString()}` : ''
    return request(`/api/people${suffix}`)
  },
  getPerson: (id) => request(`/api/people/${id}`),
  createPerson: (person) => request('/api/people', {
    method: 'POST',
    body: JSON.stringify(typeof person === 'string' ? { display_name: person } : person),
  }),
  updatePerson: (id, patch) => request(`/api/people/${id}`, {
    method: 'PATCH', body: JSON.stringify(patch),
  }),
  deletePerson: (id) => request(`/api/people/${id}`, { method: 'DELETE' }),
  syncContacts: () => request('/api/people/sync', { method: 'POST' }),
  enableContacts: (ack = true) => request('/api/people/contacts/enable', {
    method: 'POST', body: JSON.stringify({ ack_storage_disclosure: ack }),
  }),
  disconnectContacts: () => request('/api/people/contacts/disconnect', { method: 'POST' }),
  forgetContacts: () => request('/api/people/contacts/forget', {
    method: 'POST', body: JSON.stringify({ confirm: true }),
  }),
  // Absolute URL for an <img src>; resolves against the configured API base.
  personPhotoUrl: (id) => `${BASE}/api/people/${id}/photo`,

  // Settings — integration secrets. GET returns masked presence only; PUT
  // writes new values into the machine-bound vault (never echoes secrets).
  settingsGetSecrets: () => request('/api/settings/secrets'),
  settingsPutSecrets: (values) => request('/api/settings/secrets', {
    method: 'PUT',
    body: JSON.stringify({ values }),
  }),
}
