/* Scuffed OS — shared task state.
   The one rich task list (review D1), synced to the API: Home, TasksScreen and
   the assistant all read and mutate this same set. Updates are optimistic with
   a short debounce per task so typing in the detail drawer doesn't PATCH per
   keystroke. Falls back to the design-prototype sample (local-only edits) when
   the backend is unreachable. */
import React from 'react'
import { api } from './api.js'

const API_FIELDS = ['label', 'done', 'group', 'deadline', 'prio', 'list',
  'description', 'subtasks', 'labels', 'reminders', 'files']

const SAMPLE_TASKS = [
  { id: 1, label: 'Reply to Priya about Lighthouse', group: 'Today', due: 'Today', prio: 'high', list: 'Work',
    description: 'She asked about the moved deadline — confirm the 30th works and loop in the design review.',
    subtasks: [{ id: 11, label: 'Check calendar for the 30th', done: true }, { id: 12, label: 'Draft reply', done: false }],
    reminders: ['1 hour before'], files: [{ id: 101, name: 'lighthouse-brief.pdf', size: 248000 }] },
  { id: 2, label: 'Log lunch', group: 'Today', due: 'Today', prio: 'low', list: 'Health', labels: ['nutrition'], reminders: ['1:00pm'] },
  { id: 3, label: 'Book dentist follow-up', group: 'Today', due: 'Overdue', late: true, prio: 'med', list: 'Health',
    description: 'Call Oak Street Dental — ask for an early-morning slot.' },
  { id: 4, label: 'Move $120 to savings', group: 'Today', due: 'Today', prio: 'med', list: 'Finance',
    description: 'Roll over the dining-budget surplus.', labels: ['savings'] },
  { id: 5, label: 'Pay rent', group: 'Today', due: 'Done 8:02am', prio: 'high', list: 'Finance', done: true },
  { id: 6, label: 'Draft Q3 planning doc', group: 'Upcoming', due: 'Tomorrow', prio: 'high', list: 'Work',
    description: 'Outline goals, headcount, and the roadmap themes.',
    subtasks: [{ id: 61, label: 'Goals', done: false }, { id: 62, label: 'Roadmap themes', done: false }], labels: ['planning'] },
  { id: 7, label: "Order mom's birthday gift", group: 'Upcoming', due: 'Jun 12', prio: 'med', list: 'Personal',
    description: 'The ceramics class she mentioned in a voice note.', reminders: ['Jun 11, 9:00am'],
    files: [{ id: 701, name: 'ceramics-studio.png', size: 1340000 }, { id: 702, name: 'gift-ideas.txt', size: 1200 }] },
  { id: 8, label: 'Meal prep for the week', group: 'Upcoming', due: 'Sun', prio: 'low', list: 'Health' },
  { id: 9, label: 'Renew gym membership', group: 'Someday', prio: 'low', list: 'Health' },
  { id: 10, label: "Read 'Deep Work'", group: 'Someday', prio: 'low', list: 'Personal', labels: ['reading'] },
].map((t) => ({ done: false, late: false, deadline: null, description: '', subtasks: [], labels: [], reminders: [], files: [], ...t }))

export function useTasks() {
  const [tasks, setTasks] = React.useState(SAMPLE_TASKS)
  // id -> { patch, timer } of edits not yet flushed to the API.
  const pending = React.useRef({})

  const refresh = React.useCallback(() => {
    api.listTasks()
      .then((data) => { if (Array.isArray(data)) setTasks(data) })
      .catch(() => {}) // backend down — keep the sample, edits stay local
  }, [])

  React.useEffect(() => { refresh() }, [refresh])

  const updateTask = (id, patch) => {
    setTasks((ts) => ts.map((t) => (t.id === id ? { ...t, ...patch } : t)))
    if (typeof id !== 'number') return // optimistic row not saved yet

    const apiPatch = {}
    for (const key of API_FIELDS) {
      if (key in patch) apiPatch[key] = patch[key] === '' && key === 'deadline' ? null : patch[key]
    }
    if (!Object.keys(apiPatch).length) return

    const entry = pending.current[id] || (pending.current[id] = { patch: {} })
    Object.assign(entry.patch, apiPatch)
    clearTimeout(entry.timer)
    entry.timer = setTimeout(() => {
      const body = entry.patch
      delete pending.current[id]
      api.updateTask(id, body)
        .then((saved) => {
          // Reconcile derived fields (due/late/completed_at) unless the user
          // has typed again since this flush.
          if (!pending.current[id]) setTasks((ts) => ts.map((t) => (t.id === id ? saved : t)))
        })
        .catch(() => {})
    }, 400)
  }

  const toggleTask = (id) => {
    const t = tasks.find((x) => x.id === id)
    if (t) updateTask(id, { done: !t.done })
  }

  const addTask = (fields) => {
    const body = typeof fields === 'string' ? { label: fields } : fields
    if (!body.label || !body.label.trim()) return
    const tempId = 'tmp-' + Date.now()
    setTasks((ts) => [{
      done: false, late: false, due: null, deadline: null, group: 'Today', prio: 'med',
      list: 'Personal', description: '', subtasks: [], labels: [], reminders: [], files: [],
      ...body, id: tempId,
    }, ...ts])
    api.createTask(body)
      .then((saved) => { if (saved) setTasks((ts) => ts.map((t) => (t.id === tempId ? saved : t))) })
      .catch(() => {})
  }

  return { tasks, addTask, toggleTask, updateTask, refresh }
}
