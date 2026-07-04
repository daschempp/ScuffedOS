/* Scuffed OS — Task manager.
   A view over the shared task list (lib/useTasks.js) — the same rows Home and
   the assistant work with. All mutations flow up through the handlers. */
import React from 'react'
import { Card, Stat, ProgressBar, Button, Badge, Checkbox } from '../components/ui.jsx'
import { Icon } from '../lib/Icon.jsx'
import { TaskDetail } from './TaskDetail.jsx'

const LIST_COLOR = { Work: 'sky', Health: 'green', Finance: 'honey', Personal: 'plum' }
const withColor = (t) => ({ ...t, listColor: LIST_COLOR[t.list] || 'neutral' })

export function TasksScreen({ tasks, onToggle, onUpdate, onAdd, onRefresh }) {
  const [openId, setOpenId] = React.useState(null)
  const [quickAdd, setQuickAdd] = React.useState('')

  const submitQuickAdd = () => {
    if (!quickAdd.trim()) return
    onAdd({ label: quickAdd.trim(), group: 'Today' })
    setQuickAdd('')
  }

  const lists = [
    { name: 'Work', color: 'sky' }, { name: 'Health', color: 'green' },
    { name: 'Finance', color: 'honey' }, { name: 'Personal', color: 'plum' },
  ]
  const groups = ['Today', 'Upcoming', 'Someday']
  const openCount = tasks.filter((t) => !t.done).length
  const doneToday = tasks.filter((t) => t.done).length
  const openTask = tasks.find((t) => t.id === openId)

  const TaskRow = (raw) => {
    const t = withColor(raw)
    const subs = t.subtasks || []
    const subsDone = subs.filter((s) => s.done).length
    // Moodle deadlines are merged in read-only (contract §M): editable===false
    // and a string id "moodle:<n>" that already 422s any mutation endpoint
    // server-side. Suppress the detail-opener, toggle and chevron; show a
    // "Moodle" chip instead.
    const readOnly = t.editable === false || t.source === 'moodle'
    return (
      <div className={'kit-task' + (t.done ? ' kit-task--done' : '')} key={t.id} onClick={readOnly ? undefined : () => setOpenId(t.id)}>
        <span onClick={(e) => e.stopPropagation()} style={{ display: 'inline-flex' }}>
          <Checkbox checked={t.done} disabled={readOnly} onChange={readOnly ? undefined : () => onToggle(t.id)} />
        </span>
        <div className="kit-task__main">
          <p className="kit-task__title">{t.label}</p>
          <div className="kit-task__meta">
            <span className="kit-prio" style={{ background: t.prio === 'high' ? 'var(--clay-600)' : t.prio === 'med' ? 'var(--honey-600)' : 'var(--green-500)' }} />
            {t.due && <span className={'kit-task__due' + (t.late ? ' is-late' : '')}><Icon name={t.late ? 'alarm-clock' : 'clock'} />{t.due}</span>}
            <Badge color={t.listColor}>{t.list}</Badge>
            {subs.length > 0 && <span className="kit-task__due"><Icon name="list-checks" />{subsDone}/{subs.length}</span>}
            {(t.files || []).length > 0 && <span className="kit-task__due"><Icon name="paperclip" />{t.files.length}</span>}
          </div>
        </div>
        {readOnly
          ? <Badge color="plum">Moodle</Badge>
          : <span className="kit-task__chev"><Icon name="chevron-right" /></span>}
      </div>
    )
  }

  return (
    <React.Fragment>
      <div className="kit-grid" style={{ gridTemplateColumns: '1fr 280px' }}>
        <div className="kit-col">
          <div className="kit-quickadd">
            <Icon name="plus" />
            <input
              placeholder="Add a task — or say it as a voice note…"
              value={quickAdd}
              onChange={(e) => setQuickAdd(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && submitQuickAdd()}
            />
            <Badge color="green" icon={<Icon name="mic" />}>Voice</Badge>
          </div>

          {groups.map((g) => {
            const rows = tasks.filter((t) => t.group === g)
            if (!rows.length) return null
            return (
              <Card key={g} title={g} action={<span className="kit-muted">{rows.filter((t) => !t.done).length} open</span>}>
                <div className="kit-tasklist">{rows.map(TaskRow)}</div>
              </Card>
            )
          })}
        </div>

        <div className="kit-col">
          <Card title="Progress" variant="sunken">
            <div className="kit-spread" style={{ marginBottom: 14 }}>
              <Stat label="Open" value={openCount} />
              <Stat label="Done today" value={doneToday} trend="up" delta="+2" />
            </div>
            <ProgressBar label="Today" value={doneToday} max={doneToday + tasks.filter((t) => t.group === 'Today' && !t.done).length} color="green" meta={`${doneToday} done`} />
          </Card>

          <Card title="Lists">
            <div className="kit-stack" style={{ gap: 0 }}>
              {lists.map((l) => (
                <div className="kit-listrow" key={l.name}>
                  <span className="kit-listrow__dot" style={{ background: `var(--${l.color}-600)` }} />
                  <span style={{ fontSize: 'var(--text-base)', fontWeight: 600, color: 'var(--text-strong)' }}>{l.name}</span>
                  <span className="kit-listrow__count">{tasks.filter((t) => t.list === l.name && !t.done).length}</span>
                </div>
              ))}
            </div>
            <div className="kit-divider" style={{ margin: '10px 0' }} />
            <Button variant="ghost" size="sm" iconLeft={<Icon name="plus" />}>New list</Button>
          </Card>

          <Card title="Assistant" eyebrow="Suggestion">
            <div className="kit-insight">
              <div className="kit-insight__icon"><Icon name="sparkles" /></div>
              <p>3 tasks are <strong>overdue or due today</strong>. Want me to reschedule the rest to this evening?</p>
            </div>
            <div className="kit-inline" style={{ marginTop: 12 }}>
              <Button variant="soft" size="sm">Reschedule</Button>
              <Button variant="ghost" size="sm">No thanks</Button>
            </div>
          </Card>
        </div>
      </div>

      {openTask && <TaskDetail task={withColor(openTask)} onUpdate={onUpdate} onClose={() => setOpenId(null)} onRefresh={onRefresh} />}
    </React.Fragment>
  )
}
