/* Scuffed OS — Task detail drawer */
import React from 'react'
import { Badge, IconButton, Checkbox, Button } from '../components/ui.jsx'
import { Icon } from '../lib/Icon.jsx'

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

export function TaskDetail({ task, onUpdate, onClose }) {
  const [subInput, setSubInput] = React.useState('')
  const [remInput, setRemInput] = React.useState('')
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

  const addRem = () => {
    if (remInput.trim()) patch({ reminders: [...reminders, remInput.trim()] })
    setRemInput(''); setAddingRem(false)
  }
  const presetRems = ['1 hour before', '9:00am', 'Tonight']

  const onFiles = (e) => {
    const picked = Array.from(e.target.files || []).map((f) => ({ id: Date.now() + Math.random(), name: f.name, size: f.size }))
    if (picked.length) patch({ files: [...files, ...picked] })
    e.target.value = ''
  }
  const delFile = (id) => patch({ files: files.filter((f) => f.id !== id) })

  const PRIOS = [['low', 'Low', 'var(--green-500)'], ['med', 'Medium', 'var(--honey-600)'], ['high', 'High', 'var(--clay-600)']]

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
            <span className="kit-field__label"><Icon name="bell" />Reminders</span>
            <div className="kit-chips">
              {reminders.map((r, i) => (
                <span className="kit-chip" key={i}>
                  <Icon name="bell" />{r}
                  <span className="kit-chip__x" onClick={() => patch({ reminders: reminders.filter((_, j) => j !== i) })}><Icon name="x" /></span>
                </span>
              ))}
              {addingRem ? (
                <span className="kit-chip">
                  <input autoFocus value={remInput} onChange={(e) => setRemInput(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && addRem()} onBlur={addRem}
                    placeholder="When?" style={{ border: 'none', outline: 'none', background: 'transparent', font: 'inherit', width: 90 }} />
                </span>
              ) : (
                <span className="kit-chip kit-chip__add" onClick={() => setAddingRem(true)}><Icon name="plus" />Add</span>
              )}
            </div>
            {reminders.length === 0 && !addingRem && (
              <div className="kit-chips">
                {presetRems.map((r) => (
                  <span className="kit-chip kit-chip__add" key={r} onClick={() => patch({ reminders: [...reminders, r] })}>{r}</span>
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
                    <div className="kit-file" key={f.id}>
                      <span className="kit-file__ico" style={{ background: `var(--${fi.tint}-100)`, color: `var(--${fi.tint}-600)` }}><Icon name={fi.icon} /></span>
                      <div className="kit-file__main">
                        <div className="kit-file__name">{f.name}</div>
                        <div className="kit-file__size">{fmtSize(f.size)}</div>
                      </div>
                      <span className="kit-file__del" onClick={() => delFile(f.id)}><Icon name="x" /></span>
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
