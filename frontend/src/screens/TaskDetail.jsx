/* Scuffed OS — Task detail drawer */
import React from 'react'
import { Badge, IconButton, Checkbox, Button } from '../components/ui.jsx'
import { Icon } from '../lib/Icon.jsx'
import { api } from '../lib/api.js'

const TASK_LISTS = [
  { name: 'Work', color: 'sky' }, { name: 'Health', color: 'green' },
  { name: 'Finance', color: 'honey' }, { name: 'Personal', color: 'plum' },
]

function fileIcon(name) {
  const ext = (name.split('.').pop() || '').toLowerCase()
  if (['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'heic'].includes(ext)) return { icon: 'image', tint: 'plum' }
  if (['pdf'].includes(ext)) return { icon: 'file-text', tint: 'clay' }
  if (['doc', 'docx', 'txt', 'md', 'pages'].includes(ext)) return { icon: 'file-text', tint: 'sky' }
  if (['xls', 'xlsx', 'csv', 'numbers'].includes(ext)) return { icon: 'table', tint: 'green' }
  if (['mp3', 'wav', 'm4a', 'ogg'].includes(ext)) return { icon: 'audio-lines', tint: 'honey' }
  return { icon: 'file', tint: 'green' }
}
function fmtSize(bytes) {
  if (bytes == null) return ''
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(0) + ' KB'
  return (bytes / 1024 / 1024).toFixed(1) + ' MB'
}

export function TaskDetail({ task, onUpdate, onClose, onRefresh }) {
  const [subInput, setSubInput] = React.useState('')
  const [remWhen, setRemWhen] = React.useState('')
  const [remLabel, setRemLabel] = React.useState('')
  const [addingRem, setAddingRem] = React.useState(false)
  const fileRef = React.useRef(null)

  React.useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const patch = (p) => onUpdate(task.id, p)
  const subs = task.subtasks || []
  const reminders = task.reminders || []
  const files = task.files || []
  const subsDone = subs.filter((s) => s.done).length

  const addSub = () => {
    if (!subInput.trim()) return
    patch({ subtasks: [...subs, { id: Date.now(), label: subInput.trim(), done: false }] })
    setSubInput('')
  }
  const toggleSub = (id) => patch({ subtasks: subs.map((s) => s.id === id ? { ...s, done: !s.done } : s) })
  const delSub = (id) => patch({ subtasks: subs.filter((s) => s.id !== id) })

  const addReminderAt = (when, label) =>
    api.addTaskReminder(task.id, when.toISOString(), label).then(onRefresh).catch(() => {})
  const addRem = () => {
    if (remWhen) addReminderAt(new Date(remWhen), remLabel.trim() || undefined)
    setRemWhen(''); setRemLabel(''); setAddingRem(false)
  }
  const delRem = (rid) => api.deleteTaskReminder(task.id, rid).then(onRefresh).catch(() => {})
  // Quick chips — concrete datetimes, not free-text strings.
  const quickRems = [
    ['Tomorrow 9am', () => {
      const d = new Date(); d.setDate(d.getDate() + 1); d.setHours(9, 0, 0, 0); return d
    }],
    ['Tonight 8pm', () => {
      const d = new Date(); d.setHours(20, 0, 0, 0)
      if (d <= new Date()) d.setDate(d.getDate() + 1) // 8pm already passed — tomorrow 8pm
      return d
    }],
  ]

  const onFiles = (e) => {
    const picked = Array.from(e.target.files || [])
    e.target.value = ''
    if (!picked.length) return
    picked
      .reduce((p, f) => p.then(() => api.uploadTaskFile(task.id, f)).catch(() => {}), Promise.resolve())
      .then(onRefresh)
  }
  const openFile = (f) => {
    if (typeof f.id !== 'string') return // temp/sample row — nothing to download
    window.open(api.taskFileUrl(task.id, f.id), '_blank')
  }
  const delFile = (id) => api.deleteTaskFile(task.id, id).then(onRefresh).catch(() => {})

  const PRIOS = [['low', 'Low', 'var(--green-500)'], ['med', 'Medium', 'var(--honey-600)'], ['high', 'High', 'var(--clay-600)']]
  const RECURS = [
    [null, 'None'], ['FREQ=DAILY', 'Daily'], ['FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR', 'Weekdays'],
    ['FREQ=WEEKLY', 'Weekly'], ['FREQ=MONTHLY', 'Monthly'],
  ]
  const customRecurrence = task.recurrence && !RECURS.some(([val]) => val === task.recurrence)

  return (
    <React.Fragment>
      <div className="kit-scrim" onClick={onClose} />
      <aside className="kit-drawer" role="dialog" aria-label="Task details">
        <div className="kit-drawer__head">
          <Badge color={task.listColor || 'neutral'}>{task.list}</Badge>
          <div style={{ flex: 1 }} />
          <IconButton label="Close" size="sm" onClick={onClose}><Icon name="x" /></IconButton>
        </div>

        <div className="kit-drawer__body">
          <div className={'kit-dtitle' + (task.done ? ' kit-dtitle--done' : '')}>
            <Checkbox checked={task.done} onChange={() => patch({ done: !task.done })} />
            <input value={task.label} onChange={(e) => patch({ label: e.target.value })} placeholder="Task name" />
          </div>

          <div className="kit-field">
            <span className="kit-field__label"><Icon name="align-left" />Description</span>
            <textarea className="kit-desc" value={task.description || ''} placeholder="Add more detail…"
              onChange={(e) => patch({ description: e.target.value })} />
          </div>

          <div className="kit-field">
            <span className="kit-field__label"><Icon name="folder" />List</span>
            <div className="kit-chips">
              {TASK_LISTS.map((l) => {
                const on = task.list === l.name
                return (
                  <span key={l.name} className={'kit-pick' + (on ? ' is-on' : '')}
                    style={on ? { background: `var(--${l.color}-100)`, borderColor: `var(--${l.color}-300, var(--border-soft))` } : undefined}
                    onClick={() => patch({ list: l.name, listColor: l.color })}>
                    <span className="kit-pick__dot" style={{ background: `var(--${l.color}-600)` }} />
                    {l.name}
                    {on && <Icon name="check" />}
                  </span>
                )
              })}
            </div>
          </div>

          <div className="kit-field">
            <span className="kit-field__label"><Icon name="list-checks" />Subtasks {subs.length > 0 && <span style={{ color: 'var(--text-disabled)', fontWeight: 600 }}>· {subsDone}/{subs.length}</span>}</span>
            <div>
              {subs.map((s) => (
                <div className={'kit-subtask' + (s.done ? ' kit-subtask--done' : '')} key={s.id}>
                  <Checkbox checked={s.done} onChange={() => toggleSub(s.id)} />
                  <span className="kit-subtask__txt">{s.label}</span>
                  <span className="kit-subtask__del" onClick={() => delSub(s.id)}><Icon name="trash-2" /></span>
                </div>
              ))}
            </div>
            <div className="kit-addrow">
              <Icon name="plus" />
              <input value={subInput} onChange={(e) => setSubInput(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && addSub()} placeholder="Add a subtask…" />
            </div>
          </div>

          <div className="kit-field">
            <span className="kit-field__label"><Icon name="flag" />Priority</span>
            <div className="kit-seg">
              {PRIOS.map(([val, lbl, col]) => (
                <button key={val} className={task.prio === val ? 'is-on' : ''} onClick={() => patch({ prio: val })}>
                  <span className="kit-prio" style={{ background: col }} />{lbl}
                </button>
              ))}
            </div>
          </div>

          <div className="kit-field">
            <span className="kit-field__label"><Icon name="calendar" />Deadline</span>
            <div className="kit-deadline">
              <Icon name="calendar-days" />
              <input type="date" value={task.deadline || ''} onChange={(e) => patch({ deadline: e.target.value })} />
            </div>
          </div>

          <div className="kit-field">
            <span className="kit-field__label"><Icon name="repeat" />Repeats</span>
            <div className="kit-seg">
              {RECURS.map(([val, lbl]) => (
                <button key={lbl} className={!customRecurrence && (task.recurrence || null) === val ? 'is-on' : ''}
                  onClick={() => patch({ recurrence: val })}>{lbl}</button>
              ))}
              {customRecurrence && <button className="is-on">{task.recurrence_label || 'Repeats (custom)'}</button>}
            </div>
          </div>

          <div className="kit-field">
            <span className="kit-field__label"><Icon name="bell" />Reminders</span>
            <div className="kit-chips">
              {reminders.map((r) => (
                <span className="kit-chip" key={r.id} style={r.fired_at ? { opacity: 0.5, textDecoration: 'line-through' } : undefined}>
                  <Icon name="bell" />{r.display}
                  <span className="kit-chip__x" onClick={() => delRem(r.id)}><Icon name="x" /></span>
                </span>
              ))}
              {!addingRem && (
                <span className="kit-chip kit-chip__add" onClick={() => setAddingRem(true)}><Icon name="plus" />Add</span>
              )}
            </div>
            {addingRem && (
              <div className="kit-addrow">
                <Icon name="bell" />
                <input autoFocus type="datetime-local" value={remWhen} onChange={(e) => setRemWhen(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && addRem()} style={{ width: 'auto', flex: 1 }} />
                <input value={remLabel} onChange={(e) => setRemLabel(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && addRem()} placeholder="Label (optional)" style={{ width: 110 }} />
                <Button variant="soft" size="sm" onClick={addRem}>Set</Button>
              </div>
            )}
            {reminders.length === 0 && !addingRem && (
              <div className="kit-chips">
                {quickRems.map(([lbl, when]) => (
                  <span className="kit-chip kit-chip__add" key={lbl} onClick={() => addReminderAt(when())}>{lbl}</span>
                ))}
              </div>
            )}
          </div>

          <div className="kit-field">
            <span className="kit-field__label"><Icon name="paperclip" />Files {files.length > 0 && <span style={{ color: 'var(--text-disabled)', fontWeight: 600 }}>· {files.length}</span>}</span>
            {files.length > 0 && (
              <div className="kit-files">
                {files.map((f) => {
                  const fi = fileIcon(f.name)
                  return (
                    <div className="kit-file" key={f.id} onClick={() => openFile(f)}
                      style={typeof f.id === 'string' ? { cursor: 'pointer' } : undefined}>
                      <span className="kit-file__ico" style={{ background: `var(--${fi.tint}-100)`, color: `var(--${fi.tint}-600)` }}><Icon name={fi.icon} /></span>
                      <div className="kit-file__main">
                        <div className="kit-file__name">{f.name}</div>
                        <div className="kit-file__size">{fmtSize(f.size)}</div>
                      </div>
                      <span className="kit-file__del" onClick={(e) => { e.stopPropagation(); delFile(f.id) }}><Icon name="x" /></span>
                    </div>
                  )
                })}
              </div>
            )}
            <div className="kit-dropzone" onClick={() => fileRef.current && fileRef.current.click()}>
              <Icon name="upload" />Attach a file
            </div>
            <input ref={fileRef} type="file" multiple onChange={onFiles} style={{ display: 'none' }} />
          </div>
        </div>

        <div className="kit-drawer__foot">
          <span className="kit-muted" style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
            <Icon name="check-check" />{task.done ? 'Completed' : 'In progress'}
          </span>
          <Button variant="primary" size="sm" onClick={onClose}>Done</Button>
        </div>
      </aside>
    </React.Fragment>
  )
}
