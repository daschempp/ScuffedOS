/* Scuffed OS — habits state for the current week.
   Holds the whole /api/habits week payload; toggles are optimistic (flip the
   day immediately, reconcile with the server row on success) mirroring
   useTasks. Renders sensibly from empty defaults while the backend is down. */
import React from 'react'
import { api } from './api.js'

/* week_start (YYYY-MM-DD) + n days → YYYY-MM-DD, via UTC math so the local
   timezone can't shift the date. */
function addDaysIso(isoDate, n) {
  const [y, m, d] = isoDate.split('-').map(Number)
  return new Date(Date.UTC(y, m - 1, d + n)).toISOString().slice(0, 10)
}

export function useHabits() {
  const [data, setData] = React.useState(null)

  const refresh = React.useCallback(() => {
    api.habitsWeek()
      .then((week) => { if (week) setData(week) })
      .catch(() => {}) // backend down — keep what we have
  }, [])

  React.useEffect(() => { refresh() }, [refresh])

  const toggle = (habitId, dayIndex) => {
    if (!data) return
    setData((d) => d && {
      ...d,
      habits: d.habits.map((h) => (h.id === habitId
        ? { ...h, days: h.days.map((v, i) => (i === dayIndex ? !v : v)) }
        : h)),
    })
    api.toggleHabit(habitId, addDaysIso(data.week_start, dayIndex))
      .then((saved) => {
        if (saved) setData((d) => d && { ...d, habits: d.habits.map((h) => (h.id === habitId ? saved : h)) })
        // done_today / week_pct are week-level summaries the toggle response
        // doesn't carry — refetch so the Today ring and stats move too.
        refresh()
      })
      .catch(() => {}) // keep the optimistic flip
  }

  const addHabit = (name) => {
    if (!name || !name.trim()) return
    api.createHabit({ name: name.trim() })
      .then(() => refresh())
      .catch(() => {})
  }

  return {
    habits: data ? data.habits : [],
    doneToday: data ? data.done_today : 0,
    weekPct: data ? data.week_pct : 0,
    prevWeekPct: data ? data.prev_week_pct : 0,
    todayIndex: data ? data.today_index : null,
    toggle,
    addHabit,
    refresh,
  }
}
