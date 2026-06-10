/* Scuffed OS — Second Brain (AI memory).
   Memories load from GET /api/memory, falling back to the bundled sample set if
   the backend is unreachable. The voice inbox is passed down from the app. */
import React from 'react'
import { Card, Badge, IconButton } from '../components/ui.jsx'
import { Button } from '../components/ui.jsx'
import { Icon } from '../lib/Icon.jsx'
import { api } from '../lib/api.js'

const SAMPLE_MEMORIES = [
  { text: "Mom's birthday is March 14 — she mentioned wanting that ceramics class.", src: 'voice note', tags: ['family', 'gifts'], color: 'plum' },
  { text: 'Prefer morning workouts; energy dips after 8pm. Schedule deep work before noon.', src: 'learned', tags: ['health', 'routine'], color: 'green' },
  { text: 'Project Lighthouse deadline moved to June 30. Loop in Priya before the 20th.', src: 'telegram', tags: ['work'], color: 'sky' },
  { text: 'Trying to cut dining out to twice a week. Cook salmon more often.', src: 'voice note', tags: ['finance', 'nutrition'], color: 'clay' },
]

export function MemoryScreen({ voiceNotes }) {
  const [memories, setMemories] = React.useState(SAMPLE_MEMORIES)
  React.useEffect(() => {
    let alive = true
    api.listMemories()
      .then((data) => { if (alive && Array.isArray(data) && data.length) setMemories(data) })
      .catch(() => {}) // keep sample on failure
    return () => { alive = false }
  }, [])

  const tagColor = { family: 'plum', gifts: 'plum', health: 'green', routine: 'green', work: 'sky', finance: 'clay', nutrition: 'honey' }
  return (
    <div className="kit-grid" style={{ gridTemplateColumns: '1.5fr 1fr' }}>
      <div className="kit-col">
        <Card>
          <div className="kit-inline" style={{ gap: 12 }}>
            <span className="kit-insight__icon" style={{ width: 42, height: 42 }}><Icon name="sparkles" /></span>
            <div style={{ flex: 1 }}>
              <input className="kit-search" style={{ width: '100%', border: 'none', boxShadow: 'none', background: 'transparent', padding: 0, fontSize: 'var(--text-md)', color: 'var(--text-strong)' }}
                placeholder="Ask anything — “what did I say about the Lighthouse deadline?”" />
            </div>
            <Button variant="primary" size="sm" iconRight={<Icon name="corner-down-left" />}>Ask</Button>
          </div>
        </Card>

        <Card title="Recent memories" eyebrow="142 stored" action={<Badge color="green" dot>Learning</Badge>}>
          <div className="kit-stack">
            {memories.map((m, i) => (
              <div className="kit-memory" key={i}>
                <div className="kit-memory__top">
                  <span className="kit-cat" style={{ background: `var(--${m.color}-600)` }} />
                  <Badge color={m.color}>{m.src}</Badge>
                  <span className="kit-memory__src">{m.when || '2 days ago'}</span>
                </div>
                <p>{m.text}</p>
                <div className="kit-tags">
                  {m.tags.map((t) => <Badge key={t} color={tagColor[t] || 'neutral'}>#{t}</Badge>)}
                </div>
              </div>
            ))}
          </div>
        </Card>
      </div>

      <div className="kit-col">
        <Card eyebrow="Telegram" title="Voice inbox" action={<IconButton label="Record" variant="solid" size="sm"><Icon name="mic" /></IconButton>}>
          <div className="kit-voice kit-voice--idle" style={{ marginBottom: 14 }}>
            <span className="kit-insight__icon" style={{ background: 'var(--green-600)', color: '#fff' }}><Icon name="mic" /></span>
            <div className="kit-voice__wave">{Array.from({ length: 22 }).map((_, i) => <i key={i} style={{ height: 6 + (i % 5) * 4, animationDelay: (i * 0.05) + 's' }} />)}</div>
            <div className="kit-voice__label"><b>Send from anywhere</b>@scuffed_os_bot</div>
          </div>
          {voiceNotes.map((v, i) => (
            <div className="kit-row" key={i}>
              <span className="kit-meal__ico" style={{ width: 34, height: 34, background: 'var(--green-100)', color: 'var(--green-700)' }}><Icon name="audio-lines" /></span>
              <div className="kit-row__main">
                <p className="kit-row__title" style={{ fontWeight: 500, fontSize: 'var(--text-sm)' }}>{v.text}</p>
                <p className="kit-row__sub">{v.time} · {v.len}</p>
              </div>
              {v.done && <Icon name="check-check" />}
            </div>
          ))}
        </Card>

        <Card title="Connections" variant="sunken">
          <p className="kit-muted" style={{ marginBottom: 12 }}>Topics your brain links most</p>
          <div className="kit-tags">
            {[['nutrition', 'honey', 28], ['work', 'sky', 41], ['family', 'plum', 12], ['health', 'green', 33], ['finance', 'clay', 19]].map(([t, c, n]) => (
              <Badge key={t} color={c}>#{t} <span style={{ opacity: 0.6, fontFamily: 'var(--font-mono)' }}>{n}</span></Badge>
            ))}
          </div>
        </Card>
      </div>
    </div>
  )
}
