/* Scuffed OS — Assistant chat panel.
   Streams replies from the server-side tool loop (SSE), renders action cards
   for tools that actually executed, resumes the last conversation across
   restarts, and falls back to labeled capture-only mode when offline.
   Text renders as plain text — never HTML (review R4). */
import React from 'react'
import { IconButton } from '../components/ui.jsx'
import { Icon } from '../lib/Icon.jsx'
import { api } from '../lib/api.js'
import { useSpeech } from '../lib/useSpeech.js'
import { captureReply } from './assistantLogic.js'

const GREETING = {
  id: 'greeting', role: 'ai',
  text: "Hi — I'm your assistant. I can manage your tasks, file things into your second brain, and read your day. What do you need?",
}

export function ChatPanel({ onClose, onNavigate, onDataChanged }) {
  const [messages, setMessages] = React.useState([GREETING])
  const [conversationId, setConversationId] = React.useState(null)
  const [input, setInput] = React.useState('')
  const [busy, setBusy] = React.useState(false)
  const [toolStatus, setToolStatus] = React.useState(null)
  const [offline, setOffline] = React.useState(false)
  const logRef = React.useRef(null)
  const speech = useSpeech()

  React.useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  React.useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight
  }, [messages, busy])

  // Resume the latest conversation — history survives backend restarts.
  React.useEffect(() => {
    let alive = true
    api.latestConversation()
      .then((conv) => {
        if (!alive || !conv) return
        setConversationId(conv.id)
        setMessages([GREETING, ...conv.messages.map((m) => ({
          id: m.id, role: m.role === 'assistant' ? 'ai' : 'user',
          text: m.content, actions: m.actions || [],
        }))])
      })
      .catch((err) => { if (alive && err?.name !== 'ApiError') setOffline(true) })
    return () => { alive = false }
  }, [])

  // Dictation streams straight into the composer.
  React.useEffect(() => {
    if (speech.listening) setInput(speech.transcript)
  }, [speech.listening, speech.transcript])

  const updateMessage = (id, patch) =>
    setMessages((ms) => ms.map((m) => (m.id === id ? { ...m, ...patch(m) } : m)))

  const send = async (raw) => {
    const text = (raw != null ? raw : input).trim()
    if (!text || busy) return
    if (speech.listening) speech.stop()
    setInput('')
    setMessages((ms) => [...ms, { id: 'u' + Date.now(), role: 'user', text }])
    setBusy(true)

    const aiId = 'a' + Date.now()
    let streamed = false
    try {
      await api.chatStream(text, conversationId, (event, data) => {
        if (event === 'meta') setConversationId(data.conversation_id)
        else if (event === 'delta') {
          setToolStatus(null)
          if (!streamed) {
            streamed = true
            setMessages((ms) => [...ms, { id: aiId, role: 'ai', text: data.text, actions: [] }])
          } else {
            updateMessage(aiId, (m) => ({ text: m.text + data.text }))
          }
        } else if (event === 'tool') setToolStatus(data.name.replaceAll('_', ' '))
        else if (event === 'action') {
          if (streamed) updateMessage(aiId, (m) => ({ actions: [...m.actions, data] }))
          if (data.screen && onDataChanged) onDataChanged(data.screen)
        } else if (event === 'error') {
          throw new Error(data.message)
        } else if (event === 'done') {
          setOffline(false)
          const final = { id: aiId, role: 'ai', text: data.text, actions: data.actions || [] }
          setMessages((ms) => streamed
            ? ms.map((m) => (m.id === aiId ? final : m))
            : [...ms, final])
        }
      })
    } catch {
      setOffline(true)
      const fallback = await captureReply(text)
      setMessages((ms) => [...ms.filter((m) => m.id !== aiId),
        { id: aiId, role: 'ai', text: fallback.text, actions: fallback.action ? [fallback.action] : [] }])
    } finally {
      setToolStatus(null)
      setBusy(false)
    }
  }

  const goAction = (screen) => { if (screen && onNavigate) onNavigate(screen); onClose() }
  const suggestions = ['Plan my day', 'Add a task to call the dentist', 'How much did I spend on dining?', "What's in my second brain?"]

  return (
    <React.Fragment>
      <div className="kit-scrim" onClick={onClose} />
      <aside className="kit-drawer kit-chat" role="dialog" aria-label="Assistant">
        <div className="kit-chat__head">
          <div className="kit-chat__id"><img src="/assets/logo-mark.svg" alt="" /></div>
          <div style={{ flex: 1 }}>
            <div className="kit-chat__name">Scuffed Assistant</div>
            <div className="kit-chat__status" style={offline ? { color: 'var(--clay-600)' } : undefined}>
              {offline ? 'Offline — capture only' : 'Connected to your second brain'}
            </div>
          </div>
          <IconButton label="Close" size="sm" onClick={onClose}><Icon name="x" /></IconButton>
        </div>

        <div className="kit-chat__log" ref={logRef}>
          {messages.map((m) => (
            <div key={m.id} className={'kit-msg kit-msg--' + m.role}>
              {m.role === 'ai' && <span className="kit-msg__av"><Icon name="sparkles" /></span>}
              <div>
                <div className="kit-bubble" style={{ whiteSpace: 'pre-wrap' }}>{m.text}</div>
                {(m.actions || []).map((a, i) => (
                  <div className="kit-action" key={i}>
                    <span className="kit-action__ico"><Icon name={a.icon} /></span>
                    <div className="kit-action__main">
                      <div className="kit-action__title"><Icon name="check" />{a.title}</div>
                      <div className="kit-action__meta">{a.meta}</div>
                    </div>
                    <span className="kit-action__cta" onClick={() => goAction(a.screen)}>{a.cta}</span>
                  </div>
                ))}
              </div>
            </div>
          ))}
          {busy && (
            <div className="kit-msg kit-msg--ai">
              <span className="kit-msg__av"><Icon name="sparkles" /></span>
              <div className="kit-bubble" style={toolStatus ? undefined : { padding: 0 }}>
                {toolStatus
                  ? <span className="kit-muted" style={{ fontSize: 'var(--text-sm)' }}><Icon name="loader-circle" /> {toolStatus}…</span>
                  : <div className="kit-typing"><i /><i /><i /></div>}
              </div>
            </div>
          )}
        </div>

        <div className="kit-chat__suggest">
          {suggestions.map((s) => <span key={s} className="kit-suggest" onClick={() => send(s)}>{s}</span>)}
        </div>

        <div className="kit-composer">
          <div className="kit-composer__box">
            <textarea rows="1" value={input}
              placeholder={speech.listening ? 'Listening…' : 'Ask or tell your assistant…'}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() } }} />
            <IconButton
              label={speech.listening ? 'Stop dictation' : 'Dictate'}
              variant={speech.listening ? 'solid' : 'ghost'} size="sm"
              disabled={!speech.supported}
              onClick={() => (speech.listening ? speech.stop() : speech.start())}
            >
              <Icon name={speech.listening ? 'square' : 'mic'} />
            </IconButton>
          </div>
          <IconButton label="Send" variant="solid" onClick={() => send()}><Icon name="arrow-up" /></IconButton>
        </div>
      </aside>
    </React.Fragment>
  )
}
