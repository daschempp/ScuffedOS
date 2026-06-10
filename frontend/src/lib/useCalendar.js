/* Scuffed OS — calendar state.
   One visible week (Monday-first), navigated as an offset from the current
   Monday. Fetches the week's occurrences, the up-next list, and the visible
   month's occurrences (for the mini-grid dots). All fetches fail soft —
   the previous state sticks around when the backend is down. */
import React from 'react'
import { api } from './api.js'

const DOW = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

/* Local-midnight Monday of the week containing d. */
function startOfWeek(d) {
  const date = new Date(d.getFullYear(), d.getMonth(), d.getDate())
  date.setDate(date.getDate() - ((date.getDay() + 6) % 7))
  return date
}

function addDays(d, n) {
  const x = new Date(d)
  x.setDate(x.getDate() + n)
  return x
}

const sameDay = (a, b) =>
  a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate()

/* The backend serializes true UTC instants ("...Z"), so day-of math must go
   through a local Date — slicing the string would bucket evening events
   into the wrong day for anyone west of UTC. */
const localDayNum = (s) => new Date(s).getDate()
const isLocalToday = (s) => sameDay(new Date(s), new Date())
const inLocalMonth = (s, y, m) => {
  const d = new Date(s)
  return d.getFullYear() === y && d.getMonth() === m
}

export function useCalendar() {
  const [weekOffset, setWeekOffset] = React.useState(0)
  const [events, setEvents] = React.useState([])
  const [upNext, setUpNext] = React.useState([])
  const [monthEvents, setMonthEvents] = React.useState([])
  const [todayEvents, setTodayEvents] = React.useState(null) // null until fetched
  const [tick, setTick] = React.useState(0)

  React.useEffect(() => {
    const ws = addDays(startOfWeek(new Date()), weekOffset * 7)
    api.listEvents(ws.toISOString(), addDays(ws, 7).toISOString())
      .then((data) => { if (Array.isArray(data)) setEvents(data) })
      .catch(() => {}) // backend down — keep what we have
    api.upNext(3)
      .then((data) => { if (Array.isArray(data)) setUpNext(data) })
      .catch(() => {})
    const monthStart = new Date(ws.getFullYear(), ws.getMonth(), 1)
    const monthEnd = new Date(ws.getFullYear(), ws.getMonth() + 1, 1)
    api.listEvents(monthStart.toISOString(), monthEnd.toISOString())
      .then((data) => { if (Array.isArray(data)) setMonthEvents(data) })
      .catch(() => {})
    // Today's count is its own fetch: the visible week changes with
    // navigation, so deriving "N events today" from it would zero out the
    // header the moment the user clicks Previous.
    const midnight = new Date(new Date().getFullYear(), new Date().getMonth(), new Date().getDate())
    api.listEvents(midnight.toISOString(), addDays(midnight, 1).toISOString())
      .then((data) => { if (Array.isArray(data)) setTodayEvents(data) })
      .catch(() => {})
  }, [weekOffset, tick])

  const today = new Date()
  const weekStart = addDays(startOfWeek(today), weekOffset * 7)
  const days = Array.from({ length: 7 }, (_, i) => {
    const date = addDays(weekStart, i)
    return { date, dow: DOW[i], dayNum: date.getDate(), isToday: sameDay(date, today) }
  })

  // Mini month grid for the month containing the visible week's Monday.
  const y = weekStart.getFullYear()
  const m = weekStart.getMonth()
  const dotDays = new Set()
  for (const e of monthEvents) {
    if (inLocalMonth(e.start, y, m)) dotDays.add(localDayNum(e.start))
  }
  const first = new Date(y, m, 1)
  const daysInMonth = new Date(y, m + 1, 0).getDate()
  const isCurrentMonth = y === today.getFullYear() && m === today.getMonth()
  const monthDays = []
  for (let i = 0; i < (first.getDay() + 6) % 7; i++) {
    monthDays.push({ d: null, today: false, dot: false }) // leading blanks → Mon-start columns
  }
  for (let d = 1; d <= daysInMonth; d++) {
    monthDays.push({ d, today: isCurrentMonth && d === today.getDate(), dot: dotDays.has(d) })
  }
  const monthLabel = first.toLocaleDateString('en-US', { month: 'long', year: 'numeric' })

  return {
    weekStart,
    days,
    events,
    upNext,
    monthLabel,
    monthDays,
    // Local-day count for the header subtitle; null until the fetch lands
    // so App can fall back to the static sub instead of showing a wrong 0.
    todayCount: todayEvents === null ? null : todayEvents.filter((e) => isLocalToday(e.start)).length,
    goPrev: () => setWeekOffset((o) => o - 1),
    goNext: () => setWeekOffset((o) => o + 1),
    goToday: () => setWeekOffset(0),
    refresh: () => setTick((t) => t + 1),
  }
}
