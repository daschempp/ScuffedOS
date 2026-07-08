/* Scuffed OS — App shell + state */
import React from 'react'
import { Card, Button } from './components/ui.jsx'
import { Icon } from './lib/Icon.jsx'
import { Sidebar } from './shell/Sidebar.jsx'
import { TopBar } from './shell/TopBar.jsx'
import { DashboardScreen } from './screens/DashboardScreen.jsx'
import { CalendarScreen } from './screens/CalendarScreen.jsx'
import { TasksScreen } from './screens/TasksScreen.jsx'
import { HabitsScreen } from './screens/HabitsScreen.jsx'
import { NutritionScreen } from './screens/NutritionScreen.jsx'
import { FitnessScreen } from './screens/FitnessScreen.jsx'
import { FinanceScreen } from './screens/FinanceScreen.jsx'
import { CRMScreen } from './screens/CRMScreen.jsx'
import { EmailScreen } from './screens/EmailScreen.jsx'
import { SchoolScreen } from './screens/SchoolScreen.jsx'
import { MemoryScreen } from './screens/MemoryScreen.jsx'
import { SettingsScreen } from './screens/SettingsScreen.jsx'
import { ChatPanel } from './assistant/ChatPanel.jsx'
import { api } from './lib/api.js'
import { useTasks } from './lib/useTasks.js'
import { useCalendar } from './lib/useCalendar.js'
import { useHabits } from './lib/useHabits.js'
import { useNutrition } from './lib/useNutrition.js'
import { useSpeech } from './lib/useSpeech.js'

const SCREENS = {
  home: { title: 'Good morning, Sam', sub: 'Tuesday, June 9 · 4 things need you today' },
  nutrition: { title: 'Nutrition', sub: '1,690 of 2,100 kcal · 410 to go' },
  fitness: { title: 'Fitness', sub: 'Recovery, sleep, strain & workouts' },
  finance: { title: 'Finance', sub: '$129,050 net worth · on budget for June' },
  memory: { title: 'Second Brain', sub: '142 memories · learning from your notes' },
  calendar: { title: 'Calendar', sub: '3 events today' },
  tasks: { title: 'Tasks', sub: '5 open · 2 done today' },
  habits: { title: 'Habits', sub: '2 of 5 done · keep your streaks alive' },
  people: { title: 'People', sub: '142 contacts · 2 to reach out to' },
  email: { title: 'Email', sub: '12 new · 4 need a reply' },
  school: { title: 'School', sub: 'Courses, deadlines & grades' },
  settings: { title: 'Settings', sub: 'Preferences & connections' },
}

function Placeholder({ icon, name }) {
  return (
    <Card variant="flat" style={{ textAlign: 'center', padding: '56px 24px' }}>
      <div style={{ display: 'inline-flex', width: 56, height: 56, borderRadius: 'var(--radius-lg)', background: 'var(--accent-soft)', color: 'var(--accent-text)', alignItems: 'center', justifyContent: 'center', marginBottom: 14 }}>
        <Icon name={icon} />
      </div>
      <h3 style={{ fontFamily: 'var(--font-display)', fontSize: 'var(--text-xl)', color: 'var(--text-strong)', margin: '0 0 6px' }}>{name}</h3>
      <p className="kit-muted" style={{ maxWidth: 360, margin: '0 auto' }}>This surface isn't part of the current design-system sample. The Home, Nutrition, Finance and Second Brain screens are fully built out.</p>
    </Card>
  )
}

/* Live header subtitle when real data has loaded; null falls back to the
   static SCREENS sub. */
function liveSub(screen, calendar, habitsState, nutrition) {
  if (screen === 'calendar' && calendar.todayCount !== null) {
    const n = calendar.todayCount
    return `${n} event${n === 1 ? '' : 's'} today`
  }
  if (screen === 'habits' && habitsState.habits.length) {
    return `${habitsState.doneToday} of ${habitsState.habits.length} done · keep your streaks alive`
  }
  if (screen === 'nutrition' && nutrition.day) {
    const eaten = Math.round(nutrition.day.totals.kcal)
    const goal = nutrition.day.targets.calories
    return `${eaten.toLocaleString('en-US')} of ${goal.toLocaleString('en-US')} kcal · ${Math.max(0, goal - eaten).toLocaleString('en-US')} to go`
  }
  return null
}

export function App() {
  const [screen, setScreen] = React.useState('home')
  // The one rich task list (D1) — Home, TasksScreen and the assistant share it.
  const { tasks, addTask, toggleTask, updateTask, refresh } = useTasks()
  // Calendar, habits and nutrition state — same shared-hook pattern.
  const calendar = useCalendar()
  const habitsState = useHabits()
  // Reaching (or leaving) the water goal auto-completes a water-linked habit
  // server-side; refetch habits so the checkmark/streak follow.
  const nutrition = useNutrition({ onWaterChanged: () => habitsState.refresh() })
  const [voiceNotes, setVoiceNotes] = React.useState([
    { text: '“Remind me to call mom about the ceramics class”', time: '8:10am', len: '0:06', done: true },
    { text: '“Lighthouse deadline moved to the 30th”', time: 'Yesterday', len: '0:11', done: true },
    { text: '“Cut dining out to twice a week”', time: 'Yesterday', len: '0:04', done: true },
  ])
  const [assistantOpen, setAssistantOpen] = React.useState(false)

  // "Voice note" in the top bar: dictate → file into the second brain.
  const speech = useSpeech()
  const recording = speech.listening
  const toggleRecord = () => {
    if (!recording) { speech.start(); return }
    speech.stop()
    const text = speech.transcript.trim()
    if (!text) return
    api.createMemory(text, { src: 'voice note' }).catch(() => {})
    setVoiceNotes((notes) => [{ text: `“${text}”`, time: 'just now', len: '', done: true }, ...notes])
  }

  const meta = SCREENS[screen] || SCREENS.home
  const sub = liveSub(screen, calendar, habitsState, nutrition) || meta.sub

  // Assistant action → refresh whichever domain it touched. Nutrition also
  // refreshes habits: water actions deep-link to 'nutrition' but can flip a
  // water-linked habit's completion.
  const onDataChanged = (target) => {
    if (target === 'tasks') refresh()
    else if (target === 'calendar') calendar.refresh()
    else if (target === 'habits') habitsState.refresh()
    else if (target === 'nutrition') { nutrition.refresh(); habitsState.refresh() }
  }

  let body
  if (screen === 'home') body = <DashboardScreen tasks={tasks.filter((t) => t.group === 'Today')} onToggleTask={toggleTask} voiceNotes={voiceNotes} calendar={calendar} nutrition={nutrition} onNavigate={setScreen} />
  else if (screen === 'nutrition') body = <NutritionScreen nutrition={nutrition} />
  else if (screen === 'finance') body = <FinanceScreen />
  else if (screen === 'memory') body = <MemoryScreen voiceNotes={voiceNotes} />
  else if (screen === 'calendar') body = <CalendarScreen calendar={calendar} />
  else if (screen === 'tasks') body = <TasksScreen tasks={tasks} onToggle={toggleTask} onUpdate={updateTask} onAdd={addTask} onRefresh={refresh} />
  else if (screen === 'fitness') body = <FitnessScreen />
  else if (screen === 'habits') body = <HabitsScreen habits={habitsState} />
  else if (screen === 'people') body = <CRMScreen />
  else if (screen === 'email') body = <EmailScreen />
  else if (screen === 'school') body = <SchoolScreen />
  else if (screen === 'settings') body = <SettingsScreen />
  else body = <Placeholder icon={{ settings: 'settings' }[screen] || 'sparkles'} name={meta.title} />

  return (
    <div className="kit">
      <Sidebar active={screen} onNavigate={setScreen} />
      <main className="kit-main">
        <TopBar title={meta.title} subtitle={sub} recording={recording} onToggleRecord={toggleRecord} />
        <div className="kit-page">
          {recording && (
            <div className="kit-voice" style={{ marginBottom: 'var(--gutter)' }}>
              <span className="kit-insight__icon" style={{ background: 'var(--green-600)', color: '#fff' }}><Icon name="mic" /></span>
              <div className="kit-voice__wave">{Array.from({ length: 30 }).map((_, i) => <i key={i} style={{ height: 6 + (i % 6) * 3, animationDelay: (i * 0.04) + 's' }} />)}</div>
              <div className="kit-voice__label">
                <b>Listening…</b>{speech.transcript || "Speak — I'll file it into your second brain"}
              </div>
              <Button variant="secondary" size="sm" onClick={toggleRecord}>Done</Button>
            </div>
          )}
          {body}
        </div>
      </main>

      {!assistantOpen && (
        <button className="kit-fab" onClick={() => setAssistantOpen(true)}>
          <span className="kit-fab__pulse" />
          <Icon name="sparkles" />Assistant
        </button>
      )}
      {assistantOpen && (
        <ChatPanel onClose={() => setAssistantOpen(false)} onNavigate={setScreen} onDataChanged={onDataChanged} />
      )}
    </div>
  )
}
